"""İngilizce "On This Day / Did you know?" Shorts'u: Wikipedia'nın tarihte bugün listesinden bir olay.

Metin yalnızca Wikipedia'daki olay cümlesi ve ilgili sayfaların özetinden yazılır (uydurma bilgi olmasın).
Görsel, olayın Wikipedia sayfasındaki fotoğraftır; yalnızca Commons'taki (serbest lisanslı) dosyalar alınır,
İngilizce Wikipedia'ya "adil kullanım" ile yüklenmiş telifli dosyalar (ör. film kareleri) elenir.
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

from . import script
from .news import is_sensitive

FEED = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/all/{month:02d}/{day:02d}"
UA = "faceless-shorts/1.0 (https://github.com/Akyaz/faceless-shorts)"
MAX_CANDIDATES = 25

RULES = """Task: write the English voice-over for a YouTube Short in the series "On This Day". The goal is that a
general international audience watches to the end, learns something surprising and shares it.

Pick: from the events below, the one that is most surprising, curious or delightful for a global audience and easy to
picture: discoveries, inventions, firsts, strange or famous moments, space, science, sport, culture, famous people.
Avoid events centred on deaths, disasters, wars, attacks or crimes, and partisan political events.
Put the number of the event you picked in "pick".

Script rules:
1. The first sentence is a hook of at most 12 words, ideally starting with "Did you know" or a surprising fact.
2. Say the year and what happened in plain words; then the most interesting details; then why it still matters or
   what happened next.
3. Use ONLY facts that appear in the event text and the page summaries below. Do not add names, numbers, places or
   outcomes that are not there. If something is disputed (a claim, an unproven sighting), say it is a claim.
4. Short sentences (at most 14 words), conversational, addressing the viewer as "you". 75-90 words, 4-5 paragraphs.
5. The last sentence is a short question that invites a comment.
   """ + script.QUESTION_RULE_EN + """

Other fields:
- hook_title: on-screen title, at most 5 words (example: "Bigfoot on Film, 1967").
- title: YouTube title, at most 70 characters, starting with the main keyword; include the year.
- image_queries: 3 Wikimedia Commons searches in English, 1-4 words each, for the people, objects or places of
  the event (example: "Patterson-Gimlin film site", "Stanford Linear Accelerator").
- hashtags: 3 topic tags; one word each, lowercase.

Return only JSON:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "image_queries": ["..."], "hashtags": ["..."]}
"""


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as resp:
        return json.load(resp)


def _commons_file(page):
    """Sayfanın fotoğrafı Commons'taysa "File:..." adı; yerel (adil kullanım) dosyalar, bayrak ve arma gibi
    çizimler (svg) için boş. Adres küçültülmüş görsel olabilir: .../commons/thumb/a/ab/Ad.jpg/3840px-Ad.jpg?utm=..."""
    source = (page.get("originalimage") or {}).get("source", "").split("?", 1)[0]
    if "/wikipedia/commons/" not in source:
        return ""
    parts = source.split("/")
    name = urllib.parse.unquote(parts[-2] if "/thumb/" in source else parts[-1]).replace("_", " ")
    if not name.lower().endswith((".jpg", ".jpeg", ".png")):
        return ""
    return "File:" + name


def candidates(day):
    """Bugünün olayları: can kaybı, saldırı ve benzeri olaylar elenir."""
    feed = _get(FEED.format(month=day.month, day=day.day))
    events, seen = [], set()
    for kind in ("selected", "events"):
        for event in feed.get(kind, []):
            text = event.get("text", "")
            pages = event.get("pages", [])[:2]
            summaries = " ".join(p.get("extract", "") for p in pages)
            if text in seen or is_sensitive(text, summaries):
                continue
            seen.add(text)
            events.append({"year": event.get("year"), "text": text, "pages": pages})
    return events[:MAX_CANDIDATES]


def plan(day=None):
    day = day or (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).date()
    events = candidates(day)
    if not events:
        raise RuntimeError("Bugün için uygun olay yok")
    blocks = []
    for n, event in enumerate(events, 1):
        pages = "\n".join(f"   Page \"{p.get('normalizedtitle') or p.get('title')}\": {p.get('extract', '')[:700]}"
                          for p in event["pages"])
        blocks.append(f"{n}. {event['year']}: {event['text']}\n{pages}")
    prompt = RULES + f"\nDate: {day:%B} {day.day}\n\nEvents:\n" + "\n".join(blocks)
    out = json.loads(script._generate(prompt, os.environ["GEMINI_API_KEY"]))
    event = events[max(0, min(int(out.get("pick", 1)), len(events)) - 1)]
    print(f"Seçilen olay: {event['year']}: {event['text']}")
    files = [f for f in dict.fromkeys(_commons_file(p) for p in event["pages"]) if f]
    sources = [{"title": p.get("normalizedtitle") or p.get("title", ""), "source": "Wikipedia",
                "link": p.get("content_urls", {}).get("desktop", {}).get("page", "")} for p in event["pages"]]
    headline = {**sources[0], "related": sources[1:]} if sources else {"title": event["text"], "source": "Wikipedia"}
    segments = [{"kind": "story", "source": "Wikipedia", "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "hook_title": out.get("hook_title", ""), "label": "ON THIS DAY", "lang": "en",
            "segments": segments, "sources": [headline], "kind": "history", "era": str(event["year"]),
            "image_queries": [q for q in out.get("image_queries") or [] if q], "object_query": "",
            "place": {"country": "", "city": ""}, "image_files": files, "fill_with_search": True, "mood": "notr",
            "hashtags": script._tags(out.get("hashtags")) + ["onthisday", "history"],
            "category": "27", "image_prompt": ""}
