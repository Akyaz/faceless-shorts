"""Türkçe seslendirme ve kelime zamanlamaları.

Önce Edge TTS denenir. Microsoft bu servisi zaman zaman GitHub sunucularına kapatıyor (403); o durumda
video çıkmamasın diye bilgisayarda çalışan açık kaynak Piper sesine geçilir.
"""
import asyncio
import re
import subprocess
import wave
from pathlib import Path

import edge_tts

# Diyaloglu uzun videolarda iki konuşmacı ayrı seslerle konuşur
VOICES = {"tr": {"male": "tr-TR-AhmetNeural", "female": "tr-TR-EmelNeural"},
          "en": {"male": "en-US-GuyNeural", "female": "en-US-JennyNeural"}}
RATE = "+15%"  # Shorts temposu
PIPER_VOICES = {("tr", "male"): "tr_TR-dfki-medium", ("tr", "female"): "tr_TR-dfki-medium",
                ("en", "male"): "en_US-ryan-medium", ("en", "female"): "en_US-lessac-medium"}
# Piper'da Türkçe kadın sesi yok; iki konuşmacı ayırt edilebilsin diye aynı ses biraz inceltilir
PIPER_PITCH = {("tr", "female"): 1.12}
PIPER_DIR = Path.home() / ".cache" / "faceless-shorts" / "piper"
PIPER_PACE = 0.87  # Edge'deki +%15 hıza denk
# Reddedilen ses aynı çalışmada yeniden denenmez; böylece her konuşmacı video boyunca tek sesle konuşur.
# Ses bazında tutulur: Edge bir sesi (ör. tr-TR-AhmetNeural) kapatınca diğer konuşmacı Edge'de kalabilsin.
_edge_down = set()
_piper = {}

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


def synthesize(text, out_path, lang="tr", speaker="male", rate=RATE, pronounce=None):
    """Sesi out_path'e yazar, [{text, start, end}] kelime listesini döner (saniye).
    speaker: "male" ya da "female"; rate: Edge hızı ("+0%" uzun anlatım için daha rahat)."""
    voice = VOICES[lang][speaker]
    text, back = _respell(text, lang, pronounce if lang == "tr" else None)
    if voice not in _edge_down:
        try:
            words = asyncio.run(_synthesize(text, out_path, voice, rate))
            if words:
                return _restore(words, back)
            raise RuntimeError("kelime zamanı gelmedi")
        except Exception as exc:
            _edge_down.add(voice)
            print(f"Edge TTS {voice} kullanılamadı ({type(exc).__name__}: {str(exc)[:80]}); bu ses için yedek sese geçiliyor")
    pace = PIPER_PACE * (1 + 0.15) / (1 + int(rate.strip("%+") or 0) / 100)  # Edge hızına denk
    return _restore(_synthesize_piper(text, out_path, lang, speaker, pace), back)
