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

VOICE = "tr-TR-AhmetNeural"
RATE = "+15%"  # Shorts temposu
PIPER_VOICE = "tr_TR-dfki-medium"
PIPER_DIR = Path.home() / ".cache" / "faceless-shorts" / "piper"
PIPER_PACE = 0.87  # Edge'deki +%15 hıza denk
_edge_down = False  # bir kez reddedildiyse aynı çalışmada yeniden denenmez; video tek sesle çıksın
_piper = None


async def _synthesize(text, out_path, voice):
    try:
        comm = edge_tts.Communicate(text, voice, rate=RATE, boundary="WordBoundary")
    except TypeError:  # eski sürümler kelime sınırını varsayılan gönderir
        comm = edge_tts.Communicate(text, voice, rate=RATE)
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


def _piper_voice():
    global _piper
    if _piper is None:
        from piper import PiperVoice
        from piper.download_voices import download_voice
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        if not (PIPER_DIR / f"{PIPER_VOICE}.onnx").exists():
            download_voice(PIPER_VOICE, PIPER_DIR)
        _piper = PiperVoice.load(PIPER_DIR / f"{PIPER_VOICE}.onnx")
    return _piper


def _synthesize_piper(text, out_path):
    """Piper kelime zamanı vermez: her cümlenin süresi kelimelerine harf sayısıyla orantılı paylaştırılır."""
    from piper import SynthesisConfig
    voice = _piper_voice()
    wav_path = Path(out_path).with_suffix(".wav")
    words, clock = [], 0.0
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(voice.config.sample_rate)
        for sentence in filter(None, (s.strip() for s in re.split(r"(?<=[.!?…])\s+", text))):
            frames = b"".join(c.audio_int16_bytes for c in
                              voice.synthesize(sentence, syn_config=SynthesisConfig(length_scale=PIPER_PACE)))
            wav.writeframes(frames)
            duration = len(frames) / 2 / voice.config.sample_rate
            tokens = sentence.split()
            weights = [len(t) + 1 for t in tokens]
            for token, weight in zip(tokens, weights):
                span = duration * weight / sum(weights)
                words.append({"text": token.strip(".,!?…:;\"'“”"), "start": clock, "end": clock + span})
                clock += span
    # Edge sesiyle aynı düzeye getirilir ki fon müziği dengesi değişmesin
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-af", "loudnorm=I=-17:TP=-1.5",
                    "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)], check=True)
    wav_path.unlink()
    return [w for w in words if w["text"]]


def synthesize(text, out_path, voice=VOICE):
    """Sesi out_path'e yazar, [{text, start, end}] kelime listesini döner (saniye)."""
    global _edge_down
    if not _edge_down:
        try:
            words = asyncio.run(_synthesize(text, out_path, voice))
            if words:
                return words
            raise RuntimeError("kelime zamanı gelmedi")
        except Exception as exc:
            _edge_down = True
            print(f"Edge TTS kullanılamadı ({type(exc).__name__}: {str(exc)[:80]}); yedek sese geçiliyor")
    return _synthesize_piper(text, out_path)
