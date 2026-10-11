"""Haberlerden seslendirilecek video metnini hazırlar.

Üç tür video var: "story" tek bir haberi anlatır, "digest" günün öne çıkan haberlerini,
"sports" spor gündemini toplu özetler. GEMINI_API_KEY yoksa ya da model yanıt vermezse
başlıkların düz okunduğu özet formatına düşülür.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

# Yoğunlukta 503 dönebiliyor; sırayla denenir
DEFAULT_MODELS = "gemini-flash-latest,gemini-3.5-flash,gemini-flash-lite-latest"
_out_of_quota = set()  # 429 dönen model bu çalışmada bir daha denenmez; kota dakikalar içinde açılmıyor


def _generate(prompt, key, images=(), models=None):
    """images: istemin sonuna eklenecek JPEG baytları (görsel değerlendirme için).
    models: denenecek modeller, virgülle; verilmezse metin yazımı için ayrılan sıra kullanılır."""
    parts = [{"text": prompt}] + [{"inline_data": {"mime_type": "image/jpeg",
                                                   "data": base64.b64encode(img).decode()}} for img in images]
    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    models = (models or os.environ.get("GEMINI_MODELS", DEFAULT_MODELS)).split(",")
    last_err = None
    for model in models:
        if model in _out_of_quota:
            continue
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
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                    # Hangi sınırın dolduğu (dakikalık mı günlük mü) yanıtın içinde yazıyor
                    print("  " + " ".join(exc.read().decode("utf-8", "replace").split())[:300])
                    _out_of_quota.add(model)
                    break
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (500, 503):
                    break  # tekrar denemek işe yaramaz, sıradaki modele geç
                time.sleep(10)
    raise RuntimeError(f"Hiçbir Gemini modeli yanıt vermedi: {last_err}")


ACCURACY = """KESİN kurallar (başlık, ekran yazısı ve metin için aynen geçerli):
- Yalnızca verilen başlıklardaki bilgileri kullan. Başlıkta olmayan tarih, kurum, rakam, yer, isim, sonuç ekleme.
- Abartma, yanlış izlenim verme. Başlıkta yazmayan bir etki ya da tepki uydurma ("piyasalar karıştı", "ortalık yıkıldı").
- Bir başlıktaki talep, çağrı veya öneriyi alınmış karar gibi sunma ("engelleyin" diyen başlık "engellendi" demek değildir).
- 18 yaşından küçüklerin, mağdurların ve kamuya mal olmamış kişilerin adını yazma; "16 yaşındaki genç" gibi anlat.
"""

IMAGE_FIELDS = """Wikimedia Commons araması (yer, nesne, kurum; kişi adı değil). Haberin geçtiği yeri ya da kurumu adıyla
  ara (örnek: "E-5 İstanbul", "Kapıkule", "TCDD train", "Rams Park"); yer adlarını Türkçe yazabilirsin. Konunun
  nesnesini yakın planda gösteren aramalar 2-3 kelimelik İngilizce olsun (örnek: "cigarette pack", "football stadium")."""

STORY_RULES = """Görev: YouTube Shorts için Türkçe haber anlatımı. Kanalın sözü: "seni etkileyen haber, 40 saniyede".
Amaç izleyicinin kaydırmadan sonuna kadar izlemesi ve videodan işine yarar bir şey öğrenmesi.

Haber seçimi: İzleyicinin gündelik hayatını doğrudan etkileyen haberi seç: zam, maaş, vergi, yeni düzenleme, yasak,
resmi uyarı, deprem ve hava durumu, ulaşım ve yol durumu, sağlık, eğitim, teknoloji.
Seçme: cinayet, cinsel suç, kaza ve ölüm ayrıntısı öne çıkan haberler; adı geçen kişilere yönelik suçlama ve
tutuklama haberleri; seçim ve parti çekişmesi; köşe yazısı ve yorum; magazin; Türkiye'deki izleyicinin hayatına
dokunmayan dış politika haberleri. "pick" alanına seçtiğin haberin numarasını yaz.

Metin kuralları:
1. İlk cümle en fazla 10 kelime: şaşırtıcı bir tezat ya da doğrudan izleyiciye soru. Selam, giriş, "bugün" yok.
2. Asıl çarpıcı ayrıntıyı hemen verme: önce bağlam, sonra "ama asıl dikkat çeken şu" gibi bir geçişle en sona yakın ver.
3. Cümleler kısa (en fazla 12 kelime), konuşur gibi, "sen" diye hitap et. Tekrar ve dolgu cümle yok
   ("takipte kalın", "merakla bekleniyor", "dikkatle izleniyor" yasak).
4. Sondan bir önceki paragraf "Peki bu senin için ne demek?" diye başlasın ve başlıklardaki bilgiden doğrudan çıkan
   pratik sonucu söylesin (örnek: "O yolu kullanıyorsan yarın erken çık."). Başlıklardan böyle bir sonuç çıkmıyorsa
   bu paragrafı hiç yazma; tahmin yürütme.
5. Son cümle izleyiciye yorum yaptıracak kısa bir soru olsun.
6. Toplam 75-90 kelime, 4-5 paragraf (her paragraf 1-2 cümle).

""" + ACCURACY + """
Ek alanlar:
- hook_title: ekranda yazacak en fazla 5 kelimelik başlık.
- title: YouTube başlığı, en fazla 70 karakter; haberin anahtar kelimesi başta olsun.
- image_queries: 5 farklı """ + IMAGE_FIELDS + """
  İlk ikisi yer ya da kurum, sonraki ikisi nesne, sonuncusu tek kelimelik çok genel bir İngilizce kavram olsun
  (örnek: "smartphone", "earthquake", "courthouse").
- mood: fon müziği için haberin duygusu, şunlardan biri: "notr" (bilgilendirici, gündelik; emin değilsen bu),
  "gergin" (kriz, afet, tehlike, uyarı, çatışma), "umutlu" (iyi haber, başarı, açılış, kolaylık),
  "huzunlu" (kayıp, yas, üzücü olay).
- hashtags: konuya özel 3 etiket; tek kelime, küçük harf, boşluksuz (örnek: "deprem", "istanbul", "emekli").
- image_prompt: konuyu sembolik anlatan, gerçek kişi ve yazı içermeyen dikey illüstrasyon tarifi (İngilizce).

Sadece JSON döndür:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "image_queries": ["..."], "mood": "notr", "hashtags": ["..."], "image_prompt": "..."}
"""

DIGEST_RULES = """Görev: YouTube Shorts için Türkçe {subject}. Aşağıdaki haberlerden birbirinden farklı {count} tanesini
seç ve her birini çok kısa anlat. İzleyici bir dakikadan kısa sürede günün özetini almış olmalı.

Haber seçimi: {selection}
Seçme: köşe yazısı ve yorum; cinayet, cinsel suç ve ölüm ayrıntısı öne çıkan haberler; {avoid}

Alanlar:
- intro: en fazla 8 kelimelik giriş cümlesi, selam yok (örnek: "{intro_example}").
- items: seçtiğin her haber için, önem sırasıyla:
  - pick: haberin numarası
  - heading: ekranda yazacak en fazla 5 kelimelik başlık
  - text: 1-2 kısa cümle, en fazla 22 kelime; haberin özü, konuşur gibi
  - image_queries: 3 farklı """ + IMAGE_FIELDS + """
- outro: izleyiciye yorum yaptıracak kısa bir soru (örnek: "{outro_example}").
- title: YouTube başlığı, en fazla 70 karakter; en dikkat çekici iki haberi ansın.
- hashtags: konuya özel 3 etiket; tek kelime, küçük harf, boşluksuz.

""" + ACCURACY + """
Sadece JSON döndür:
{{"intro": "...", "items": [{{"pick": 1, "heading": "...", "text": "...", "image_queries": ["..."]}}], "outro": "...", "title": "...", "hashtags": ["..."]}}
"""

# Toplu özet türleri: ekran etiketi, istem ayrıntıları ve dil modeli yokken kullanılacak yedekler
DIGESTS = {
    "digest": {
        "label": "GÜNÜN ÖZETİ", "count": 5, "mood": "notr", "hashtags": ["gündem", "haber"],
        "subject": "günün öne çıkan haberleri özeti",
        "selection": "Türkiye'de bugün en çok konuşulan ve izleyicinin hayatına dokunan haberler; konular çeşitli olsun.",
        "avoid": "seçim ve parti çekişmesi; magazin.",
        "intro_example": "Bugünün beş haberi, bir dakikada.",
        "outro_example": "Sence bugünün en önemli haberi hangisiydi?",
        "fallback_title": "Günün Öne Çıkan Haberleri", "fallback_intro": "Bugün Türkiye'de öne çıkan haberler.",
        "fallback_outro": "Sence günün en önemli haberi hangisiydi?",
        "fallback_queries": ["Istanbul skyline", "Ankara city", "Bosphorus bridge", "Izmir city"],
    },
    "sports": {
        "label": "SPOR", "count": 4, "mood": "umutlu", "hashtags": ["spor", "futbol"],
        "subject": "spor gündemi özeti",
        "selection": "Süper Lig ve milli takımlar başta olmak üzere en çok konuşulan maç sonuçları, transferler ve "
                     "açıklamalar; farklı takım ve branşlardan seç.",
        "avoid": "canlı anlatım, muhtemel on bir ve bahis içerikleri; yalnızca bir yorumcunun görüşünü aktaran haberler.",
        "intro_example": "Spor gündeminde bugün dört başlık var.",
        "outro_example": "Sence haftanın sürprizi hangisi?",
        "fallback_title": "Spor Gündemi", "fallback_intro": "Spor gündeminde bugün öne çıkanlar.",
        "fallback_outro": "Sence günün spor haberi hangisiydi?",
        "fallback_queries": ["football stadium", "football pitch", "soccer ball"],
    },
}


def _sentence(text):
    text = text.strip()
    return text if text[-1:] in ".!?" else text + "."


def _blocks(headlines):
    blocks = []
    for i, h in enumerate(headlines, 1):
        related = "\n".join(f"   - {r['title']} ({r['source']})" for r in h.get("related", [])[:6])
        blocks.append(f"{i}. {h['title']} ({h['source']})" + (f"\n   Diğer kaynaklar:\n{related}" if related else ""))
    return blocks


def _pick(headlines, number):
    return headlines[max(0, min(int(number), len(headlines)) - 1)]


def source_label(headline, limit=2):
    """Ekranda gösterilecek kaynak adları: haber kümesindeki ilk birkaç yayın."""
    names = [headline["source"]] + [r["source"] for r in headline.get("related", [])]
    return ", ".join(list(dict.fromkeys(n for n in names if n))[:limit])


def _tags(values):
    return [t for t in (re.sub(r"[^\w]", "", str(v)).lower() for v in values or []) if t][:3]


def story_script(headlines, count=8, recent=()):
    headlines = headlines[:count]
    prompt = STORY_RULES
    if recent:
        # Aynı olay farklı başlıkla yeniden gelebiliyor; başlık eşleşmesi yetmez
        prompt += ("\nSon videolarda işlenen konular (aynı olayı anlatan haberi seçme):\n"
                   + "\n".join(f"- {t}" for t in recent) + "\n")
    prompt += "\nHaberler:\n" + "\n".join(_blocks(headlines))
    out = json.loads(_generate(prompt, os.environ["GEMINI_API_KEY"]))
    headline = _pick(headlines, out.get("pick", 1))
    segments = [{"kind": "story", "source": source_label(headline), "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "hook_title": out.get("hook_title", ""), "label": "GÜNDEM", "segments": segments,
            "sources": [headline], "image_queries": out.get("image_queries") or [],
            "mood": out.get("mood", "notr"), "hashtags": _tags(out.get("hashtags")) + ["gündem", "haber"],
            "image_prompt": out.get("image_prompt", "")}


def _digest_plan(kind, title, intro, items, outro, hashtags=()):
    """items: [(haber, ekran başlığı, metin, görsel aramaları)]"""
    spec = DIGESTS[kind]
    segments = [{"kind": "intro", "text": intro}]
    for i, (headline, heading, text, queries) in enumerate(items, 1):
        segments.append({"kind": "item", "label": f"{spec['label']} {i}/{len(items)}", "heading": heading,
                         "source": source_label(headline), "text": _sentence(text),
                         "headline": headline, "image_queries": queries})
    segments.append({"kind": "outro", "text": outro})
    return {"title": title, "hook_title": "", "label": spec["label"], "segments": segments,
            "sources": [h for h, *_ in items], "mood": spec["mood"],
            "hashtags": _tags(hashtags) + spec["hashtags"]}


def digest_script(headlines, kind, count=14):
    spec = DIGESTS[kind]
    headlines = headlines[:count]
    prompt = DIGEST_RULES.format(**spec) + "\nHaberler:\n" + "\n".join(_blocks(headlines))
    out = json.loads(_generate(prompt, os.environ["GEMINI_API_KEY"]))
    items, seen = [], set()
    for item in out["items"]:
        headline = _pick(headlines, item.get("pick", 1))
        if headline["title"] not in seen:
            seen.add(headline["title"])
            items.append((headline, item.get("heading", ""), item["text"], item.get("image_queries") or []))
    return _digest_plan(kind, out["title"], out["intro"], items[:spec["count"]], out["outro"], out.get("hashtags"))


def plain_digest(headlines, kind="digest", count=3):
    """Dil modeli olmadan: ilk başlıklar olduğu gibi okunur, genel fotoğraflar kullanılır."""
    spec = DIGESTS[kind]
    queries = spec["fallback_queries"]
    items = [(h, "", h["title"], [queries[i % len(queries)]]) for i, h in enumerate(headlines[:count])]
    return _digest_plan(kind, spec["fallback_title"], spec["fallback_intro"], items, spec["fallback_outro"])


def build_script(headlines, mode="story", recent=()):
    if os.environ.get("GEMINI_API_KEY"):
        try:
            if mode == "story":
                return story_script(headlines, recent=recent)
            return digest_script(headlines, mode)
        except Exception as exc:  # dil modeli düşerse o saatin videosu yine çıksın
            print(f"Gemini başarısız, özet formatına geçiliyor: {exc}")
    return plain_digest(headlines, "digest" if mode == "story" else mode)
