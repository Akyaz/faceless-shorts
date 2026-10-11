"""Haftanın tek haber videolarından yatay, uzun bir derleme üretir.

Kullanım: python -m pipeline.weekly --week week --out out
--week altında o haftanın Short çalışmalarından indirilmiş metadata.json dosyaları aranır (alt klasörler dahil).
Metinler yeniden yazılmaz: her haberin Short'taki anlatımı, kapanış sorusu atılarak arka arkaya okunur.
"""
import argparse
import datetime
import json
import os
import re
from pathlib import Path

from . import images, music, render, script
from .tts import synthesize

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
          "Aralık"]
COUNT = 10
# Günler sonra izlenen derlemede "yarın kapanıyor" gibi o güne bağlı ifadeler yanlış bilgi olur
DATED = re.compile(r"\b(yarın|bugün|dün|bu (sabah|akşam|gece))\b", re.I)

CHOOSE_RULES = """Bir haber kanalının haftalık derleme videosu için haber seçiyorsun. Aşağıda bu hafta videosu yapılmış
haberler var. İzleyicinin hayatını en çok etkileyen, hâlâ geçerli ve birbirinden farklı {count} haberi seç;
aynı olayı anlatan iki haberden yalnızca birini al. En önemlisi başta olsun.
title: YouTube başlığı, en fazla 70 karakter; en dikkat çekici iki haberi ansın, yalnızca listedeki bilgilerle.
Sadece JSON döndür: {{"pick": [4, 1, 9], "title": "..."}}
"""


def collect(week_dir):
    """Haftanın tek haber planları, eskiden yeniye; aynı haber bir kez."""
    plans, seen = [], set()
    for path in sorted(Path(week_dir).rglob("metadata.json")):
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))["plan"]
        except (ValueError, KeyError):
            continue
        segments = plan.get("segments") or []
        key = (plan.get("sources") or [{}])[0].get("title")
        if not key or key in seen or not segments or any(s.get("kind") != "story" for s in segments):
            continue
        if DATED.search(" ".join([plan.get("title", ""), plan.get("hook_title", "")] + [s["text"] for s in segments])):
            continue
        seen.add(key)
        # İlk günlerin çalışmalarında tek bir arama kayıtlı
        plan["image_queries"] = plan.get("image_queries") or [q for q in [plan.get("image_query")] if q]
        plans.append(plan)
    return plans


def _stems(plan):
    return {w[:5] for w in re.findall(r"\w{4,}", plan["title"].lower())}


def _distinct(plans, count):
    """Başlığı öncekilerden biriyle büyük ölçüde örtüşen haberi atar: aynı olay iki kez anlatılmasın."""
    kept = []
    for plan in plans:
        stems = _stems(plan)
        if all(len(stems & _stems(k)) < 0.5 * min(len(stems), len(_stems(k))) for k in kept):
            kept.append(plan)
    return kept[:count]


def choose(plans, count=COUNT):
    """(seçilen planlar, başlık). Dil modeli yoksa ya da yanıt vermezse en yeni haberler alınır."""
    newest = _distinct(plans[::-1], count)
    fallback = newest, f"Haftanın {len(newest)} Haberi"
    if not os.environ.get("GEMINI_API_KEY") or len(plans) <= count:
        return fallback
    listing = "\n".join(f"{i}. {p['title']} ({p['sources'][0]['title']})" for i, p in enumerate(plans, 1))
    try:
        out = json.loads(script._generate(CHOOSE_RULES.format(count=count) + "\nHaberler:\n" + listing,
                                          os.environ["GEMINI_API_KEY"]))
        picked = _distinct([plans[int(n) - 1] for n in dict.fromkeys(out["pick"]) if 1 <= int(n) <= len(plans)], count)
        return (picked, out["title"]) if picked else fallback
    except Exception as exc:
        print(f"Haber seçimi yapılamadı, en yeni haberler kullanılacak: {exc}")
        return fallback


def _source(plan):
    head = plan["sources"][0]
    # Eski çalışmalarda ilgili başlıklar düz metin olarak kayıtlı
    related = [r for r in head.get("related", []) if isinstance(r, dict)]
    return script.source_label({**head, "related": related})


def build_segments(picked, today):
    week = f"{today.day} {MONTHS[today.month - 1]}"
    segments = [{"kind": "intro", "chapter": "Giriş",
                 "text": f"Bu hafta Türkiye'de öne çıkan {len(picked)} haber, birkaç dakikada."}]
    for i, plan in enumerate(picked, 1):
        heading = plan.get("hook_title") or plan["title"]
        # Son paragraf Short'un izleyiciye sorduğu soru; derlemede her haberden sonra tekrarlanmasın
        paragraphs = [s["text"] for s in plan["segments"]][:-1] or [plan["segments"][0]["text"]]
        for j, text in enumerate(paragraphs):
            segments.append({"kind": "story", "label": f"HAFTANIN ÖZETİ {i}/{len(picked)}", "heading": heading,
                             "source": _source(plan), "text": text, "item": i - 1,
                             **({"chapter": heading} if j == 0 else {})})
    segments.append({"kind": "outro", "chapter": "Kapanış", "label": f"{week} HAFTASI",
                     "text": "Sence haftanın en önemli haberi hangisiydi? Yorumlara yaz. "
                             "Günün haberlerini her gün kısa ve net izlemek için abone ol."})
    return segments


def _clock(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="week")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    plans = collect(args.week)
    print(f"Haftanın tek haber videoları: {len(plans)}")
    if len(plans) < 3:
        raise SystemExit("Derleme için yeterli haber yok.")
    picked, title = choose(plans)
    for i, plan in enumerate(picked, 1):
        print(f"{i}. {plan['title']}")
    segments = build_segments(picked, datetime.date.today())

    # Her haberin kendi görselleri; paragraflar arasında döner
    backgrounds, credits = {}, []
    for i, plan in enumerate(picked):
        found = images.find_backgrounds(plan, work / f"item{i}", 4, per_query=3) if plan.get("image_queries") else []
        backgrounds[i] = [path for path, _ in found]
        credits += [credit for _, credit in found]

    parts, chapters, clock, shown = [], [], 0.0, {}
    for n, seg in enumerate(segments):
        audio, card, ass, part = (work / f"seg{n}.{ext}" for ext in ("mp3", "png", "ass", "mp4"))
        words = synthesize(seg["text"], audio)
        # Giriş ilk haberin, kapanış son haberin görsellerini kullanır
        item = seg.get("item", 0 if n == 0 else len(picked) - 1)
        pool = backgrounds[item]
        shown[item] = shown.get(item, -1) + 1
        render.draw_wide_card(seg, item, card, pool[shown[item] % len(pool)] if pool else None,
                              subscribe=n == len(segments) - 1)
        render.write_ass(words, ass, wide=True)
        render.render_segment(card, audio, ass, part, zoom_out=n % 2 == 1, size=render.WIDE)
        if seg.get("chapter"):
            chapters.append(f"{_clock(clock)} {seg['chapter']}")
        clock += render.audio_duration(part)
        parts.append(part)

    render.concat(parts, work / "voice.mp4")
    music_credit = music.add(work / "voice.mp4", "notr", out / "short.mp4")

    sources = "\n".join(f"- {p['sources'][0]['title']} ({p['sources'][0]['source']})" for p in picked)
    image_credit = "\n".join(dict.fromkeys(credits))
    meta = {
        "title": title[:100],
        "description": f"{title}\n\nGünün haberleri her gün kısa ve net. Kaçırmamak için kanala abone ol.\n\n"
                       + "\n".join(chapters) + f"\n\nKaynaklar:\n{sources}\n"
                       + (f"\nGörseller temsilidir.\n{image_credit}\n" if image_credit else "")
                       + f"\n{music_credit}\n\n#gündem #haber #haftanınözeti",
        "tags": ["gündem", "haber", "haftanın özeti", "haftanın haberleri", "türkiye"],
        "category": "25",
    }
    (out / "metadata.json").write_text(json.dumps({**meta, "segments": segments}, ensure_ascii=False, indent=2))
    print(f"Başlık: {title}")
    print("\n".join(chapters))
    print(f"Hazır: {out / 'short.mp4'} ({_clock(clock)})")


if __name__ == "__main__":
    main()
