"""Tarih gibi konularda 8-12 dakikalık yatay video: iki kişinin diyaloğuyla açılır, bölüm bölüm anlatır.

Kullanım: python -m pipeline.longform scripts/longform/<ad>.json [--out out]
          python -m pipeline.longform --next   (sıradaki yayınlanmamış metnin yolunu yazar)
Metin dosyasının alanları için scripts/longform/README.md dosyasına bakın. Metinler elle yazılır ve kaynaklarla
karşılaştırılır; bu modül yalnızca görselleri bulur, seslendirir ve videoyu birleştirir.
"""
import argparse
import json
import math
import re
from pathlib import Path

from . import images, music, render
from .tts import synthesize

RATE = "-5%"  # belgesel temposu: Shorts hızı uzun anlatımda yorar
MUSIC_GAIN_DB = -21  # konuşma uzun; müzik Shorts'takinden daha geride
CHAPTER_CARD_SECONDS = 3.5
LINES_PER_IMAGE = 2  # görsel her iki konuşmada bir değişir
PAUSE = 0.45  # konuşmalar arasında nefes payı
TEXT = {
    "tr": {"intro": "Giriş", "subscribe": "Tarihin az bilinen hikâyelerini kaçırmamak için kanala abone ol.",
           "sources": "Kaynaklar:", "images": "Görseller (Wikimedia Commons):",
           "public": "Kamu malı görseller ayrıca listelenmemiştir.", "unknown": "Bilinmiyor"},
    "en": {"intro": "Introduction", "subscribe": "Subscribe for more of history's untold stories.",
           "sources": "Sources:", "images": "Images (Wikimedia Commons):",
           "public": "Public domain images are not listed separately.", "unknown": "Unknown"},
}
FREE = re.compile(r"^(public domain|pd|cc0)", re.I)


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _credits(lines, lang):
    """Görsel künyeleri kısaltılır: açıklama 5000 karakterle sınırlı, uzun videoda onlarca görsel var."""
    seen = []
    for line in lines:
        match = re.match(r"Görsel: (.*), ([^,]+), Wikimedia Commons", line)
        if not match or FREE.match(match.group(2).strip()):
            continue
        artist = match.group(1).replace("Bilinmiyor", TEXT[lang]["unknown"])
        entry = f"{artist[:60]} ({match.group(2).strip()})"
        if entry not in seen:
            seen.append(entry)
    return seen


def _silence(seconds, out_path):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", f"{seconds:.2f}", "-c:a", "libmp3lame", str(out_path)], check=True)
    return out_path


def build(script, out):
    lang = script.get("lang", "tr")
    text = TEXT[lang]
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    speakers = script["speakers"]
    order = list(speakers)  # konuşmacı sırası rengini belirler

    parts, chapters, credits, clock, used = [], [], [], 0.0, set()
    for c, chapter in enumerate(script["chapters"]):
        lines = chapter["lines"]
        count = max(2, math.ceil(len(lines) / LINES_PER_IMAGE))
        plan = {"title": f"{script['topic']}: {chapter['heading']}", "sources": [{"title": chapter["heading"]}],
                "kind": "history", "era": script.get("era", ""),
                "place": {"country": chapter.get("country", script.get("country", "")),
                          "city": chapter.get("city", "")},
                "image_queries": chapter.get("image_queries", []), "image_files": chapter.get("image_files", []),
                "object_query": ""}
        found = images.find_backgrounds(plan, work / f"chapter{c}", count, per_query=4, exclude=used)
        pool = [path for path, _ in found]
        credits += [credit for _, credit in found]
        print(f"Bölüm {c + 1}: {chapter['heading']} | {len(lines)} konuşma, {len(pool)} görsel")

        chapters.append(f"{_clock(clock)} {chapter['heading'] if c else text['intro']}")
        if c:  # ilk bölüm diyalogla doğrudan başlar; sonrakilerden önce bölüm kartı
            card = work / f"c{c}.png"
            render.draw_wide_card({"label": script["label"], "heading": chapter["heading"], "chapter_card": True},
                                  c, card, pool[0] if pool else None, lang=lang)
            parts.append((card, _silence(CHAPTER_CARD_SECONDS, work / f"c{c}.mp3"), []))
            clock += CHAPTER_CARD_SECONDS
        for i, line in enumerate(lines):
            who = speakers[line["s"]]
            audio = work / f"c{c}l{i}.mp3"
            words = synthesize(line["t"], audio, lang, who["voice"], RATE)
            card = work / f"c{c}l{i}.png"
            background = pool[(i // LINES_PER_IMAGE) % len(pool)] if pool else None
            render.draw_wide_card({"label": script["label"], "heading": chapter["heading"], "small_heading": True,
                                   "speaker": who["name"], "speaker_index": order.index(line["s"])},
                                  c, card, background, lang=lang)
            parts.append((card, audio, words))
            clock += render.audio_duration(audio) + PAUSE

    clips = []
    for n, (card, audio, words) in enumerate(parts):
        ass, clip = work / f"p{n}.ass", work / f"p{n}.mp4"
        render.write_ass(words, ass, wide=True)
        render.render_segment(card, audio, ass, clip, pad=PAUSE if words else 0, zoom_out=n % 2 == 1, size=render.WIDE)
        clips.append(clip)
    render.concat(clips, work / "voice.mp4")
    music_credit = music.add(work / "voice.mp4", script.get("mood", "notr"), out / "video.mp4", MUSIC_GAIN_DB)
    duration = render.audio_duration(out / "video.mp4")

    if lang == "en":
        music_credit = music_credit.replace("Müzik: ", "Music: ")
    sources = "\n".join(f"- {s['title']}: {s['url']}" for s in script["sources"])
    image_lines = _credits(credits, lang)
    description = (f"{script['description']}\n\n{text['subscribe']}\n\n" + "\n".join(chapters)
                   + f"\n\n{text['sources']}\n{sources}\n\n{music_credit}\n\n"
                   + " ".join(f"#{t}" for t in script.get("hashtags", [])))
    # Görsel künyeleri sığdığı kadar eklenir; YouTube açıklaması 5000 karakterle sınırlı
    room = 4900 - len(description) - len(text["images"]) - len(text["public"]) - 10
    listed = []
    for entry in image_lines:
        if sum(len(e) + 2 for e in listed) + len(entry) > room:
            break
        listed.append(entry)
    description = description.replace(f"\n\n{music_credit}", f"\n\n{text['images']} {'; '.join(listed)}. "
                                      f"{text['public']}\n\n{music_credit}")
    meta = {"title": script["title"][:100], "description": description[:5000],
            "tags": script.get("tags", []), "category": "27", "language": lang}
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(chapters))
    print(f"Hazır: {out / 'video.mp4'} ({_clock(duration)})")
    if not 7.5 * 60 <= duration <= 12.5 * 60:
        print(f"Uyarı: süre 8-12 dakika aralığının dışında ({_clock(duration)})")


QUEUE = Path(__file__).resolve().parent.parent / "scripts" / "longform" / "queue.txt"


def next_in_queue():
    """Sıradaki, henüz YouTube'a yüklenmemiş metin; panel kaydından (panel-data dalı) bakılır."""
    from .report import BRANCH, FEED, _github
    import base64
    import os
    published = set()
    try:
        data = _github("GET", f"/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{FEED}?ref={BRANCH}")
        for entry in json.loads(base64.b64decode(data["content"])):
            if entry.get("script") and any(v.get("url") for v in entry.get("videos", [])):
                published.add(entry["script"])
    except Exception as exc:
        print(f"Panel kaydı okunamadı, sıra baştan alınır: {exc}", file=__import__("sys").stderr)
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        path = line.split("#")[0].strip()
        if path and path not in published:
            return path
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?")
    ap.add_argument("--out", default="out")
    ap.add_argument("--next", action="store_true", help="sıradaki metnin yolunu yaz ve çık")
    args = ap.parse_args()
    if args.next:
        print(next_in_queue())
        return
    build(json.loads(Path(args.script).read_text(encoding="utf-8")), Path(args.out))


if __name__ == "__main__":
    main()
