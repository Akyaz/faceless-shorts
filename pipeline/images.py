"""Habere uygun arka plan görseli bulur.

Sıra: Wikimedia Commons (serbest lisanslı gerçek fotoğraf) -> Gemini illüstrasyonu -> yok.
Haber sitelerinin fotoğrafları telifli olduğu için kullanılmaz.
"""
import base64
import html
import json
import os
import re
import urllib.parse
import urllib.request

UA = "faceless-shorts/0.1 (https://github.com/Akyaz/faceless-shorts)"
FREE_LICENSE = re.compile(r"^(CC0|CC BY(-SA)?( \d\.\d)?|Public domain|PD)", re.I)


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _strip(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


def wikimedia(query, out_path):
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 15,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400,
    })
    data = _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = _strip(meta.get("LicenseShortName", {}).get("value"))
        if not FREE_LICENSE.match(license_name) or info.get("width", 0) < 800:
            continue
        req = urllib.request.Request(info["thumburl"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
        artist = _strip(meta.get("Artist", {}).get("value")) or "Bilinmiyor"
        return f"Görsel: {artist}, {license_name}, Wikimedia Commons ({info['descriptionurl']})"
    return None


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


def find_background(plan, out_path):
    """Görseli out_path'e yazar, açıklamaya eklenecek kaynak satırını döner (yoksa None)."""
    query = plan.get("image_query") or ""
    short = " ".join(query.split()[:2])
    attempts = [("Wikimedia", wikimedia, query),
                ("Wikimedia", wikimedia, short if short != query else ""),  # daha genel arama
                ("Gemini", gemini_illustration, plan.get("image_prompt"))]
    for name, fn, arg in attempts:
        if not arg:
            continue
        try:
            credit = fn(arg, out_path)
        except Exception as exc:
            print(f"{name} görseli alınamadı: {exc}")
            continue
        if credit:
            print(f"Arka plan: {name} ({arg})")
            return credit
        print(f"{name}: uygun görsel bulunamadı ({arg})")
    return None
