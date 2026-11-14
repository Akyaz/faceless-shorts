"""Videonun seslendirme metninden SRT altyazı.

YouTube'un Türkçe otomatik altyazısı özel isimlerde çok hata yapıyor (Organize İşler, Omar Sy). Seslendirmenin birebir
metni altyazı olarak yüklenince YouTube araması, Google ve yapay zekâ araçları videonun ne anlattığını doğru okur
(14 Kasım 2026, bulunabilirlik çalışması). Metin metadata.json'da "captions" alanında taşınır; panelden sonradan
yapılan yükleme de altyazıyı alır (pipeline/upload.py).
"""
import re

MAX_WORDS = 10  # bir altyazı satırı: ekranda okunacak kadar kısa


NUMBER_WORDS = {"bin", "milyon", "milyar", "trilyon", "yüz"}


def _number(word):
    return word[:1].isdigit() or word.lower().strip(".,") in NUMBER_WORDS


def _chunks(text):
    """Cümlelere, uzun cümleyi en fazla MAX_WORDS kelimelik parçalara böler."""
    out = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        words = sentence.split()
        while words:
            n = min(MAX_WORDS, len(words))
            if len(words) - MAX_WORDS in (1, 2):  # sona tek-iki kelime kalmasın
                n = (len(words) + 1) // 2
            # Sayı ortadan bölünmesin ("2 milyon | 684 bin 738 araç")
            cut = n
            while 0 < cut < len(words) and _number(words[cut - 1]) and _number(words[cut]):
                cut -= 1
            take = words[:cut or n]
            out.append(" ".join(take))
            words = words[len(take):]
    return [c for c in out if c]


def cues(lines):
    """lines: [(başlangıç sn, süre sn, metin)] → [(başlangıç, bitiş, metin)].
    Satırın süresi parçalara harf sayısına göre dağıtılır (seslendirme hızı sabit)."""
    found = []
    for start, duration, text in lines:
        parts = _chunks(text)
        total = sum(len(p) for p in parts) or 1
        clock = start
        for p in parts:
            span = duration * len(p) / total
            found.append((clock, clock + span, p))
            clock += span
    return found


def _stamp(seconds):
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(lines):
    return "".join(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{t}\n\n" for n, (a, b, t) in enumerate(cues(lines), 1))
