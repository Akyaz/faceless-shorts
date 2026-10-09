"""Google News Türkiye RSS'ten günün başlıklarını çeker."""
import html
import re
import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://news.google.com/rss?hl=tr&gl=TR&ceid=TR:tr"


def fetch_headlines(limit=10):
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())

    items = []
    for item in root.iter("item"):
        raw_title = html.unescape(item.findtext("title", "")).strip()
        source = item.findtext("source", "").strip()
        # Google News başlıkları "Başlık - Kaynak" biçiminde gelir
        title = re.sub(r"\s+-\s+[^-]+$", "", raw_title) if source else raw_title
        items.append({"title": title, "source": source, "link": item.findtext("link", "")})
        if len(items) >= limit:
            break
    return items
