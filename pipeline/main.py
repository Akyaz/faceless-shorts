"""Gündem Short'u üretir: haber -> metin -> ses -> video.

Kullanım: python -m pipeline.main [--mode story|world|trend|digest|sports] [--out out] [--offline] [--history dosya.json]
--mode story tek gündem haberini anlatır (varsayılan), world dünya gündeminden bir haberi İngilizce anlatır; digest günün öne çıkan haberlerini, sports spor gündemini,
trend bilim ve teknolojiden merak uyandıran gelişmeleri özetler.
--offline ağ olmadan sahte haber ve sessiz ses ile render'ı dener.
--history story, world ve trend videolarında işlenen haberleri tutar; aynı haber ikinci kez videoya dönmez.
"""
import argparse
import json
import subprocess
from pathlib import Path

from . import images, music, render, script


def _offline_audio(text, out_path):
    words, t = [], 0.0
    for w in text.split():
        dur = 0.08 * len(w) + 0.12
        words.append({"text": w, "start": t, "end": t + dur})
        t += dur + 0.05
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{t:.2f}", "-c:a", "libmp3lame", str(out_path)],
                   check=True)
    return words


HISTORY_KEEP = 150  # günde 7 tek haber ve 8 trend maddesiyle yaklaşık 10 gün


def load_history(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_history(path, history, plan):
    history = history + [{"source": h["title"], "title": plan["title"]} for h in plan["sources"]]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(history[-HISTORY_KEEP:], ensure_ascii=False, indent=2), encoding="utf-8")


CATEGORIES = {"sports": "17", "trend": "28"}  # Spor, Bilim ve Teknoloji; diğerleri 25: Haber ve Politika
DESCRIPTION = {
    "tr": {"subscribe": "Günün haberleri her gün kısa ve net. Kaçırmamak için kanala abone ol.",
           "sources": "Kaynaklar:", "images": "Görseller temsilidir.", "tags": ["son dakika", "türkiye", "shorts"]},
    "en": {"subscribe": "World news in under a minute, every day. Subscribe so you don't miss it.",
           "sources": "Sources:", "images": "Images are illustrative.", "tags": ["breaking news", "world", "shorts"]},
}


def _credit(line, lang):
    """Görsel ve müzik künyeleri Türkçe üretilir; İngilizce videoda etiketleri çevrilir."""
    if lang != "en" or not line:
        return line
    return (line.replace("Görsel: ", "Image: ").replace("Müzik: ", "Music: ").replace("Bilinmiyor", "Unknown")
            .replace("yapay zekâ ile üretilmiş temsili illüstrasyon", "AI-generated illustration"))


def build_metadata(plan, mode="story"):
    lang = plan.get("lang", "tr")
    text = DESCRIPTION[lang]
    # Haber kümesindeki bütün yayınlar: metin yalnızca en üstteki başlığa dayanmıyor
    cluster = [x for h in plan["sources"] for x in [h] + h.get("related", [])[:4]]
    sources = "\n".join(f"- {x['title']} ({x['source']})" for x in cluster)
    tags = list(dict.fromkeys(plan.get("hashtags") or ["gündem", "haber"]))
    image_credit, music_credit = _credit(plan.get("image_credit"), lang), _credit(plan.get("music_credit"), lang)
    return {
        "title": plan["title"][:100],
        "description": f"{plan['title']}\n\n{text['subscribe']}\n\n{text['sources']}\n{sources}\n"
                       + (f"\n{text['images']}\n{image_credit}\n" if image_credit else "")
                       + (f"\n{music_credit}\n" if music_credit else "")
                       + "\n" + " ".join(f"#{t}" for t in tags + ["shorts"]),
        "tags": tags + text["tags"],
        "category": CATEGORIES.get(mode, "25"),
        "language": lang,
    }


def find_images(plan, work):
    """Her segment için arka plan dosyası (yoksa None) ve kaynak satırları."""
    segments = plan["segments"]
    if plan.get("image_queries") or plan.get("image_prompt"):  # tek haber: görseller paragraflar arasında döner
        found = images.find_backgrounds(plan, work, len(segments))
        paths = [path for path, _ in found]
        return [paths[i % len(paths)] if paths else None for i in range(len(segments))], [c for _, c in found]

    per_segment, credits = [None] * len(segments), []
    for i, seg in enumerate(segments):  # toplu özet: her haberin kendi görseli
        if not seg.get("image_queries"):
            continue
        item = {"title": seg.get("heading") or seg["text"], "sources": [seg["headline"]],
                **{k: seg.get(k) for k in ("image_queries", "object_query", "place")}}
        found = images.find_backgrounds(item, work / f"item{i}", 1, per_query=2)
        if found:
            per_segment[i], credit = found[0]
            credits.append(credit)
    # Giriş ilk haberin, kapanış son haberin görselini kullanır
    known = [p for p in per_segment if p]
    if known:
        per_segment[0], per_segment[-1] = per_segment[0] or known[0], per_segment[-1] or known[-1]
    return per_segment, credits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["story", "world", "trend", "digest", "sports"], default="story")
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--background", help="--offline ile denenecek arka plan görseli")
    ap.add_argument("--history", help="işlenen haberlerin tutulduğu JSON dosyası")
    args = ap.parse_args()

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    if args.offline:
        headlines = [{"title": f"Örnek haber başlığı numara {i} burada yer alıyor", "source": "Örnek Kaynak",
                      "link": ""} for i in range(1, 4)]
    else:
        from .news import fetch_headlines
        if args.mode == "trend":  # iki akış sırayla karıştırılır, ikisinde de çıkan haber bir kez alınır
            mixed = [h for pair in zip(fetch_headlines(20, "science"), fetch_headlines(20, "technology")) for h in pair]
            headlines = list({h["title"]: h for h in mixed}.values())
        else:
            headlines = fetch_headlines(limit=30, topic=args.mode if args.mode in ("sports", "world") else "top")
    single = args.mode in script.STORIES
    if args.mode in ("story", "world", "trend") and not args.offline:
        # Can kaybı ve ağır suç haberleri tek başına videoya dönmez; günün özetinde sade bir dille geçer
        from .news import sensitive_headline
        calm = [h for h in headlines if not sensitive_headline(h)]
        print(f"Hassas içerik nedeniyle ayrılan haber: {len(headlines) - len(calm)}")
        headlines = calm or headlines
    if single and not args.offline:
        # Tek başlıktan 80 kelimelik metin çıkmaz, model boşluğu uydurarak doldurur; en az üç başlığı olan haber aranır
        rich = [h for h in headlines if len(h.get("related", [])) >= 2]
        print(f"Yeterli kaynağı olan haber: {len(rich)}/{len(headlines)}")
        headlines = rich if len(rich) >= 3 else headlines
    # Günün özeti ve spor, günün haberlerini yeniden anar; tekrar kaydı tek haber ve trend videoları içindir
    use_history = bool(args.history) and args.mode in ("story", "world", "trend")
    history = load_history(args.history) if use_history else []
    used = {h["source"] for h in history}
    fresh = [h for h in headlines if h["title"] not in used]
    if fresh:
        headlines = fresh
    else:
        print("Yeni haber yok, işlenmiş haberler yeniden kullanılacak.")
    plan = script.build_script(headlines, args.mode, recent=[h["title"] for h in history[-12:]])
    if use_history:
        save_history(args.history, history, plan)
    for src in plan["sources"]:
        print(f"Kaynak başlık: {src['title']} ({src['source']})")
        for r in src.get("related", []):
            print(f"  ilgili: {r['title']} ({r['source']})")
    print(f"Başlık: {plan['title']}")
    if plan.get("hook_title"):
        print(f"Ekran başlığı: {plan['hook_title']}")
    for seg in plan["segments"]:
        heading = f"{seg['heading']}: " if seg.get("heading") else ""
        print(f"  [{seg['kind']}] {heading}{seg['text']}")

    segments = plan["segments"]
    if args.offline:
        backgrounds, credits = [args.background] * len(segments), []
    else:
        backgrounds, credits = find_images(plan, work)
    plan["image_credit"] = "\n".join(dict.fromkeys(credits)) or None

    parts = []
    for i, seg in enumerate(segments):
        audio = work / f"seg{i}.mp3"
        if args.offline:
            words = _offline_audio(seg["text"], audio)
        else:
            from .tts import synthesize
            words = synthesize(seg["text"], audio, plan.get("lang", "tr"))
        card = work / f"card{i}.png"
        ass = work / f"seg{i}.ass"
        render.draw_card(seg, i, card, backgrounds[i], plan.get("hook_title", ""), plan.get("label", "GÜNDEM"),
                         subscribe=i == len(segments) - 1, lang=plan.get("lang", "tr"))
        render.write_ass(words, ass)
        part = work / f"seg{i}.mp4"
        render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1)
        parts.append(part)

    render.concat(parts, work / "voice.mp4")
    plan["music_credit"] = music.add(work / "voice.mp4", plan.get("mood"), out / "short.mp4")
    meta = build_metadata(plan, args.mode)
    for seg in segments:  # haberin tamamı zaten plan["sources"] içinde
        seg.pop("headline", None)
    (out / "metadata.json").write_text(json.dumps({**meta, "plan": plan}, ensure_ascii=False, indent=2))
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
