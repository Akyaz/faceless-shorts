"""Eskimeyen Türkçe "Biliyor muydun?" Shorts'u: scripts/evergreen/topics.txt listesindeki sıradaki konu.

Haber videoları birkaç saat içinde eskiyor; bu videolar aylarca önerilebilir. Metin yalnızca konunun Vikipedi
sayfasından yazılır (uydurma bilgi olmasın): önce Türkçe sayfa, kısaysa İngilizce sayfa kullanılır.
Görsel, sayfanın Commons'taki fotoğrafı ve konuya göre yapılan Commons aramalarıdır.
İşlenen konular state/evergreen.json'da tutulur; liste bitince en eski işlenenden yeniden başlanır.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import onthisday, script

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "scripts" / "evergreen" / "topics.txt"
STATE = Path("state") / "evergreen.json"
UA = "faceless-shorts/1.0 (https://github.com/Akyaz/faceless-shorts)"
MIN_TEXT = 1500  # bundan kısa Türkçe sayfada İngilizce sayfaya da bakılır
MAX_TEXT = 7000

RULES = """Görev: YouTube Shorts için Türkçe eskimeyen bilgi videosu. Konu eskimeyen bir merak konusu; video
aylar sonra da izlenecek. Amaç izleyicinin kaydırmadan sonuna kadar izlemesi, "vay be" demesi ve videoyu konuyu
sevecek bir arkadaşına göndermesi.

Metin kuralları:
1. İlk cümle en fazla 10 kelime ve konunun EN şaşırtıcı bilgisiyle başlar: bir sayı, bir tezat ya da inanılması
   zor bir gerçek (örnek: "Bu hayvanın üç kalbi ve mavi kanı var."). Selam, giriş, "bugün", "merhaba" yok.
   "Biliyor muydun" ile başlamak zorunda değilsin; her videoda aynı kalıbı kullanma.
2. Sonra kısa bağlam: ne, nerede, ne zaman. Ardından en ilginç iki-üç ayrıntı, her biri somut (sayı, ölçü, yer, yıl).
   Sade ve betimleyen anlatım: izleyici gözünde canlandırabilsin (boyut, renk, ses, kaç kişi, ne kadar sürede).
3. Soru ve retorik açılış yok ("hiç düşündün mü", "biliyor musun", "merak ediyor musun"); abartı ve dolgu yok.
4. Son cümle akılda kalan somut bir ayrıntı ya da bugüne bağlanan bir bilgi (örnek: "Bugün hâlâ 30 tanesi yollarda.").
   Soru sorma.
5. Cümleler kısa (en fazla 12 kelime), gündelik sözcükler, bir arkadaşa anlatır gibi.
6. Toplam 55-75 kelime, 3-4 paragraf (her paragraf 1-2 cümle).
7. YALNIZCA aşağıdaki Vikipedi metnindeki bilgileri kullan. Metinde olmayan sayı, tarih, isim ya da sonuç ekleme.
   Tartışmalı ya da kanıtlanmamış bir şeyse "iddia ediliyor", "tahmin ediliyor" de. Metin İngilizceyse Türkçeye çevir.

Ek alanlar:
- hook_title: ekranda yazacak en fazla 5 kelimelik merak başlığı; cevabı videoda olsun (örnek: "Üç Kalpli Hayvan").
- title: YouTube başlığı, en fazla 70 karakter; konunun adı başta, merak uyandıran ama yanıltmayan.
- image_queries: Wikimedia Commons için 4 farklı İngilizce arama, her biri 1-4 kelime; konunun kendisi ve anlatılan
  ayrıntılar (örnek: "Derinkuyu underground city", "Cappadocia tunnel", "stone door").
- object_query: konuyla ilgili insan ve yer içermeyen yakın plan nesne fotoğrafı için tek İngilizce arama; yoksa boş.
- country: konu belirli bir ülkedeyse İngilizce adı ("Turkey" gibi); değilse boş.
- mood: "notr", "umutlu", "gergin" ya da "huzunlu" (çoğu konu için "notr" ya da "umutlu").
- hashtags: konuya özel 3 etiket; tek kelime, küçük harf, boşluksuz.
""" + script.PRONOUNCE_FIELD + """
Sadece JSON döndür:
{"hook_title": "...", "title": "...", "paragraphs": ["..."], "image_queries": ["..."], "object_query": "", "country": "", "mood": "notr", "hashtags": ["..."], "pronounce": {}}
"""


# Konu serileri: 12:00 ve 15:00 videoları kategoriler arasında sırayla döner (kanal sahibinin seçtiği gruplar,
# 12 Kasım 2026). angle: o serinin metnine eklenen yön ve sınırlar.
CATEGORIES = {
    "bilgi": {"label": "BİLİYOR MUYDUN?", "hashtags": ["biliyormuydun", "bilgi"], "angle": ""},
    "otomobil": {"label": "OTOMOBİL", "hashtags": ["otomobil", "araba"],
                 "angle": "Seri: otomobil ve motor. Aracın ya da sporcunun en çarpıcı rakamını (hız, üretim adedi, "
                          "fiyat, rekor) ve ilginç bir mühendislik ayrıntısını anlat."},
    "para": {"label": "PARA VE İŞ", "hashtags": ["girişim", "ekonomi"],
             "angle": "Seri: para ve iş dünyası hikâyeleri. Nasıl başladığını, dönüm noktasını ve rakamları anlat. "
                      "Yatırım tavsiyesi verme, bir hisseyi ya da yatırımı önerme; skandallarda yalnızca mahkeme "
                      "kararıyla ya da resmi olarak kesinleşmiş bilgileri anlat."},
    "muhendislik": {"label": "BİLİM VE MÜHENDİSLİK", "hashtags": ["megaproje", "bilim"],
                    "angle": "Seri: mega projeler, havacılık, uzay, yapay zekâ ve siber güvenlik. Ölçüleri gözde "
                             "canlandırılacak biçimde ver (uzunluk, ağırlık, kaç yılda, kaç kişiyle)."},
    "tarih": {"label": "TARİH VE DÜNYA", "hashtags": ["tarih", "dünya"],
              "angle": "Seri: antik ve orta çağ tarihi, saraylar ve şatolar, doğa olayları, eski filmler, satranç ve "
                       "psikoloji. Doğa olaylarında can kaybını öne çıkarma; olayın bilimini ve ölçeğini anlat."},
}


def topics():
    """[(kategori, Türkçe arama, İngilizce arama)] dosyadaki sırayla; "[kategori]" satırı sonraki konuların kategorisi."""
    rows, category = [], "bilgi"
    for line in TOPICS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            category = line[1:-1].strip()
            if category not in CATEGORIES:
                raise ValueError(f"Bilinmeyen kategori: {category}")
            continue
        tr, _, en = (part.strip() for part in line.partition("|"))
        rows.append((category, tr, en or tr))
    return rows


def load_state(path=STATE):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _fold(text):
    return re.sub(r"\W+", " ", text.replace("İ", "i").lower().translate(str.maketrans("çğıöşüâî", "cgiosuai"))).strip()


def published(rows):
    """Panel kaydında (feed.json) yayınlanmış bilgi videolarının konuları. Konu kaydı çalışmalar arasında önbellekle
    taşınıyor; aynı anda çalışan iki çalışma ya da panelden sonradan yüklenen deneme videosu kaydı kaçırabiliyor
    (Devrim iki kez çıktı, 13 Kasım 2026). Yayınlanan başlıkta konunun adı geçiyorsa konu işlenmiş sayılır."""
    if not (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return []
    import base64
    from .report import BRANCH, FEED, _github
    try:
        feed = json.loads(base64.b64decode(_github(
            "GET", f"/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{FEED}?ref={BRANCH}")["content"]))
    except Exception as exc:
        print(f"Panel kaydı okunamadı: {exc}")
        return []
    titles = [_fold(v.get("title", "")) for e in feed if e.get("mode") == "fact"
              for v in e.get("videos", []) if v.get("url")]
    return [r[1] for r in rows if any(f" {_fold(r[1])} " in f" {t} " for t in titles)]


def next_topic(rows, done, extra=()):
    """Sırası gelen kategorinin (en uzun zamandır video çıkmayan) işlenmemiş ilk konusu; kategorinin bütün konuları
    işlendiyse o kategoride en uzun zamandır işlenmeyen."""
    used = [d["topic"] for d in done] + [t for t in extra if t not in {d["topic"] for d in done}]
    last_cat = {}
    for i, d in enumerate(done):
        last_cat[d.get("category", "bilgi")] = i
    categories = list(dict.fromkeys(r[0] for r in rows))
    category = min(categories, key=lambda c: (last_cat.get(c, -1), categories.index(c)))
    pool = [r for r in rows if r[0] == category]
    fresh = [r for r in pool if r[1] not in used]
    if fresh:
        return fresh[0]
    return min(pool, key=lambda r: max(i for i, t in enumerate(used) if t == r[1]))


def _api(lang, **params):
    query = urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    req = urllib.request.Request(f"https://{lang}.wikipedia.org/w/api.php?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def wiki_page(search, lang):
    """Aramanın ilk sonucu: başlık, düz metin, adres ve sayfa fotoğrafı (Commons'taysa)."""
    hits = _api(lang, action="query", list="search", srsearch=search, srlimit=1)["query"]["search"]
    if not hits:
        return None
    page = _api(lang, action="query", prop="extracts|pageimages|info", titles=hits[0]["title"], redirects=1,
                explaintext=1, piprop="original", inprop="url")["query"]["pages"][0]
    original = (page.get("original") or {}).get("source", "")
    return {"title": page["title"], "text": (page.get("extract") or "")[:MAX_TEXT], "url": page.get("fullurl", ""),
            "image": onthisday._commons_file({"originalimage": {"source": original}}), "lang": lang}


def plan(state_path=STATE):
    rows = topics()
    done = load_state(state_path)
    category, tr, en = next_topic(rows, done, published(rows))
    spec = CATEGORIES[category]
    pages = [p for p in [wiki_page(tr, "tr")] if p]
    if not pages or len(pages[0]["text"]) < MIN_TEXT:
        english = wiki_page(en, "en")
        if english:
            pages.append(english)
    pages = [p for p in pages if p["text"]]
    if not pages:
        raise RuntimeError(f"Vikipedi'de bulunamadı: {tr}")
    print(f"Konu: {tr} -> " + ", ".join(f"{p['lang']}:{p['title']} ({len(p['text'])} harf)" for p in pages))

    text = "\n\n".join(f"Vikipedi ({p['lang']}) \"{p['title']}\":\n{p['text']}" for p in pages)
    rules = RULES + (f"\n{spec['angle']}\n" if spec["angle"] else "")
    out = json.loads(script._generate(rules + "\n" + text, os.environ["GEMINI_API_KEY"]))
    unclear = [p for p in out["paragraphs"] if script.vague(p)]
    if unclear:
        print(f"Belirsiz cümle: {unclear}")

    sources = [{"title": p["title"], "source": "Vikipedi" if p["lang"] == "tr" else "Wikipedia", "link": p["url"]}
               for p in pages]
    segments = [{"kind": "story", "source": sources[0]["source"], "text": p} for p in out["paragraphs"]]
    result = {"title": out["title"], "hook_title": out.get("hook_title", ""), "label": spec["label"],
              "lang": "tr", "segments": segments, "sources": [{**sources[0], "related": sources[1:]}],
              "kind": "fact", **script._image_fields(out),
              "image_files": [p["image"] for p in pages if p["image"]][:1], "fill_with_search": True,
              "mood": out.get("mood", "notr"),
              "hashtags": script._tags(out.get("hashtags")) + spec["hashtags"],
              "category": "27", "image_prompt": "", "pronounce": script._pronounce(out),
              # Haber kanalının "günün haberleri" sözü bu videoya uymuyor
              "texts": {"subscribe": "Her gün bir \"vay be\" bilgisi. Kaçırmamak için kanala abone ol.",
                        "tags": ["bilgi", "ilginç bilgiler", "shorts"]},
              "promise": "Her gün bir ilginç bilgi bu kanalda", "dated": False}
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(done + [{"topic": tr, "category": category, "title": out["title"]}], ensure_ascii=False, indent=2),
                                encoding="utf-8")
    return result
