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


def _brand(img):
    """Sol üst köşede küçük kanal logosu."""
    size = 128
    logo = Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)
    # Kenardan pay: video boyunca %6 yakınlaşınca logo kadrajın dışına taşmasın
    img.paste(logo, (60, 76), logo)


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


def draw_card(segment, idx, out_path, background=None, hook_title="", label="GÜNDEM", subscribe=False, lang="tr"):
    """segment'teki label ve heading, videonun genel etiketinin ve başlığının yerine geçer."""
    accent = ACCENTS[idx % len(ACCENTS)]
    img = _photo(background) if background else _gradient(accent)

    d = ImageDraw.Draw(img)
    bold = ImageFont.truetype(_font_path(True), 56)
    regular = ImageFont.truetype(_font_path(False), 44)

    _brand(img)
    label = segment.get("label") or label
    hook_title = segment.get("heading") or hook_title
    lw = d.textlength(label, font=bold)
    d.rounded_rectangle([(W - lw) / 2 - 36, 180, (W + lw) / 2 + 36, 280], radius=50, fill=accent)
    d.text((W / 2, 230), label, font=bold, fill="white", anchor="mm")

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

    _brand(img)
    bold = ImageFont.truetype(_font_path(True), 50)
    regular = ImageFont.truetype(_font_path(False), 40)
    lw = d.textlength(label, font=bold)
    d.rounded_rectangle([(W - lw) / 2 - 36, 184, (W + lw) / 2 + 36, 276], radius=46, fill=ACCENTS[1])
    d.text((W / 2, 230), label, font=bold, fill="white", anchor="mm")
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
