"""Haberin yayın sitesindeki metni: metin denetimi başlığın söylemediği ayrıntıyı (hangi ilçeler, neden) buradan alır.

Google News bağlantıları yönlendirme değil, kodlanmış kimlik: asıl adres Google News'in kendi sayfasının verdiği imza
ile sorulur. Metin önce sayfanın yapısal verisinden (JSON-LD articleBody), yoksa paragraflardan çıkarılır.
Google News bu biçimi değiştirirse ya da site erişimi engellerse boş döner; denetim o zaman yapılmaz.
"""
import html
import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"}
MIN_CHARS = 300  # bundan kısası çerez uyarısı, abonelik duvarı ya da özet olur


def _get(url, data=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(3_000_000).decode("utf-8", "replace")


def resolve(link):
    """news.google.com/rss/articles/... → yayın sitesindeki adres."""
    if "news.google.com" not in link:
        return link
    aid = urllib.parse.urlparse(link).path.rstrip("/").split("/")[-1]
    page = _get(f"https://news.google.com/rss/articles/{aid}")
    sig = re.search(r'data-n-a-sg="([^"]+)"', page).group(1)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None,
                                        None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        aid, int(ts), sig])
    out = _get("https://news.google.com/_/DotsSplashUi/data/batchexecute",
               data=urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode(),
               headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    return json.loads(json.loads(out.split("\n\n")[1])[0][2])[1]


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _bodies(node):
    if isinstance(node, dict):
        if isinstance(node.get("articleBody"), str):
            yield node["articleBody"]
        for value in node.values():
            yield from _bodies(value)
    elif isinstance(node, list):
        for value in node:
            yield from _bodies(value)


def extract(page):
    """Sayfadan haber metni."""
    for raw in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            found = max(_bodies(json.loads(raw.strip())), key=len, default="")
        except ValueError:
            continue
        if len(found) >= MIN_CHARS:
            return _text(found)
    page = re.sub(r"<(script|style|noscript|nav|footer|aside)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    # Kısa paragraflar menü, etiket ve "ilginizi çekebilir" bağlantıları
    return " ".join(p for p in (_text(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)) if len(p) > 60)


def article_text(link, limit):
    try:
        text = extract(_get(resolve(link)))
    except Exception as exc:  # engelleyen site, değişen Google biçimi: denetim bu kaynak olmadan sürer
        print(f"  Haber metni alınamadı ({link[:60]}…): {exc}")
        return ""
    return text[:limit] if len(text) >= MIN_CHARS else ""


META_IMAGE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]*>', re.I)


def lead_image(link):
    """Haberin kapak görseli (og:image): dizi ve film haberlerinde çoğu zaman yapımın resmi tanıtım görseli.
    (adres, site) ya da None."""
    try:
        url = resolve(link)
        page = _get(url)
    except Exception as exc:
        print(f"  Kapak görseli alınamadı ({link[:60]}…): {exc}")
        return None
    for tag in META_IMAGE.findall(page):
        found = re.search(r'content=["\']([^"\']+)', tag)
        if found:
            image = urllib.parse.urljoin(url, html.unescape(found.group(1)))
            # Bazı siteler küçük boy verir (?w=127): boyut parametresi atılınca asıl görsel gelir
            image = re.sub(r"([?&])(?:w|width|h|height)=\d+&?", r"\1", image).rstrip("?&")
            if not re.search(r"logo|placeholder|default|favicon", image, re.I):
                return image, urllib.parse.urlparse(url).netloc.removeprefix("www.")
    return None


def texts(headline, count=3, limit=3500):
    """Haber kümesindeki yayınlardan en fazla count metin: [{"source", "title", "text"}]."""
    out = []
    cluster = [i for i in [headline] + headline.get("related", []) if i.get("link")]
    for item in cluster[:count + 3]:  # birkaç site engellese de süre uzamasın
        if len(out) >= count:
            break
        text = article_text(item["link"], limit)
        if text:
            out.append({"source": item.get("source", ""), "title": item["title"], "text": text})
    return out
