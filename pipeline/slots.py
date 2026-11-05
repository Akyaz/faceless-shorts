"""Zamanlanmış çalışmanın hangi saatin videosu olduğunu ve o saatin videosunun bugün üretilip üretilmediğini söyler.

GitHub zamanlanmış çalışmaları saatlerce geciktirebiliyor ya da hiç başlatmayabiliyor. Bu yüzden asıl tetikleme
dışarıdan (cron-job.org) slot girdisiyle gelir; GitHub'ın kendi zamanlaması ve her saatin 25 dakika sonrasındaki
tetikleme yedektir: o saatin videosu o gün kayda geçtiyse yedek hiçbir şey üretmeden kapanır.

Kurallar:
- "Kayda geçti": o saatin o günkü kaydında video var (yüklenemediyse panelden yeniden yüklenir) ya da çalışma
  başarılı bitti. Video çıkmadan düşen çalışma (ör. Gemini 503) sayılmaz; yedek tetikleme yeniden dener.
- Bayat tetikleme atlanır: GitHub zamanlamayı saatin kendisinden MAX_LATE sonra başlattıysa ya da çalışma
  kuyrukta MAX_LATE beklediyse video yanlış saatte çıkmasın diye üretilmez. Panelden elle "şimdi üret" geç saatte
  de çalışır (yalnızca kuyrukta bekleme sınırı uygulanır).
- Saatler ve günler Türkiye saatiyle; çalışmanın günü, tetiklendiği andır (kuyrukta bekleyen dünkü tetikleme
  bugünün videosu sayılmaz).

Kullanım (GitHub Actions adımı): python -m pipeline.slots
Ortam: GITHUB_EVENT_NAME, SCHEDULE (github.event.schedule), SLOT_INPUT (elle/dışarıdan tetiklemede saat adı,
ör. "10:00"), INPUT_MODE, CUSTOM (elle metin varsa 1)
Çıktı (GITHUB_OUTPUT): run=true|false, mode=..., slot=..., script=...

Önceden yazılmış video: scripts/scheduled/YYYY-AA-GG-SSDD.json (Türkiye tarihi ve saati, ör. 2026-10-24-2030.json)
varsa o saatte otomatik video yerine bu metin üretilir (derbi serisi gibi önceden planlanan içerikler).
"""
import datetime
import json
import os
import time
import urllib.request

TURKEY = datetime.timezone(datetime.timedelta(hours=3))
MAX_LATE = datetime.timedelta(hours=3)
WAIT_MINUTES = 120  # öndeki çalışmalar en fazla bu kadar beklenir (iş akışındaki slot işinin süresi bundan uzun)

# cron -> (saat adı, video türü). Saatler UTC; Türkiye saati = UTC+3. Her saatin ikinci satırı yedektir.
# Saat eklenir ya da değişirse panelin günlük planı da güncellenmeli (faceless-shorts-panel/api.js, PLAN).
SLOTS = {
    # Günde 6 Shorts (maç günü 7). 07:15 sabah özeti ve 16:00 İngilizce "On This Day" kaldırıldı: özetler akılda
    # kalmıyordu, İngilizce video Türkçe kitleyi karıştırıyordu.
    "50 6 * * *": ("10:00", "story"), "15 7 * * *": ("10:00", "story"),
    # 12:00 ve 15:00: eskimeyen "Biliyor muydun?" (haber birkaç saatte eskiyor, bu videolar aylarca önerilebilir)
    "50 8 * * *": ("12:00", "fact"), "15 9 * * *": ("12:00", "fact"),
    # 13:30: maç programı; Süper Lig maçı yoksa Türk takımlarının Avrupa maçları, o da yoksa video çıkmaz
    "20 10 * * *": ("13:30", "matchday"), "45 10 * * *": ("13:30", "matchday"),
    "50 11 * * *": ("15:00", "fact"), "15 12 * * *": ("15:00", "fact"),
    # 17:00: magazin ve kültür-sanat (film, dizi, konser, tiyatro, ödül)
    "50 13 * * *": ("17:00", "culture"), "15 14 * * *": ("17:00", "culture"),
    # 19:00: tek konulu spor haberi (taraftarı yoruma çağıran soruyla biter)
    "50 15 * * *": ("19:00", "sportstory"), "15 16 * * *": ("19:00", "sportstory"),
    # 20:30 günün özeti yorum getirmiyordu: yerine "Sen ne dersin?" tartışma videosu
    "20 17 * * *": ("20:30", "debate"), "45 17 * * *": ("20:30", "debate"),
    # 13:00: yalnızca önceden zamanlanmış video varsa (ör. bayram tebriği); yoksa hiçbir şey üretilmez
    "0 10 * * *": ("13:00", "scheduled"), "25 10 * * *": ("13:00", "scheduled"), "55 10 * * *": ("13:00", "scheduled"),
    # Tarih videosu ve haftalık derleme kendi iş akışlarında
    "0 18 * * *": ("21:00", "longform"), "30 18 * * *": ("21:00", "longform"),
    "50 7 * * 0": ("pazar 11:00", "weekly"), "15 8 * * 0": ("pazar 11:00", "weekly"),
}


def slot_time(slot, day):
    """Saat adının o gündeki anı (Türkiye saati): "10:00", "pazar 11:00"."""
    hour, minute = map(int, slot.split()[-1].split(":"))
    return datetime.datetime.combine(day, datetime.time(hour, minute), TURKEY)


def turkey_day(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TURKEY).date()


def is_done(feed, slot, day):
    """O günün o saati kayda geçmiş mi (modül açıklamasındaki kural)."""
    return any(e.get("slot") == slot and e.get("time") and turkey_day(e["time"]) == day
               and (e.get("videos") or e.get("status") == "success") for e in feed)


def stale(event, slot, created, now):
    """Tetikleme bayatsa sebebi, değilse boş."""
    if now - created > MAX_LATE:
        return f"çalışma {(now - created) / datetime.timedelta(hours=1):.1f} saat kuyrukta bekledi"
    if event == "schedule" and created - slot_time(slot, created.astimezone(TURKEY).date()) > MAX_LATE:
        return f"GitHub tetiklemeyi {slot} saatinden çok sonra başlattı"
    return ""


def _api(path):
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}", headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def created_at():
    """Bu çalışmanın tetiklendiği an; okunamazsa şimdi (bayatlık denetimi yapılamaz)."""
    try:
        return datetime.datetime.fromisoformat(_api(f"/actions/runs/{os.environ['GITHUB_RUN_ID']}")["created_at"]
                                               .replace("Z", "+00:00"))
    except Exception as exc:
        print(f"Çalışmanın başlama zamanı okunamadı ({exc})")
        return datetime.datetime.now(datetime.timezone.utc)


def done(slot, day):
    """Kayıt okunamazsa üretime izin verilir (GitHub aksarken video hiç çıkmamaktansa)."""
    from .report import read_feed
    for attempt in range(3):
        try:
            return is_done(read_feed()[0], slot, day)
        except Exception as exc:
            print(f"Kayıt okunamadı ({exc})")
            time.sleep(10 * (attempt + 1))
    print("Kayıt okunamadı; video üretilecek")
    return False


def wait_for_running():
    """Aynı iş akışının başka bir zamanlanmış ya da dışarıdan tetiklenmiş çalışması sürüyorsa
    bitmesini bekler; böylece kayda bakıldığında asıl çalışmanın sonucu görünür ve aynı anda üretilen iki video
    aynı konuyu seçmez (işlenen konu kaydı çalışmalar arasında taşınır). En fazla WAIT_MINUTES.
    Yalnızca daha önce başlamış çalışmalar beklenir: aynı anda başlayan iki çalışma birbirini beklemesin."""
    me, workflow = os.environ.get("GITHUB_RUN_ID"), os.environ.get("WORKFLOW_FILE")
    if not (os.environ.get("GITHUB_REPOSITORY") and me and workflow and os.environ.get("GITHUB_TOKEN")):
        return
    for _ in range(WAIT_MINUTES * 2):
        busy = []
        for status in ("in_progress", "queued"):
            runs = _api(f"/actions/workflows/{workflow}/runs?status={status}&per_page=50")["workflow_runs"]
            busy += [r["id"] for r in runs if r["id"] < int(me)]
        if not busy:
            return
        print(f"Daha önce başlamış bir çalışma sürüyor ({busy}); bitmesi bekleniyor")
        time.sleep(30)
    print("Bekleme süresi doldu; devam ediliyor")


SCHEDULED_DIR = "scripts/scheduled"


def _scheduled_file(slot, day, ext):
    """scripts/scheduled/YYYY-AA-GG-SSDD.<ext>: .json o saate önceden yazılmış metin, .skip o günün iptali."""
    path = f"{SCHEDULED_DIR}/{day:%Y-%m-%d}-{slot.split()[-1].replace(':', '')}.{ext}"
    return path if slot[:1].isdigit() and os.path.exists(path) else ""


def _wait():
    try:
        wait_for_running()
    except Exception as exc:  # bekleme yapılamasa da karar kayda göre verilir
        print(f"Süren çalışmalar okunamadı: {exc}")


def decide():
    """(üretilsin mi, tür, saat, önceden yazılmış metin)"""
    slot_input = os.environ.get("SLOT_INPUT", "").strip()
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if slot_input:  # dışarıdan tetikleme: zamanlanmış çalışmayla aynı kurallar
        modes = {name: mode for name, mode in SLOTS.values()}
        if slot_input not in modes:
            raise SystemExit(f"Bilinmeyen saat: {slot_input} (geçerli: {', '.join(modes)})")
        slot, mode = slot_input, modes[slot_input]
    elif event != "schedule":  # elle üretim: saati yok, yine de öndeki çalışmayla aynı konuyu seçmesin
        _wait()
        mode = "custom" if os.environ.get("CUSTOM") else (os.environ.get("INPUT_MODE") or "story")
        return True, mode, "", ""
    else:
        slot, mode = SLOTS[os.environ["SCHEDULE"]]
    created = created_at()
    reason = stale(event, slot, created, datetime.datetime.now(datetime.timezone.utc))
    if reason:
        print(f"{slot} tetiklemesi bayat ({reason}); video yanlış saatte çıkmasın diye atlanıyor.")
        return False, mode, slot, ""
    day = created.astimezone(TURKEY).date()
    _wait()
    if done(slot, day):
        print(f"{slot} videosu {day} için zaten kayıtta; bu tetikleme atlanıyor.")
        return False, mode, slot, ""
    if _scheduled_file(slot, day, "skip"):
        print(f"{slot} videosu bugün için iptal edildi (.skip dosyası).")
        return False, mode, slot, ""
    script = _scheduled_file(slot, day, "json")
    if script:
        print(f"{slot} için önceden yazılmış metin: {script}")
        return True, "custom", slot, script
    if mode == "scheduled":  # bu saatin kendi otomatik videosu yok
        print(f"{slot} için bugün zamanlanmış video yok.")
        return False, mode, slot, ""
    return True, mode, slot, ""


def main():
    run, mode, slot, script = decide()
    print(f"Üretim: {run}, tür: {mode}, saat: {slot or '-'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as out:
        out.write(f"run={'true' if run else 'false'}\nmode={mode}\nslot={slot}\nscript={script}\n")


if __name__ == "__main__":
    main()
