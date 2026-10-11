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


def _subscribe(d, bold, regular):
    """Son kartta altyazının altında abone çağrısı."""
    d.text((W / 2, 1270), "Günün haberleri her gün bu kanalda", font=regular, fill="white", anchor="mm",
           stroke_width=3, stroke_fill="black")
    text = "ABONE OL"
    tw = d.textlength(text, font=bold)
    d.rounded_rectangle([(W - tw) / 2 - 48, 1330, (W + tw) / 2 + 48, 1440], radius=55, fill=SUBSCRIBE_RED)
    d.text((W / 2, 1385), text, font=bold, fill="white", anchor="mm")


def draw_card(segment, idx, out_path, background=None, hook_title="", label="GÜNDEM", subscribe=False):
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
        _subscribe(d, bold, regular)
    if segment.get("source"):
        d.text((W / 2, 1560), f"Kaynak: {segment['source']}", font=regular, fill=(230, 230, 230),
               anchor="mm", stroke_width=3, stroke_fill="black")
    img.save(out_path)


def draw_wide_card(segment, idx, out_path, background=None, subscribe=False):
    """Yatay derleme kartı: üstte etiket ve haber başlığı, altyazı altta kalır."""
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

    if segment.get("heading"):
        font = ImageFont.truetype(_font_path(True), 76)
        y = 270
        for line in _wrap(d, segment["heading"], font, w - 300):
            d.text((w / 2, y), line, font=font, fill=(255, 214, 0), anchor="mm", stroke_width=5, stroke_fill="black")
            y += 94
    if subscribe:
        text = "ABONE OL"
        tw = d.textlength(text, font=bold)
        d.rounded_rectangle([(w - tw) / 2 - 44, 500, (w + tw) / 2 + 44, 600], radius=50, fill=SUBSCRIBE_RED)
        d.text((w / 2, 550), text, font=bold, fill="white", anchor="mm")
    if segment.get("source"):
        # Kenardan pay: yakınlaşınca yazı kadrajın dışına taşmasın
        d.text((w - 110, h - 90), f"Kaynak: {segment['source']}", font=regular, fill=(230, 230, 230),
               anchor="rm", stroke_width=3, stroke_fill="black")
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


def render_segment(card, audio, ass, out_path, pad=0.35, zoom_out=False, size=(W, H)):
    w, h = size
    dur = audio_duration(audio) + pad
    # Hafif hareket: görüntü boyunca %6 yakınlaşır ya da uzaklaşır
    progress = f"on/({dur}*30)"
    zoom = f"1.06-0.06*{progress}" if zoom_out else f"1+0.06*{progress}"
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
