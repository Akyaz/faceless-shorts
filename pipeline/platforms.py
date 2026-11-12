"""Dijital platformlar (Netflix, Disney+, Prime Video, HBO Max, tabii, Exxen): trend ve yeni yapım haberleri,
dizi ve filmlerin resmi afiş ve sahne görselleri.

Netflix'in her hafta yayınladığı ülke Top 10 listesi (resmi veri) haberlerle birleştirilir: listedeki her yapım
için Google News'te haber aranır, yeterli kaynağı olan yapım tek konulu videoya aday olur. Diğer platformların
resmi listesi yok; onların yeni yapımları haber aramasından gelir.

Görseller (kanal sahibinin kararı, 12 Kasım 2026): dizi ve film videolarında resmi afiş ve sahne görselleri
kullanılır. Bunlar telifli tanıtım görselleridir; hak sahibi açıklamada belirtilir. TMDB_API_KEY varsa TMDB'nin
sahne görselleri (backdrop) ve afişi, yoksa Vikipedi bilgi kutusundaki afiş alınır.
"""
import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request

from .news import search_headlines

TOP10_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
UA = {"User-Agent": "faceless-shorts/0.1 (https://github.com/Akyaz/faceless-shorts)"}
PLATFORM_QUERIES = ["Netflix yeni dizi when:7d", "Netflix film when:7d", "Netflix fragman when:7d",
                    "Disney+ dizi when:7d", "Prime Video dizi when:7d", "HBO Max dizi when:7d", "tabii dizi when:7d",
                    "Exxen dizi when:7d"]
BODY_CHARS = 1500  # arama sonuçları kümesiz: metin, haberin sitesindeki yazının başından alınır


def _get(url, timeout=60, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def netflix_top10(country="Turkey", raw=None):
    """Ülkenin son haftaki listesi: [{"week", "category" ("TV"|"Films"), "rank", "title", "season", "weeks"}]."""
    text = raw if raw is not None else _get(TOP10_URL, timeout=180).decode("utf-8")  # 33 MB
    rows = [r for r in csv.DictReader(io.StringIO(text), delimiter="\t") if r["country_name"] == country]
    if not rows:
        return []
    week = max(r["week"] for r in rows)
    out = [{"week": week, "category": r["category"], "rank": int(r["weekly_rank"]), "title": r["show_title"],
            "season": "" if r["season_title"] == "N/A" else r["season_title"],
            "weeks": int(r["cumulative_weeks_in_top_10"] or 1)} for r in rows if r["week"] == week]
    return sorted(out, key=lambda r: (r["category"] != "TV", r["rank"]))


def top10_note(item):
    kind = "dizi" if item["category"] == "TV" else "film"
    return (f"Netflix Türkiye haftalık Top 10 ({item['week']} haftası): {kind} listesinde {item['rank']}. sıra, "
            f"listede {item['weeks']}. haftası")


def headlines(limit=16):
    """Top 10 yapımları (haberleriyle) ve platformların yeni yapım haberleri; aynı haber bir kez."""
    out = []
    try:
        top = netflix_top10()
    except Exception as exc:  # liste alınamazsa haber aramasıyla devam edilir
        print(f"Netflix Top 10 alınamadı: {exc}")
        top = []
    for item in [t for t in top if t["category"] == "TV"][:5] + [t for t in top if t["category"] == "Films"][:3]:
        found = search_headlines(f'"{item["title"]}" Netflix', 5)
        if not found:
            continue
        head = found[0]
        related = head.get("related", []) + [{"title": f["title"], "source": f["source"], "link": f["link"]}
                                             for f in found[1:]]
        # Sıra bilgisi kaynak gibi eklenir: model "Netflix'te bir numara" bilgisini buradan alır
        out.append({**head, "related": related + [{"title": top10_note(item), "source": "Netflix Top 10",
                                                   "link": ""}], "top10": item})
    for query in PLATFORM_QUERIES:
        try:
            out += search_headlines(query, 4)
        except Exception as exc:
            print(f"Platform haberi aranamadı ({query}): {exc}")
    picked = list({h["title"]: h for h in out}.values())[:limit]
    from .articles import article_text
    for h in picked:
        if h.get("link"):
            h["body"] = article_text(h["link"], BODY_CHARS)
    with_body = [h for h in picked if h.get("body") or len(h.get("related", [])) >= 2]
    print(f"Platform haberi: {len(with_body)}/{len(picked)} metniyle")
    return with_body


# --- Resmi görseller -------------------------------------------------------------------------------------------

def _tmdb(path, **params):
    query = urllib.parse.urlencode({"api_key": os.environ["TMDB_API_KEY"], **params})
    return json.loads(_get(f"https://api.themoviedb.org/3{path}?{query}", 30))


def tmdb_images(title, year="", kind="", limit=5):
    """TMDB: sahne görselleri (yatay, yazısız olanlar önce) ve afiş. Anahtar yoksa ya da bulunamazsa boş."""
    if not os.environ.get("TMDB_API_KEY"):
        return []
    kinds = ["tv", "movie"] if kind != "movie" else ["movie", "tv"]
    for media in kinds:
        params = {"query": title, "language": "tr-TR"}
        if year:
            params["first_air_date_year" if media == "tv" else "year"] = year
        try:
            hits = _tmdb(f"/search/{media}", **params).get("results") or _tmdb(f"/search/{media}", query=title)["results"]
        except Exception as exc:
            print(f"TMDB araması yapılamadı ({title}): {exc}")
            return []
        if not hits:
            continue
        hit = hits[0]
        name = hit.get("name") or hit.get("title") or title
        try:
            pics = _tmdb(f"/{media}/{hit['id']}/images", include_image_language="null,tr,en")
        except Exception as exc:
            print(f"TMDB görselleri alınamadı ({name}): {exc}")
            return []
        stills = sorted(pics.get("backdrops", []), key=lambda b: (b.get("iso_639_1") is not None, -b.get("vote_average", 0)))
        posters = pics.get("posters", [])[:1]
        credit = f"Görsel: \"{name}\" resmi tanıtım görseli, hakları yapımcısına aittir (TMDB)"
        found = [{"url": f"https://image.tmdb.org/t/p/w1280{b['file_path']}", "about": f"{name} sahne görseli",
                  "credit": credit, "neutral": False} for b in stills[:limit - len(posters)]]
        found += [{"url": f"https://image.tmdb.org/t/p/w780{p['file_path']}", "about": f"{name} afişi",
                   "credit": credit, "neutral": False} for p in posters]
        print(f"TMDB ({name}): {len(found)} resmi görsel")
        return found
    return []


def _wiki(lang, **params):
    query = urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    return json.loads(_get(f"https://{lang}.wikipedia.org/w/api.php?{query}", 30))


INFOBOX_IMAGE = re.compile(r"^\s*\|\s*(?:image|görsel|resim|afiş)\s*=\s*(?:\[\[)?(?:File:|Dosya:|Image:)?([^|\]\n<]+?\.(?:jpe?g|png))",
                           re.I | re.M)


def wiki_poster(title, kind=""):
    """Vikipedi bilgi kutusundaki afiş (yerel, adil kullanım dosyası). Sayfa başlığı yapım adını içermeli."""
    words = set(re.findall(r"\w+", title.lower()))
    suffix = " film" if kind == "movie" else " dizi" if kind == "tv" else ""
    for lang in ("tr", "en"):
        try:
            hits = _wiki(lang, action="query", list="search", srsearch=title + suffix, srlimit=3)["query"]["search"]
            for hit in hits:
                if not words <= set(re.findall(r"\w+", hit["title"].lower())):
                    continue
                text = _wiki(lang, action="parse", page=hit["title"], prop="wikitext", section=0,
                             redirects=1)["parse"]["wikitext"]
                match = INFOBOX_IMAGE.search(text)
                if not match:
                    break
                file = "File:" + match.group(1).strip()
                info = _wiki(lang, action="query", titles=file, prop="imageinfo", iiprop="url",
                             iiurlwidth=1280)["query"]["pages"][0].get("imageinfo") or []
                if not info:
                    break
                print(f"Vikipedi afişi ({title}): {lang}:{hit['title']} -> {file}")
                return [{"url": info[0].get("thumburl") or info[0]["url"], "about": f"{hit['title']} afişi",
                         "neutral": False, "credit": f"Görsel: \"{hit['title']}\" afişi, hakları yapımcısına aittir "
                                                     f"(Vikipedi, {info[0]['descriptionurl']})"}]
        except Exception as exc:
            print(f"Vikipedi afişi aranamadı ({title}, {lang}): {exc}")
    return []


def news_images(work, sources, limit=4):
    """Yapımı anlatan haberlerin kapak görselleri (og:image). Yeni yapımın çoğu zaman Vikipedi sayfası yok;
    haber siteleri ise platformun dağıttığı tanıtım görselini kapak yapar. Yalnızca başlığında yapım adı geçen
    haberlerin görseli alınır."""
    from .articles import lead_image
    words = set(re.findall(r"\w+", work["title"].split(":")[0].lower()))
    items = [s for h in sources for s in [h] + h.get("related", []) if s.get("link")]
    out, seen = [], set()
    for item in items[:8]:
        if len(out) >= limit:
            break
        if not words <= set(re.findall(r"\w+", item["title"].lower())):
            continue
        found = lead_image(item["link"])
        if not found or found[0] in seen:
            continue
        seen.add(found[0])
        out.append({"url": found[0], "about": f"{work['title']} tanıtım görseli", "neutral": False,
                    "credit": f"Görsel: \"{work['title']}\" tanıtım görseli, hakları yapımcısına aittir ({found[1]})"})
    print(f"Haber kapak görseli ({work['title']}): {len(out)}")
    return out


def work_images(work, sources=()):
    """work: {"title", "year", "type": "tv"|"movie"} → resmi görsel adayları: önce TMDB, yoksa Vikipedi afişi ve
    haberlerin kapak görselleri (afiş tek görsel; video birkaç farklı görselle daha iyi akar)."""
    if not work or not work.get("title"):
        return []
    title, year, kind = work["title"].strip(), str(work.get("year") or ""), work.get("type", "")
    found = tmdb_images(title, year, kind)
    if found:
        return found
    return wiki_poster(title, kind) + news_images({**work, "title": title}, sources)
