"""Haberlerden seslendirilecek video metnini hazırlar.

Beş tür video var: "story" tek bir gündem haberini, "world" dünya gündeminden tek bir haberi İngilizce
anlatır; "digest" günün öne çıkan haberlerini, "sports" spor
gündemini, "trend" bilim ve teknolojiden merak uyandıran gelişmeleri toplu özetler. GEMINI_API_KEY yoksa ya da model yanıt vermezse
başlıkların düz okunduğu özet formatına düşülür.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from .news import sensitive_headline

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
                    print("  " + " ".join(exc.read().decode("utf-8", "replace").split())[:700])
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
- Can kaybı, yaralanma ya da mağduriyet içeren bir haberi yalnızca sade ve saygılı bir dille, ayrıntıya girmeden
  aktar: merak kancası, ünlem, "feci", "dehşet" gibi sözcükler ve izleyiciye soru yok. Başlıkta yazmayan
  "ekipler sevk edildi", "trafik etkilendi" gibi ayrıntılar ekleme.
"""

IMAGE_FIELDS = """Wikimedia Commons araması (yer, nesne, kurum; kişi adı değil). Haberin geçtiği yeri ya da kurumu adıyla
  ara (örnek: "E-5 İstanbul", "Kapıkule", "TCDD train", "Rams Park"); yer adlarını Türkçe yazabilirsin. Konunun
  nesnesini yakın planda gösteren aramalar 2-3 kelimelik İngilizce olsun (örnek: "cigarette pack", "football stadium")."""

# Tek konulu video türleri: ekran etiketi, görev ve seçim tarifi
STORIES = {
    "story": {
        "label": "GÜNDEM", "hashtags": ["gündem", "haber"],
        "brief": """Görev: YouTube Shorts için Türkçe haber anlatımı. Kanalın sözü: "seni etkileyen haber, 40 saniyede".
Amaç izleyicinin kaydırmadan sonuna kadar izlemesi ve videodan işine yarar bir şey öğrenmesi.

Haber seçimi: İzleyicinin gündelik hayatını doğrudan etkileyen haberi seç: zam, maaş, vergi, yeni düzenleme, yasak,
resmi uyarı, deprem ve hava durumu, ulaşım ve yol durumu, sağlık, eğitim, teknoloji.
Seçme: cinayet, cinsel suç, kaza ve ölüm ayrıntısı öne çıkan haberler; adı geçen kişilere yönelik suçlama ve
tutuklama haberleri; seçim ve parti çekişmesi; köşe yazısı ve yorum; magazin; Türkiye'deki izleyicinin hayatına
dokunmayan dış politika haberleri. "pick" alanına seçtiğin haberin numarasını yaz.
""",
    },
    "world": {
        "label": "WORLD", "hashtags": ["worldnews", "news"], "lang": "en",
        "brief": """Task: write the English voice-over for a YouTube Short about one world news story. The channel's promise
is "world news in under a minute". The goal is that the viewer watches to the end and learns something real.

Story selection: pick the story a general international audience will care about most today: major diplomacy,
economy and markets, technology, science, climate and weather, health, or a decision that affects many people.
Do not pick: stories centred on deaths, attacks or violence; accusations against or arrests of named private people;
celebrity and entertainment news; opinion pieces; live blogs. Put the number of the story you picked in "pick".
""",
    },
}

# Aşağıdaki İngilizce kurallar Türkçe olanların karşılığıdır; biri değişirse diğeri de güncellenmeli.
ACCURACY_EN = """STRICT rules (they apply to the title, the on-screen text and the script alike):
- Use only information that appears in the headlines below. Do not add dates, institutions, numbers, places, names
  or outcomes that are not in a headline.
- Do not exaggerate or create a false impression. Do not invent an effect or reaction ("markets panicked").
- Do not present a demand, call or proposal as a decision that has been taken.
- Do not name minors, victims or private individuals; say "a 16-year-old" instead.
- If a story involves loss of life, injury or suffering, report it plainly and respectfully, without detail:
  no curiosity hook, no exclamation marks, no words like "horrific", and no question to the viewer.
"""

STORY_RULES_EN = """
Script rules:
1. The first sentence has at most 10 words: a surprising contrast or a direct question to the viewer.
   No greeting, no introduction, no "today".
2. Do not give the most striking detail straight away: context first, then lead into it near the end with a
   transition like "but here is what stands out".
3. Short sentences (at most 14 words), conversational, addressing the viewer as "you". No filler
   ("stay tuned", "only time will tell", "all eyes are on").
4. If the story is a rule, warning, price change, ban or service change, the second-to-last paragraph starts with
   "So what does this mean for you?" and states the practical consequence that follows directly from the headlines.
   If no such consequence follows, or people were harmed, leave this paragraph out; do not speculate.
5. The last sentence is a short question that invites a comment.
6. 75-90 words in total, 4-5 paragraphs (1-2 sentences each). Write everything in English.

""" + ACCURACY_EN + """
Other fields:
- hook_title: on-screen title, at most 5 words.
- title: YouTube title, at most 70 characters, with the story's main keyword first.
- image_queries: 5 different Wikimedia Commons searches in English (places, objects, institutions; never a
  person's name). The first two name the place or institution in the story (example: "Brussels European
  Commission", "Port of Rotterdam"), the next two show the subject as an object in 2-3 words (example:
  "oil tanker", "wind turbines"), the last is one very general word (example: "parliament", "satellite").
- mood: one of "notr" (informative, everyday; use this when unsure), "gergin" (crisis, disaster, danger, warning,
  conflict), "umutlu" (good news, success, opening), "huzunlu" (loss, mourning). Use these exact words.
- hashtags: 3 topic-specific tags; one word each, lowercase, no spaces (example: "eu", "inflation", "nasa").
- image_prompt: a symbolic vertical illustration of the topic with no real people and no text.

Return only JSON:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "image_queries": ["..."], "mood": "notr", "hashtags": ["..."], "image_prompt": "..."}
"""

STORY_RULES = """
Metin kuralları:
1. İlk cümle en fazla 10 kelime: şaşırtıcı bir tezat ya da doğrudan izleyiciye soru. Selam, giriş, "bugün" yok.
2. Asıl çarpıcı ayrıntıyı hemen verme: önce bağlam, sonra "ama asıl dikkat çeken şu" gibi bir geçişle en sona yakın ver.
3. Cümleler kısa (en fazla 12 kelime), konuşur gibi, "sen" diye hitap et. Tekrar ve dolgu cümle yok
   ("takipte kalın", "merakla bekleniyor", "dikkatle izleniyor" yasak).
4. Haber bir düzenleme, uyarı, zam, yasak ya da hizmet değişikliğiyse sondan bir önceki paragraf
   "Peki bu senin için ne demek?" diye başlasın ve başlıklardaki bilgiden doğrudan çıkan pratik sonucu söylesin
   (örnek: "O yolu kullanıyorsan yarın erken çık."). Başlıklardan böyle bir sonuç çıkmıyorsa ya da haberde
   zarar gören insanlar varsa bu paragrafı hiç yazma; tahmin yürütme.
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
    # Bilim ve teknoloji akışı haber başına tek başlık verir; tek haberlik uzun anlatım için malzeme yetmez
    # (model boşluğu uydurarak dolduruyor), bu yüzden trendler de kısa maddeler hâlinde verilir.
    "trend": {
        "label": "TREND", "count": 4, "mood": "notr", "hashtags": ["bilim", "teknoloji"],
        "subject": "bilim ve teknolojiden merak uyandıran gelişmeler özeti (ciddi bir haber kanalının "
                   "\"bunu duydun mu?\" köşesi; üslup meraklı ve canlı ama abartısız)",
        "selection": "En şaşırtıcı, \"vay be\" dedirten ve herkesin anlayabileceği gelişmeler: keşifler, uzay, yapay zekâ, "
                     "yeni teknolojiler, doğa olayları, rekorlar, Türkiye'den bilim ve teknoloji başarıları. Başlığı ne "
                     "olduğunu somut olarak söyleyen haberleri seç.",
        "avoid": "ne olduğunu söylemeyen merak tuzağı başlıklar (\"mucizeyi yaşadılar\", \"duyan inanamadı\"); magazin, "
                 "dizi ve ünlüler; ürün tanıtımı, indirim ve fiyat haberleri; sızıntı ve söylentiler; savaş ve silah "
                 "haberleri; siyaset; dinî yorum içeren haberler.",
        "intro_example": "Bugün bilim dünyasından dört şaşırtıcı gelişme.",
        "outro_example": "Hangisi seni en çok şaşırttı?",
        "fallback_title": "Bilim ve Teknolojide Bugün", "fallback_intro": "Bilim ve teknolojide bugün öne çıkanlar.",
        "fallback_outro": "Hangisi seni en çok şaşırttı?",
        "fallback_queries": ["space telescope", "laboratory microscope", "circuit board"],
    },
}


def _sentence(text):
    text = text.strip()
    return text if text[-1:] in ".!?" else text + "."


def _blocks(headlines, english=False):
    others = "Other sources" if english else "Diğer kaynaklar"
    blocks = []
    for i, h in enumerate(headlines, 1):
        related = "\n".join(f"   - {r['title']} ({r['source']})" for r in h.get("related", [])[:6])
        blocks.append(f"{i}. {h['title']} ({h['source']})" + (f"\n   {others}:\n{related}" if related else ""))
    return blocks


def _pick(headlines, number):
    return headlines[max(0, min(int(number), len(headlines)) - 1)]


def source_label(headline, limit=2):
    """Ekranda gösterilecek kaynak adları: haber kümesindeki ilk birkaç yayın."""
    names = [headline["source"]] + [r["source"] for r in headline.get("related", [])]
    return ", ".join(list(dict.fromkeys(n for n in names if n))[:limit])


def _tags(values):
    return [t for t in (re.sub(r"[^\w]", "", str(v)).lower() for v in values or []) if t][:3]


def story_script(headlines, kind="story", count=10, recent=()):
    spec = STORIES[kind]
    english = spec.get("lang") == "en"
    headlines = headlines[:count]
    prompt = spec["brief"] + (STORY_RULES_EN if english else STORY_RULES)
    if recent:
        # Aynı olay farklı başlıkla yeniden gelebiliyor; başlık eşleşmesi yetmez
        prompt += ("\nTopics covered in recent videos (do not pick a story about the same event):\n" if english
                   else "\nSon videolarda işlenen konular (aynı olayı anlatan haberi seçme):\n")
        prompt += "\n".join(f"- {t}" for t in recent) + "\n"
    prompt += ("\nStories:\n" if english else "\nHaberler:\n") + "\n".join(_blocks(headlines, english))
    out = json.loads(_generate(prompt, os.environ["GEMINI_API_KEY"]))
    headline = _pick(headlines, out.get("pick", 1))
    segments = [{"kind": "story", "source": source_label(headline), "text": p} for p in out["paragraphs"]]
    return {"title": out["title"], "hook_title": out.get("hook_title", ""), "label": spec["label"],
            "lang": spec.get("lang", "tr"), "segments": segments,
            "sources": [headline], "image_queries": out.get("image_queries") or [],
            "mood": out.get("mood", "notr"), "hashtags": _tags(out.get("hashtags")) + spec["hashtags"],
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
            heading, text = item.get("heading", ""), item["text"]
            if sensitive_headline(headline):  # acı haber ünlemle verilmez
                heading, text = heading.replace("!", ""), text.replace("!", ".")
            items.append((headline, heading, text, item.get("image_queries") or []))
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
            if mode in STORIES:
                return story_script(headlines, mode, recent=recent)
            return digest_script(headlines, mode)
        except Exception as exc:  # dil modeli düşerse o saatin videosu yine çıksın
            print(f"Gemini başarısız, özet formatına geçiliyor: {exc}")
    if STORIES.get(mode, {}).get("lang") == "en":
        raise RuntimeError("İngilizce video dil modeli olmadan yazılamıyor; bu saatin videosu atlanıyor.")
    return plain_digest(headlines, "digest" if mode in STORIES else mode)
