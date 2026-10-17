"""Haberlerden seslendirilecek video metnini hazırlar.

Beş tür video var: "story" tek bir gündem haberini, "world" dünya gündeminden tek bir haberi İngilizce
anlatır; "digest" günün, "morning" sabahın öne çıkan haberlerini, "sports" spor
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

# Görsel alanları. Yer adı aramaya kodda eklenir: böylece insan, sokak ve bina fotoğrafları yalnızca haberin
# geçtiği ülkeden ya da şehirden aranır.
IMAGE_FIELDS = """- country: haberin geçtiği ülkenin İngilizce adı (örnek: "Turkey", "France"). Haber belirli bir ülkede
  geçmiyorsa (uzay, genel bilim, küresel teknoloji) boş bırak.
- city: haber tek bir şehirde geçiyorsa o şehrin adı (örnek: "Istanbul", "Tokat", "Paris"); değilse boş bırak.
- image_queries: Wikimedia Commons için {n} farklı İngilizce arama, her biri 1-3 kelime; haberde görülmesi gereken
  yer, bina, kurum ya da ortam (örnek: "school building", "courthouse", "highway traffic", "stadium").
  Aramaya ülke ya da şehir adı YAZMA (onlar ayrıca eklenir) ve kişi adı yazma.
- object_query: haberin konusu olan nesnenin, içinde insan ve yer olmayan yakın plan fotoğrafı için tek bir
  İngilizce arama (örnek: "cigarette pack", "banknotes", "smartphone"); uygun bir nesne yoksa boş bırak."""

IMAGE_FIELDS_EN = """- country: English name of the country where the story takes place (example: "Poland", "Japan"). Leave empty
  if the story is not tied to one country (space, global technology).
- city: the city, if the story takes place in a single city (example: "Brussels", "Paris"); otherwise empty.
- image_queries: {n} different Wikimedia Commons searches in English, 1-3 words each: the place, building,
  institution or setting the viewer should see (example: "parliament building", "container port", "power plant").
  Do NOT put the country or city name in the search (it is added separately) and never a person's name.
- object_query: one English search for a close-up of the object the story is about, with no people and no
  location in the frame (example: "oil barrel", "banknotes", "satellite dish"); empty if there is none."""

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
4. The last sentence is a short question that invites a comment.
5. 75-90 words in total, 4-5 paragraphs (1-2 sentences each). Write everything in English.
6. Leave nothing unresolved. Anything the title, on-screen title or script makes the viewer curious about must be
   answered clearly in the script: if you say "a surprise decision", say what the decision is. If the answer is not
   in the headlines (including the other sources), do not pick that story.

""" + ACCURACY_EN + """
Other fields:
- hook_title: on-screen title, at most 5 words.
- title: YouTube title, at most 70 characters, with the story's main keyword first.
""" + IMAGE_FIELDS_EN.format(n=4) + """
- mood: one of "notr" (informative, everyday; use this when unsure), "gergin" (crisis, disaster, danger, warning,
  conflict), "umutlu" (good news, success, opening), "huzunlu" (loss, mourning). Use these exact words.
- hashtags: 3 topic-specific tags; one word each, lowercase, no spaces (example: "eu", "inflation", "nasa").
- image_prompt: a symbolic vertical illustration of the topic with no real people and no text.

Return only JSON:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "country": "...", "city": "", "image_queries": ["..."], "object_query": "", "mood": "notr", "hashtags": ["..."], "image_prompt": "..."}
"""

# Seslendirme yabancı isimleri bu okunuşla söyler, altyazıda orijinal yazım kalır (tts.PRONOUNCE)
PRONOUNCE_FIELD = """- pronounce: metindeki Türkçe olmayan özel isimlerin (kişi, kulüp, şirket, yer, marka) Türkçe harflerle okunuşu
  (örnek: {"Osimhen": "Osimhen", "Chelsea": "Çelsi", "Microsoft": "Maykrosoft", "Bordeaux": "Bordo"}).
  Yalnızca Türkçe yazıldığı gibi okununca yanlış çıkacak isimleri yaz; yoksa boş bırak. Metinde isimlerin
  orijinal yazımını kullan.
"""

STORY_RULES = """
Metin kuralları:
1. İlk cümle en fazla 10 kelime: şaşırtıcı bir tezat ya da doğrudan izleyiciye soru. Selam, giriş, "bugün" yok.
2. Asıl çarpıcı ayrıntıyı hemen verme: önce bağlam, sonra "ama asıl dikkat çeken şu" gibi bir geçişle en sona yakın ver.
3. Cümleler kısa (en fazla 12 kelime), konuşur gibi, "sen" diye hitap et. Tekrar ve dolgu cümle yok
   ("takipte kalın", "merakla bekleniyor", "dikkatle izleniyor" yasak).
4. Son cümle izleyiciye yorum yaptıracak kısa bir soru olsun.
5. Toplam 75-90 kelime, 4-5 paragraf (her paragraf 1-2 cümle).
6. Belirsizlik bırakma. Başlıkta, ekran başlığında ya da metinde merak uyandırdığın her şeyin cevabı metinde açıkça
   olsun: "ilk 11'de sürpriz" diyorsan sürprizin ne olduğunu (hangi oyuncu, kimin yerine) söyle; "şok karar"
   diyorsan kararın ne olduğunu söyle. Cevap verilen başlıklarda (diğer kaynaklar dahil) yoksa o haberi seçme.

""" + ACCURACY + """
Ek alanlar:
- hook_title: ekranda yazacak en fazla 5 kelimelik başlık.
- title: YouTube başlığı, en fazla 70 karakter; haberin anahtar kelimesi başta olsun.
""" + IMAGE_FIELDS.format(n=4) + """
- mood: fon müziği için haberin duygusu, şunlardan biri: "notr" (bilgilendirici, gündelik; emin değilsen bu),
  "gergin" (kriz, afet, tehlike, uyarı, çatışma), "umutlu" (iyi haber, başarı, açılış, kolaylık),
  "huzunlu" (kayıp, yas, üzücü olay).
- hashtags: konuya özel 3 etiket; tek kelime, küçük harf, boşluksuz (örnek: "deprem", "istanbul", "emekli").
- image_prompt: konuyu sembolik anlatan, gerçek kişi ve yazı içermeyen dikey illüstrasyon tarifi (İngilizce).
""" + PRONOUNCE_FIELD + """
Sadece JSON döndür:
{"pick": 1, "hook_title": "...", "title": "...", "paragraphs": ["..."], "country": "...", "city": "", "image_queries": ["..."], "object_query": "", "mood": "notr", "hashtags": ["..."], "image_prompt": "...", "pronounce": {}}
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
  - text: 1-2 kısa cümle, en fazla 22 kelime; haberin özü, konuşur gibi. Belirsizlik bırakma: başlıkta merak
    uyandırdığın şeyin cevabı metinde olsun ("ilk 11'de sürpriz" diyorsan hangi oyuncu olduğunu söyle).
    Ne olduğunu söylemeyen ("sürpriz karar", "flaş gelişme", "herkes bunu konuşuyor") ve cevabı verilen
    başlıklarda bulunmayan haberleri seçme.
""" + "\n".join("  " + line for line in IMAGE_FIELDS.format(n=2).splitlines()).replace("{", "{{").replace("}", "}}") + """
- outro: izleyiciye yorum yaptıracak kısa bir soru (örnek: "{outro_example}").
- title: YouTube başlığı, en fazla 70 karakter; en dikkat çekici iki haberi ansın.
- hashtags: konuya özel 3 etiket; tek kelime, küçük harf, boşluksuz.
""" + PRONOUNCE_FIELD.replace("{", "{{").replace("}", "}}") + """
""" + ACCURACY + """
Sadece JSON döndür:
{{"intro": "...", "items": [{{"pick": 1, "heading": "...", "text": "...", "country": "...", "city": "", "image_queries": ["..."], "object_query": ""}}], "outro": "...", "title": "...", "hashtags": ["..."], "pronounce": {{}}}}
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
    # Sabah özeti: YouTube'un günlük yükleme sınırı yüzünden üç ayrı sabah videosunun yerini tek video aldı
    "morning": {
        "label": "SABAH ÖZETİ", "count": 5, "mood": "notr", "hashtags": ["gündem", "haber"],
        "subject": "sabah haber özeti (güne başlarken bilinmesi gerekenler)",
        "selection": "Geceden sabaha Türkiye'de öne çıkan ve izleyicinin o gününü etkileyen haberler: yeni düzenleme ve "
                     "kararlar, zam ve ödemeler, hava ve yol durumu, resmi uyarılar; konular çeşitli olsun.",
        "avoid": "seçim ve parti çekişmesi; magazin.",
        "intro_example": "Güne başlarken bilmen gereken beş haber.",
        "outro_example": "Bugün seni en çok hangisi etkileyecek?",
        "fallback_title": "Sabah Haber Özeti", "fallback_intro": "Güne başlarken öne çıkan haberler.",
        "fallback_outro": "Bugün seni en çok hangisi etkileyecek?",
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
    # Bazı yayınlar adına slogan ekliyor ("ABC News - Breaking News, Latest News and Videos")
    names = list(dict.fromkeys(n.split(" - ")[0].strip() for n in names if n))[:limit]
    label = ", ".join(names)
    return label if len(label) <= 34 else names[0][:34]  # ekrana tek satırda sığmalı


def _image_fields(out):
    """Modelin yanıtındaki görsel alanları: aramalar, nesne araması ve haberin geçtiği yer."""
    return {"image_queries": [q for q in out.get("image_queries") or [] if q],
            "object_query": (out.get("object_query") or "").strip(),
            "place": {"country": (out.get("country") or "").strip(), "city": (out.get("city") or "").strip()}}


def _pronounce(out):
    """Modelin verdiği okunuşlar; bozuk yanıtta seslendirme yine çalışsın."""
    value = out.get("pronounce")
    if not isinstance(value, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in value.items() if str(k).strip() and str(v).strip()}


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
            "sources": [headline], **_image_fields(out),
            "mood": out.get("mood", "notr"), "hashtags": _tags(out.get("hashtags")) + spec["hashtags"],
            "image_prompt": out.get("image_prompt", ""), "pronounce": _pronounce(out)}


def _digest_plan(kind, title, intro, items, outro, hashtags=()):
    """items: [(haber, ekran başlığı, metin, görsel alanları)]"""
    spec = DIGESTS[kind]
    segments = [{"kind": "intro", "text": intro}]
    for i, (headline, heading, text, queries) in enumerate(items, 1):
        segments.append({"kind": "item", "label": f"{spec['label']} {i}/{len(items)}", "heading": heading,
                         "source": source_label(headline), "text": _sentence(text),
                         "headline": headline, **queries})
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
            items.append((headline, heading, text, _image_fields(item)))
    plan = _digest_plan(kind, out["title"], out["intro"], items[:spec["count"]], out["outro"], out.get("hashtags"))
    return {**plan, "pronounce": _pronounce(out)}


def plain_digest(headlines, kind="digest", count=3):
    """Dil modeli olmadan: ilk başlıklar olduğu gibi okunur, genel fotoğraflar kullanılır."""
    spec = DIGESTS[kind]
    queries = spec["fallback_queries"]
    items = [(h, "", h["title"], {"image_queries": [queries[i % len(queries)]]})
             for i, h in enumerate(headlines[:count])]
    return _digest_plan(kind, spec["fallback_title"], spec["fallback_intro"], items, spec["fallback_outro"])


def custom_plan(item):
    """Elle yazılmış bir videonun planı. item alanları için scripts/custom/ altındaki dosyalara bakın."""
    sources = item["sources"]
    headline = {**sources[0], "related": sources[1:]}
    english = item.get("lang") == "en"
    # Paragraf düz metin ya da bölüm başı olabilir: {"text", "heading", "source" (kaynak sırası, 1'den),
    # "image_queries", "object_query", "country", "city"}. Bölüm başlığı sonraki düz paragraflara da geçer;
    # yatay uzun videoda (wide) ekranda yazar, bölümün kendi görselleri ve açıklamada zaman damgası olur.
    segments, sections = [], []
    current = {"heading": "", "source": source_label(headline), "section": None}
    for p in item["paragraphs"]:
        if isinstance(p, dict):
            if p.get("heading"):
                index = p.get("source")
                own = sources[index - 1] if isinstance(index, int) and 1 <= index <= len(sources) else None
                fields = _image_fields(p)
                has_images = fields["image_queries"] or fields["object_query"]
                sections.append({"title": p["heading"], "sources": [own or headline], **fields} if has_images else None)
                current = {"heading": p["heading"], "source": source_label(own) if own else source_label(headline),
                           "section": len(sections) - 1, "chapter": p["heading"]}
            text = p["text"]
        else:
            text = p
        segments.append({"kind": "story", "text": text, **current})
        current = {k: v for k, v in current.items() if k != "chapter"}  # zaman damgası yalnız bölümün ilk paragrafında
    return {"title": item["title"], "hook_title": item.get("hook_title", ""),
            "wide": bool(item.get("wide")), "sections": sections,
            "label": item.get("label", "NEWS" if english else "GÜNDEM"), "lang": item.get("lang", "tr"),
            "segments": segments, "sources": [headline], **_image_fields(item),
            "image_files": item.get("image_files") or [], "mood": item.get("mood", "notr"),
            "hashtags": _tags(item.get("hashtags")) + (["news"] if english else ["gündem", "haber"]),
            "category": item.get("category"), "subscribe": item.get("subscribe", True), "image_prompt": "",
            "pronounce": item.get("pronounce") or {}}


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
