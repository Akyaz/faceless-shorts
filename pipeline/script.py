"""Haberlerden seslendirilecek video metnini hazırlar.

GEMINI_API_KEY varsa tek bir haberi özgün bir hikayeye çevirir.
Yoksa "Günün 3 haberi" özet formatına düşer (dil modeli gerekmez).
"""
import json
import os
import urllib.request


def digest_script(headlines, count=3):
    picked = headlines[:count]
    segments = [{"kind": "intro", "text": "Bugün Türkiye'de öne çıkan üç haber."}]
    for i, h in enumerate(picked, 1):
        segments.append({"kind": "headline", "index": i, "total": len(picked),
                         "source": h["source"], "text": h["title"].rstrip(".") + "."})
    segments.append({"kind": "outro", "text": "Günün haberleri için takipte kalın."})
    return {"title": "Günün 3 Haberi", "segments": segments, "sources": picked}


def story_script(headline):
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = (
        "Aşağıdaki Türkçe haber başlığından YouTube Shorts için 35-45 saniyelik, "
        "özgün ve tarafsız bir anlatım metni yaz. İlk cümle merak uyandıran bir kanca olsun. "
        "Başlıkta olmayan bilgi uydurma; emin olmadığın ayrıntıyı ekleme. "
        "Sadece JSON döndür: {\"title\": \"...\", \"paragraphs\": [\"...\", \"...\"]}\n\n"
        f"Başlık: {headline['title']}\nKaynak: {headline['source']}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    out = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    segments = [{"kind": "story", "source": headline["source"], "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "segments": segments, "sources": [headline]}


def build_script(headlines):
    if os.environ.get("GEMINI_API_KEY"):
        return story_script(headlines[0])
    return digest_script(headlines)
