"""Animasyonlu sahneler: bilgi videosunda sayı, karşılaştırma, tarih dizisi ve harita kodla çizilir (14 Kasım 2026).

Kişi ve tarih konularında serbest lisanslı fotoğraf az: Sakıp Sabancı denemesinde aynı müze fotoğrafı dört karenin
üçünde döndü. Kanal sahibi fotoğrafla animasyonun karışık kullanıldığı örneği seçti (14 Kasım): sahnesiz paragrafta
gerçek görüntü tam ekran, sahneli paragrafta bulanık arka plan olarak kalır.

- Sahneyi Gemini önerir (paragraf başına en fazla bir, videoda en fazla MAX_SCENES).
- Sahnedeki her sayı ve yıl o paragrafta yazıldığı gibi geçmelidir. Bunu kod denetler; uydurma sayı çizilmez.
- Haritadaki yerin koordinatı Vikipedi'den alınır, modelin tahmininden değil. Yer adı paragrafta geçmelidir.
- Sayaç ve zaman çizelgesi, sayının seslendirmede söylendiği ana göre ilerler (kelime zamanları).
- Harita verisi: Natural Earth 1:10m ülke sınırları (kamu malı), world-atlas paketinden (assets/map).
"""
import functools
import json
import math
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import render

W, H, FPS = render.W, render.H, 30
MAP = Path(__file__).resolve().parent.parent / "assets" / "map" / "countries-10m.json"
UA = "faceless-shorts/1.0 (https://github.com/Akyaz/faceless-shorts)"
MAX_SCENES = 2
# Yazı katmanının (render._compact_card) boş bıraktığı orta bölge: üstte başlık, altta altyazı var. Alt sınır abone
# düğmesinin (render._subscribe_layer, 980-1150) üstünde: Sakıp Sabancı denemesinde son sayacın birimi düğmenin
# altında kaldı (14 Kasım 2026)
TOP, BOTTOM = 520, 960
MAX_LABEL = 34  # karakter; daha uzunu kutuya sığmıyor

BG1, BG2 = (10, 22, 40), (18, 44, 74)
LAND, LAND_EDGE, WATER = (44, 64, 88), (90, 120, 150), (14, 30, 52)
GOLD, WHITE, MUTED, TRACK, GRID = (255, 196, 0), (255, 255, 255), (175, 190, 205), (30, 50, 76), (24, 46, 72)

NUM = re.compile(r"\d+(?:[.,]\d+)*")


# ---------- sayılar ----------
def parse(text):
    """Türkçe yazılmış sayı: (değer, ondalık hane, binlik ayırıcı var mı). "3,2" -> 3.2; "22.413" -> 22413."""
    text = str(text).strip()
    if not NUM.fullmatch(text):
        return None
    if "," in text:
        whole, _, frac = text.rpartition(",")
        return float(whole.replace(".", "") + "." + frac), len(frac), "." in whole
    parts = text.split(".")
    if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
        return float(text.replace(".", "")), 0, True
    if len(parts) == 2:  # "1.5" gibi yazılmış ondalık
        return float(text), len(parts[1]), False
    return (float(text), 0, False) if len(parts) == 1 else None


def fmt(value, decimals=0, thousands=False):
    """Metindeki yazılışla aynı biçim: ondalık virgülle, binlik ayırıcı yalnızca metinde varsa."""
    if decimals:
        whole, frac = f"{value:.{decimals}f}".split(".")
    else:
        whole, frac = str(int(round(value))), ""
    if thousands:
        whole = f"{int(whole):,}".replace(",", ".")
    return whole + ("," + frac if frac else "")


def _literal(value, text):
    """Sayı paragrafta aynen geçiyorsa metindeki yazılışı; geçmiyorsa None."""
    found = set(NUM.findall(text))
    raw = str(value if value is not None else "").strip()
    for cand in (raw, raw.replace(".", ",")):
        if cand and cand in found:
            return cand
    return None


def _fold(text):
    return text.replace("İ", "i").replace("I", "ı").lower()


# ---------- sahne denetimi ----------
def check(scene, text):
    """Modelin önerdiği sahne: kurallara uyuyorsa temizlenmiş hâli, uymuyorsa None."""
    if not isinstance(scene, dict):
        return None
    clean = lambda v: str(v or "").strip()
    kind = scene.get("type")
    if kind == "sayac":
        value = _literal(scene.get("value"), text)
        if not value or not parse(value):
            return None
        out = {"type": kind, "value": value, "unit": clean(scene.get("unit")), "label": clean(scene.get("label"))}
        labels = [out["unit"], out["label"]]
    elif kind == "karsilastirma":
        items = []
        for item in (scene.get("items") or [])[:3]:
            value = _literal(item.get("value"), text) if isinstance(item, dict) else None
            if not value or not parse(value) or parse(value)[0] <= 0 or not clean(item.get("name")):
                return None
            items.append({"name": clean(item["name"]), "value": value})
        if len(items) < 2:
            return None
        out = {"type": kind, "label": clean(scene.get("label")), "unit": clean(scene.get("unit")), "items": items}
        labels = [out["label"], out["unit"]] + [i["name"] for i in items]
    elif kind == "zaman":
        points = []
        for point in (scene.get("points") or [])[:4]:
            year = _literal(point.get("year"), text) if isinstance(point, dict) else None
            if not year or not re.fullmatch(r"\d{3,4}", year):
                return None
            points.append({"year": year, "label": clean(point.get("label"))})
        if len(points) < 2 or len({p["year"] for p in points}) < len(points):
            return None
        out = {"type": kind, "points": sorted(points, key=lambda p: int(p["year"]))}
        labels = [p["label"] for p in points]
    elif kind == "harita":
        place = clean(scene.get("place"))
        # Yer paragrafta geçmeli: başka bir yerin haritası gösterilmesin
        if not place or _fold(place.split()[0])[:4] not in _fold(text):
            return None
        out = {"type": kind, "place": place, "label": clean(scene.get("label")) or place}
        labels = [out["label"]]
    else:
        return None
    if any(len(s) > MAX_LABEL for s in labels):
        return None
    # Etiketteki sayılar da metinden: "10 yılda" yazıyorsa metinde 10 geçmeli
    if any(_literal(tok, text) is None for s in labels for tok in NUM.findall(s)):
        return None
    return out


def coords(place):
    """Yerin Vikipedi'deki koordinatı (enlem, boylam); önce Türkçe, sonra İngilizce Vikipedi."""
    for lang in ("tr", "en"):
        for params in ({"titles": place, "redirects": 1},
                       {"generator": "search", "gsrsearch": place, "gsrlimit": 1}):
            query = urllib.parse.urlencode({"action": "query", "prop": "coordinates", "format": "json",
                                            "formatversion": 2, **params})
            req = urllib.request.Request(f"https://{lang}.wikipedia.org/w/api.php?{query}",
                                         headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    pages = json.load(resp).get("query", {}).get("pages", [])
            except Exception as exc:
                print(f"Koordinat alınamadı ({place}, {lang}): {exc}")
                continue
            for page in pages:
                for c in page.get("coordinates") or []:
                    return c["lat"], c["lon"]
    return None


def prepare(paragraphs, raw, limit=MAX_SCENES):
    """{paragraf sırası: sahne}. Kurala uymayan ya da haritada yeri bulunamayan sahne atlanır."""
    chosen = {}
    for scene in raw if isinstance(raw, list) else []:
        if len(chosen) >= limit:
            break
        try:
            i = int(scene.get("paragraph")) - 1
        except (AttributeError, TypeError, ValueError):
            continue
        if not 0 <= i < len(paragraphs) or i in chosen:
            continue
        out = check(scene, paragraphs[i])
        if out and out["type"] == "harita":
            spot = coords(out["place"])
            out = {**out, "lat": spot[0], "lon": spot[1]} if spot else None
        if not out:
            print(f"Sahne atlandı (paragraf {i + 1}): {json.dumps(scene, ensure_ascii=False)[:160]}")
            continue
        print(f"Sahne: paragraf {i + 1}, {out['type']}: {json.dumps(out, ensure_ascii=False)[:160]}")
        chosen[i] = out
    return chosen


def spread(backgrounds, segments):
    """Fotoğraflar önce sahnesiz paragraflara sırayla dağılır (aynı fotoğraf daha az tekrar eder). Sahneli paragrafa
    arka plan olarak henüz gösterilmemiş bir fotoğraf, yoksa komşu paragrafınki düşer."""
    photos = list(dict.fromkeys(b for b in backgrounds if b))
    if not photos or not any(s.get("scene") for s in segments):
        return backgrounds
    out, k = [], 0
    for seg in segments:
        out.append(None if seg.get("scene") else photos[k % len(photos)])
        k += 0 if seg.get("scene") else 1
    unused = [p for p in photos if p not in out]
    for i, seg in enumerate(segments):
        if seg.get("scene"):
            near = [p for p in out[i - 1:i] + out[i + 1:i + 2] if p]
            out[i] = unused.pop(0) if unused else (near or photos)[0]
    return out


# ---------- çizim yardımcıları ----------
def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = max(0.0, min(1.0, x))
    return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def pop(x):  # hafif taşan büyüme (easeOutBack)
    x = max(0.0, min(1.0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


@functools.lru_cache(maxsize=None)
def _font(size, bold=True):
    return ImageFont.truetype(render._font_path(bold), size)


def _fit(d, text, size, width, bold=True, smallest=28):
    while size > smallest and d.textlength(text, font=_font(size, bold)) > width:
        size -= 4
    return _font(size, bold)


def _centered(d, text, y, font, fill=WHITE, stroke=0):
    d.text((W / 2, y), text, font=font, fill=fill, anchor="mt", stroke_width=stroke, stroke_fill=(0, 0, 0))


def _pill(d, text, cx, cy, font, bg, fg=WHITE, scale=1.0):
    if scale <= 0.02:
        return
    w, h = d.textlength(text, font=font) + 64, font.size * 1.5
    d.rounded_rectangle([cx - w * scale / 2, cy - h * scale / 2, cx + w * scale / 2, cy + h * scale / 2],
                        radius=h * scale / 2, fill=bg)
    if scale > 0.7:
        d.text((cx, cy), text, font=font, fill=fg, anchor="mm")


def _said(words, token):
    """Seslendirmede token'ın söylendiği an (saniye); bulunamazsa None."""
    digits = re.sub(r"\D", "", token)
    for w in words or []:
        text = w.get("text", "")
        if digits:
            if re.sub(r"\D", "", text).startswith(digits):
                return w["start"]
        elif _fold(text).startswith(_fold(token)[:4]):
            return w["start"]
    return None


def _backdrop(photo):
    """Sahnenin zemini: fotoğraf varsa bulanık ve koyu hâli, yoksa koyu lacivert degrade."""
    if photo:
        try:
            img = render._photo(photo, dim=0)
            img = img.resize((W // 6, H // 6)).filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BILINEAR)
            return Image.blend(img, Image.new("RGB", (W, H), BG1), 0.6), False
        except Exception as exc:  # bozuk dosya: degradeyle devam
            print(f"Sahne zemini için fotoğraf açılamadı: {exc}")
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(0, H, 8):
        d.rectangle([0, y, W, y + 8], fill=tuple(int(BG1[i] + (BG2[i] - BG1[i]) * y / H) for i in range(3)))
    return img, True


def _grid(img, t):
    d = ImageDraw.Draw(img)
    off = (t * 20) % 90
    for x in range(-90, W + 90, 90):
        d.line([(x + off, 0), (x + off, H)], fill=GRID, width=2)
    for y in range(-90, H + 90, 90):
        d.line([(0, y + off), (W, y + off)], fill=GRID, width=2)


# ---------- sahneler ----------
def _counter(img, t, dur, sc, ctx):
    """Büyük sayı sıfırdan sayar, söylendiği anda tamamlanır; altında birimi."""
    d = ImageDraw.Draw(img)
    value, decimals, thousands = parse(sc["value"])
    said = _said(ctx["words"], sc["value"])
    end = min(max(said + 0.3, 1.0) if said is not None else 1.8, max(1.0, dur - 0.4))
    p = ease((t - 0.2) / max(0.6, end - 0.2))
    unit = sc["unit"]
    glued = unit[:1] in (".", "%", "'", "’")  # "147." sıra, "%40"
    final = fmt(value, decimals, thousands) + (unit if glued else "")
    font = _fit(d, final, 190, W - 140)
    y = TOP + 20
    if sc["label"]:
        _centered(d, sc["label"], y, _fit(d, sc["label"], 52, W - 140, bold=False), MUTED)
        y += 80
    _centered(d, fmt(value * p, decimals, thousands) + (unit if glued else ""), y, font, WHITE, stroke=4)
    y += font.size + 20
    if unit and not glued:
        q = ease((t - end + 0.1) / 0.4)
        if q > 0.05:
            unit_font = _fit(d, unit, 64, W - 160)
            d.text((W / 2, y + 30 * (1 - q)), unit, font=unit_font, fill=GOLD, anchor="mt", stroke_width=3,
                   stroke_fill=(0, 0, 0))
        y += 90
    half = 220 * ease((t - 0.2) / 1.0)
    if half > 4:
        d.rounded_rectangle([W / 2 - half, y, W / 2 + half, y + 14], radius=7, fill=ctx["accent"])


def _compare(img, t, dur, sc, ctx):
    """İki-üç çubuk sırayla dolar; en büyük değer vurgu renginde."""
    d = ImageDraw.Draw(img)
    items = [(i["name"], parse(i["value"])) for i in sc["items"]]
    top = max(v[0] for _, v in items)
    y0 = TOP + 20
    if sc["label"]:
        _centered(d, sc["label"], y0, _fit(d, sc["label"], 56, W - 140), WHITE, stroke=3)
        y0 += 110
    row = min(200, (BOTTOM - y0) // len(items))
    bar = max(36, min(80, row - 64))
    full, left = W - 200, 100
    unit = f" {sc['unit']}" if sc["unit"] else ""
    for k, (name, (value, decimals, thousands)) in enumerate(items):
        y = y0 + k * row
        p = ease((t - 0.25 - 0.45 * k) / 1.3)
        d.text((left, y), name, font=_fit(d, name, 44, full, bold=False), fill=WHITE, stroke_width=2,
               stroke_fill=(0, 0, 0))
        d.rounded_rectangle([left, y + 56, left + full, y + 56 + bar], radius=bar // 4, fill=TRACK)
        if p > 0.01:
            d.rounded_rectangle([left, y + 56, left + max(40, full * value / top * p), y + 56 + bar], radius=bar // 4,
                                fill=ctx["accent"] if value == top else MUTED)
        d.text((left + 26, y + 56 + bar / 2), fmt(value * p, decimals, thousands) + unit, font=_font(min(48, bar)),
               fill=WHITE,
               anchor="lm", stroke_width=3, stroke_fill=(0, 0, 0))


def _timeline(img, t, dur, sc, ctx):
    """Yıllar yukarıdan aşağı, her biri söylendiği anda belirir; aralarındaki çizgi uzar."""
    d = ImageDraw.Draw(img)
    points = sc["points"]
    n = len(points)
    step = min(220, (BOTTOM - TOP - 100) / (n - 1))
    ys = [(TOP + BOTTOM) / 2 - step * (n - 1) / 2 + i * step for i in range(n)]
    times = []
    for i, p in enumerate(points):
        said = _said(ctx["words"], p["year"])
        at = said if said is not None else 0.3 + i * min(1.4, max(0.5, (dur - 1.0) / n))
        if i == 0:  # ekran ilk saniyede boş kalmasın
            at = min(at, 0.4)
        at = min(at, dur - 0.8 - 0.35 * (n - 1 - i))  # son yıl da parça bitmeden görünsün
        times.append(max(at, times[-1] + 0.35) if times else max(0.2, at))
    x = 150
    for i in range(1, n):
        g = ease((t - times[i] + 0.45) / 0.45)
        if g > 0 and t >= times[i - 1]:
            d.line([(x, ys[i - 1]), (x, ys[i - 1] + (ys[i] - ys[i - 1]) * g)], fill=MUTED, width=8)
    for i, p in enumerate(points):
        q = pop((t - times[i]) / 0.45)
        if q <= 0.02:
            continue
        current = i == max(k for k in range(n) if t >= times[k] - 0.01) if t >= times[0] else False
        r = 26 * q
        d.ellipse([x - r, ys[i] - r, x + r, ys[i] + r], fill=ctx["accent"] if current else GOLD, outline=WHITE,
                  width=5)
        shift = (1 - ease((t - times[i]) / 0.4)) * 60
        year_font = _font(min(88, int(step * 0.7)))
        d.text((x + 60 + shift, ys[i]), p["year"], font=year_font, fill=GOLD, anchor="lm", stroke_width=3,
               stroke_fill=(0, 0, 0))
        if p["label"]:
            lx = x + 60 + shift + d.textlength(p["year"], font=year_font) + 30
            d.text((lx, ys[i]), p["label"], font=_fit(d, p["label"], 50, W - 70 - lx, bold=False, smallest=28),
                   fill=WHITE, anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))


@functools.lru_cache(maxsize=1)
def _rings():
    """Ülke sınırlarının dış halkaları: [(min_lon, min_lat, max_lon, max_lat, noktalar)]."""
    topo = json.loads(MAP.read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    out = []
    for g in topo["objects"]["countries"]["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]] if g["type"] == "Polygon" else []
        for poly in polys:
            pts = []
            for i in poly[0]:
                a = arcs[i] if i >= 0 else arcs[~i][::-1]
                pts.extend(a if not pts else a[1:])
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            out.append((min(xs), min(ys), max(xs), max(ys), pts))
    return out


def _map(img, t, dur, sc, ctx):
    """Bölgeden yere yakınlaşan harita; yer işareti ve adı."""
    d = ImageDraw.Draw(img)
    lat, lon = sc["lat"], sc["lon"]
    zoom_end = max(1.5, min(3.2, dur * 0.6))
    z = ease_io(t / zoom_end)
    ppd = math.exp(math.log(28) + (math.log(380) - math.log(28)) * z)  # derece başına piksel
    k = math.cos(math.radians(lat))
    cy = (TOP + BOTTOM) / 2 - 40
    half_lon, up, down = W / 2 / (ppd * k) + 0.5, cy / ppd + 0.5, (H - cy) / ppd + 0.5
    d.rectangle([0, 0, W, H], fill=WATER)
    step = max(1, int(240 / ppd))
    for x0, y0, x1, y1, pts in _rings():
        if x1 < lon - half_lon or x0 > lon + half_lon or y1 < lat - down or y0 > lat + up:
            continue
        poly = [(W / 2 + (x - lon) * ppd * k, cy - (y - lat) * ppd) for x, y in pts[::step]]
        if len(poly) > 2:
            d.polygon(poly, fill=LAND, outline=LAND_EDGE)
    said = _said(ctx["words"], sc["place"])
    pin = max(0.6, min(zoom_end * 0.7, said if said is not None else zoom_end * 0.7))
    q = pop((t - pin) / 0.45)
    if q > 0.02:
        ring = ((t - pin) % 1.4) / 1.4
        r = 24 + 70 * ring
        d.ellipse([W / 2 - r, cy - r, W / 2 + r, cy + r], outline=GOLD, width=max(1, int(6 * (1 - ring))))
        r = 18 * q
        d.ellipse([W / 2 - r, cy - r, W / 2 + r, cy + r], fill=GOLD, outline=WHITE, width=5)
        _pill(d, sc["label"], W / 2, cy + 110, _fit(d, sc["label"], 56, W - 220), ctx["accent"], scale=q)


DRAW = {"sayac": _counter, "karsilastirma": _compare, "zaman": _timeline, "harita": _map}


def frame(scene, t, dur, base, ctx):
    img = base.copy() if base else Image.new("RGB", (W, H), WATER)
    if ctx.get("grid") and scene["type"] != "harita":
        _grid(img, t)
    DRAW[scene["type"]](img, t, dur, scene, ctx)
    return img


def render_scene(scene, words, out_path, dur, photo=None, accent=(229, 57, 53)):
    """Sahneyi dur saniyelik sessiz videoya (out_path, .mp4) çizer. Yazı katmanı ve altyazı render_segment'te eklenir."""
    base, grid = (None, False) if scene["type"] == "harita" else _backdrop(photo)
    ctx = {"accent": tuple(accent), "words": words, "grid": grid}
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                             "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)], stdin=subprocess.PIPE)
    try:
        for n in range(int(math.ceil(dur * FPS))):
            proc.stdin.write(frame(scene, n / FPS, dur, base, ctx).tobytes())
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code:
        raise RuntimeError(f"Sahne videosu yazılamadı (ffmpeg {code})")
