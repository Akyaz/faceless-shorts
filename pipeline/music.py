"""Seslendirmenin altına haberin duygusuna uygun hafif bir fon müziği ekler.

Parçalar assets/music altında durur: Kevin MacLeod (incompetech.com), CC BY 3.0, Wikimedia Commons'tan alındı.
Hepsi aynı ses düzeyine (-20 LUFS) getirilmiş ilk 95 saniyedir; video daha uzunsa baştan döner.
"""
import subprocess
from pathlib import Path

from . import render

MUSIC_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"
TRACKS = {
    "notr": "Deliberate Thought",    # genel haber
    "gergin": "The Complex",         # kriz, afet, uyarı
    "umutlu": "Inspired",            # iyi haber
    "huzunlu": "Heartbreaking",      # kayıp, üzücü olay
}
GAIN_DB = -15  # seslendirmenin yaklaşık 17 LU altı: duyulur ama konuşmayı bastırmaz


def add(video, mood, out_path):
    """Müziği videoya karıştırır, açıklamaya eklenecek kaynak satırını döner."""
    mood = mood if mood in TRACKS else "notr"
    dur = render.audio_duration(video)
    fade = max(dur - 1.5, 0)
    mix = (f"[1:a]volume={GAIN_DB}dB,afade=t=in:d=1,afade=t=out:st={fade:.2f}:d=1.5[m];"
           f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-stream_loop", "-1", "-i", str(MUSIC_DIR / f"{mood}.mp3"),
        "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-t", f"{dur:.2f}",
        "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k",
        "-movflags", "+faststart", str(out_path),
    ], check=True)
    print(f"Müzik: {TRACKS[mood]} ({mood})")
    return f'Müzik: "{TRACKS[mood]}" Kevin MacLeod (incompetech.com), CC BY 3.0'
