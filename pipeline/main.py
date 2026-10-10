"""Gündem Short'u üretir: haber -> metin -> ses -> video.

Kullanım: python -m pipeline.main [--out out] [--offline] [--history dosya.json]
--offline ağ olmadan sahte haber ve sessiz ses ile render'ı dener.
--history daha önce işlenen haberleri tutar; aynı haber ikinci kez videoya dönmez.
"""
import argparse
import json
import subprocess
from pathlib import Path

from . import images, render, script


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


HISTORY_KEEP = 60  # günde 6 videoyla yaklaşık 10 gün


def load_history(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_history(path, history, plan):
    history = history + [{"source": h["title"], "title": plan["title"]} for h in plan["sources"]]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(history[-HISTORY_KEEP:], ensure_ascii=False, indent=2), encoding="utf-8")


def build_metadata(plan):
    sources = "\n".join(f"- {h['title']} ({h['source']})" for h in plan["sources"])
    title = f"{plan['title']} #shorts"
    return {
        "title": title[:100],
        "description": f"{plan['title']}\n\nKaynaklar:\n{sources}\n"
                       + (f"\nGörseller temsilidir.\n{plan['image_credit']}\n" if plan.get("image_credit") else "")
                       + "\n#gündem #haber #shorts",
        "tags": ["gündem", "haber", "son dakika", "türkiye", "shorts"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--background", help="--offline ile denenecek arka plan görseli")
    ap.add_argument("--history", help="işlenen haberlerin tutulduğu JSON dosyası")
    args = ap.parse_args()

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    if args.offline:
        headlines = [{"title": f"Örnek haber başlığı numara {i} burada yer alıyor", "source": "Örnek Kaynak",
                      "link": ""} for i in range(1, 4)]
    else:
        from .news import fetch_headlines
        headlines = fetch_headlines(limit=30)
    history = load_history(args.history) if args.history else []
    used = {h["source"] for h in history}
    fresh = [h for h in headlines if h["title"] not in used]
    if fresh:
        headlines = fresh
    else:
        print("Yeni haber yok, işlenmiş haberler yeniden kullanılacak.")
    plan = script.build_script(headlines, recent=[h["title"] for h in history[-12:]])
    if args.history:
        save_history(args.history, history, plan)
    for src in plan["sources"]:
        print(f"Kaynak başlık: {src['title']} ({src['source']})")
        for r in src.get("related", []):
            print(f"  ilgili: {r}")
    print(f"Başlık: {plan['title']}")
    if plan.get("hook_title"):
        print(f"Ekran başlığı: {plan['hook_title']}")
    for seg in plan["segments"]:
        print(f"  [{seg['kind']}] {seg['text']}")

    backgrounds, credits = [], []
    if args.offline:
        backgrounds = [args.background] if args.background else []
    else:
        found = images.find_backgrounds(plan, work, len(plan["segments"]))
        backgrounds = [path for path, _ in found]
        credits = [credit for _, credit in found]
    plan["image_credit"] = "\n".join(dict.fromkeys(credits)) or None

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
        # Görsel sayısı paragraftan azsa baştan döner
        background = backgrounds[i % len(backgrounds)] if backgrounds else None
        render.draw_card(seg, i, card, background, plan.get("hook_title", ""))
        render.write_ass(words, ass)
        part = work / f"seg{i}.mp4"
        render.render_segment(card, audio, ass, part, zoom_out=i % 2 == 1)
        parts.append(part)

    render.concat(parts, out / "short.mp4")
    meta = build_metadata(plan)
    (out / "metadata.json").write_text(json.dumps({**meta, "plan": plan}, ensure_ascii=False, indent=2))
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
