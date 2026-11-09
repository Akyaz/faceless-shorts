"""Haftalık burç yorumu: pazartesi üç Shorts, her birinde dört burç (Koç-Yengeç, Aslan-Akrep, Yay-Balık).

Yorum yalnızca "Koç için yorum yaz" diye istenince her hafta aynı genel cümleler çıkıyor. Bu yüzden haftanın
gökyüzü olayları (gezegenlerin burç değiştirdiği günler, dolunay ve yeniay, geri hareket, Ay'ın hangi gün hangi
burçta olduğu) PyEphem ile hesaplanır ve Gemini yorumu bu tarihlere dayandırır. Burçlar tropikal zodyağa göre
(günün ekinoksuna göre ekliptik boylam). Görsel, her burcun 1824 tarihli Urania's Mirror kartı (Commons, kamu malı).
"""
import datetime
import json
import os

import ephem

from . import script

TURKEY = datetime.timezone(datetime.timedelta(hours=3))
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
          "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

CARD = "File:Sidney Hall - Urania's Mirror - {}"
# (ad, tarih aralığı, yönetici gezegen, element, Commons kartı); sıra zodyak sırası, boylam 0° Koç
SIGNS = [
    ("Koç", "21 Mart - 19 Nisan", "Mars", "ateş", CARD.format("Aries and Musca Borealis.jpg")),
    ("Boğa", "20 Nisan - 20 Mayıs", "Venüs", "toprak", CARD.format("Taurus.jpg")),
    ("İkizler", "21 Mayıs - 20 Haziran", "Merkür", "hava", CARD.format("Gemini.jpg")),
    ("Yengeç", "21 Haziran - 22 Temmuz", "Ay", "su", CARD.format("Cancer.jpg")),
    ("Aslan", "23 Temmuz - 22 Ağustos", "Güneş", "ateş", CARD.format("Leo Major and Leo Minor.jpg")),
    ("Başak", "23 Ağustos - 22 Eylül", "Merkür", "toprak", CARD.format("Virgo.jpg")),
    ("Terazi", "23 Eylül - 22 Ekim", "Venüs", "hava", CARD.format("Libra.jpg")),
    ("Akrep", "23 Ekim - 21 Kasım", "Mars", "su", CARD.format("Scorpio.jpg")),
    ("Yay", "22 Kasım - 21 Aralık", "Jüpiter", "ateş",
     CARD.format("Sagittarius and Corona Australis, Microscopium, and Telescopium.png")),
    ("Oğlak", "22 Aralık - 19 Ocak", "Satürn", "toprak", CARD.format("Capricornus.jpg")),
    ("Kova", "20 Ocak - 18 Şubat", "Satürn", "hava", CARD.format("Aquarius, Piscis Australis & Ballon Aerostatique.jpg")),
    ("Balık", "19 Şubat - 20 Mart", "Jüpiter", "su", CARD.format("Pisces.jpg")),
]
PARTS = {1: SIGNS[0:4], 2: SIGNS[4:8], 3: SIGNS[8:12]}

BODIES = [("Güneş", ephem.Sun), ("Merkür", ephem.Mercury), ("Venüs", ephem.Venus), ("Mars", ephem.Mars),
          ("Jüpiter", ephem.Jupiter), ("Satürn", ephem.Saturn)]
RETRO = {"Merkür", "Venüs", "Mars", "Jüpiter", "Satürn"}  # Güneş geri gitmez
PHASES = [("Yeniay", ephem.next_new_moon), ("İlk dördün", ephem.next_first_quarter_moon),
          ("Dolunay", ephem.next_full_moon), ("Son dördün", ephem.next_last_quarter_moon)]


def week_start(now=None):
    """Bu haftanın pazartesisi (Türkiye saatiyle)."""
    today = (now or datetime.datetime.now(TURKEY)).astimezone(TURKEY).date()
    return today - datetime.timedelta(days=today.weekday())


def date_text(day):
    return f"{day.day} {MONTHS[day.month - 1]}"


def range_text(start):
    end = start + datetime.timedelta(days=6)
    if start.month == end.month:
        return f"{start.day}-{end.day} {MONTHS[end.month - 1]}"
    return f"{date_text(start)} - {date_text(end)}"


def _utc(day, hour=12):
    """Türkiye saatiyle o günün belirtilen saati, PyEphem'in istediği UTC zamanı olarak."""
    moment = datetime.datetime.combine(day, datetime.time(hour), TURKEY).astimezone(datetime.timezone.utc)
    return ephem.Date(moment.replace(tzinfo=None))


def longitude(body_class, when):
    """Günün ekinoksuna göre ekliptik boylam (derece): tropikal burçlar buna göre."""
    body = body_class(when)
    return float(ephem.Ecliptic(body, epoch=when).lon) * 180 / ephem.pi


def sign_of(lon):
    return SIGNS[int(lon // 30) % 12][0]


def _turkey_day(when):
    return ephem.Date(when).datetime().replace(tzinfo=datetime.timezone.utc).astimezone(TURKEY).date()


def sky(start):
    """Haftanın gökyüzü olayları: {"events": [metin], "positions": [metin], "moon": [metin]}."""
    days = [start + datetime.timedelta(days=i) for i in range(8)]  # ertesi pazartesi: son günün değişimi için
    events, positions = [], []
    for name, cls in BODIES:
        lons = [longitude(cls, _utc(d)) for d in days]
        moving = [((b - a + 180) % 360) - 180 for a, b in zip(lons, lons[1:])]  # günlük hareket, 0°'yi aşarken de
        retro_now = name in RETRO and moving[0] < 0
        positions.append(f"{name} {sign_of(lons[0])} burcunda" + (" (geri harekette)" if retro_now else ""))
        for i in range(7):
            if sign_of(lons[i]) != sign_of(lons[i + 1]):
                events.append((days[i + 1], f"{name} {sign_of(lons[i + 1])} burcuna geçiyor"))
            if name in RETRO and i and (moving[i - 1] < 0) != (moving[i] < 0):
                events.append((days[i], f"{name} " + ("geri harekete başlıyor" if moving[i] < 0
                                                       else "geri hareketini bitiriyor")))
    begin = _utc(start, 0)
    for phase, find in PHASES:
        when = find(begin)
        day = _turkey_day(when)
        if day < start + datetime.timedelta(days=7):
            events.append((day, f"{phase} {sign_of(longitude(ephem.Moon, when))} burcunda"))
    events.sort(key=lambda e: e[0])
    moon = [f"{DAYS[i]} {date_text(d)}: Ay {sign_of(longitude(ephem.Moon, _utc(d)))} burcunda"
            for i, d in enumerate(days[:7])]
    return {"events": [f"{DAYS[d.weekday()]} {date_text(d)}: {text}" for d, text in events],
            "positions": positions, "moon": moon}


RULES = """Görev: YouTube Shorts için Türkçe haftalık burç yorumu. Hafta: {week}. Bu videoda dört burç var: {names}.
İzleyici kendi burcunu bekleyerek sonuna kadar izlemeli ve yorumlara burcunu yazmalı.

Haftanın gökyüzü (hesaplanmış, kesin):
Hafta başında konumlar: {positions}
Olaylar:
{events}
Ay'ın günlere göre burcu:
{moon}

Burçlar:
{signs}

Kurallar:
1. Her burç için "text": 2 kısa cümle, toplam 20-28 kelime, "sen" diye hitap et.
   - En az bir somut gün ya da tarih ver ve onu yukarıdaki gökyüzü olaylarından birine bağla (örnek: "14 Kasım'daki
     Boğa dolunayı...", "Çarşamba Ay burcuna geçince..."). Önce o burcun kendi burcundaki olayları, sonra yönetici
     gezegeninin olaylarını, sonra Ay'ın o burçta olduğu günü kullan.
   - Bir yaşam alanı seç (aşk, ilişkiler, iş, para, aile, arkadaşlık, enerji) ve somut, uygulanabilir bir tavsiye ver.
     Dört burçta dört farklı alan kullan; aynı kalıbı tekrarlama.
   - Yasak: "bu hafta senin için önemli", "evren seninle", "her şey yoluna girecek" gibi her burca uyan boş cümleler;
     korkutma ve kesin kehanet ("kesinlikle", "kaza", "hastalık", "ayrılık kapıda"); sağlık ve tedavi önerisi;
     yatırım, borsa, kripto ve kumar önerisi. Yukarıda olmayan bir gökyüzü olayı uydurma.
   - Türkçe terim kullan: "geri hareket", "ileri harekete geçiyor". "Retro", "retrograd" ve "rötar" yazma
     (rötar gecikme demektir; seslendirmede de yanlış anlaşılıyor).
2. "intro": en fazla 12 kelime; haftanın en dikkat çekici gökyüzü olayını tarihiyle söyle (selam yok).
3. "outro": izleyiciyi burcunu yorumlara yazmaya çağıran kısa bir soru (örnek: "Senin burcun hangisi? Yorumlara yaz.").
""" + script.PRONOUNCE_FIELD.replace("{", "{{").replace("}", "}}") + """
Sadece JSON döndür:
{{"intro": "...", "signs": [{{"name": "Koç", "text": "..."}}], "outro": "...", "pronounce": {{}}}}
"""


def plan(part, now=None):
    signs = PARTS[part]
    start = week_start(now)
    week = range_text(start)
    heavens = sky(start)
    print(f"Hafta {week}; olaylar: {heavens['events']}")
    names = ", ".join(s[0] for s in signs)
    prompt = RULES.format(
        week=week, names=names, positions="; ".join(heavens["positions"]),
        events="\n".join(f"- {e}" for e in heavens["events"]) or "- (bu hafta burç değişimi yok)",
        moon="\n".join(f"- {m}" for m in heavens["moon"]),
        signs="\n".join(f"- {n} ({dates}): yönetici gezegen {ruler}, {element} elementi"
                        for n, dates, ruler, element, _ in signs))
    out = json.loads(script._generate(prompt, os.environ["GEMINI_API_KEY"]))
    texts = {str(s.get("name", "")).strip(): str(s.get("text", "")).strip() for s in out.get("signs") or []}
    missing = [s[0] for s in signs if not texts.get(s[0])]
    if missing:
        raise RuntimeError(f"Burç yorumu eksik: {', '.join(missing)}")
    vague = [n for n, t in texts.items() if script.vague(t)]
    if vague:
        print(f"Belirsiz cümle: {vague}")

    source = {"title": f"Haftanın gökyüzü ({week}): gezegen konumları PyEphem ile hesaplandı",
              "source": "PyEphem", "link": "https://rhodesmill.org/pyephem/"}
    segments = [{"kind": "intro", "text": script._sentence(out["intro"]), "image_files": [signs[0][4]]}]
    for i, (name, dates, *_rest, card) in enumerate(signs, 1):
        segments.append({"kind": "item", "label": f"BURÇ {i}/4", "heading": f"{name} ({dates})",
                         "text": script._sentence(texts[name]), "source": "", "image_files": [card],
                         "headline": source})
    segments.append({"kind": "outro", "text": out["outro"].strip(), "image_files": [signs[-1][4]]})
    return {"title": f"{', '.join(s[0] for s in signs)} Haftalık Burç Yorumu ({week})", "hook_title": "",
            "label": "HAFTALIK BURÇ", "lang": "tr", "segments": segments, "sources": [source],
            "kind": "horoscope", "mood": "umutlu", "category": "24", "image_prompt": "",
            "hashtags": ["burçyorumu", "haftalıkburç", "astroloji"], "pronounce": script._pronounce(out),
            "texts": {"subscribe": "Her pazartesi haftalık burç yorumları bu kanalda. Kaçırmamak için abone ol. "
                                   "Burç yorumları eğlence amaçlıdır.",
                      "tags": ["burç yorumu", "haftalık burç yorumları", "astroloji", "shorts"]
                      + [s[0].lower() + " burcu" for s in signs]},
            "promise": "Her pazartesi haftalık burç yorumu", "dated": False}
