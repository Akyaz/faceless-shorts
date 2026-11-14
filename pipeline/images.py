"""Habere uygun arka plan görsellerini ve video kliplerini bulur.

Kaynaklar (hepsi ticari kullanıma ve kırpmaya izin veren lisanslar):
- Wikimedia Commons: serbest lisanslı fotoğraflar.
- Openverse: Flickr ve müze arşivlerindeki CC BY, CC BY-SA, CC0 ve kamu malı fotoğraflar (anahtarsız).
- Pexels ve Pixabay: fotoğraf ve HD video klipler (PEXELS_API_KEY, PIXABAY_API_KEY varsa).
- NASA görsel arşivi: bilgi serisinde uzay ve bilim konuları (kamu malı, anahtarsız).
Yalnızca Commons'a bağlı kalınca aynı birkaç fotoğraf dönüyor, video hiç yoktu (14 Kasım 2026). Bütün adaylar
Gemini'nin görsel elemesinden geçer. Eleme yapılamazsa yalnızca Commons sonuçları kullanılır: stok sitelerinin
etiketleri gevşek, konunun kendisi olmayan "temsili" görsel gelebiliyor.
Gemini illüstrasyonu en son çaredir. Haber sitelerinin fotoğrafları telifli olduğu için kullanılmaz. Tek istisna dizi
ve film haberleri: yapımın resmi afişi ve sahne görselleri (pipeline/platforms.py, save_direct) kullanılır ve hak
sahibi açıklamada belirtilir.
"""
import base64
import html
import json
import os
import re
import urllib.parse
import urllib.request

from . import script

UA = "faceless-shorts/0.1 (https://github.com/Akyaz/faceless-shorts)"
# Lisansı serbest görünse de açıklamasında "tüm hakları saklıdır" yazan ve müstehcen sayılabilecek görseller atlanır
EXCLUDED = re.compile(r"all rights reserved|diritti riservati|todos los derechos|alle rechte|tüm hakları|"
                      r"ithyphallic|phallic|phallus|nude|naked|erotic", re.I)
# Kanal ve şirket binaları dizi ve televizyon haberinde konuyu göstermiyor (her dizi haberinde aynı Kanal D binası)
MEDIA_BUILDINGS = re.compile(r"headquarters|merkez binas|genel merkez|media cent|medya merkez|plaza\b|"
                             r"\b(kanal d|show tv|star tv|atv|fox tv|now tv|tv8|trt|demirören|doğan medya)\b", re.I)
# Son günlerde kullanılmış arama görselleri (state/images.json): aynı fotoğraf her videoda dönmesin.
# Kişinin ya da yapımın kendi fotoğrafı bu kurala girmez.
RECENT = set()
USED = []
FREE_LICENSE = re.compile(r"^(CC0|CC BY(-SA)?( \d\.\d)?|Public domain|PD)", re.I)


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _strip(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


def wikimedia(query, limit=5):
    """Serbest lisanslı fotoğraf adaylarını döner: url, credit, about (dosya adı ve açıklaması)."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        # Sadece JPEG: PNG sonuçlar çoğunlukla logo, harita ve şema
        "gsrsearch": f"filemime:image/jpeg {query}", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400,
    })
    data = _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = _strip(meta.get("LicenseShortName", {}).get("value"))
        width, height = info.get("width", 0), info.get("height", 0)
        # Çok yatık panoramalar dikeye kırpılınca ince bir şerit kalıyor
        if not FREE_LICENSE.match(license_name) or width < 800 or width > 2.5 * height:
            continue
        described = page.get("title", "") + " " + _strip(meta.get("ImageDescription", {}).get("value"))
        if EXCLUDED.search(described) or MEDIA_BUILDINGS.search(described):
            continue
        artist = _strip(meta.get("Artist", {}).get("value")) or "Bilinmiyor"
        about = f"{page.get('title', '')} | {_strip(meta.get('ImageDescription', {}).get('value'))[:200]}"
        taken = re.search(r"(1[89]|20)\d\d", _strip(meta.get("DateTimeOriginal", {}).get("value"))
                          or _strip(meta.get("DateTime", {}).get("value")))
        found.append({"url": info["thumburl"], "about": about, "year": int(taken.group()) if taken else 0,
                      "source": "commons", "credit":
                      f"Görsel: {artist}, {license_name}, Wikimedia Commons ({info['descriptionurl']})"})
        if len(found) >= limit:
            break
    return found


LANDSCAPE_LIMIT = 2.5  # daha yatık panorama dikeye kırpılınca ince bir şerit kalıyor


def _usable(width, height, about):
    if width and (width < 800 or width > LANDSCAPE_LIMIT * (height or 1)):
        return False
    return not (EXCLUDED.search(about) or MEDIA_BUILDINGS.search(about))


def openverse(query, limit=5):
    """Openverse: Flickr ve müze arşivlerindeki serbest lisanslı fotoğraflar. NC (ticari olmayan) ve ND (değiştirilemez)
    lisanslar alınmaz: kanal para kazanıyor, fotoğraf da kırpılıyor. Commons sonuçları ayrıca arandığı için atlanır.
    Anahtarsız sınır günde 200 istek (videoda 3-5 arama yapılıyor)."""
    params = urllib.parse.urlencode({"q": query, "license": "by,by-sa,cc0,pdm", "page_size": 20, "mature": "false"})
    names = {"cc0": "CC0", "pdm": "Public domain"}
    found = []
    # Servis yavaş (15 sn) ve ara sıra 504 veriyor: hata find_backgrounds içinde kaynak atlanarak geçilir
    for r in _get_json(f"https://api.openverse.org/v1/images/?{params}", timeout=25).get("results", []):
        if r.get("source") == "wikimedia" or r.get("category") not in (None, "photograph", "digitized_artwork"):
            continue
        tags = " ".join(t.get("name", "") for t in r.get("tags") or [])
        about = f"{r.get('title', '')} | {tags}"[:240]
        if not r.get("url") or not _usable(r.get("width") or 0, r.get("height") or 0, about):
            continue
        license_name = names.get(r["license"]) or f"CC {r['license'].upper()} {r.get('license_version') or ''}".strip()
        # Flickr'ın kendi küçük boyutu (320 px) önizleme için yeter; Openverse'in önizleme servisi sınırı harcamasın
        preview = re.sub(r"_[a-z]\.jpg$", "_n.jpg", r["url"]) if "staticflickr" in r["url"] else r.get("thumbnail")
        found.append({"url": r["url"], "preview": preview, "about": about, "year": 0, "source": "openverse",
                      "credit": f"Görsel: {r.get('creator') or 'Bilinmiyor'}, {license_name}, "
                                f"{(r.get('source') or 'Openverse').capitalize()} ({r.get('foreign_landing_url')})"})
        if len(found) >= limit:
            break
    return found


def _slug(url):
    """Pexels sayfa adresindeki açıklama: .../video/aerial-view-of-a-bridge-123/ -> aerial view of a bridge"""
    tail = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    return re.sub(r"-?\d+$", "", tail).replace("-", " ")


def _best_file(files):
    """Dikey 1080x1920 için en az 720 piksellik en küçük dosya: büyüğü indirmesi uzun, küçüğü bulanık."""
    ok = [f for f in files if min(f.get("width") or 0, f.get("height") or 0) >= 720 and f.get("link", f.get("url"))]
    return min(ok, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0)) if ok else None


def pexels(query, limit=5, video=False):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    path = "videos/search" if video else "v1/search"
    req = urllib.request.Request(f"https://api.pexels.com/{path}?" + urllib.parse.urlencode(
        {"query": query, "per_page": 15}), headers={"Authorization": key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    found = []
    for r in data.get("videos" if video else "photos", []):
        about = (r.get("alt") or _slug(r.get("url", ""))) + " | Pexels"
        name = (r.get("user") or {}).get("name") if video else r.get("photographer")
        if video:
            best = _best_file(r.get("video_files") or [])
            if not best or not r.get("image") or not _usable(0, 0, about):
                continue
            found.append({"url": r["image"], "preview": r["image"], "video": best["link"], "about": about,
                          "year": 0, "source": "pexels",
                          "credit": f"Video: {name or 'Bilinmiyor'}, Pexels lisansı, Pexels ({r['url']})"})
        else:
            if not _usable(r.get("width") or 0, r.get("height") or 0, about):
                continue
            found.append({"url": r["src"]["large2x"], "preview": r["src"]["medium"], "about": about, "year": 0,
                          "source": "pexels",
                          "credit": f"Görsel: {name or 'Bilinmiyor'}, Pexels lisansı, Pexels ({r['url']})"})
        if len(found) >= limit:
            break
    return found


def pixabay(query, limit=5, video=False):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    params = {"key": key, "q": query[:100], "per_page": 20, "safesearch": "true"}
    if not video:
        params["image_type"] = "photo"
    data = _get_json(f"https://pixabay.com/api/{'videos/' if video else ''}?" + urllib.parse.urlencode(params))
    found = []
    for r in data.get("hits", []):
        about = f"{r.get('tags', '')} | Pixabay"
        credit = f"{'Video' if video else 'Görsel'}: {r.get('user') or 'Bilinmiyor'}, Pixabay lisansı, " \
                 f"Pixabay ({r.get('pageURL')})"
        if video:
            files = [{**v, "link": v.get("url")} for v in (r.get("videos") or {}).values()]
            best = _best_file(files)
            poster = ((r.get("videos") or {}).get("medium") or {}).get("thumbnail")
            if not best or not poster or not _usable(0, 0, about):
                continue
            found.append({"url": poster, "preview": poster, "video": best["link"], "about": about, "year": 0,
                          "source": "pixabay", "credit": credit})
        else:
            if not _usable(r.get("imageWidth") or 0, r.get("imageHeight") or 0, about):
                continue
            found.append({"url": r["largeImageURL"], "preview": r["webformatURL"], "about": about, "year": 0,
                          "source": "pixabay", "credit": credit})
        if len(found) >= limit:
            break
    return found


def nasa(query, limit=5):
    """NASA görsel arşivi: uzay ve bilim konuları. Asıl dosya indirilirken seçilir (_resolve)."""
    params = urllib.parse.urlencode({"q": query, "media_type": "image", "page_size": 20})
    found = []
    for item in _get_json(f"https://images-api.nasa.gov/search?{params}")["collection"]["items"]:
        data, links = item["data"][0], item.get("links") or []
        about = f"{data.get('title', '')} | {data.get('description', '')}"[:240]
        if not links or not _usable(0, 0, about):
            continue
        found.append({"url": item["href"], "preview": links[0]["href"], "about": about, "source": "nasa",
                      "year": int(data.get("date_created", "0")[:4] or 0),
                      "credit": f"Görsel: {data.get('secondary_creator') or 'NASA'}, kamu malı, NASA "
                                f"(https://images.nasa.gov/details/{data.get('nasa_id')})"})
        if len(found) >= limit:
            break
    return found


def _resolve(url):
    """NASA'nın dosya listesinden dikey video için yeterli en küçük boyut."""
    if not url.endswith("collection.json"):
        return url
    files = _get_json(url)
    for size in ("~large.jpg", "~medium.jpg", "~orig.jpg"):
        for f in files:
            if f.endswith(size):
                return f.replace("http://", "https://")
    raise ValueError("NASA dosyası yok")


def commons_files(titles):
    """Elle seçilmiş Wikimedia dosyaları ("File:...") wikimedia() ile aynı biçimde, verilen sırayla."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "titles": "|".join(titles),
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400,
    })
    pages = {p.get("title"): p for p in _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
             .get("query", {}).get("pages", {}).values()}
    found = []
    for title in titles:
        info = ((pages.get(title) or {}).get("imageinfo") or [None])[0]
        if not info:
            print(f"Wikimedia dosyası bulunamadı: {title}")
            continue
        meta = info.get("extmetadata", {})
        license_name = _strip(meta.get("LicenseShortName", {}).get("value"))
        artist = _strip(meta.get("Artist", {}).get("value")) or "Bilinmiyor"
        found.append({"url": info["thumburl"], "about": title, "neutral": False, "credit":
                      f"Görsel: {artist}, {license_name}, Wikimedia Commons ({info['descriptionurl']})"})
    return found


def _fold(text):
    import unicodedata
    text = text.lower().translate(str.maketrans("çğıöşüâî", "cgiosuai"))
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _wiki(lang, **params):
    query = urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    return _get_json(f"https://{lang}.wikipedia.org/w/api.php?{query}")


def subject_file(name):
    """Haberde adı geçen kişinin, eserin ya da yerin kendi fotoğrafı: Vikipedi sayfasının ana görseli,
    yalnızca Commons'taysa (serbest lisanslı). Sayfa başlığı ismin bütün kelimelerini içermeli (yanlış kişi olmasın).
    Ajans fotoğrafı, dizi karesi ve afiş (adil kullanım dosyaları) hiçbir zaman alınmaz. Bulunamazsa boş."""
    words = _fold(name).split()
    for lang in ("tr", "en"):
        try:
            hits = _wiki(lang, action="query", list="search", srsearch=name, srlimit=3)["query"]["search"]
            for hit in hits:
                # Sayfa adı ismin kendisi olmalı (parantez içi açıklama hariç): "Yeraltı" dizisi "Yeraltı Camii"
                # sayfasıyla eşleşmesin
                if _fold(re.sub(r"\s*\(.*?\)", "", hit["title"])).split() != words:
                    continue
                page = _wiki(lang, action="query", prop="pageimages", titles=hit["title"], redirects=1,
                             piprop="original")["query"]["pages"][0]
                source = (page.get("original") or {}).get("source", "").split("?", 1)[0]
                if "/wikipedia/commons/" not in source:
                    break  # sayfa doğru ama görseli yok ya da adil kullanım: diğer dile bak
                parts = source.split("/")
                file = urllib.parse.unquote(parts[-2] if "/thumb/" in source else parts[-1]).replace("_", " ")
                if file.lower().endswith((".jpg", ".jpeg")):  # png/svg çoğunlukla logo ve arma
                    print(f"Konu görseli ({name}): {lang}:{hit['title']} -> {file}")
                    return "File:" + file
                break
        except Exception as exc:
            print(f"Konu görseli aranamadı ({name}, {lang}): {exc}")
    print(f"Konu görseli yok: {name}")
    return ""


def subject_photos(name, limit=3):
    """Kişinin, kulübün ya da yapımın Commons'taki başka fotoğrafları: dosya adında ismin bütün kelimeleri geçmeli.
    Genel ortam aramasının (stüdyo, şehir manzarası) yerine destek görseli olarak kullanılır."""
    words = _fold(name).split()
    try:
        found = wikimedia(f'"{name}"', limit * 3)
    except Exception as exc:
        print(f"Konu fotoğrafı aranamadı ({name}): {exc}")
        return []
    # Güncel haber için: imza, belge, arma ve 2010 öncesi fotoğraflar (kulübün 1913 tüzüğü gibi) alınmaz
    own = [c for c in found if all(w in _fold(c["about"].split("|")[0]) for w in words)
           and not re.search(r"signature|imza|logo|emblem|arma|tüzük|charter|document|belge", c["about"], re.I)
           and c.get("year", 0) >= 2010]
    own = list({re.sub(r"\s*\(cropped\)", "", c["about"].split("|")[0]): c for c in own}.values())  # kırpılmış kopyası
    print(f"Konu fotoğrafları ({name}): {len(own)}")
    return [{**c, "neutral": False} for c in own[:limit]]


def _download(url, out_path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())


def gemini_illustration(prompt, out_path):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    body = json.dumps({
        "contents": [{"parts": [{"text": f"Vertical 9:16 editorial illustration, no text, no real people: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(inline["data"]))
            return "Görsel: yapay zekâ ile üretilmiş temsili illüstrasyon"
    return None


SELECT_RULES = """Bir haber videosunun arka planı için fotoğraf seçiyorsun. Aşağıda numaralı adayların dosya adı ve
açıklaması, ardından aynı sırayla fotoğrafların kendisi var. Fotoğrafa bakarak karar ver.

EN ÖNEMLİ KURAL - YER: {place_rule}

Seç: haberin geçtiği yeri, kurumu ya da ortamı açıkça gösteren, net ve iyi çekilmiş fotoğraflar.
[nesne] işaretli adaylar yalnızca içinde insan olmayan, yeri belli etmeyen yakın plan nesne fotoğrafıysa seçilebilir.

Seçme:
- Konuyla ilgisi zayıf olanlar. Emin değilsen seçme; az ama doğru görsel, çok ama alakasız görselden iyidir.
- Başka bir olaya ait olduğu belli olanlar (örnek: başka bir depremin yıkımı).
- Harita, grafik, tablo, logo, belge, ekran görüntüsü ve yazı ağırlıklı görseller.
- Siyah beyaz ya da eski tarihli, bulanık, karanlık ya da özensiz çekilmiş fotoğraflar.
- Bir kişinin yüzünün öne çıktığı fotoğraflar.
- Dikey videoda ortası kırpılınca konusu kadraj dışında kalacak fotoğraflar.

Birbirinden farklı görünenleri tercih et. En fazla 5 aday seç. Kurallara uyan aday yoksa boş liste döndür.
Sadece JSON döndür, en uygun olan başta: {{"pick": [3, 1, 7]}}
"""
HISTORY_RULES = """Tarih belgeseli için arka plan görseli seçiyorsun. Aşağıda numaralı adayların dosya adı ve açıklaması,
ardından aynı sırayla görsellerin kendisi var. Görsele bakarak karar ver.

Konu: {topic}
Dönem: {era}
Yer: {where}

Seç: bu konuyu, dönemi ve yeri gerçekten gösteren görseller: o döneme ait tablolar, gravürler, minyatürler,
haritalar, el yazmaları, müzedeki eserler, arkeolojik alanın ve yapıların fotoğrafları, dönemin fotoğrafları.
Siyah beyaz ve eski görseller uygundur.

Seçme:
- Başka bir olaya, döneme ya da yere ait olanlar (örnek: Osmanlı konusu için Roma mozaiği).
- Film, dizi, oyun görüntüleri; afişler; fantastik ya da yapay zekâ ile üretilmiş canlandırmalar.
- Konuyla ilgisi zayıf modern fotoğraflar; turistlerin, yakın plan kişilerin öne çıktığı fotoğraflar.
- Yazının görseli kapladığı belgeler, grafikler, logolar; bulanık, çok karanlık ya da çok küçük görseller.
- Dikey ya da kare görseller yatay videoda kırpılınca konusu kadraj dışında kalacaksa.

Birbirinden farklı görünenleri tercih et, en uygun olan başta. En fazla 8 aday seç; uygun aday yoksa boş liste dön.
Sadece JSON döndür: {{"pick": [3, 1, 7]}}
"""
FACT_RULES = """Kısa bir "Biliyor muydun?" videosunun dikey arka planı için fotoğraf seçiyorsun. Aşağıda numaralı adayların
dosya adı ve açıklaması, ardından aynı sırayla fotoğrafların kendisi var. Fotoğrafa bakarak karar ver.

Konu: {topic}
Yer: {where}

Seç: konunun kendisini açıkça ve çarpıcı biçimde gösteren, renkli, net, iyi çekilmiş fotoğraflar: hayvanın ya da
bitkinin kendisi, yapının ya da antik kentin kendisi, gök cisminin görüntüsü, müzedeki eser, doğal alanın manzarası.
İlk sıradaki görsel videonun ilk karesi olur: en göz alıcı olanı başa koy.

Seçme:
- Başka bir konuya, türe ya da yere ait olanlar; konuyla ilgisi zayıf olanlar. Emin değilsen seçme.
- Harita, grafik, şema, logo, belge ve yazı ağırlıklı görseller.
- Bulanık, karanlık, çok küçük ya da özensiz çekilmiş fotoğraflar; turistlerin ya da bir kişinin yüzünün öne çıktığı fotoğraflar.
- Film, dizi, oyun görüntüleri; yapay zekâ ile üretilmiş canlandırmalar.
- Dikey videoda ortası kırpılınca konusu kadraj dışında kalacak fotoğraflar.

Birbirinden farklı görünenleri tercih et. En fazla 6 aday seç; uygun aday yoksa boş liste dön.
Sadece JSON döndür, en uygun olan başta: {{"pick": [3, 1, 7]}}
"""
PLACE_RULE = ("Haber {where} ile ilgili. İçinde insan, sokak, bina, okul, taşıt ya da manzara olan her fotoğraf "
              "{where} içinde çekilmiş olmalı. Dosya adından, açıklamasından ya da görüntüsünden (yazılar, tabelalar, "
              "bayraklar, mimari, insanlar) başka bir ülkede ya da şehirde çekildiği anlaşılan fotoğrafı seçme; "
              "nerede çekildiği anlaşılmayan insan fotoğrafını da seçme.")
NO_PLACE_RULE = ("Haber belirli bir ülkeyle ilgili değil. Belirli bir ülkeyi ya da halkı temsil eden insan ve sokak "
                 "fotoğraflarını seçme; konuyu gösteren nesne, cihaz, doğa ve uzay fotoğraflarını tercih et.")
PREVIEW_WIDTH = 330  # Wikimedia'nın hazır küçük boyutlarından biri
# Ücretsiz kota model başına sayılıyor: görsel eleme hafif modele gider, iyi model metin yazımına kalır
SELECT_MODELS = "gemini-flash-lite-latest,gemini-flash-latest"


STOCK_RULE = """
Etiketler:
- [stok] stok fotoğraf ve video sitesinden gelir; etiketleri gevşektir. Yalnızca konunun kendisini (aynı yapı, aynı
  yer, aynı canlı türü, aynı nesne) tanınır biçimde gösteriyorsa seç. Benzeyen ama başka bir yapı ya da yer, ya da
  konuyu "temsil eden" genel bir sahne ise seçme.
- [video] kısa bir video klibin ilk karesidir. Hareketli görüntü videoyu canlandırır: uygunsa fotoğrafa tercih et.
"""
STOCK_SOURCES = {"pexels", "pixabay"}


def _preview(cand):
    small = cand.get("preview") or re.sub(r"/\d+px-", f"/{PREVIEW_WIDTH}px-", cand["url"])
    req = urllib.request.Request(small, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _tags(cand):
    tags = "[nesne] " if cand.get("neutral") else ""
    tags += "[stok] " if cand.get("source") in STOCK_SOURCES else ""
    return tags + ("[video] " if cand.get("video") else "")


def _select(plan, candidates):
    """Adayları dil modeline gösterip eletir; model yoksa ya da yanıt vermezse None döner."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    shown, previews = [], []
    for cand in candidates:
        try:
            previews.append(_preview(cand))
            shown.append(cand)
        except Exception as exc:
            print(f"Önizleme alınamadı: {exc}")
    listing = "\n".join(f"{i}. {_tags(c)}{c['about']}" for i, c in enumerate(shown, 1))
    where = _where(plan)
    if plan.get("kind") == "fact":
        rules = FACT_RULES.format(topic=plan["title"], where=where or "-")
    elif plan.get("kind") == "history":
        rules = HISTORY_RULES.format(topic=plan["title"], era=plan.get("era", ""), where=where or "-")
    else:
        rules = SELECT_RULES.format(place_rule=PLACE_RULE.format(where=where) if where else NO_PLACE_RULE)
    prompt = f"{rules}{STOCK_RULE}\nHaber: {plan['title']}\n{plan['sources'][0]['title']}\n\nAdaylar:\n{listing}"
    try:
        picks = json.loads(script._generate(prompt, os.environ["GEMINI_API_KEY"], previews, SELECT_MODELS))["pick"]
        print(f"Görsel seçimi: {picks} ({len(shown)} aday içinden)")
        return [shown[int(n) - 1] for n in dict.fromkeys(picks) if 1 <= int(n) <= len(shown)]
    except Exception as exc:
        print(f"Görsel seçimi yapılamadı, arama sırası kullanılacak: {exc}")
        return None


def _where(plan):
    place = plan.get("place") or {}
    return ", ".join(x for x in (place.get("city"), place.get("country")) if x)


def _searches(plan):
    """(arama, nesne mi) listesi. Yer biliniyorsa her arama şehir ve ülke adıyla yapılır; yersiz arama yapılmaz."""
    place = plan.get("place") or {}
    city, country = place.get("city", ""), place.get("country", "")
    # Yalnızca şehir adıyla arama yapılmaz: "Istanbul" her seferinde aynı genel manzarayı (Ataşehir) getiriyordu;
    # şehir, aramalara yer bilgisi olarak eklenir. Başka arama yoksa şehrin kendisi aranır.
    searches = [] if plan.get("image_queries") or plan.get("object_query") or not city else [(city, False)]
    for query in plan.get("image_queries") or []:
        located = [f"{query} {loc}" for loc in (city, country) if loc and loc.lower() not in query.lower()]
        searches += [(q, False) for q in (located or [query])]
    if plan.get("object_query"):
        searches.append((plan["object_query"], True))
    return list(dict.fromkeys(searches))


def _save(picked, out_dir, count, exclude_out=None):
    """Adayları sırayla indirir; (dosya, kaynak satırı) listesi döner."""
    results = []
    for cand in picked:
        path = out_dir / f"background{len(results)}.jpg"
        try:
            _download(_resolve(cand["url"]), path)
            if cand.get("video"):  # klip, ilk karesinin yanında aynı adla durur (render.draw_card onu bulur)
                _download(cand["video"], path.with_suffix(".mp4"))
        except Exception as exc:
            print(f"Görsel indirilemedi: {exc}")
            path.with_suffix(".mp4").unlink(missing_ok=True)
            continue
        print(f"Arka plan{' (video)' if cand.get('video') else ''}: {cand['about'][:120]}")
        USED.append(cand["url"])
        results.append((path, cand["credit"]))
        if exclude_out is not None:
            exclude_out.add(cand["url"])
        if len(results) >= count:
            break
    return results


def save_direct(candidates, out_dir, count):
    """Dışarıdan gelen hazır adaylar (resmi afiş ve sahne görselleri): sırayla indirilir, eleme yapılmaz."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return _save(candidates, out_dir, count)


MAX_CANDIDATES = 30  # Gemini'ye gösterilen önizleme sayısı


def _sources(plan):
    """(ad, arama işlevi) listesi. Video klipler yalnızca dikey Short'ta oynatılıyor (render.render_segment)."""
    found = [("Wikimedia", wikimedia), ("Openverse", openverse),
             ("Pexels", pexels), ("Pixabay", pixabay)]
    if not plan.get("wide"):
        found += [("Pexels video", lambda q, n: pexels(q, n, video=True)),
                  ("Pixabay video", lambda q, n: pixabay(q, n, video=True))]
    if plan.get("kind") == "fact":
        found.append(("NASA", nasa))
    return found


def find_backgrounds(plan, out_dir, count, per_query=3, exclude=None):
    """En fazla count görseli out_dir'e yazar; (dosya, kaynak satırı) listesi döner.
    exclude: daha önce kullanılmış adresler; uzun videoda bölümler aynı görseli tekrarlamasın diye."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if plan.get("image_files"):  # görseller elle seçilmiş: arama ve eleme yapılmaz, sıra korunur
        fixed = _save(commons_files(plan["image_files"]), out_dir, count, exclude)
        if len(fixed) >= count or not plan.get("fill_with_search"):
            return fixed
        # Olayın sayfasındaki bir-iki fotoğraf yetmezse geri kalanı aramayla tamamlanır (tarihte bugün)
        rest = find_backgrounds({**plan, "image_files": []}, out_dir / "search", count - len(fixed), per_query, exclude)
        known = {credit for _, credit in fixed}  # aynı dosya aramada da çıkabiliyor; iki kez gösterilmesin
        return fixed + [(path, credit) for path, credit in rest if credit not in known]
    pools = []
    for query, neutral in _searches(plan):
        for name, search in _sources(plan):
            try:
                found = [{**c, "neutral": neutral} for c in search(query, per_query)]
            except Exception as exc:
                print(f"{name} görseli alınamadı ({query}): {exc}")
                continue
            print(f"{name} ({query}): {len(found)} aday")
            if found:
                pools.append(found)

    # Sorgular arasında sırayla dolaşılır ki görseller haberin farklı yönlerini göstersin
    candidates, seen = [], set()
    for rank in range(max(map(len, pools), default=0)):
        for pool in pools:
            if rank >= len(pool):
                continue
            # "Sokak 05.jpg" ile "Sokak 06.jpg" aynı çekimin kareleri; biri yeter
            series = re.sub(r"[\d\s]+", "", pool[rank]["about"].split("|")[0])
            if series not in seen:
                seen.add(series)
                candidates.append(pool[rank])
    fresh = [c for c in candidates if c["url"] not in RECENT]
    if len(fresh) < len(candidates):
        print(f"Son günlerde kullanılmış {len(candidates) - len(fresh)} görsel atlandı")
    candidates = fresh
    if exclude:  # hepsi kullanılmışsa tekrar kabul edilir; görselsiz bölüm olmasın
        candidates = [c for c in candidates if c["url"] not in exclude] or candidates
    candidates = candidates[:MAX_CANDIDATES]

    picked = _select(plan, candidates) if candidates else []
    if picked is None:
        # Eleme yapılamadıysa yalnızca Commons'ta yer adıyla bulunan ilk sonuçlara güvenilir; nesne aramaları ve
        # stok siteleri elenmeden kullanılmaz
        picked = [c for c in candidates if not c["neutral"] and c.get("source", "commons") == "commons"][:2]

    results = _save(picked, out_dir, count, exclude)
    if not results and plan.get("image_prompt"):
        path = out_dir / "background.png"
        try:
            credit = gemini_illustration(plan["image_prompt"], path)
        except Exception as exc:
            print(f"Gemini görseli alınamadı: {exc}")
            credit = None
        if credit:
            results.append((path, credit))
    print(f"Arka plan: {len(results)} görsel")
    return results
