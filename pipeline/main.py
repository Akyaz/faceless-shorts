"""Gündem Short'u üretir: haber -> metin -> ses -> video.

Kullanım: python -m pipeline.main [--mode story|world|trend|digest|morning|sports|fact] [--out out] [--offline] [--history dosya.json]
--mode story tek gündem haberini anlatır (varsayılan), world dünya gündeminden bir haberi İngilizce anlatır; digest günün öne çıkan haberlerini, sports spor gündemini,
trend bilim ve teknolojiden merak uyandıran gelişmeleri özetler; fact eskimeyen bir "Biliyor muydun?" konusu anlatır
(scripts/evergreen/topics.txt).
--offline ağ olmadan sahte haber ve sessiz ses ile render'ı dener.
--script ile metni elle yazılmış bir video üretilir (bkz. scripts/custom/); haber çekilmez.
--history story, world ve trend videolarında işlenen haberleri tutar; aynı haber ikinci kez videoya dönmez.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path

from . import captions, evergreen, horoscope, images, music, onthisday, platforms, playlists, render, review, scenes, script, trends


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


IMAGES_KEEP = 120  # son kullanılan arama görselleri (yaklaşık 10 gün)


def load_recent_images(path):
    try:
        images.RECENT.update(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def save_recent_images(path):
    try:
        old = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = []
    keep = [u for u in old if u not in images.USED] + images.USED
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(keep[-IMAGES_KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")


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


def _closing_question(plan):
    """Videonun son cümlesi soruysa o soru."""
    last = plan["segments"][-1]["text"].strip() if plan["segments"] else ""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", last) if x.strip()]
    questions = [x for x in sentences if x.endswith("?")]
    return questions[-1] if questions else ""


def _spoken(clock, words, fallback):
    """Konuşmanın videodaki başlangıcı ve süresi: kelime zamanları varsa onlardan, yoksa parçanın tamamı."""
    if words:
        return clock + words[0]["start"], max(0.5, words[-1]["end"] - words[0]["start"])
    return clock, fallback


def build_metadata(plan, mode="story"):
    lang = plan.get("lang", "tr")
    text = {**DESCRIPTION[lang], **(plan.get("texts") or {})}  # türün kendi abone cümlesi ve etiketleri
    # Haber kümesindeki bütün yayınlar: metin yalnızca en üstteki başlığa dayanmıyor
    cluster = [x for h in plan["sources"] for x in [h] + h.get("related", [])[:6]]
    sources = "\n".join(f"- {x['title']} ({x['source']})" + (f": {x['link']}" if x.get("link") else "") for x in cluster)
    tags = list(dict.fromkeys(plan.get("hashtags") or ["gündem", "haber"]))
    image_credit, music_credit = _credit(plan.get("image_credit"), lang), _credit(plan.get("music_credit"), lang)
    wide = plan.get("wide")  # yatay uzun video Short değildir: #shorts etiketi ve "bir dakikada" vaadi yok
    chapters = plan.get("chapters") or []
    summary = "" if wide else _summary(plan)  # uzun videoda bölüm listesi aynı işi görür
    return {
        "title": plan["title"][:100],
        "description": f"{plan['title']}\n\n"
                       + (f"{render.date_line(lang)}\n" if plan.get("dated", True) else "")  # eskimeyen videoda tarih yok
                       + f"{render.channel_line(lang, plan.get('subscribe', True))}\n\n"
                       + (f"{text['summary']}\n{summary}\n\n" if summary else "")
                       + f"{text['subscribe_long' if wide else 'subscribe']}\n\n"
                       + (f"{text['chapters']}\n" + "\n".join(chapters) + "\n\n" if chapters else "")
                       + f"{text['sources']}\n{sources}\n"
                       # Kişinin kendi (resmi arşiv) fotoğrafları temsili değil
                       + (f"\n{'' if plan.get('own_images') else text['images'] + chr(10)}{image_credit}\n"
                          if image_credit else "")
                       + (f"\n{music_credit}\n" if music_credit else "")
                       + "\n" + " ".join(f"#{t}" for t in tags + ([] if wide else ["shorts"])),
        "tags": list(dict.fromkeys(tags + [t for t in text["tags"] if not (wide and t == "shorts")])),
        "category": plan.get("category") or CATEGORIES.get(mode, "25"),
        # Videodaki soru kanal adına ilk yorum olarak yazılır (acı haberde soru ve çağrı yok)
        "comment": _closing_question(plan) if plan.get("subscribe", True) else "",
        "language": lang,
        "playlist": playlists.for_video(mode, plan.get("label")),
    }


def news_context(plan):
    """Adaş denetimi için haberin kendisi (images.same_subject): ilk kaynak başlığı ve videonun ilk iki paragrafı."""
    head = (plan.get("sources") or [{}])[0].get("title", "")
    text = " ".join(s["text"] for s in plan.get("segments", [])[:2]) or " ".join(plan.get("paragraphs", [])[:2])
    return f"{head}. {text}".strip(". ")[:600]


def _subject_support(plan, work, count):
    """Konudaki isimlerin (kişi, kulüp, yapım) Commons'taki diğer fotoğrafları; ana fotoğrafla aynısı hariç."""
    known = set(plan.get("subject_files") or [])
    pool = [c for n in plan.get("subjects") or [] for c in images.subject_photos(n, context=news_context(plan))
            if "File:" + c["about"].split("|")[0].strip().removeprefix("File:") not in known]
    return images.save_direct(list({c["url"]: c for c in pool}.values()), work / "support", count)


def _item_images(seg, plan, out_dir):
    """Özet maddesinin görseli, tek konulu haberle aynı karar (subject_kind): olayda yer alan kişinin fotoğrafı; yoksa
    olayın şehrinin fotoğrafı; o da yoksa görsel yok, madde bilgi kartıyla anlatılır. Ülke düzeyinde genel arama yok:
    sabah özetinde Karadeniz'deki yağış uyarısına güneşli Boğaz, Çin'deki zirveye 2023'teki başka bir zirvenin
    salonu geldi (15 Kasım 2026). Burç kartı gibi elle verilen görsel olduğu gibi kullanılır."""
    item = {"title": seg.get("heading") or seg["text"], "sources": [seg.get("headline") or plan["sources"][0]],
            **{k: seg.get(k) for k in ("image_queries", "object_query", "place", "image_files")}}
    if seg.get("image_files"):
        return images.find_backgrounds(item, out_dir, 1, per_query=2)
    for name in seg.get("subjects") or []:
        own = images.subject_file(name, context=seg["text"])
        if own:
            return images.find_backgrounds({**item, "image_files": [own], "fill_with_search": False}, out_dir, 1)
    return _place_photos(item, out_dir, 1)


def _place_photos(plan, work, count):
    """Kişi haberinde olayın geçtiği şehrin fotoğrafları: yalnızca şehir adını içeren aramalar ("Selimiye Edirne").
    Ülke düzeyinde genel arama ("football stadium Italy") yok. Turnbull'un Edirne ziyaretinde videoda Edirne hiç
    görünmedi (15 Kasım 2026)."""
    city = ((plan.get("place") or {}).get("city") or "").strip()
    key = images._fold(city)
    queries = [q for q in plan.get("image_queries") or [] if key and key in images._fold(q)]
    if not queries:
        return []
    return images.find_backgrounds({**plan, "image_queries": queries, "object_query": "", "image_files": []},
                                   work / "place", count)


def settle_scenes(plan, backgrounds):
    """Görseller bulunduktan sonra videonun nasıl anlatılacağı (ilke: gerçek görüntü; yoksa grafik; o da yoksa video yok):
    - en az MIN_IMAGES farklı gerçek görsel: fotoğraflı video; haberde ilk paragraf hariç en fazla bir kart
    - haber ve her paragrafın kartı var: kartlı video (yeri olmayan haber: burs, zam)
    - ikisi de yoksa video üretilmez. Tek görselli video yok (Gönül Dağı, 15 Kasım 2026). Maç kartları hariç."""
    if plan.get("match"):
        return
    segments = plan["segments"]
    if plan.get("mode") and any(s.get("kind") == "item" for s in segments):
        _settle_digest(plan, backgrounds)
        return
    real = len({b for b in backgrounds if b})
    news = bool(plan.get("mode"))  # bilgi serisi ve elle yazılan metin kendi sahne kararını verir
    if real >= MIN_IMAGES:
        if news:
            kept = 0
            for i, seg in enumerate(segments):
                if seg.get("scene") and (i == 0 or kept >= scenes.NEWS_SCENE_LIMIT):
                    seg.pop("scene")
                elif seg.get("scene"):
                    kept += 1
        return
    if news and segments and all(seg.get("scene") for seg in segments):
        print("Yeterli gerçek görsel yok; video bilgi kartlarıyla anlatılıyor")
        return
    raise RuntimeError(f"Yalnızca {real} görsel bulundu (en az {MIN_IMAGES}) ve kartlar her paragrafı karşılamıyor; "
                       "video üretilmiyor, bu saat atlanıyor.")


def _settle_digest(plan, backgrounds):
    """Özet: kendi görüntüsü olan madde fotoğrafla, olmayan bilgi kartıyla anlatılır; ikisi de yoksa madde çıkar.
    İkiden az madde kalırsa video üretilmez. Listeler yerinde değişir (main'deki segments ve backgrounds)."""
    segments = plan["segments"]
    kept = []
    for seg, bg in zip(segments, backgrounds):
        if seg.get("kind") == "item":
            if bg:
                seg.pop("scene", None)  # fotoğrafın üstünde başlık zaten yazıyor
            elif not seg.get("scene"):
                print(f"Görüntüsü ve kartı olmayan madde çıkarıldı: {seg['text']}")
                continue
        kept.append((seg, bg))
    items = [s for s, _ in kept if s.get("kind") == "item"]
    total, before = len(items), sum(1 for s in segments if s.get("kind") == "item")
    if total < 2:
        raise RuntimeError("Özette görüntüsü ya da kartı olan yeterli madde kalmadı; bu saat atlanıyor.")
    for i, seg in enumerate(items, 1):
        seg["label"] = re.sub(r"\d+/\d+$", f"{i}/{total}", seg.get("label", ""))
    for seg, _ in kept:
        if seg.get("kind") == "intro":
            seg["text"] = review.recount(seg["text"], before, total)
    plan["title"] = review.recount(plan["title"], before, total)
    plan["sources"] = [s["headline"] for s in items if s.get("headline")] or plan["sources"]
    segments[:] = [s for s, _ in kept]
    backgrounds[:] = [b for _, b in kept]


def subject_kind(plan):
    """Görsel kararı konuya göre verilir, video türüne göre değil (15 Kasım 2026: dizi kuralı yalnızca dizi saatinde
    çalışıyordu; gündeme düşen Gönül Dağı videosunun tek görseli bir televizyon stüdyosuydu):
    - "yapim": dizi, film ya da konunun elle verilmiş resmi görselleri; yalnızca onlar.
    - "kisi": haberde adı geçen kişinin, kulübün ya da eserin kendi fotoğrafları; yalnızca onlar.
    - "yer": ikisi de yoksa haberin yeri ve olayı için arama."""
    if plan.get("work_images"):
        return "yapim"
    if plan.get("subject_files"):
        return "kisi"
    return "yer"


def find_images(plan, work):
    """Her segment için arka plan dosyası (yoksa None) ve kaynak satırları."""
    segments = plan["segments"]
    if any(plan.get("sections") or []):
        return _section_images(plan, work)
    kind = subject_kind(plan)
    if kind == "yapim":
        # Yapımın (ya da konunun) resmi görselleri, paragraflar arasında sırayla; başka görsel karışmaz
        own = images.save_direct(plan["work_images"], work / "work", len(segments))
        paths = [p for p, _ in own]
        return [paths[i % len(paths)] if paths else None for i in range(len(segments))], [c for _, c in own]
    if kind == "kisi":
        # Kişinin (kulübün, eserin) kendi fotoğrafı ilk karede ve iki paragrafta bir; aradakiler onun başka
        # fotoğrafları. Genel ortam araması yok: Ronaldinho videosunda stat kapısı geliyordu (15 Kasım 2026)
        own = images.find_backgrounds({**plan, "image_files": plan["subject_files"], "fill_with_search": False},
                                      work / "subject", len(plan["subject_files"]))
        rest = _place_photos(plan, work, max(1, len(segments) // 2))
        rest += _subject_support(plan, work, max(1, len(segments) // 2 - len(rest)))
        mine, other = [p for p, _ in own], [p for p, _ in rest] or [p for p, _ in own]
        backgrounds = [(mine[(i // 2) % len(mine)] if i % 2 == 0 or not other else other[(i // 2) % len(other)])
                       if mine else None for i in range(len(segments))]
        return backgrounds, [c for _, c in own + rest]
    single = all(s.get("kind", "story") == "story" for s in segments)  # özetlerde yer her maddenin kendisinde
    if plan.get("mode") and single and not ((plan.get("place") or {}).get("city") or "").strip():
        # Yeri olmayan haber (burs, zam, sınav): bina araması alakasız görsel getiriyordu; video kartlarla anlatılır.
        # Yalnızca tek konulu haber: sabah özeti bu kural yüzünden hiç görsel aramadı (15 Kasım 2026 denemesi)
        return [None] * len(segments), []
    if plan.get("image_queries") or plan.get("image_prompt") or plan.get("image_files"):
        # Tek haber: görseller paragraflar arasında sırayla döner
        found = images.find_backgrounds(plan, work, len(segments))
        paths = [path for path, _ in found]
        return [paths[i % len(paths)] if paths else None for i in range(len(segments))], [c for _, c in found]

    per_segment, credits = [None] * len(segments), []
    for i, seg in enumerate(segments):  # toplu özet: her haberin kendi görseli (burçta her burcun kartı)
        if seg.get("kind") != "item":
            continue
        found = _item_images(seg, plan, work / f"item{i}")
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


def _draw_scene(scene, words, card, audio, background, look, idx):
    """Animasyonlu sahne kartın yanına (.anim.mp4) yazılır; çizilemezse parça fotoğrafla devam eder."""
    anim = card.with_suffix(".anim.mp4")
    palette = render.PALETTES.get(look.get("palette"), render.ACCENTS)
    try:
        # Parça sesten 0,35 sn uzun (render_segment); sahne biraz daha uzun çizilir ki görüntü erken bitmesin
        scenes.render_scene(scene, words, anim, render.audio_duration(audio) + 0.6, background,
                            palette[idx % len(palette)])
    except Exception as exc:
        anim.unlink(missing_ok=True)
        print(f"Sahne çizilemedi, fotoğraf kullanılıyor: {exc}")


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def news_plan(args, exclude=(), _tries=0):
    """Haber akışından o saatin videosunu planlar. exclude: bu çalışmada elenmiş haberlerin başlıkları."""
    if args.offline:
        headlines = [{"title": f"Örnek haber başlığı numara {i} burada yer alıyor", "source": "Örnek Kaynak",
                      "link": ""} for i in range(1, 4)]
    else:
        from .news import fetch_headlines
        if args.mode == "trend":  # iki akış sırayla karıştırılır, ikisinde de çıkan haber bir kez alınır
            mixed = [h for pair in zip(fetch_headlines(20, "science"), fetch_headlines(20, "technology")) for h in pair]
            headlines = list({h["title"]: h for h in mixed}.values())
        elif args.mode == "platform":  # Netflix Türkiye Top 10 ve platformların yeni yapımları
            headlines = platforms.headlines()
        elif args.mode == "debate":  # tartışılacak bir tercih için geniş havuz: gündem, spor, teknoloji
            feeds = [fetch_headlines(15, t) for t in ("top", "sports", "technology")]
            mixed = [h for group in zip(*feeds) for h in group]
            headlines = list({h["title"]: h for h in mixed}.values())
        elif args.mode == "story" and (searched := trends.headlines(trends.fetch())):
            # Gündem: Türkiye'de Google'da en çok aranan konular (pipeline/trends.py, 15 Kasım 2026 ölçümü)
            headlines = searched
        else:
            topic = ("sports" if args.mode in ("sports", "sportstory") else "world" if args.mode == "world"
                     else "entertainment" if args.mode == "culture" else "top")
            headlines = fetch_headlines(limit=30, topic=topic)
        if args.mode in TREND_BOOSTED:  # aranan konunun haberi öne
            headlines = trends.boost(headlines, trends.fetch())
    single = args.mode in script.STORIES
    if args.mode in ("story", "world", "trend", "debate", "sportstory", "culture", "platform") and not args.offline:
        # Can kaybı ve ağır suç haberleri tek başına videoya dönmez; günün özetinde sade bir dille geçer
        from .news import sensitive_headline
        calm = [h for h in headlines if not sensitive_headline(h)]
        print(f"Hassas içerik nedeniyle ayrılan haber: {len(headlines) - len(calm)}")
        headlines = calm or headlines
    if single and not args.offline:
        # Tek başlıktan 80 kelimelik metin çıkmaz, model boşluğu uydurarak doldurur; en az üç başlığı olan haber aranır
        rich = [h for h in headlines if len(h.get("related", [])) >= 2 or h.get("body")]
        print(f"Yeterli kaynağı olan haber: {len(rich)}/{len(headlines)}")
        headlines = rich if len(rich) >= 3 else headlines
    # Günün özeti ve spor, günün haberlerini yeniden anar; tekrar kaydı tek haber ve trend videoları içindir
    headlines = [h for h in headlines if h["title"] not in exclude] or headlines
    use_history = bool(args.history) and args.mode in ("story", "world", "trend", "debate", "sportstory", "culture", "platform")
    history = load_history(args.history) if use_history else []
    used = {h["source"] for h in history}
    fresh = [h for h in headlines if h["title"] not in used]
    if fresh:
        headlines = fresh
    else:
        print("Yeni haber yok, işlenmiş haberler yeniden kullanılacak.")
    published = published_titles(history) if use_history and not args.offline else []
    try:
        plan = script.build_script(headlines, args.mode, recent=published[-20:])
    except script.TextRejected as exc:
        if _tries >= REVIEW_TRIES:
            raise RuntimeError(f"{exc}; başka haber kalmadı, bu saat atlanıyor.") from exc
        print(f"{exc}; başka haber deneniyor")
        return news_plan(args, exclude=list(exclude) + [exc.headline["title"]], _tries=_tries + 1)
    repeat = repeated(plan, published) if args.mode in REPEAT_CHECKED else ""
    if repeat and not args.offline:
        # Aynı yapımın haberi farklı başlıkla ertesi gün yine seçildi (Bir Başkadır, 15 Kasım 2026): başka haber
        if _tries >= REVIEW_TRIES:
            raise RuntimeError(f"Son videolarda işlenmiş konu ({repeat}); başka haber kalmadı, bu saat atlanıyor.")
        print(f"Son videolarda işlenmiş konu ({repeat}); başka haber deneniyor")
        return news_plan(args, exclude=list(exclude) + [h["title"] for h in plan["sources"]], _tries=_tries + 1)
    if not args.offline:
        try:
            plan = review.check(plan, single)
            # Denetim paragrafı değiştirdiyse kartın satırları metinde aynen geçmeyebilir: yeniden kontrol
            for seg in plan["segments"]:
                if seg.get("scene"):
                    checked = scenes.check(seg["scene"], seg["text"])
                    if checked:
                        seg["scene"] = checked
                    else:
                        del seg["scene"]
        except review.Incomplete as exc:
            # Cevabı kaynaklarda bulunmayan haber atlanır, sıradaki denenir (belirsiz video yayınlanmaz)
            if not single or _tries >= REVIEW_TRIES:
                raise RuntimeError(f"Metin eksik kaldı; bu saatin videosu atlanıyor: {exc}") from exc
            print(f"Metin eksik ({exc}); başka haber deneniyor")
            return news_plan(args, exclude=list(exclude) + [h["title"] for h in plan["sources"]], _tries=_tries + 1)
    if use_history:
        save_history(args.history, history, plan)
    return plan


REVIEW_TRIES = 2  # eksik bilgisi bulunamayan haber yerine denenecek haber sayısı
MIN_IMAGES = 2  # bundan az farklı gerçek görselle video üretilmez
TREND_BOOSTED = {"culture", "sportstory", "platform"}  # Google'da aranan konunun haberi öne alınır
REPEAT_CHECKED = {"platform"}  # yapım haberi: aynı dizi iki gün üst üste video olmaz
# Son RECENT_DAYS günde kanala yüklenen videoların başlıkları panel kaydından okunur. Eskiden çalışma kaydının
# son 8 satırına bakılıyordu; her video 3-5 kaynak satırı yazdığı için bu yalnızca son iki video ediyordu ve
# Bir Başkadır dört günde dört kez seçildi (17 Kasım 2026)
RECENT_DAYS = 7


def published_titles(history, days=RECENT_DAYS, now=None):
    """Son günlerde kanala yüklenen videoların başlıkları (eskiden yeniye); panel kaydı okunamazsa çalışma kaydı."""
    from .report import read_feed
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        feed = read_feed()[0]
    except Exception as exc:
        print(f"Panel kaydı okunamadı, çalışma kaydına bakılıyor ({exc})")
        return list(dict.fromkeys(h["title"] for h in history))[-20:]
    titles = []
    for entry in sorted(feed, key=lambda e: e.get("time") or ""):
        try:
            when = datetime.datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if now - when <= datetime.timedelta(days=days):
            titles += [v["title"] for v in entry.get("videos", []) if v.get("url") and v.get("title")]
    return titles


def _fold(text):
    return re.sub(r"\W+", " ", (text or "").replace("İ", "i").replace("I", "ı").lower()).strip()


def repeated(plan, recent_titles):
    """Planın yapımı ya da adı geçen biri son video başlıklarından birinde geçiyorsa o ad; yoksa boş."""
    names = [(plan.get("work") or {}).get("title", "")] + list(plan.get("subjects") or [])
    titles = [f" {_fold(t)} " for t in recent_titles]
    for name in filter(None, names):
        if len(_fold(name)) >= 4 and any(f" {_fold(name)} " in t for t in titles):
            return name
    return ""


# Bu türlerde haber bir kişi ya da eser hakkında olmalı: yer ve olay aramasına düşen haber atlanır.
SUBJECT_REQUIRED = {"culture", "sportstory", "platform"}
SUBJECT_TRIES = 4


def with_subject_photos(args):
    """news_plan + konunun kendi görselleri (subject_kind). Konunun en az MIN_IMAGES görseli yoksa sıradaki haber."""
    tried = []
    for attempt in range(SUBJECT_TRIES):
        plan = news_plan(args, exclude=tried)
        plan["mode"] = args.mode
        if args.offline:
            plan["subject_files"], plan["work_images"] = [], []
            return plan
        if plan.get("work"):
            # Dizi ya da film: yalnızca yapımın kareleri (haber kapakları, Vikipedi afişi)
            plan["subject_files"] = []
            plan["work_images"] = platforms.work_images(plan["work"], plan.get("sources", []))
            count = len({c["url"] for c in plan["work_images"]})
            if count >= MIN_IMAGES:
                return plan
            reason = f"yapımın yeterli karesi yok ({count})"
        else:
            plan["work_images"] = []
            names = plan.get("subjects") or []
            context = news_context(plan)
            plan["subject_files"] = [f for f in dict.fromkeys(images.subject_file(n, context) for n in names) if f]
            if not plan["subject_files"]:
                if args.mode not in SUBJECT_REQUIRED:
                    return plan  # yer ve olay: arama (en az iki görsel denetimi main'de)
                reason = f"konunun kendi fotoğrafı yok ({', '.join(names) or 'isim yok'})"
            else:
                support = {c["url"] for n in names for c in images.subject_photos(n, context=context)}
                if len(plan["subject_files"]) + len(support) >= MIN_IMAGES:
                    return plan
                reason = "konunun yalnızca bir fotoğrafı var"
        tried += [h["title"] for h in plan["sources"]]
        print(f"{reason}; başka haber deneniyor")
    raise RuntimeError("Görseli yeterli haber çıkmadı; bu saatin videosu atlanıyor.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["story", "world", "trend", "digest", "morning", "sports", "debate", "onthisday", "fact", "sportstory", "culture", "platform",
                                       "horoscope1", "horoscope2", "horoscope3"],
                    default="story")
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
        if args.mode == "onthisday":
            plan = onthisday.plan()
        elif args.mode.startswith("horoscope"):  # haftalık burç: horoscope1 Koç-Yengeç, 2 Aslan-Akrep, 3 Yay-Balık
            plan = horoscope.plan(int(args.mode[-1]))
        elif args.mode == "fact":
            plan = evergreen.plan(Path(args.history).parent / "evergreen.json" if args.history else evergreen.STATE)
        else:
            plan = with_subject_photos(args)
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
    wide = plan.get("wide")
    # Dikey videolar başlıktan türetilen kendi görünümü ve sesiyle çıkar (render.make_style)
    look = None if wide else render.make_style(plan["title"], plan.get("lang", "tr"))
    if look:
        plan["style"] = look
        print("Stil: " + ", ".join(f"{k}={v}" for k, v in look.items() if k != "lang"))
    if args.offline:
        backgrounds, credits = [args.background] * len(segments), []
    else:
        recent = Path(args.history).parent / "images.json" if args.history else None
        if os.environ.get("FACT_TOPIC") and args.mode == "fact":
            # Aynı konunun yeniden üretimi: önceki denemenin görselleri "son kullanılan" sayılınca Sakıp Sabancı'da
            # Sabancı Center yerine banknot, Uluburun'da tek aday kaldı (14 Kasım 2026). Eski video kaldırılacağı
            # için tekrar sayılmaz.
            recent = None
        if recent:
            load_recent_images(recent)
        backgrounds, credits = find_images(plan, work)
        if recent:
            save_recent_images(recent)
        backgrounds = scenes.spread(backgrounds, segments)
        # Görselsiz (yalnızca renkli zemin) video kaydırılıp geçiliyor: hiç görsel bulunamadıysa video üretilmez.
        # Maç kartları kendi grafiğini çizdiği için hariç.
        settle_scenes(plan, backgrounds)
    plan["image_credit"] = "\n".join(dict.fromkeys(credits)) or None

    # Önce bütün sesler: anlatıcının sesi ortada değişirse önceki parçalar da yeni sesle okunur
    if args.offline:
        spoken = [_offline_audio(seg["text"], work / f"seg{i}.mp3") for i, seg in enumerate(segments)]
    else:
        from .tts import RATE, speak_all
        spoken = speak_all([{"text": seg["text"], "out": work / f"seg{i}.mp3", "lang": plan.get("lang", "tr"),
                             "speaker": (look or {}).get("speaker", "male"), "rate": (look or {}).get("rate", RATE),
                             "pronounce": plan.get("pronounce")}
                            for i, seg in enumerate(segments)])

    parts, chapters, clock, spoken_lines = [], [], 0.0, []
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
        elif seg.get("card") and plan.get("match"):
            render.draw_match_card(seg["card"], plan["match"], card, plan.get("label", "SPOR"), seg.get("source", ""),
                                   backgrounds[i])
            render.write_ass(words, ass, look=look)
            render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1, look=look, idx=i)
        else:
            render.draw_card(seg, i, card, backgrounds[i], plan.get("hook_title", ""), plan.get("label", "GÜNDEM"),
                             lang=plan.get("lang", "tr"), style=look)
            if seg.get("scene") and look:
                _draw_scene(seg["scene"], words, card, audio, backgrounds[i], look, i)
            render.write_ass(words, ass, look=look)
            render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1, look=look, idx=i)
        if seg.get("chapter"):
            chapters.append(f"{_clock(clock)} {seg['chapter']}")
        length = render.audio_duration(part)
        spoken_lines.append((*_spoken(clock, words, length), seg["text"]))
        clock += length
        parts.append(part)

    # YouTube bölümleri 0:00 ile başlamalı ve en az üç tane olmalı
    if wide and chapters:
        if not chapters[0].startswith("0:00 "):
            chapters.insert(0, "0:00 Intro" if plan.get("lang") == "en" else "0:00 Giriş")
        plan["chapters"] = chapters if len(chapters) >= 3 else []

    render.concat(parts, work / "voice.mp4")
    voice = work / "voice.mp4"
    if plan.get("subscribe", True):  # acı haberde abone çağrısı yapılmaz
        render.add_subscribe(voice, work / "voice_sub.mp4", plan.get("lang", "tr"), wide=bool(wide),
                             promise=plan.get("promise"))
        voice = work / "voice_sub.mp4"
    plan["music_credit"] = music.add(voice, plan.get("mood"), out / "short.mp4")
    meta = build_metadata(plan, args.mode)
    meta["captions"] = captions.srt(spoken_lines)
    for seg in segments:  # haberin tamamı zaten plan["sources"] içinde
        seg.pop("headline", None)
    (out / "metadata.json").write_text(json.dumps({**meta, "plan": plan}, ensure_ascii=False, indent=2))
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
