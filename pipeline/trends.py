"""Google Trends Türkiye: son saatlerde Google'da en çok aranan konular ve ilgili haberleri (resmi RSS, ücretsiz).

Kanalın en çok izlenen haberleri insanların aradığı ve birine gönderdiği "işe yarar" haberlerdi: şiddetli yağış
uyarısı (4.750), Yalova depremi (3.667), okulların tatil edilmesi (3.648), saat farkı (1.349). Gündem haberinin
ortancası ise 151'de kaldı (15 Kasım 2026 ölçümü). Bu yüzden 21:00 gündem videosunun konusu Türkiye'de en çok aranan
konulardan seçilir; kültür, spor ve dizi saatlerinde de aranan konunun haberi öne alınır.
X (Twitter) gündemi kullanılmaz: resmi servisi ücretli, listesi çoğunlukla siyasi ve hayran kampanyası hashtag'leri.
"""
import datetime
import email.utils
import html
import re
import urllib.request
import xml.etree.ElementTree as ET

FEED = "https://trends.google.com/trending/rss?geo=TR"
NS = {"ht": "https://trends.google.com/trending/rss"}
UA = {"User-Agent": "Mozilla/5.0"}
# Liste son 24 saati kapsıyor: gece 01:30'da dün akşamki "Gönül Dağı bu akşam var mı?" araması seçildi ve video
# yayınlanmış bölümü "yayına giriyor" diye anlattı (15 Kasım 2026). Yalnızca son saatlerde yükselen aramalar.
FRESH_HOURS = 12


def _started(text):
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _fold(text):
    return re.sub(r"\W+", " ", (text or "").replace("İ", "i").replace("I", "ı").lower()).strip()


def _traffic(text):
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else 0


def parse(xml_text, now=None):
    """[{"query", "traffic", "news": [{"title", "source", "link"}]}], en çok arananlar önce. Başlangıcı FRESH_HOURS'tan
    eski aramalar alınmaz (tarihi okunamayan alınır)."""
    root = ET.fromstring(xml_text)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = []
    for item in root.iter("item"):
        started = _started(item.findtext("pubDate", ""))
        if started and now - started > datetime.timedelta(hours=FRESH_HOURS):
            continue
        news = [{"title": html.unescape(n.findtext("ht:news_item_title", "", NS)).strip(),
                 "source": (n.findtext("ht:news_item_source", "", NS) or "").strip(),
                 "link": (n.findtext("ht:news_item_url", "", NS) or "").strip()}
                for n in item.findall("ht:news_item", NS)]
        news = [n for n in news if n["title"]]
        if news:
            out.append({"query": item.findtext("title", "").strip(),
                        "traffic": _traffic(item.findtext("ht:approx_traffic", "", NS)), "news": news})
    return sorted(out, key=lambda t: -t["traffic"])


def fetch():
    """Alınamazsa boş liste (video, haber akışıyla devam eder)."""
    try:
        req = urllib.request.Request(FEED, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            items = parse(resp.read())
    except Exception as exc:
        print(f"Google Trends alınamadı: {exc}")
        return []
    print("Google Trends: " + ", ".join(f"{t['query']} ({t['traffic']}+)" for t in items[:10]))
    return items


def note(trend):
    return {"title": f"Google'da son saatlerde {trend['traffic']}+ arama: \"{trend['query']}\"",
            "source": "Google Trends", "link": ""}


def headlines(items):
    """Her aranan konu bir haber: ilk haberi başlık, diğerleri ve arama bilgisi kaynak satırı."""
    out = []
    for t in items:
        first, rest = t["news"][0], t["news"][1:]
        out.append({**first, "related": rest + [note(t)], "trend": t["query"]})
    return out


def boost(heads, items):
    """Aranan bir konuyla eşleşen haberler öne alınır ve arama bilgisi kaynak satırı olarak eklenir."""
    keys = [(t, _fold(t["query"])) for t in items if len(_fold(t["query"])) >= 4]
    hot, rest = [], []
    for h in heads:
        text = f" {_fold(h['title'])} "
        match = next((t for t, k in keys if f" {k} " in text), None)
        if match:
            hot.append({**h, "related": list(h.get("related", [])) + [note(match)], "trend": match["query"]})
        else:
            rest.append(h)
    if hot:
        print("Aranan konuyla eşleşen haber: " + ", ".join(h["trend"] for h in hot))
    return hot + rest
