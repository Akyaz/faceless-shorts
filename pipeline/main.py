"""Gündem Short'u üretir: haber -> metin -> ses -> video.

Kullanım: python -m pipeline.main [--out out] [--offline]
--offline ağ olmadan sahte haber ve sessiz ses ile render'ı dener.
"""
import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from . import render, script


def _offline_audio(text, out_path):
    words, t = [], 0.0
    for w in text.split():
        dur = 0.08 * len(w) + 0.12
        words.append({"text": w, "start": t, "end": t + dur})
        t += dur + 0.05
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{t:.2f}", "-c:a", "libmp3lame", str(out_path)],
                   check=True)
    return words


def build_metadata(plan):
    sources = "\n".join(f"- {h['title']} ({h['source']})" for h in plan["sources"])
    title = f"{plan['title']} | {date.today().strftime('%d.%m.%Y')} #shorts"
    return {
        "title": title[:100],
        "description": f"{plan['title']}\n\nKaynaklar:\n{sources}\n\n#gündem #haber #shorts",
        "tags": ["gündem", "haber", "son dakika", "türkiye", "shorts"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    if args.offline:
        headlines = [{"title": f"Örnek haber başlığı numara {i} burada yer alıyor", "source": "Örnek Kaynak",
                      "link": ""} for i in range(1, 4)]
    else:
        from .news import fetch_headlines
        headlines = fetch_headlines()
    plan = script.build_script(headlines)

    parts = []
    for i, seg in enumerate(plan["segments"]):
        audio = work / f"seg{i}.mp3"
        if args.offline:
            words = _offline_audio(seg["text"], audio)
        else:
            from .tts import synthesize
            words = synthesize(seg["text"], audio)
        card = work / f"card{i}.png"
        ass = work / f"seg{i}.ass"
        render.draw_card(seg, i, card)
        render.write_ass(words, ass)
        part = work / f"seg{i}.mp4"
        render.render_segment(card, audio, ass, part)
        parts.append(part)

    render.concat(parts, out / "short.mp4")
    meta = build_metadata(plan)
    (out / "metadata.json").write_text(json.dumps({**meta, "plan": plan}, ensure_ascii=False, indent=2))
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
