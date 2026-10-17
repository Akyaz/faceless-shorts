"""Seslendirme ve kelime zamanlamaları.

Ses sırası: Gemini (en doğal; ücretsiz kotası var) -> Microsoft Edge -> Piper (bilgisayarda çalışan, mekanik).
Bir konuşmacının sesi video ortasında değişmez: kullandığı ses düşerse o konuşmacının o ana kadarki bütün
cümleleri yeni sesle baştan okunur (speak_all). Cinsiyet her basamakta korunur.
"""
import array
import asyncio
import base64
import json
import math
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


GEMINI_RATE_HZ = 24000
BATCH_CHARS = 1400  # tek istekte okunacak en fazla metin; uzun ses bölünürken kayma riski artar


def _gemini_request(text, model, voices):
    """voices: {konuşmacı etiketi: ses adı}. Tek ses ya da iki kişilik diyalog; ham PCM döner."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise VoiceDown("GEMINI_API_KEY yok")
    if len(voices) == 1:
        speech = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": next(iter(voices.values()))}}}
    else:
        speech = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": label, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": name}}}
            for label, name in voices.items()]}}
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech}}
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                out = json.load(resp)
            pcm = base64.b64decode(out["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            if len(pcm) < 4800:  # 0,1 saniyeden kısa: ses gelmedi
                raise ValueError("boş ses")
            return pcm
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
            quota = re.findall(r'"quotaId":\s*"([^"]+)"[^}]*?"quotaValue":\s*"(\d+)"', detail, re.S)
            reason = "; ".join(f"{q} sınırı {v}" for q, v in quota) or detail[:200]
            raise VoiceDown(f"HTTP {exc.code}: {reason}")
        except (KeyError, IndexError, ValueError) as exc:
            if attempt < 2:
                continue
            raise VoiceDown(f"ses gelmedi ({exc})")


def _write_pcm(pcm, text, out_path, rate):
    wav_path = Path(out_path).with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(GEMINI_RATE_HZ)
        wav.writeframes(pcm)
    factor = _rate_factor(rate)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-af",
                    f"atempo={factor:.3f},loudnorm=I=-17:TP=-1.5", "-ar", "24000", "-c:a", "libmp3lame",
                    "-b:a", "96k", str(out_path)], check=True)
    wav_path.unlink()
    return _estimate_words(text, len(pcm) / 2 / GEMINI_RATE_HZ / factor)


def _silences(pcm, frame=480, min_frames=8):
    """20 ms'lik pencerelerde sessiz aralıklar: [(başlangıç örneği, bitiş örneği)]."""
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    levels = []
    for i in range(0, len(samples) - frame, frame):
        chunk = samples[i:i + frame]
        levels.append(math.sqrt(sum(x * x for x in chunk[::4]) / len(chunk[::4])))
    loud = sorted(levels)[int(len(levels) * 0.9)] if levels else 0
    quiet = [lvl < max(120, loud * 0.06) for lvl in levels]
    runs, n = [], 0
    while n < len(quiet):
        if quiet[n]:
            m = n
            while m < len(quiet) and quiet[m]:
                m += 1
            if m - n >= min_frames:
                runs.append((n * frame, m * frame))
            n = m
        else:
            n += 1
    return runs


def _split(pcm, texts):
    """Tek parça sesi metinlere böler: beklenen sınırı (harf oranı) en yakın sessizliğe oturtur.
    Uygun sessizlik bulunamazsa None (o parça cümle cümle okunur)."""
    total = len(pcm) // 2
    weights = [len(t) + 8 for t in texts]
    runs = _silences(pcm)
    cuts, used, acc = [0], set(), 0
    for k in range(len(texts) - 1):
        acc += weights[k]
        expected = total * acc / sum(weights)
        window = max(1.6 * GEMINI_RATE_HZ, total * weights[k] / sum(weights) * 0.45)
        # Yakın ve uzun sessizlik öne çıkar: cümle içindeki kısa duraklama paragraf arasıyla karışmasın
        options = [(abs((a + b) / 2 - expected) / window - (b - a) / (0.5 * GEMINI_RATE_HZ), i)
                   for i, (a, b) in enumerate(runs)
                   if i not in used and (a + b) / 2 > cuts[-1] and abs((a + b) / 2 - expected) <= window]
        if not options:
            return None
        _, i = min(options)
        used.add(i)
        cuts.append(int(sum(runs[i]) / 2))
    cuts.append(total)
    pad = GEMINI_RATE_HZ // 10  # parça başında ve sonunda 0,1 sn nefes payı kalır
    pieces = []
    for a, b in zip(cuts, cuts[1:]):
        lo, hi = a, b
        for x, y in runs:  # kenardaki sessizlik kırpılır
            if x <= lo < y:
                lo = max(lo, y - pad)
            if x < hi <= y:
                hi = min(hi, x + pad)
        pieces.append(pcm[lo * 2:hi * 2])
    return pieces


def _gemini_batch(items, model):
    """Bir grubun (kısa video ya da tarih videosunun bir bölümü) cümlelerini tek istekte okur."""
    labels = list(dict.fromkeys(item.get("name") or item["speaker"] for item in items))
    voices = {label: GEMINI_VOICES[next(i["speaker"] for i in items if (i.get("name") or i["speaker"]) == label)]
              for label in labels}
    if len(voices) > 2 or len(set(voices.values())) < len(voices):
        return [_gemini_one(item, model) for item in items]  # Gemini en fazla iki farklı sesle diyalog okur
    if len(voices) == 1:
        text = "\n\n".join(item["text"] for item in items)
    else:
        text = "\n".join(f"{item.get('name') or item['speaker']}: {item['text']}" for item in items)
    pieces = _split(_gemini_request(text, model, voices), [item["text"] for item in items])
    if pieces is None:
        print(f"Gemini sesi cümlelere bölünemedi ({len(items)} cümle); cümle cümle okunuyor")
        return [_gemini_one(item, model) for item in items]
    return [_write_pcm(piece, item["text"], item["out"], item["rate"]) for piece, item in zip(pieces, items)]


def _gemini_one(item, model):
    label = item.get("name") or item["speaker"]
    pcm = _gemini_request(item["text"], model, {label: GEMINI_VOICES[item["speaker"]]})
    return _write_pcm(pcm, item["text"], item["out"], item["rate"])


def _batches(items):
    """Aynı gruptaki ardışık cümleler, BATCH_CHARS'ı aşmayacak parçalar hâlinde: [[sıra no]]."""
    batches, current, size = [], [], 0
    for n, item in enumerate(items):
        same = current and items[current[-1]].get("group", 0) == item.get("group", 0)
        if current and (not same or size + len(item["text"]) > BATCH_CHARS):
            batches.append(current)
            current, size = [], 0
        current.append(n)
        size += len(item["text"])
    return batches + ([current] if current else [])


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
    """Gemini düştükten sonra bu konuşmacı için denenecek sesler, sırayla."""
    return [("edge", v) for v in EDGE_VOICES[lang][speaker]] + [("piper", PIPER_VOICES[(lang, speaker)])]


def _speak(tier, item):
    engine, name = tier
    text, out, lang, speaker, rate = item["text"], item["out"], item["lang"], item["speaker"], item["rate"]
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


def _speak_gemini(items):
    """Bütün video aynı Gemini modeliyle okunur; model düşerse sıradakiyle baştan. Hiçbiri olmazsa None.
    Gemini yabancı isimleri kendisi doğru okur; okunuş yazımı gerekmez."""
    for model in GEMINI_MODELS:
        if ("gemini", model) in _down:
            continue
        try:
            results = [None] * len(items)
            for batch in _batches(items):
                for n, words in zip(batch, _gemini_batch([items[n] for n in batch], model)):
                    results[n] = words
            print(f"Seslendirme: gemini {model} ({len(_batches(items))} parça)")
            return results
        except VoiceDown as exc:
            print(f"Ses kullanılamadı (gemini {model}: {exc}); video sıradaki sesle baştan okunuyor")
            _down.add(("gemini", model))
    return None


def speak_all(items):
    """items: [{text, out, lang, speaker, rate, pronounce, name?, group?}] -> her biri için kelime listesi.
    name: diyalogda konuşmacının adı; group: birlikte okunabilecek cümleler (ör. aynı bölüm).
    Her konuşmacı baştan sona tek sesle okunur."""
    results = _speak_gemini(items)
    if results is not None:
        return results
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
    for key in dict.fromkeys((i["lang"], i["speaker"]) for i in items):
        engine, name = _tiers(*key)[_choice[key]]
        print(f"Seslendirme {key[0]}/{key[1]}: {engine} {name}")
    return results


def synthesize(text, out_path, lang="tr", speaker="male", rate=RATE, pronounce=None):
    """Tek parça seslendirme; sesi out_path'e yazar, [{text, start, end}] kelime listesini döner (saniye)."""
    return speak_all([{"text": text, "out": out_path, "lang": lang, "speaker": speaker, "rate": rate,
                       "pronounce": pronounce}])[0]
