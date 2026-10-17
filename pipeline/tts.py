"""Seslendirme ve kelime zamanlamaları.

Ses sırası: Gemini (en doğal; ücretsiz kotası var) -> Microsoft Edge -> Piper (bilgisayarda çalışan, mekanik).
Bir konuşmacının sesi video ortasında değişmez: kullandığı ses düşerse o konuşmacının o ana kadarki bütün
cümleleri yeni sesle baştan okunur (speak_all). Cinsiyet her basamakta korunur.
"""
import asyncio
import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import edge_tts

# Gemini seslendirme modelleri, sırayla; her birinin ayrı ücretsiz günlük kotası var
GEMINI_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview",
                 "gemini-2.5-flash-preview-tts"]
GEMINI_VOICES = {"male": "Charon", "female": "Kore"}  # çok dilli: Türkçe ve İngilizce aynı ses
# Microsoft sesleri, sırayla. tr-TR-AhmetNeural Ekim 2026'da ses döndürmüyor; çok dilli erkek ses Türkçe de konuşur.
EDGE_VOICES = {"tr": {"male": ["tr-TR-AhmetNeural", "en-US-AndrewMultilingualNeural"], "female": ["tr-TR-EmelNeural"]},
               "en": {"male": ["en-US-GuyNeural"], "female": ["en-US-JennyNeural"]}}
VOICES = {lang: {g: v[0] for g, v in genders.items()} for lang, genders in EDGE_VOICES.items()}
RATE = "+15%"  # Shorts temposu
PIPER_VOICES = {("tr", "male"): "tr_TR-dfki-medium", ("tr", "female"): "tr_TR-dfki-medium",
                ("en", "male"): "en_US-ryan-medium", ("en", "female"): "en_US-lessac-medium"}
# Piper'da Türkçe kadın sesi yok; iki konuşmacı ayırt edilebilsin diye aynı ses biraz inceltilir
PIPER_PITCH = {("tr", "female"): 1.12}
PIPER_DIR = Path.home() / ".cache" / "faceless-shorts" / "piper"
PIPER_PACE = 0.87  # Edge'deki +%15 hıza denk
_down = set()  # bu çalışmada düşen sesler (kota bitti, servis reddetti); yeniden denenmez
_choice = {}  # (dil, cinsiyet) -> son kullanılan basamak: ayrı çağrılar da aynı sesle başlasın
_piper = {}


class VoiceDown(Exception):
    """Bu ses bu çalışmada artık kullanılamaz; bir sonraki sese geçilir."""


# Türkçe seslendirmede yabancı isimler Türkçe harf kurallarıyla okunmasın diye okunuşlarıyla söylenir.
# Altyazıda orijinal yazım kalır: kelime zamanları gelince okunuş geri çevrilir.
PRONOUNCE = {"tr": {
    "Stonehenge": "Stonhenç", "Schmidt": "Şmit", "Braidwood": "Breydvud", "Chicago": "Şikago",
    "Schliemann": "Şliman", "Heinrich": "Haynrih", "Sophia": "Sofiya", "Wilhelm": "Vilhelm",
    "Dörpfeld": "Dörpfelt", "Calvert": "Kalvırt", "Korfmann": "Korfman", "Rostock": "Rostok",
    "Cincinnati": "Sinsinati", "Hapgood": "Hepgud", "McIntosh": "Mekintoş", "Mallery": "Meleri",
    "Gregory": "Gregori", "Charles": "Çarlz", "Arlington": "Arlingtın", "Dawkins": "Dokins",
    "Richard": "Riçırd", "Winckler": "Vinkler", "New York": "Nyu York", "UNESCO": "Yunesko",
    "Champollion": "Şampolyon", "Deissmann": "Daysman", "Michelangelo": "Mikelancelo",
    "Giustiniani": "Custinyani", "Giovanni": "Covanni", "Doria": "Dorya", "Condalmiero": "Kondalmiyero",
    "Venezia": "Venesya", "Galeone": "Galeone", "Gilles": "Jil", "Pierre": "Piyer", "Johannes": "Yohannes",
    "Kahle": "Kale", "Paul": "Pol", "Karen": "Keren", "British Museum": "Britiş Myuziyım",
    "Wilusa": "Vilusa", "Tübingen": "Tübingın", "Blegen": "Blegın",
}}


def _respell(text, lang, extra=None):
    """(okunacak metin, {okunuş kelimesi: orijinal kelime}) döner. extra: videoya özel okunuşlar."""
    back = {}
    # Uzun isim önce: "New York" içindeki "York" ayrıca değiştirilmesin
    pairs = {**PRONOUNCE.get(lang, {}), **(extra or {})}
    for original, spoken in sorted(pairs.items(), key=lambda kv: -len(kv[0])):
        if not original or not spoken or original == spoken:
            continue
        if re.search(rf"\b{re.escape(original)}\b", text):
            text = re.sub(rf"\b{re.escape(original)}\b", spoken, text)
            back.update(zip(spoken.split(), original.split()))
    return text, back


def _restore(words, back):
    for w in words:
        for spoken, original in back.items():
            # ekler korunur (Stonhenç'den -> Stonehenge'den); "Kalesi" gibi kelimeler Kahle'ye dönmez
            if w["text"] == spoken or w["text"].startswith((spoken + "'", spoken + "’")):
                w["text"] = original + w["text"][len(spoken):]
                break
    return words


async def _synthesize(text, out_path, voice, rate):
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # eski sürümler kelime sınırını varsayılan gönderir
        comm = edge_tts.Communicate(text, voice, rate=rate)
    words = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
    return words


def _piper_voice(name):
    if name not in _piper:
        from piper import PiperVoice
        from piper.download_voices import download_voice
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        if not (PIPER_DIR / f"{name}.onnx").exists():
            download_voice(name, PIPER_DIR)
        _piper[name] = PiperVoice.load(PIPER_DIR / f"{name}.onnx")
    return _piper[name]


def _synthesize_piper(text, out_path, lang, speaker="male", pace=PIPER_PACE):
    """Piper kelime zamanı vermez: her cümlenin süresi kelimelerine harf sayısıyla orantılı paylaştırılır."""
    from piper import SynthesisConfig
    voice = _piper_voice(PIPER_VOICES[(lang, speaker)])
    wav_path = Path(out_path).with_suffix(".wav")
    words, clock = [], 0.0
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(voice.config.sample_rate)
        for sentence in filter(None, (s.strip() for s in re.split(r"(?<=[.!?…])\s+", text))):
            frames = b"".join(c.audio_int16_bytes for c in
                              voice.synthesize(sentence, syn_config=SynthesisConfig(length_scale=pace)))
            wav.writeframes(frames)
            duration = len(frames) / 2 / voice.config.sample_rate
            tokens = sentence.split()
            weights = [len(t) + 1 for t in tokens]
            for token, weight in zip(tokens, weights):
                span = duration * weight / sum(weights)
                words.append({"text": token.strip(".,!?…:;\"'“”"), "start": clock, "end": clock + span})
                clock += span
    # Edge sesiyle aynı düzeye getirilir ki fon müziği dengesi değişmesin
    pitch = PIPER_PITCH.get((lang, speaker))
    rate = voice.config.sample_rate
    shift = f"asetrate={rate * pitch:.0f},aresample={rate},atempo={1 / pitch:.4f}," if pitch else ""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-af", f"{shift}loudnorm=I=-17:TP=-1.5",
                    "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)], check=True)
    wav_path.unlink()
    return [w for w in words if w["text"]]


def _rate_factor(rate):
    return 1 + int(rate.strip("%+") or 0) / 100


def _gemini(text, out_path, model, speaker, rate):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise VoiceDown("GEMINI_API_KEY yok")
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICES[speaker]}}}}}
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                out = json.load(resp)
            part = out["candidates"][0]["content"]["parts"][0]
            pcm = base64.b64decode(part["inlineData"]["data"])
            if len(pcm) < 4800:  # 0,1 saniyeden kısa: ses gelmedi
                raise ValueError("boş ses")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            wait = re.search(r'"retryDelay":\s*"(\d+)', detail)
            # Dakikalık sınır beklenir; günlük kota bittiyse bu model bu çalışmada bırakılır
            if exc.code == 429 and "PerDay" not in detail and wait and int(wait.group(1)) <= 70 and attempt < 3:
                time.sleep(int(wait.group(1)) + 1)
                continue
            if exc.code >= 500 and attempt < 2:
                time.sleep(5)
                continue
            raise VoiceDown(f"HTTP {exc.code}: {detail[:200]}")
        except (KeyError, IndexError, ValueError) as exc:
            if attempt < 2:
                continue
            raise VoiceDown(f"ses gelmedi ({exc})")
    rate_hz = 24000
    wav_path = Path(out_path).with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate_hz)
        wav.writeframes(pcm)
    factor = _rate_factor(rate)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-af",
                    f"atempo={factor:.3f},loudnorm=I=-17:TP=-1.5", "-ar", "24000", "-c:a", "libmp3lame",
                    "-b:a", "96k", str(out_path)], check=True)
    wav_path.unlink()
    return _estimate_words(text, len(pcm) / 2 / rate_hz / factor)


def _estimate_words(text, duration):
    """Gemini kelime zamanı vermez: süre kelimelere harf sayısıyla orantılı paylaştırılır, cümle sonlarında
    konuşmacının verdiği kısa duraklama için pay bırakılır."""
    tokens = text.split()
    weights = [len(t) + 1 + (4 if t[-1:] in ".!?…" else 2 if t[-1:] in ",;:" else 0) for t in tokens]
    words, clock = [], 0.0
    for token, weight in zip(tokens, weights):
        span = duration * weight / sum(weights)
        words.append({"text": token.strip(".,!?…:;\"'“”"), "start": clock, "end": clock + span * 0.85})
        clock += span
    return [w for w in words if w["text"]]


def _tiers(lang, speaker):
    """Bu konuşmacı için denenecek sesler, sırayla."""
    return ([("gemini", m) for m in GEMINI_MODELS] + [("edge", v) for v in EDGE_VOICES[lang][speaker]]
            + [("piper", PIPER_VOICES[(lang, speaker)])])


def _speak(tier, item):
    engine, name = tier
    text, out, lang, speaker, rate = item["text"], item["out"], item["lang"], item["speaker"], item["rate"]
    if engine == "gemini":  # Gemini yabancı isimleri kendisi doğru okur; okunuş yazımı gerekmez
        return _gemini(text, out, name, speaker, rate)
    spoken, back = _respell(text, lang, item.get("pronounce") if lang == "tr" else None)
    if engine == "edge":
        try:
            words = asyncio.run(_synthesize(spoken, out, name, rate))
        except Exception as exc:
            raise VoiceDown(f"{type(exc).__name__}: {str(exc)[:80]}")
        if not words:
            raise VoiceDown("kelime zamanı gelmedi")
        return _restore(words, back)
    pace = PIPER_PACE * (1 + 0.15) / _rate_factor(rate)  # Edge hızına denk
    return _restore(_synthesize_piper(spoken, out, lang, speaker, pace), back)


def speak_all(items):
    """items: [{text, out, lang, speaker, rate, pronounce}] -> her biri için kelime listesi.
    Her konuşmacı (dil + cinsiyet) baştan sona tek sesle okunur."""
    results = [None] * len(items)
    used = {}  # konuşmacı -> önceki cümlelerinin okunduğu basamak
    for n, item in enumerate(items):
        key = (item["lang"], item["speaker"])
        tiers = _tiers(*key)
        while True:
            index = _choice.get(key, 0)
            while tiers[index] in _down and index < len(tiers) - 1:
                index += 1
            _choice[key] = index
            try:
                if key in used and used[key] != index:
                    # Ses değişti: bu konuşmacının önceki cümleleri de yeni sesle okunur
                    print(f"{key[0]}/{key[1]} konuşmacısının önceki cümleleri yeni sesle yeniden okunuyor")
                    for m in range(n):
                        if (items[m]["lang"], items[m]["speaker"]) == key:
                            results[m] = _speak(tiers[index], items[m])
                results[n] = _speak(tiers[index], item)
                used[key] = index
                break
            except VoiceDown as exc:
                if index == len(tiers) - 1:
                    raise
                print(f"Ses kullanılamadı ({tiers[index][0]} {tiers[index][1]}: {exc}); sıradaki sese geçiliyor")
                _down.add(tiers[index])
    for key, index in sorted(_choice.items()):
        engine, name = _tiers(*key)[index]
        print(f"Seslendirme {key[0]}/{key[1]}: {engine} {name}")
    return results


def synthesize(text, out_path, lang="tr", speaker="male", rate=RATE, pronounce=None):
    """Tek parça seslendirme; sesi out_path'e yazar, [{text, start, end}] kelime listesini döner (saniye)."""
    return speak_all([{"text": text, "out": out_path, "lang": lang, "speaker": speaker, "rate": rate,
                       "pronounce": pronounce}])[0]
