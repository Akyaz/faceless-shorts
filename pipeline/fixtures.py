"""Şampiyonlar Ligi'nde günün maç programı videosu: takımlar ve saatler ekranda, seslendirme tek cümle.

Kullanım: python -m pipeline.fixtures [--out out] [--date YYYYAAGG] [--results] [--emphasize "Takım,Takım"]
--results önce bir önceki günün sonuçlarını (skorlar tek tek gelir), ardından günün programını gösterir.
--emphasize verilen takımların maçını kırmızı çerçeveye alır; Türk takımlarının maçı zaten sarı yazılır.
O gün maç yoksa video üretmeden çıkar. Veri ESPN'in açık skor tablosundan alınır; saatler Türkiye saatidir.
"""
import subprocess
import argparse
import datetime
import json
import urllib.request
from pathlib import Path

from . import music, render
from .tts import synthesize

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates={date}"
TR = datetime.timezone(datetime.timedelta(hours=3))
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
          "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
NUMBERS = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "on bir", "on iki",
           "on üç", "on dört", "on beş", "on altı", "on yedi", "on sekiz"]
# ESPN'in İngilizce adları yerine Türkiye'de kullanılan adlar; listede olmayan takım ESPN'deki adıyla yazılır
NAMES = {
    "Bayern Munich": "Bayern Münih", "Internazionale": "Inter", "Sporting CP": "Sporting",
    "Slavia Prague": "Slavia Prag", "Sparta Prague": "Sparta Prag", "Atlético Madrid": "Atletico Madrid",
    "PSV Eindhoven": "PSV", "Paris Saint-Germain": "PSG", "Feyenoord Rotterdam": "Feyenoord", "AS Roma": "Roma",
    "FC Porto": "Porto", "Fenerbahce": "Fenerbahçe", "Besiktas": "Beşiktaş", "Red Star Belgrade": "Kızılyıldız",
    "FC Copenhagen": "Kopenhag", "Copenhagen": "Kopenhag", "Viking FK": "Viking", "Sabah FK": "Sabah",
    "LASK Linz": "LASK", "AEK Athens": "AEK", "VfB Stuttgart": "Stuttgart", "Borussia Dortmund": "Dortmund",
    "Bayer Leverkusen": "Leverkusen", "AC Milan": "Milan", "Olympiacos": "Olympiakos", "Dinamo Zagreb": "Dinamo Zagreb",
}
TURKISH = {"Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor", "Başakşehir", "Samsunspor"}
MIN_SECONDS = 12  # tablo okunabilsin diye seslendirme bitse de görüntü ekranda kalır


def fetch(day, finished=False):
    """O günün maçları: [(Türkiye saatiyle başlama zamanı, ev sahibi, deplasman)], saat sırasıyla.
    finished=True: yalnızca bitmiş maçlar, sonlarına skor eklenir ("1 - 4")."""
    matches = []
    # Gece yarısından sonra başlayan maç ESPN'de bir önceki günün listesinde olabilir; iki gün de sorulur
    for query in (day - datetime.timedelta(days=1), day):
        req = urllib.request.Request(SCOREBOARD.format(date=query.strftime("%Y%m%d")),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            events = json.load(resp).get("events", [])
        for event in events:
            start = datetime.datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(TR)
            state = event["status"]["type"]["name"]
            if start.date() != day or state in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue
            if finished and state not in ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FINAL_AET", "STATUS_FINAL_PEN"):
                continue
            sides = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
            home, away = (NAMES.get(sides[k]["team"]["displayName"], sides[k]["team"]["displayName"])
                          for k in ("home", "away"))
            score = (f"{sides['home'].get('score', '?')} - {sides['away'].get('score', '?')}",) if finished else ()
            matches.append((start, home, away, *score))
    return sorted(set(matches))


def _silence(seconds, out_path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", f"{seconds:.2f}", "-c:a", "libmp3lame", str(out_path)], check=True)
    return out_path


def _overlay(video, voice, out_path):
    """Seslendirmeyi videonun başına, mevcut sesin üstüne ekler."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice), "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    str(out_path)], check=True)


def _label(day):
    return f"{day.day} {MONTHS[day.month - 1]} {DAYS[day.weekday()]}"


def _count(n):
    return NUMBERS[n] if n < len(NUMBERS) else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--date", help="YYYYAAGG; verilmezse bugün (Türkiye saati)")
    ap.add_argument("--results", action="store_true", help="önce bir önceki günün sonuçlarını göster")
    ap.add_argument("--emphasize", default="", help="kırmızı çerçeveye alınacak takımlar, virgülle")
    args = ap.parse_args()
    day = (datetime.datetime.strptime(args.date, "%Y%m%d").date() if args.date
           else datetime.datetime.now(TR).date())
    emphasize = {t.strip() for t in args.emphasize.split(",") if t.strip()}
    matches = fetch(day)
    results = fetch(day - datetime.timedelta(days=1), finished=True) if args.results else []
    if not matches and not results:
        print(f"{day}: Şampiyonlar Ligi'nde maç yok, video üretilmedi.")
        return

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    groups = {}
    for start, home, away in matches:
        groups.setdefault(start.strftime("%H:%M"), []).append((home, away))
    for time, rows in groups.items():
        print(time, "|", "; ".join(f"{h} - {a}" for h, a in rows))

    # Her parça: (kart, ses, ses bitince ekranda kalma süresi, hareket)
    parts = []
    intro = work / "intro.mp3"
    if results:
        yesterday = day - datetime.timedelta(days=1)
        # Türk takımının maçı en üstte, sonra öne çıkarılanlar; skorlar bu sırayla gelir
        ordered = sorted(results, key=lambda r: (not {r[1], r[2]} & TURKISH, not {r[1], r[2]} & emphasize, r[0]))
        rows = [(h, a, sc) for _, h, a, sc in ordered]
        print("Sonuçlar |", "; ".join(f"{h} {sc} {a}" for h, a, sc in rows))
        draw = lambda n, path: render.draw_fixture_card(  # noqa: E731
            "Sürprizlerle Dolu Gece", f"{yesterday.day} {MONTHS[yesterday.month - 1]} Sonuçları", [(None, rows)],
            path, "ŞAMPİYONLAR LİGİ", highlight=TURKISH, emphasize=emphasize, visible=n)
        synthesize("Şampiyonlar Ligi'nde dün gece neler oldu? İşte sonuçlar.", intro)
        # Boş tablo yalnızca bir an görünür; seslendirme skorlar gelirken üstüne eklenir
        draw(0, work / "results0.png")
        parts.append((work / "results0.png", _silence(0.8, work / "tick0.mp3"), 0.0, False))
        for n in range(1, len(rows) + 1):  # skorlar tek tek gelir
            draw(n, work / f"results{n}.png")
            parts.append((work / f"results{n}.png", _silence(0.6, work / f"tick{n}.mp3"), 0.0, False))
        parts.append((work / f"results{len(rows)}.png", _silence(3.0, work / "hold.mp3"), 0.0, False))
    if matches:
        card, voice = work / "card.png", work / "voice.mp3"
        render.draw_fixture_card("Günün Maçları", _label(day), list(groups.items()), card, "ŞAMPİYONLAR LİGİ",
                                 highlight=TURKISH, note="Saatler Türkiye saatiyle")
        synthesize("Ve bugünün programı." if results
                   else f"Şampiyonlar Ligi'nde bugün {_count(len(matches))} maç var. İşte günün programı.", voice)
        hold = max(0.35, MIN_SECONDS - render.audio_duration(voice)) if not results else 5.0
        parts.append((card, voice, hold, True))

    ass = work / "empty.ass"
    render.write_ass([], ass)  # takımlar ekranda yazıyor; altyazı tabloyu kapatmasın
    clips = []
    for i, (card, audio, pad, motion) in enumerate(parts):
        clip = work / f"part{i}.mp4"
        render.render_segment(card, audio, ass, clip, pad=pad, motion=motion)
        clips.append(clip)
    render.concat(clips, work / "voice.mp4")
    if results:
        _overlay(work / "voice.mp4", intro, work / "voiced.mp4")
    render.add_subscribe(work / ("voiced.mp4" if results else "voice.mp4"), work / "voice_sub.mp4")
    music_credit = music.add(work / "voice_sub.mp4", "gergin" if results else "umutlu", out / "short.mp4")

    teams = [t for _, home, away, *_ in results + matches for t in (home, away)]
    locals_ = list(dict.fromkeys(t for t in teams if t in TURKISH))
    listing = "\n".join(f"{start:%H:%M}  {home} - {away}" for start, home, away in matches)
    if results:
        yesterday = day - datetime.timedelta(days=1)
        title = (f"Bu Şampiyonlar Ligi Haftasında Neler Oldu?! 😱 {yesterday.day} {MONTHS[yesterday.month - 1]} "
                 f"Sonuçları ve {day.day} {MONTHS[day.month - 1]} Dev Maç Programı!")
        scores = "\n".join(f"{home} {score} {away}" for _, home, away, score in results)
        body = f"{yesterday.day} {MONTHS[yesterday.month - 1]} sonuçları:\n{scores}\n\n" + (
            f"{day.day} {MONTHS[day.month - 1]} programı:\n{listing}\n\n" if listing else "")
    else:
        title = f"Şampiyonlar Ligi'nde Bugün Hangi Maçlar Var? {day.day} {MONTHS[day.month - 1]} Maç Programı"
        body = f"{listing}\n\n"
    tags = ["ucl", "şampiyonlarligi"] + [t.lower() for t in locals_] + ["maçprogramı"]
    meta = {
        "title": title[:100],
        "description": f"{title}\n\n{render.channel_line()}\n\n{body}Saatler Türkiye saatiyledir. Kaynak: ESPN.\n\n"
                       "Günün haberleri her gün kısa ve net. Kaçırmamak için kanala abone ol.\n\n"
                       f"{music_credit}\n\n" + " ".join(f"#{t}" for t in tags + ["shorts"]),
        "tags": tags + ["şampiyonlar ligi", "maç sonuçları", "maç programı", "shorts"],
        "category": "17",
        "language": "tr",
    }
    (out / "metadata.json").write_text(json.dumps(
        {**meta, "matches": [[f"{s:%H:%M}", h, a] for s, h, a in matches],
         "results": [[h, sc, a] for _, h, a, sc in results]}, ensure_ascii=False, indent=2))
    print(f"Başlık: {title}")
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
