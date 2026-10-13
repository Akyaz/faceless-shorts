"""Habere uygun arka plan görsellerini bulur.

Sıra: Wikimedia Commons (serbest lisanslı gerçek fotoğraflar) -> Gemini illüstrasyonu -> yok.
Haber sitelerinin fotoğrafları telifli olduğu için kullanılmaz.
"""
import base64
import html
import json
import os
import re
import urllib.parse
import urllib.request

from . import script

UA = "faceless-shorts/0.1 (https://github.com/Akyaz/faceless-shorts)"
FREE_LICENSE = re.compile(r"^(CC0|CC BY(-SA)?( \d\.\d)?|Public domain|PD)", re.I)


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _strip(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


def wikimedia(query, limit=5):
    """Serbest lisanslı fotoğraf adaylarını döner: url, credit, about (dosya adı ve açıklaması)."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        # Sadece JPEG: PNG sonuçlar çoğunlukla logo, harita ve şema
        "gsrsearch": f"filemime:image/jpeg {query}", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400,
    })
    data = _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = _strip(meta.get("LicenseShortName", {}).get("value"))
        width, height = info.get("width", 0), info.get("height", 0)
        # Çok yatık panoramalar dikeye kırpılınca ince bir şerit kalıyor
        if not FREE_LICENSE.match(license_name) or width < 800 or width > 2.5 * height:
            continue
        artist = _strip(meta.get("Artist", {}).get("value")) or "Bilinmiyor"
        about = f"{page.get('title', '')} | {_strip(meta.get('ImageDescription', {}).get('value'))[:200]}"
        found.append({"url": info["thumburl"], "about": about, "credit":
                      f"Görsel: {artist}, {license_name}, Wikimedia Commons ({info['descriptionurl']})"})
        if len(found) >= limit:
            break
    return found


def _download(url, out_path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())


def gemini_illustration(prompt, out_path):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    body = json.dumps({
        "contents": [{"parts": [{"text": f"Vertical 9:16 editorial illustration, no text, no real people: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(inline["data"]))
            return "Görsel: yapay zekâ ile üretilmiş temsili illüstrasyon"
    return None


SELECT_RULES = """Bir haber videosunun arka planı için fotoğraf seçiyorsun. Aşağıda numaralı adayların dosya adı ve
açıklaması, ardından aynı sırayla fotoğrafların kendisi var. Fotoğrafa bakarak karar ver.

EN ÖNEMLİ KURAL - YER: {place_rule}

Seç: haberin geçtiği yeri, kurumu ya da ortamı açıkça gösteren, net ve iyi çekilmiş fotoğraflar.
[nesne] işaretli adaylar yalnızca içinde insan olmayan, yeri belli etmeyen yakın plan nesne fotoğrafıysa seçilebilir.

Seçme:
- Konuyla ilgisi zayıf olanlar. Emin değilsen seçme; az ama doğru görsel, çok ama alakasız görselden iyidir.
- Başka bir olaya ait olduğu belli olanlar (örnek: başka bir depremin yıkımı).
- Harita, grafik, tablo, logo, belge, ekran görüntüsü ve yazı ağırlıklı görseller.
- Siyah beyaz ya da eski tarihli, bulanık, karanlık ya da özensiz çekilmiş fotoğraflar.
- Bir kişinin yüzünün öne çıktığı fotoğraflar.
- Dikey videoda ortası kırpılınca konusu kadraj dışında kalacak fotoğraflar.

Birbirinden farklı görünenleri tercih et. En fazla 5 aday seç. Kurallara uyan aday yoksa boş liste döndür.
Sadece JSON döndür, en uygun olan başta: {{"pick": [3, 1, 7]}}
"""
PLACE_RULE = ("Haber {where} ile ilgili. İçinde insan, sokak, bina, okul, taşıt ya da manzara olan her fotoğraf "
              "{where} içinde çekilmiş olmalı. Dosya adından, açıklamasından ya da görüntüsünden (yazılar, tabelalar, "
              "bayraklar, mimari, insanlar) başka bir ülkede ya da şehirde çekildiği anlaşılan fotoğrafı seçme; "
              "nerede çekildiği anlaşılmayan insan fotoğrafını da seçme.")
NO_PLACE_RULE = ("Haber belirli bir ülkeyle ilgili değil. Belirli bir ülkeyi ya da halkı temsil eden insan ve sokak "
                 "fotoğraflarını seçme; konuyu gösteren nesne, cihaz, doğa ve uzay fotoğraflarını tercih et.")
PREVIEW_WIDTH = 330  # Wikimedia'nın hazır küçük boyutlarından biri
# Ücretsiz kota model başına sayılıyor: görsel eleme hafif modele gider, iyi model metin yazımına kalır
SELECT_MODELS = "gemini-flash-lite-latest,gemini-flash-latest"


def _preview(url):
    small = re.sub(r"/\d+px-", f"/{PREVIEW_WIDTH}px-", url)
    req = urllib.request.Request(small, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _select(plan, candidates):
    """Adayları dil modeline gösterip eletir; model yoksa ya da yanıt vermezse None döner."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    shown, previews = [], []
    for cand in candidates:
        try:
            previews.append(_preview(cand["url"]))
            shown.append(cand)
        except Exception as exc:
            print(f"Önizleme alınamadı: {exc}")
    listing = "\n".join(f"{i}. {'[nesne] ' if c.get('neutral') else ''}{c['about']}" for i, c in enumerate(shown, 1))
    where = _where(plan)
    rules = SELECT_RULES.format(place_rule=PLACE_RULE.format(where=where) if where else NO_PLACE_RULE)
    prompt = f"{rules}\nHaber: {plan['title']}\n{plan['sources'][0]['title']}\n\nAdaylar:\n{listing}"
    try:
        picks = json.loads(script._generate(prompt, os.environ["GEMINI_API_KEY"], previews, SELECT_MODELS))["pick"]
        print(f"Görsel seçimi: {picks} ({len(shown)} aday içinden)")
        return [shown[int(n) - 1] for n in dict.fromkeys(picks) if 1 <= int(n) <= len(shown)]
    except Exception as exc:
        print(f"Görsel seçimi yapılamadı, arama sırası kullanılacak: {exc}")
        return None


def _where(plan):
    place = plan.get("place") or {}
    return ", ".join(x for x in (place.get("city"), place.get("country")) if x)


def _searches(plan):
    """(arama, nesne mi) listesi. Yer biliniyorsa her arama şehir ve ülke adıyla yapılır; yersiz arama yapılmaz."""
    place = plan.get("place") or {}
    city, country = place.get("city", ""), place.get("country", "")
    searches = [(city, False)] if city else []  # şehrin kendi fotoğrafları her zaman doğru yerdendir
    for query in plan.get("image_queries") or []:
        located = [f"{query} {loc}" for loc in (city, country) if loc and loc.lower() not in query.lower()]
        searches += [(q, False) for q in (located or [query])]
    if plan.get("object_query"):
        searches.append((plan["object_query"], True))
    return list(dict.fromkeys(searches))


def find_backgrounds(plan, out_dir, count, per_query=3):
    """En fazla count görseli out_dir'e yazar; (dosya, kaynak satırı) listesi döner."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pools = []
    for query, neutral in _searches(plan):
        try:
            found = [{**c, "neutral": neutral} for c in wikimedia(query, per_query)]
        except Exception as exc:
            print(f"Wikimedia görseli alınamadı ({query}): {exc}")
            continue
        print(f"Wikimedia ({query}): {len(found)} aday")
        pools.append(found)

    # Sorgular arasında sırayla dolaşılır ki görseller haberin farklı yönlerini göstersin
    candidates, seen = [], set()
    for rank in range(max(map(len, pools), default=0)):
        for pool in pools:
            if rank >= len(pool):
                continue
            # "Sokak 05.jpg" ile "Sokak 06.jpg" aynı çekimin kareleri; biri yeter
            series = re.sub(r"[\d\s]+", "", pool[rank]["about"].split("|")[0])
            if series not in seen:
                seen.add(series)
                candidates.append(pool[rank])
    candidates = candidates[:24]

    picked = _select(plan, candidates) if candidates else []
    if picked is None:
        # Eleme yapılamadıysa yalnızca yer adıyla bulunan ilk sonuçlara güvenilir; nesne aramaları elenmeden kullanılmaz
        picked = [c for c in candidates if not c["neutral"]][:2]

    results = []
    for cand in picked:
        path = out_dir / f"background{len(results)}.jpg"
        try:
            _download(cand["url"], path)
        except Exception as exc:
            print(f"Görsel indirilemedi: {exc}")
            continue
        print(f"Arka plan: {cand['about'][:120]}")
        results.append((path, cand["credit"]))
        if len(results) >= count:
            break

    if not results and plan.get("image_prompt"):
        path = out_dir / "background.png"
        try:
            credit = gemini_illustration(plan["image_prompt"], path)
        except Exception as exc:
            print(f"Gemini görseli alınamadı: {exc}")
            credit = None
        if credit:
            results.append((path, credit))
    print(f"Arka plan: {len(results)} görsel")
    return results
