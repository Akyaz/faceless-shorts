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
    # Dil modeli yokken habere özel arama üretilemez; genel Türkiye fotoğrafları kullanılır
    return {"title": "Günün 3 Haberi", "segments": segments, "sources": picked,
            "image_queries": ["Istanbul skyline", "Ankara city", "Bosphorus bridge", "Izmir city"]}


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


STORY_RULES = """Görev: YouTube Shorts için Türkçe haber anlatımı. Amaç izleyicinin kaydırmadan sonuna kadar izlemesi.

Haber seçimi: Aşağıdaki haberlerden genel kitleyi en çok meraklandıracak, gündelik hayata dokunan birini seç.
Seçme: ölüm/şiddet ayrıntısı öne çıkan haberler, adı geçen kişilere yönelik suçlama/tutuklama haberleri,
seçim ve parti çekişmesi. "pick" alanına seçtiğin haberin numarasını yaz.

Metin kuralları:
1. İlk cümle en fazla 10 kelime: şaşırtıcı bir tezat ya da doğrudan izleyiciye soru. Selam, giriş, "bugün" yok.
2. Asıl çarpıcı ayrıntıyı hemen verme: önce bağlam, sonra "ama asıl dikkat çeken şu" gibi bir geçişle en sona yakın ver.
3. Cümleler kısa (en fazla 12 kelime), konuşur gibi, "sen" diye hitap et. Tekrar ve dolgu cümle yok
   ("takipte kalın", "merakla bekleniyor", "dikkatle izleniyor" yasak).
4. Son cümle izleyiciye yorum yaptıracak kısa bir soru olsun.
5. Toplam 70-85 kelime, 4-5 paragraf (her paragraf 1-2 cümle).
6. KESİN: Yalnızca verilen başlıklardaki bilgileri kullan. Başlıkta olmayan tarih, kurum, rakam, yer, isim ekleme.
   Merak uyandır ama abartma ve yanlış izlenim verme. Bir başlıktaki talep, çağrı veya öneriyi
   alınmış karar gibi sunma ("engelleyin" diyen başlık "engellendi" demek değildir).

Ek alanlar:
- hook_title: ekranda yazacak en fazla 5 kelimelik çarpıcı başlık (doğru olmalı).
- title: YouTube başlığı, en fazla 70 karakter, merak uyandıran ama doğru.
- image_queries: Wikimedia Commons için 4 farklı İngilizce arama (yer, nesne, kurum; kişi adı değil).
  Her biri haberin başka bir yönünü göstersin. İlk üçü 2-3 kelime, sonuncusu tek kelimelik çok genel bir kavram
  (örnek: "smartphone", "earthquake", "courthouse") olsun ki mutlaka sonuç çıksın.
  Haber belirli bir yer ya da kurumla ilgiliyse aramalardan en az biri onun adını içersin (örnek: "Edirne", "TCDD train").
- image_prompt: konuyu sembolik anlatan, gerçek kişi ve yazı içermeyen dikey illüstrasyon tarifi (İngilizce).

Sadece JSON döndür:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "image_queries": ["..."], "image_prompt": "..."}
"""


def story_script(headlines, count=8, recent=()):
    blocks = []
    for i, h in enumerate(headlines[:count], 1):
        related = "\n".join(f"   - {r}" for r in h.get("related", [])[:6])
        blocks.append(f"{i}. {h['title']} ({h['source']})" + (f"\n   Diğer kaynaklar:\n{related}" if related else ""))
    prompt = STORY_RULES
    if recent:
        # Aynı olay farklı başlıkla yeniden gelebiliyor; başlık eşleşmesi yetmez
        prompt += ("\nSon videolarda işlenen konular (aynı olayı anlatan haberi seçme):\n"
                   + "\n".join(f"- {t}" for t in recent) + "\n")
    prompt += "\nHaberler:\n" + "\n".join(blocks)
    out = json.loads(_generate(prompt, os.environ["GEMINI_API_KEY"]))
    headline = headlines[max(0, min(int(out.get("pick", 1)), len(blocks)) - 1)]
    segments = [{"kind": "story", "source": headline["source"], "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "hook_title": out.get("hook_title", ""), "segments": segments,
            "sources": [headline], "image_queries": out.get("image_queries") or [],
            "image_prompt": out.get("image_prompt", "")}


def build_script(headlines, recent=()):
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return story_script(headlines, recent=recent)
        except Exception as exc:  # dil modeli düşerse o günün videosu yine çıksın
            print(f"Gemini başarısız, özet formatına geçiliyor: {exc}")
    return digest_script(headlines)
