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


SELECT_RULES = """Bir haber videosunun arka planı için temsili fotoğraf seçiyorsun. Aşağıda aday fotoğrafların dosya adı
ve açıklaması var. Haberin konusunu anlatan fotoğrafları seç; konuyla ilgili genel bir fotoğraf da uygundur
(örnek: hızlı tren haberi için herhangi bir modern hızlı tren, deprem haberi için bir sismograf).
Seçme: konuyla ilgisiz olanlar; başka bir olaya ait olduğu açıkça belli olanlar (örnek: başka bir depremin yıkımı);
harita, grafik, tablo, logo, belge ve yazı ağırlıklı görseller; siyah beyaz ya da eski tarihli fotoğraflar;
tek bir kişinin yakın portresi.
Birbirinden farklı görünen 3-5 aday seçmeye çalış; haberin geçtiği yere ait olanları öne al.
Sadece JSON döndür, en uygun olan başta: {"pick": [3, 1, 7]}
"""


def _select(plan, candidates):
    """Adayları dil modeline eleme için verir; model yoksa ya da yanıt vermezse None döner."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    listing = "\n".join(f"{i}. {c['about']}" for i, c in enumerate(candidates, 1))
    prompt = f"{SELECT_RULES}\nHaber: {plan['title']}\n{plan['sources'][0]['title']}\n\nAdaylar:\n{listing}"
    try:
        picks = json.loads(script._generate(prompt, os.environ["GEMINI_API_KEY"]))["pick"]
        print(f"Görsel seçimi: {picks}")
        return [candidates[int(n) - 1] for n in dict.fromkeys(picks) if 1 <= int(n) <= len(candidates)]
    except Exception as exc:
        print(f"Görsel seçimi yapılamadı, arama sırası kullanılacak: {exc}")
        return None


def find_backgrounds(plan, out_dir, count):
    """En fazla count görseli out_dir'e yazar; (dosya, kaynak satırı) listesi döner."""
    pools = []
    for query in plan.get("image_queries") or []:
        try:
            found = wikimedia(query)
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

    picked = _select(plan, candidates) if candidates else []
    if not picked:  # eleme yapılamadıysa ya da hepsi elendiyse en özel iki aramanın ilk sonucu kullanılır
        picked = candidates[:2]

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
