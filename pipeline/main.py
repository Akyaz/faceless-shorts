"""Gündem Short'u üretir: haber -> metin -> ses -> video.

Kullanım: python -m pipeline.main [--mode story|world|trend|digest|morning|sports] [--out out] [--offline] [--history dosya.json]
--mode story tek gündem haberini anlatır (varsayılan), world dünya gündeminden bir haberi İngilizce anlatır; digest günün öne çıkan haberlerini, sports spor gündemini,
trend bilim ve teknolojiden merak uyandıran gelişmeleri özetler.
--offline ağ olmadan sahte haber ve sessiz ses ile render'ı dener.
--script ile metni elle yazılmış bir video üretilir (bkz. scripts/custom/); haber çekilmez.
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
    "tr": {"summary": "Videoda:", "subscribe": "Günün haberleri her gün kısa ve net. Kaçırmamak için kanala abone ol.",
           "subscribe_long": "Yeni videoları kaçırmamak için kanala abone ol.", "chapters": "Bölümler:",
           "sources": "Kaynaklar:", "images": "Görseller temsilidir.", "tags": ["son dakika", "türkiye", "shorts"]},
    "en": {"summary": "In this video:", "subscribe": "World news in under a minute, every day. Subscribe so you don't miss it.",
           "subscribe_long": "Subscribe so you don't miss the next one.", "chapters": "Chapters:",
           "sources": "Sources:", "images": "Images are illustrative.", "tags": ["breaking news", "world", "shorts"]},
}


def _credit(line, lang):
    """Görsel ve müzik künyeleri Türkçe üretilir; İngilizce videoda etiketleri çevrilir."""
    if lang != "en" or not line:
        return line
    return (line.replace("Görsel: ", "Image: ").replace("Müzik: ", "Music: ").replace("Bilinmiyor", "Unknown")
            .replace("yapay zekâ ile üretilmiş temsili illüstrasyon", "AI-generated illustration"))


def _summary(plan):
    """Videoda söylenenler açıklamaya da yazılır: izleyici cevabı açıklamada da bulabilsin."""
    lines = []
    for seg in plan["segments"]:
        if seg.get("kind") == "item":
            lines.append(f"• {seg['heading']}: {seg['text']}" if seg.get("heading") else f"• {seg['text']}")
        elif seg.get("kind") == "story":
            lines.append(seg["text"])
    return "\n".join(lines)


def build_metadata(plan, mode="story"):
    lang = plan.get("lang", "tr")
    text = DESCRIPTION[lang]
    # Haber kümesindeki bütün yayınlar: metin yalnızca en üstteki başlığa dayanmıyor
    cluster = [x for h in plan["sources"] for x in [h] + h.get("related", [])[:6]]
    sources = "\n".join(f"- {x['title']} ({x['source']})" for x in cluster)
    tags = list(dict.fromkeys(plan.get("hashtags") or ["gündem", "haber"]))
    image_credit, music_credit = _credit(plan.get("image_credit"), lang), _credit(plan.get("music_credit"), lang)
    wide = plan.get("wide")  # yatay uzun video Short değildir: #shorts etiketi ve "bir dakikada" vaadi yok
    chapters = plan.get("chapters") or []
    summary = "" if wide else _summary(plan)  # uzun videoda bölüm listesi aynı işi görür
    return {
        "title": plan["title"][:100],
        "description": f"{plan['title']}\n\n"
                       + (f"{text['summary']}\n{summary}\n\n" if summary else "")
                       + f"{text['subscribe_long' if wide else 'subscribe']}\n\n"
                       + (f"{text['chapters']}\n" + "\n".join(chapters) + "\n\n" if chapters else "")
                       + f"{text['sources']}\n{sources}\n"
                       + (f"\n{text['images']}\n{image_credit}\n" if image_credit else "")
                       + (f"\n{music_credit}\n" if music_credit else "")
                       + "\n" + " ".join(f"#{t}" for t in tags + ([] if wide else ["shorts"])),
        "tags": tags + [t for t in text["tags"] if not (wide and t == "shorts")],
        "category": plan.get("category") or CATEGORIES.get(mode, "25"),
        "language": lang,
    }


def find_images(plan, work):
    """Her segment için arka plan dosyası (yoksa None) ve kaynak satırları."""
    segments = plan["segments"]
    if any(plan.get("sections") or []):
        return _section_images(plan, work)
    if plan.get("image_queries") or plan.get("image_prompt") or plan.get("image_files"):
        # Tek haber: görseller paragraflar arasında sırayla döner
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


def _section_images(plan, work):
    """Bölümlü özel metin: her bölüm kendi görsellerini paragrafları arasında döndürür.
    Kendi araması olmayan bölümler (giriş, kapanış) videonun genel görsellerini kullanır."""
    segments, credits = plan["segments"], []
    pools = {}
    for k, section in enumerate(plan["sections"]):
        if not section:
            continue
        count = sum(1 for seg in segments if seg.get("section") == k)
        found = images.find_backgrounds(section, work / f"section{k}", max(count, 1))
        pools[k] = [path for path, _ in found]
        credits += [c for _, c in found]
    general = []
    if any(not pools.get(seg.get("section")) for seg in segments) and (
            plan.get("image_queries") or plan.get("image_files") or plan.get("object_query")):
        found = images.find_backgrounds(plan, work / "general", 4)
        general = [path for path, _ in found]
        credits += [c for _, c in found]
    shown, backgrounds = {}, []
    for seg in segments:
        key = seg.get("section") if pools.get(seg.get("section")) else "general"
        pool = pools.get(key) or general
        shown[key] = shown.get(key, -1) + 1
        backgrounds.append(pool[shown[key] % len(pool)] if pool else None)
    return backgrounds, credits


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def news_plan(args):
    """Haber akışından o saatin videosunu planlar."""
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
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["story", "world", "trend", "digest", "morning", "sports"], default="story")
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--background", help="--offline ile denenecek arka plan görseli")
    ap.add_argument("--history", help="işlenen haberlerin tutulduğu JSON dosyası")
    ap.add_argument("--script", help="metni elle yazılmış videoların JSON dosyası (scripts/custom/ altında)")
    ap.add_argument("--item", type=int, default=1, help="--script dosyasındaki kaçıncı video (1'den başlar)")
    args = ap.parse_args()

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    if args.script:
        # Metni elle yazılmış video: haber çekilmez, dil modeli yalnızca fotoğraf elemede kullanılır
        plan = script.custom_plan(json.loads(Path(args.script).read_text(encoding="utf-8"))[args.item - 1])
        if args.history:  # otomatik videolar aynı konuyu yeniden işlemesin
            save_history(args.history, load_history(args.history), plan)
    else:
        plan = news_plan(args)
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
    if plan.get("pronounce"):
        print("Okunuşlar: " + ", ".join(f"{k} -> {v}" for k, v in plan["pronounce"].items()))

    segments = plan["segments"]
    if args.offline:
        backgrounds, credits = [args.background] * len(segments), []
    else:
        backgrounds, credits = find_images(plan, work)
    plan["image_credit"] = "\n".join(dict.fromkeys(credits)) or None

    # Önce bütün sesler: anlatıcının sesi ortada değişirse önceki parçalar da yeni sesle okunur
    if args.offline:
        spoken = [_offline_audio(seg["text"], work / f"seg{i}.mp3") for i, seg in enumerate(segments)]
    else:
        from .tts import RATE, speak_all
        spoken = speak_all([{"text": seg["text"], "out": work / f"seg{i}.mp3", "lang": plan.get("lang", "tr"),
                             "speaker": "male", "rate": RATE, "pronounce": plan.get("pronounce")}
                            for i, seg in enumerate(segments)])

    parts, chapters, clock = [], [], 0.0
    wide = plan.get("wide")
    for i, seg in enumerate(segments):
        audio = work / f"seg{i}.mp3"
        words = spoken[i]
        card = work / f"card{i}.png"
        ass = work / f"seg{i}.ass"
        part = work / f"seg{i}.mp4"
        if wide:
            # Bölüm başlığı yoksa (giriş) videonun ekran başlığı yazar; renk bölüm boyunca aynı kalır
            card_seg = {**seg, "label": plan.get("label"), "heading": seg.get("heading") or plan.get("hook_title", "")}
            render.draw_wide_card(card_seg, 0 if seg.get("section") is None else seg["section"] + 1, card, backgrounds[i],
                                  lang=plan.get("lang", "tr"))
            render.write_ass(words, ass, wide=True)
            render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1, size=render.WIDE)
        else:
            render.draw_card(seg, i, card, backgrounds[i], plan.get("hook_title", ""), plan.get("label", "GÜNDEM"),
                             lang=plan.get("lang", "tr"))
            render.write_ass(words, ass)
            render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1)
        if seg.get("chapter"):
            chapters.append(f"{_clock(clock)} {seg['chapter']}")
        clock += render.audio_duration(part)
        parts.append(part)

    # YouTube bölümleri 0:00 ile başlamalı ve en az üç tane olmalı
    if wide and chapters:
        if not chapters[0].startswith("0:00 "):
            chapters.insert(0, "0:00 Intro" if plan.get("lang") == "en" else "0:00 Giriş")
        plan["chapters"] = chapters if len(chapters) >= 3 else []

    render.concat(parts, work / "voice.mp4")
    voice = work / "voice.mp4"
    if plan.get("subscribe", True):  # acı haberde abone çağrısı yapılmaz
        render.add_subscribe(voice, work / "voice_sub.mp4", plan.get("lang", "tr"), wide=bool(wide))
        voice = work / "voice_sub.mp4"
    plan["music_credit"] = music.add(voice, plan.get("mood"), out / "short.mp4")
    meta = build_metadata(plan, args.mode)
    for seg in segments:  # haberin tamamı zaten plan["sources"] içinde
        seg.pop("headline", None)
    (out / "metadata.json").write_text(json.dumps({**meta, "plan": plan}, ensure_ascii=False, indent=2))
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
