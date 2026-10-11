"""Google News Türkiye RSS'ten başlıkları çeker."""
import html
import re
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = {
    "top": "https://news.google.com/rss?hl=tr&gl=TR&ceid=TR:tr",
    "sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=tr&gl=TR&ceid=TR:tr",
    "science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=tr&gl=TR&ceid=TR:tr",
    "technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=tr&gl=TR&ceid=TR:tr",
}
# Köşe yazıları haber değil; kümenin başına geçince kaynak gösterimini de bozuyor
COLUMN = re.compile(r"\b(yazdı|yazıyor)\b", re.I)


# Can kaybı, yaralanma ve ağır suç haberleri: merak kancası, "senin için ne demek" ve abone çağrısıyla
# anlatılmaya uygun değil. Dil modeli talimata her zaman uymadığı için bu ayrım kodda yapılır.
SENSITIVE = re.compile(
    r"\böl(ü|dü|en|üm)|hayatını kaybe|yaşamını yitir|can verdi|can kayb|canından ol|cansız|cenaze|ceset|cesed"
    r"|şehit|yaralı|yaralan|katlia|katled|cinayet|intihar|tecavüz|taciz|istismar|kaza\b|kazada|kazası|facia"
    r"|feci|boğul|vuruldu|bıçakla|silahlı saldırı|bombalı|enkaz")


def is_sensitive(*texts):
    joined = " ".join(texts).replace("İ", "i").replace("I", "ı").lower()
    return bool(SENSITIVE.search(joined))


def sensitive_headline(headline):
    return is_sensitive(headline["title"], *(r["title"] for r in headline.get("related", [])))


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _related(description_html):
    """Açıklamadaki aynı habere ait diğer kaynaklar: [{title, source}]."""
    out = []
    for li in re.findall(r"<li>(.*?)</li>", html.unescape(description_html), re.S):
        title = re.search(r"<a[^>]*>(.*?)</a>", li, re.S)
        source = re.search(r"<font[^>]*>(.*?)</font>", li, re.S)
        if title and not COLUMN.search(_text(title.group(1))):
            out.append({"title": _text(title.group(1)), "source": _text(source.group(1)) if source else ""})
    return out


def fetch_headlines(limit=10, topic="top"):
    req = urllib.request.Request(FEEDS[topic], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())

    items = []
    for item in root.iter("item"):
        raw_title = html.unescape(item.findtext("title", "")).strip()
        source = item.findtext("source", "").strip()
        # Google News başlıkları "Başlık - Kaynak" biçiminde gelir
        title = re.sub(r"\s+-\s+[^-]+$", "", raw_title) if source else raw_title
        related = [r for r in _related(item.findtext("description", "")) if r["title"] != title]
        if COLUMN.search(title):
            if not related:
                continue
            title, source, related = related[0]["title"], related[0]["source"], related[1:]
        items.append({"title": title, "source": source, "link": item.findtext("link", ""), "related": related})
        if len(items) >= limit:
            break
    return items
