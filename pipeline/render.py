"""Kartları çizer, altyazıları yakar ve videoyu birleştirir: dikey Short ya da yatay haftalık derleme."""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
WIDE = (1920, 1080)  # haftalık derleme
LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
ACCENTS = [(229, 57, 53), (30, 136, 229), (67, 160, 71), (251, 140, 0), (142, 36, 170)]


def _font_path(bold=True):
    pattern = "DejaVu Sans:bold" if bold else "DejaVu Sans"
    return subprocess.run(["fc-match", "-f", "%{file}", pattern],
                          capture_output=True, text=True, check=True).stdout


def _gradient(accent, size=(W, H)):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):  # koyu dikey degrade, üstte vurgu renginin izi
        t = y / h
        r, g, b = (int(c * 0.35 * (1 - t) + 12 * t) for c in accent)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _photo(path, size=(W, H)):
    """Görseli kadraja kırpar ve altyazı okunsun diye karartır."""
    w, h = size
    src = Image.open(path).convert("RGB")
    scale = max(w / src.width, h / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
    left, top = (src.width - w) // 2, (src.height - h) // 2
    img = src.crop((left, top, left + w, top + h))
    return Image.blend(img, Image.new("RGB", size), 0.5)


def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


BRAND_TAG = "#quickrecapchannel"


def _brand(img):
    """Sol üst köşede küçük kanal logosu, altında okunabilecek kadar küçük kanal etiketi.
    Etiketin sağ kenarını döner: ortadaki etiket kutusu bununla çakışmasın."""
    size = 128
    logo = Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)
    # Kenardan pay: video boyunca %6 yakınlaşınca logo kadrajın dışına taşmasın
    img.paste(logo, (60, 76), logo)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(_font_path(False), 22)
    d.text((60, 76 + size + 10), BRAND_TAG, font=font, fill=(235, 235, 235), stroke_width=2, stroke_fill="black")
    return 60 + d.textlength(BRAND_TAG, font=font)


def _fit_label(d, text, size, left_limit, pad):
    """Ortadaki etiket kutusu kanal etiketine değmeyecek kadar küçülür."""
    while True:
        font = ImageFont.truetype(_font_path(True), size)
        if (W - d.textlength(text, font=font)) / 2 - pad >= left_limit or size <= 30:
            return font
        size -= 2


SUBSCRIBE_RED = (229, 57, 53)
TEXTS = {
    "tr": {"source": "Kaynak", "promise": "Günün haberleri her gün bu kanalda", "subscribe": "ABONE OL"},
    "en": {"source": "Source", "promise": "World news in under a minute, every day", "subscribe": "SUBSCRIBE"},
}


def _subscribe(d, bold, regular, texts):
    """Son kartta altyazının altında abone çağrısı."""
    d.text((W / 2, 1270), texts["promise"], font=regular, fill="white", anchor="mm",
           stroke_width=3, stroke_fill="black")
    text = texts["subscribe"]
    tw = d.textlength(text, font=bold)
    d.rounded_rectangle([(W - tw) / 2 - 48, 1330, (W + tw) / 2 + 48, 1440], radius=55, fill=SUBSCRIBE_RED)
    d.text((W / 2, 1385), text, font=bold, fill="white", anchor="mm")


def _subscribe_layer(path, lang, wide, promise):
    """Şeffaf katman: kırmızı abone düğmesi (dikeyde altyazının altında, yatayda sağ üst köşede)."""
    w, h = WIDE if wide else (W, H)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bold = ImageFont.truetype(_font_path(True), 46 if wide else 58)
    text = TEXTS[lang]["subscribe"]
    tw, ph = d.textlength(text, font=bold), (88 if wide else 112)
    icon = ph * 0.42  # metnin solunda beyaz "oynat" üçgeni
    pw = tw + icon + (110 if wide else 130)
    x0 = w - 70 - pw if wide else (w - pw) / 2
    y0 = 76 if wide else 1330
    d.rounded_rectangle([x0 + 6, y0 + 8, x0 + pw + 6, y0 + ph + 8], radius=ph / 2, fill=(0, 0, 0, 110))  # gölge
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph / 2, fill=SUBSCRIBE_RED + (255,),
                        outline=(255, 255, 255, 255), width=4)
    ix, cy = x0 + (44 if wide else 52), y0 + ph / 2
    d.polygon([(ix, cy - icon / 2), (ix, cy + icon / 2), (ix + icon * 0.9, cy)], fill="white")
    d.text((ix + icon + (18 if wide else 22), cy), text, font=bold, fill="white", anchor="lm")
    if promise and not wide:
        regular = ImageFont.truetype(_font_path(False), 44)
        d.text((w / 2, 1270), TEXTS[lang]["promise"], font=regular, fill="white", anchor="mm",
               stroke_width=3, stroke_fill="black")
    img.save(path)


def add_subscribe(video, out_path, lang="tr", wide=False, start=(0.5, 3.5), end_seconds=4.5):
    """Abone düğmesi videonun ilk ve son saniyelerinde yumuşakça belirip kaybolur. Ses aynen kopyalanır."""
    dur = audio_duration(video)
    first, last = Path(out_path).with_suffix(".sub1.png"), Path(out_path).with_suffix(".sub2.png")
    _subscribe_layer(first, lang, wide, promise=False)
    _subscribe_layer(last, lang, wide, promise=True)
    a, b = start
    e = max(b + 1, dur - end_seconds)  # kısa videoda iki görünüm üst üste binmesin
    fade = 0.3
    graph = (f"[1:v]format=rgba,fade=in:st={a}:d={fade}:alpha=1,fade=out:st={b - fade}:d={fade}:alpha=1[s1];"
             f"[2:v]format=rgba,fade=in:st={e:.2f}:d={fade}:alpha=1[s2];"
             f"[0:v][s1]overlay=enable='between(t,{a},{b})'[v1];"
             f"[v1][s2]overlay=enable='gte(t,{e:.2f})'[v]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", str(first),
        "-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", str(last),
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "copy",
        str(out_path),
    ], check=True)
    first.unlink()
    last.unlink()


CHANNEL_URL = "youtube.com/@QuickRecapChannel"


def _link_layer(path, text=CHANNEL_URL):
    """Instagram kopyası için şeffaf katman: altta kırmızı oynat işaretli kanal adresi."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(_font_path(True), 40)
    tw, ph, icon = d.textlength(text, font=font), 76, 30
    pw = tw + icon + 90
    x0, y0 = (W - pw) / 2, 1450  # Instagram'ın alttaki açıklama bölgesinin üstünde, kaynak satırının üstünde
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph / 2, fill=(0, 0, 0, 170))
    ix, cy = x0 + 34, y0 + ph / 2
    d.rounded_rectangle([ix - 8, cy - 20, ix + icon + 4, cy + 20], radius=10, fill=SUBSCRIBE_RED + (255,))
    d.polygon([(ix + 6, cy - 10), (ix + 6, cy + 10), (ix + icon - 6, cy)], fill="white")
    d.text((ix + icon + 22, cy), text, font=font, fill="white", anchor="lm")
    img.save(path)


def add_link(video, out_path, text=CHANNEL_URL):
    """Kanal adresi videonun tamamında altta görünür; ses aynen kopyalanır."""
    layer = Path(out_path).with_suffix(".link.png")
    _link_layer(layer, text)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-loop", "1", "-framerate", "30",
        "-t", f"{audio_duration(video):.2f}", "-i", str(layer),
        "-filter_complex", "[0:v][1:v]overlay=shortest=1[v]", "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "copy",
        "-movflags", "+faststart", str(out_path),
    ], check=True)
    layer.unlink()


def draw_card(segment, idx, out_path, background=None, hook_title="", label="GÜNDEM", subscribe=False, lang="tr"):
    """segment'teki label ve heading, videonun genel etiketinin ve başlığının yerine geçer."""
    accent = ACCENTS[idx % len(ACCENTS)]
    img = _photo(background) if background else _gradient(accent)

    d = ImageDraw.Draw(img)
    bold = ImageFont.truetype(_font_path(True), 56)
    regular = ImageFont.truetype(_font_path(False), 44)

    edge = _brand(img)
    label = segment.get("label") or label
    hook_title = segment.get("heading") or hook_title
    label_font = _fit_label(d, label, 56, edge + 20, 36)
    lw = d.textlength(label, font=label_font)
    d.rounded_rectangle([(W - lw) / 2 - 36, 180, (W + lw) / 2 + 36, 280], radius=50, fill=accent)
    d.text((W / 2, 230), label, font=label_font, fill="white", anchor="mm")

    if hook_title:  # merak başlığı her kartta üstte sabit durur
        hook_font = ImageFont.truetype(_font_path(True), 78)
        lines = _wrap(d, hook_title, hook_font, W - 140)
        y = 400
        for line in lines:
            d.text((W / 2, y), line, font=hook_font, fill=(255, 214, 0), anchor="mm",
                   stroke_width=5, stroke_fill="black")
            y += 96
    if subscribe:
        _subscribe(d, bold, regular, TEXTS[lang])
    if segment.get("source"):
        d.text((W / 2, 1560), f"{TEXTS[lang]['source']}: {segment['source']}", font=regular, fill=(230, 230, 230),
               anchor="mm", stroke_width=3, stroke_fill="black")
    img.save(out_path)


# Maç kartları: o maçın bilgileriyle çizilir (ajans fotoğrafı ve yayın görüntüsü telifli; başka tarihlerin
# fotoğrafı da o günü anlatmaz). Kulüp armaları tescilli olduğu için yalnızca takım adı ve renkleri kullanılır.
# Altyazı ekranın ortasında çıktığı için 880-1100 arası boş bırakılır.
def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _ink(color):
    """Takım renginin üstünde okunacak yazı rengi."""
    r, g, b = color
    return (20, 20, 20) if r * 0.299 + g * 0.587 + b * 0.114 > 160 else (255, 255, 255)


def _pitch():
    """Koyu çim zemin: dikey şeritler ve silik saha çizgileri."""
    img = Image.new("RGB", (W, H), (14, 48, 30))
    d = ImageDraw.Draw(img)
    for i in range(0, H, 160):
        d.rectangle([0, i, W, i + 80], fill=(17, 56, 35))
    line = (40, 84, 60)
    d.rectangle([60, 120, W - 60, H - 120], outline=line, width=4)
    d.line([60, H / 2, W - 60, H / 2], fill=line, width=4)
    d.ellipse([W / 2 - 170, H / 2 - 170, W / 2 + 170, H / 2 + 170], outline=line, width=4)
    return Image.blend(img, Image.new("RGB", (W, H)), 0.35)


def _centered(d, text, y, font, fill="white", stroke=0):
    d.text((W / 2, y), text, font=font, fill=fill, anchor="mm", stroke_width=stroke, stroke_fill="black")


def _pill(d, text, y, font, color, pad=40, height=96):
    tw = d.textlength(text, font=font)
    d.rounded_rectangle([(W - tw) / 2 - pad, y - height / 2, (W + tw) / 2 + pad, y + height / 2],
                        radius=height / 2, fill=color)
    d.text((W / 2, y), text, font=font, fill=_ink(color), anchor="mm")


def _scoreline(d, match, score, y, font):
    """Alt bölümde küçük skor tabelası: ev sahibi rengi | skor | konuk rengi."""
    home, away = _hex(match["home_color"]), _hex(match["away_color"])
    d.rounded_rectangle([90, y - 60, W - 90, y + 60], radius=30, fill=(10, 10, 10))
    d.rounded_rectangle([90, y - 60, 130, y + 60], radius=12, fill=home)
    d.rounded_rectangle([W - 130, y - 60, W - 90, y + 60], radius=12, fill=away)
    d.text((160, y), match["home"], font=font, fill="white", anchor="lm")
    d.text((W - 160, y), match["away"], font=font, fill="white", anchor="rm")
    d.text((W / 2, y), score, font=font, fill=(255, 214, 0), anchor="mm")


def draw_match_card(card, match, out_path, label="SPOR", source=""):
    """card: {"type": score|goal|event|quote|table, ...}; match: {home, away, home_color, away_color, ...}."""
    img = _pitch()
    d = ImageDraw.Draw(img)
    font = lambda size, bold=True: ImageFont.truetype(_font_path(bold), size)  # noqa: E731
    edge = _brand(img)
    _pill(d, label, 230, _fit_label(d, label, 56, edge + 20, 36), ACCENTS[0], pad=36, height=100)
    kind = card["type"]
    team = _hex(match["home_color"] if card.get("team", "home") == "home" else match["away_color"])

    if kind == "score":
        for x0, name, color in ((70, match["home"], _hex(match["home_color"])),
                                (W / 2 + 20, match["away"], _hex(match["away_color"]))):
            d.rounded_rectangle([x0, 360, x0 + W / 2 - 90, 470], radius=24, fill=color)
            size = 56 if len(name) <= 11 else 46
            d.text((x0 + (W / 2 - 90) / 2, 415), name, font=font(size), fill=_ink(color), anchor="mm")
        _centered(d, card["score"], 640, font(230), fill=(255, 214, 0), stroke=6)
        if card.get("note"):
            _centered(d, card["note"], 810, font(42, False), fill=(230, 230, 230))
    elif kind in ("goal", "event"):
        _pill(d, card.get("title", "GOL"), 360, font(60), team if kind == "goal" else (60, 60, 60), height=104)
        _centered(d, card["minute"], 540, font(200), fill=(255, 214, 0), stroke=6)
        if card.get("player"):
            _centered(d, card["player"], 720, font(80), stroke=4)
        if card.get("detail"):
            y = 800 if card.get("player") else 730
            for line in _wrap(d, card["detail"], font(42, False), W - 200)[:2]:
                _centered(d, line, y, font(42, False), fill=(230, 230, 230), stroke=2)
                y += 52
    elif kind == "quote":
        _centered(d, "“", 420, font(220), fill=(255, 214, 0))
        quote_font = font(60)
        lines = _wrap(d, card["text"], quote_font, W - 180)[:4]
        y = 560 if len(lines) > 2 else 620
        for line in lines:
            _centered(d, line, y, quote_font, stroke=3)
            y += 76
        _centered(d, card["who"], 1200, font(46, False), fill=(230, 230, 230), stroke=2)
    elif kind == "table":
        y = 380
        for row in card["rows"][:4]:
            color = _hex(row.get("color", "#FFD600"))
            d.rounded_rectangle([90, y - 52, W - 90, y + 52], radius=20, fill=(10, 10, 10))
            d.rounded_rectangle([90, y - 52, 120, y + 52], radius=8, fill=color)
            d.text((150, y), row["name"], font=font(52), fill="white", anchor="lm")
            d.text((W - 130, y), row["value"], font=font(52), fill=(255, 214, 0), anchor="rm")
            y += 128
        if card.get("next"):
            _pill(d, card["next"], 1200, font(46), (255, 255, 255), height=90)

    if card.get("score_after"):
        _scoreline(d, match, card["score_after"], 1200, font(50))
    if source:
        d.text((W / 2, 1560), f"{TEXTS['tr']['source']}: {source}", font=font(44, False), fill=(230, 230, 230),
               anchor="mm", stroke_width=3, stroke_fill="black")
    img.save(out_path)


SPEAKER_COLORS = [(30, 136, 229), (229, 57, 53)]


def draw_wide_card(segment, idx, out_path, background=None, subscribe=False, lang="tr"):
    """Yatay kart (haftalık derleme, uzun özel metin): üstte etiket ve başlık, altyazı altta kalır."""
    w, h = WIDE
    accent = ACCENTS[idx % len(ACCENTS)]
    img = _photo(background, WIDE) if background else _gradient(accent, WIDE)
    d = ImageDraw.Draw(img)
    bold = ImageFont.truetype(_font_path(True), 48)
    regular = ImageFont.truetype(_font_path(False), 36)

    logo = Image.open(LOGO).convert("RGBA").resize((120, 120), Image.LANCZOS)
    img.paste(logo, (70, 60), logo)
    d.text((70, 60 + 120 + 8), BRAND_TAG, font=ImageFont.truetype(_font_path(False), 22), fill=(235, 235, 235),
           stroke_width=2, stroke_fill="black")
    label = segment.get("label") or "HAFTANIN ÖZETİ"
    lw = d.textlength(label, font=bold)
    d.rounded_rectangle([(w - lw) / 2 - 32, 76, (w + lw) / 2 + 32, 164], radius=44, fill=accent)
    d.text((w / 2, 120), label, font=bold, fill="white", anchor="mm")

    if segment.get("chapter_card"):  # bölüm açılışı: başlık ortada ve büyük
        font = ImageFont.truetype(_font_path(True), 104)
        lines = _wrap(d, segment["heading"], font, w - 300)
        y = h / 2 - (len(lines) - 1) * 62
        for line in lines:
            d.text((w / 2, y), line, font=font, fill=(255, 214, 0), anchor="mm", stroke_width=6, stroke_fill="black")
            y += 124
    elif segment.get("heading"):
        size = 76 if not segment.get("small_heading") else 50
        font = ImageFont.truetype(_font_path(True), size)
        y = 270 if size == 76 else 235
        for line in _wrap(d, segment["heading"], font, w - 300):
            d.text((w / 2, y), line, font=font, fill=(255, 214, 0), anchor="mm", stroke_width=5, stroke_fill="black")
            y += size + 18
    if segment.get("speaker"):  # diyalogda konuşanın adı, altyazının hemen üstünde
        name, color = segment["speaker"], SPEAKER_COLORS[segment.get("speaker_index", 0) % len(SPEAKER_COLORS)]
        nw = d.textlength(name, font=bold)
        d.rounded_rectangle([w / 2 - nw / 2 - 30, h - 330, w / 2 + nw / 2 + 30, h - 250], radius=40, fill=color)
        d.text((w / 2, h - 290), name, font=bold, fill="white", anchor="mm")
    if subscribe:
        text = TEXTS[lang]["subscribe"]
        tw = d.textlength(text, font=bold)
        d.rounded_rectangle([(w - tw) / 2 - 44, 500, (w + tw) / 2 + 44, 600], radius=50, fill=SUBSCRIBE_RED)
        d.text((w / 2, 550), text, font=bold, fill="white", anchor="mm")
    if segment.get("source"):
        # Kenardan pay: yakınlaşınca yazı kadrajın dışına taşmasın
        d.text((w - 110, h - 90), f"{TEXTS[lang]['source']}: {segment['source']}", font=regular, fill=(230, 230, 230),
               anchor="rm", stroke_width=3, stroke_fill="black")
    img.save(out_path)


PITCH = (9, 24, 58)  # maç programı kartının koyu lacivert zemini


def draw_fixture_card(title, date_label, groups, out_path, label, highlight=(), note="", emphasize=(), visible=None):
    """Maç tablosu. groups: [(saat ya da None, [(ev sahibi, deplasman[, skor])])].
    highlight'taki takımların maçı sarı yazılır, emphasize'dakilerin maçı kırmızı çerçeveye alınır.
    visible verilirse yalnızca ilk o kadar maç çizilir (skorların tek tek gelmesi için); yerleşim değişmez."""
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):  # üstten alta koyulaşan lacivert
        t = y / H
        row = tuple(int(c * (1.25 - 0.9 * t)) for c in PITCH)
        for x in range(W):
            px[x, y] = row
    d = ImageDraw.Draw(img)
    line = (34, 58, 104)  # zeminde silik saha çizgileri
    d.rectangle([70, 330, W - 70, H - 250], outline=line, width=5)
    d.line([70, H / 2 + 40, W - 70, H / 2 + 40], fill=line, width=5)
    d.ellipse([W / 2 - 210, H / 2 - 170, W / 2 + 210, H / 2 + 250], outline=line, width=5)

    edge = _brand(img)
    bold = ImageFont.truetype(_font_path(True), 50)
    regular = ImageFont.truetype(_font_path(False), 40)
    label_font = _fit_label(d, label, 50, edge + 20, 36)
    lw = d.textlength(label, font=label_font)
    d.rounded_rectangle([(W - lw) / 2 - 36, 184, (W + lw) / 2 + 36, 276], radius=46, fill=ACCENTS[1])
    d.text((W / 2, 230), label, font=label_font, fill="white", anchor="mm")
    size = 84  # uzun başlık çerçeveye sığana kadar küçülür
    while d.textlength(title, font=ImageFont.truetype(_font_path(True), size)) > W - 200 and size > 50:
        size -= 2
    d.text((W / 2, 400), title, font=ImageFont.truetype(_font_path(True), size), fill=(255, 214, 0), anchor="mm",
           stroke_width=5, stroke_fill="black")
    d.text((W / 2, 490), date_label, font=ImageFont.truetype(_font_path(False), 48), fill="white", anchor="mm",
           stroke_width=3, stroke_fill="black")

    # Tablo, Shorts arayüzünün kapattığı alt bölüme taşmasın diye satır aralığı maç sayısına göre daralır
    rows = sum(len(matches) for _, matches in groups)
    headers = sum(1 for time, _ in groups if time)
    step = min(96, (1500 - 600 - 104 * headers) // max(rows, 1))
    y, drawn = 600 if headers else 580, 0
    for time, matches in groups:
        if time:
            tw = d.textlength(time, font=bold)
            d.rounded_rectangle([(W - tw) / 2 - 30, y - 38, (W + tw) / 2 + 30, y + 38], radius=38, fill=SUBSCRIBE_RED)
            d.text((W / 2, y), time, font=bold, fill="white", anchor="mm")
            y += 104 - (96 - step) // 2
        for home, away, *score in matches:
            drawn += 1
            if visible is not None and drawn > visible:
                y += step
                continue
            text = f"{home}   {score[0]}   {away}" if score else f"{home}  –  {away}"
            size = 50
            font = ImageFont.truetype(_font_path(True), size)
            while d.textlength(text, font=font) > W - 170 and size > 30:
                size -= 2
                font = ImageFont.truetype(_font_path(True), size)
            if home in emphasize or away in emphasize:
                half = d.textlength(text, font=font) / 2 + 28
                d.rounded_rectangle([W / 2 - half, y - step / 2 + 6, W / 2 + half, y + step / 2 - 6], radius=16,
                                    outline=SUBSCRIBE_RED, width=6)
            color = (255, 214, 0) if home in highlight or away in highlight else "white"
            d.text((W / 2, y), text, font=font, fill=color, anchor="mm", stroke_width=4, stroke_fill="black")
            y += step
        y += 26
    if note:
        d.text((W / 2, min(y + 10, 1540)), note, font=regular, fill=(200, 210, 230), anchor="mm")
    img.save(out_path)


def _ass_escape(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _ts(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(words, out_path, words_per_line=3, wide=False):
    w, h = WIDE if wide else (W, H)
    # Dikeyde altyazı ortada ve iri; yatayda altta, satır daha uzun
    style = "64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,120,120,150,1" if wide \
        else "92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,5,80,80,0,1"
    words_per_line = 6 if wide else words_per_line
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,DejaVu Sans,{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    chunks = [words[i:i + words_per_line] for i in range(0, len(words), words_per_line)]
    lines = []
    for i, chunk in enumerate(chunks):
        start = chunk[0]["start"]
        end = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else chunk[-1]["end"] + 0.3
        text = _ass_escape(" ".join(w["text"] for w in chunk))
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{text}")
    Path(out_path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def render_segment(card, audio, ass, out_path, pad=0.35, zoom_out=False, size=(W, H), motion=True):
    """motion=False: görüntü kıpırdamaz (art arda gelen kartlarda sıçrama olmasın diye)."""
    w, h = size
    dur = audio_duration(audio) + pad
    # Hafif hareket: görüntü boyunca %6 yakınlaşır ya da uzaklaşır
    progress = f"on/({dur}*30)"
    zoom = "1" if not motion else f"1.06-0.06*{progress}" if zoom_out else f"1+0.06*{progress}"
    vf = (f"scale={w}:{h},zoompan=z='{zoom}':d=1:s={w}x{h}:fps=30,"
          f"ass={ass}")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-i", str(card), "-i", str(audio),
        "-vf", vf, "-af", f"apad=pad_dur={pad}", "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", str(out_path),
    ], check=True)


def concat(parts, out_path):
    listing = Path(out_path).with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out_path)],
                   check=True)
