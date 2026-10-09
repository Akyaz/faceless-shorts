"""Haberlerden seslendirilecek video metnini hazırlar.

GEMINI_API_KEY varsa tek bir haberi özgün bir hikayeye çevirir.
Yoksa "Günün 3 haberi" özet formatına düşer (dil modeli gerekmez).
"""
import json
import os
import time
import urllib.error
import urllib.request

# Yoğunlukta 503 dönebiliyor; sırayla denenir
DEFAULT_MODELS = "gemini-flash-latest,gemini-3.5-flash,gemini-flash-lite-latest"


def _sentence(text):
    text = text.strip()
    return text if text[-1:] in ".!?" else text + "."


def digest_script(headlines, count=3):
    picked = headlines[:count]
    segments = [{"kind": "intro", "text": "Bugün Türkiye'de öne çıkan üç haber."}]
    for i, h in enumerate(picked, 1):
        segments.append({"kind": "headline", "index": i, "total": len(picked),
                         "source": h["source"], "text": _sentence(h["title"])})
    segments.append({"kind": "outro", "text": "Günün haberleri için takipte kalın."})
    return {"title": "Günün 3 Haberi", "segments": segments, "sources": picked}


def _generate(prompt, key):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    models = os.environ.get("GEMINI_MODELS", DEFAULT_MODELS).split(",")
    last_err = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent"
        for attempt in range(2):
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                  "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.load(resp)
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (urllib.error.HTTPError, TimeoutError, urllib.error.URLError) as exc:
                last_err = exc
                print(f"Gemini {model} deneme {attempt + 1}: {exc}")
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 503):
                    break  # tekrar denemek işe yaramaz, sıradaki modele geç
                time.sleep(10)
    raise RuntimeError(f"Hiçbir Gemini modeli yanıt vermedi: {last_err}")


def story_script(headline):
    related = "\n".join(f"- {r}" for r in headline.get("related", [])[:8]) or "- (yok)"
    prompt = (
        "YouTube Shorts için Türkçe, tarafsız bir haber anlatımı yaz (35-40 saniye, yaklaşık 90-110 kelime, "
        "3-4 paragraf). İlk cümle merak uyandıran bir kanca olsun.\n"
        "KESİN KURAL: Yalnızca aşağıdaki başlıklarda geçen bilgileri kullan. Başlıklarda olmayan hiçbir "
        "tarih, kurum, rakam, yer veya isim ekleme. Bilgi azsa konuyu genel çerçevede açıkla ve "
        "izleyiciye ne beklemesi gerektiğini söyle; uydurma.\n"
        "Ayrıca arka plan görseli için:\n"
        "- image_query: Wikimedia Commons'ta aranacak 2-4 kelimelik İngilizce anahtar (yer, nesne veya kurum; "
        "kişi adı değil). Örn: \"smartphone social media\", \"Istanbul Bosphorus\".\n"
        "- image_prompt: konuyu sembolik anlatan, gerçek kişi ve yazı içermeyen, dikey bir illüstrasyon tarifi (İngilizce).\n"
        "Sadece JSON döndür: {\"title\": \"...\", \"paragraphs\": [\"...\"], "
        "\"image_query\": \"...\", \"image_prompt\": \"...\"}\n\n"
        f"Ana başlık: {headline['title']} ({headline['source']})\nAynı haberin diğer kaynaklardaki başlıkları:\n{related}"
    )
    out = json.loads(_generate(prompt, os.environ["GEMINI_API_KEY"]))
    segments = [{"kind": "story", "source": headline["source"], "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "segments": segments, "sources": [headline],
            "image_query": out.get("image_query", ""), "image_prompt": out.get("image_prompt", "")}


def build_script(headlines):
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return story_script(headlines[0])
        except Exception as exc:  # dil modeli düşerse o günün videosu yine çıksın
            print(f"Gemini başarısız, özet formatına geçiliyor: {exc}")
    return digest_script(headlines)
