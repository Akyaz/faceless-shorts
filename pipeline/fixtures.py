"""Şampiyonlar Ligi'nde günün maç programı videosu: takımlar ve saatler ekranda, seslendirme tek cümle.

Kullanım: python -m pipeline.fixtures [--out out] [--date YYYYAAGG]
O gün maç yoksa video üretmeden çıkar. Veri ESPN'in açık skor tablosundan alınır; saatler Türkiye saatidir.
"""
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


def fetch(day):
    """O günün maçları: [(Türkiye saatiyle başlama zamanı, ev sahibi, deplasman)], saat sırasıyla."""
    matches = []
    # Gece yarısından sonra başlayan maç ESPN'de bir önceki günün listesinde olabilir; iki gün de sorulur
    for query in (day - datetime.timedelta(days=1), day):
        req = urllib.request.Request(SCOREBOARD.format(date=query.strftime("%Y%m%d")),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            events = json.load(resp).get("events", [])
        for event in events:
            start = datetime.datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(TR)
            if start.date() != day or event["status"]["type"]["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue
            teams = {c["homeAway"]: c["team"]["displayName"] for c in event["competitions"][0]["competitors"]}
            matches.append((start, NAMES.get(teams["home"], teams["home"]), NAMES.get(teams["away"], teams["away"])))
    return sorted(set(matches))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--date", help="YYYYAAGG; verilmezse bugün (Türkiye saati)")
    args = ap.parse_args()
    day = (datetime.datetime.strptime(args.date, "%Y%m%d").date() if args.date
           else datetime.datetime.now(TR).date())
    matches = fetch(day)
    if not matches:
        print(f"{day}: Şampiyonlar Ligi'nde maç yok, video üretilmedi.")
        return

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    groups = {}
    for start, home, away in matches:
        groups.setdefault(start.strftime("%H:%M"), []).append((home, away))
    date_label = f"{day.day} {MONTHS[day.month - 1]} {DAYS[day.weekday()]}"
    for time, rows in groups.items():
        print(time, "|", "; ".join(f"{h} - {a}" for h, a in rows))

    card, audio, ass = work / "card.png", work / "voice.mp3", work / "empty.ass"
    render.draw_fixture_card("Günün Maçları", date_label, list(groups.items()), card, "ŞAMPİYONLAR LİGİ",
                             highlight=TURKISH, note="Saatler Türkiye saatiyle")
    count = NUMBERS[len(matches)] if len(matches) < len(NUMBERS) else str(len(matches))
    synthesize(f"Şampiyonlar Ligi'nde bugün {count} maç var. İşte günün programı.", audio)
    render.write_ass([], ass)  # takımlar ekranda yazıyor; altyazı tabloyu kapatmasın
    pad = max(0.35, MIN_SECONDS - render.audio_duration(audio))
    render.render_segment(card, audio, ass, work / "voice.mp4", pad=pad)
    music_credit = music.add(work / "voice.mp4", "umutlu", out / "short.mp4")

    locals_ = [team for _, home, away in matches for team in (home, away) if team in TURKISH]
    listing = "\n".join(f"{start:%H:%M}  {home} - {away}" for start, home, away in matches)
    title = f"Şampiyonlar Ligi'nde Bugün Hangi Maçlar Var? {day.day} {MONTHS[day.month - 1]} Maç Programı"
    tags = ["şampiyonlarligi", "ucl"] + [t.lower() for t in locals_] + ["maçprogramı"]
    meta = {
        "title": title[:100],
        "description": f"{title}\n\n{listing}\n\nSaatler Türkiye saatiyledir. Kaynak: ESPN.\n\n"
                       "Günün haberleri her gün kısa ve net. Kaçırmamak için kanala abone ol.\n\n"
                       f"{music_credit}\n\n" + " ".join(f"#{t}" for t in tags + ["shorts"]),
        "tags": tags + ["şampiyonlar ligi", "maç programı", "bugünkü maçlar", "shorts"],
        "category": "17",
        "language": "tr",
    }
    (out / "metadata.json").write_text(json.dumps({**meta, "matches": [[f"{s:%H:%M}", h, a] for s, h, a in matches]},
                                                  ensure_ascii=False, indent=2))
    print(f"Başlık: {title}")
    print(f"Hazır: {out / 'short.mp4'} ({render.audio_duration(out / 'short.mp4'):.1f} sn)")


if __name__ == "__main__":
    main()
