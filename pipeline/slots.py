"""Zamanlanmış çalışmanın hangi saatin videosu olduğunu ve o saatin videosunun bugün üretilip üretilmediğini söyler.

GitHub zamanlanmış çalışmaları geciktirebiliyor ya da hiç başlatmayabiliyor. Bu yüzden her saatin 25 dakika
sonrasında bir yedek tetikleme var: asıl çalışma o gün kayda geçtiyse yedek hiçbir şey üretmeden kapanır.

Kullanım (GitHub Actions adımı): python -m pipeline.slots
Ortam: GITHUB_EVENT_NAME, SCHEDULE (github.event.schedule), INPUT_MODE, CUSTOM (elle metin varsa 1)
Çıktı (GITHUB_OUTPUT): run=true|false, mode=..., slot=..., script=...

Önceden yazılmış video: scripts/scheduled/YYYY-AA-GG-SSDD.json (Türkiye tarihi ve saati, ör. 2026-10-24-2030.json)
varsa o saatte otomatik video yerine bu metin üretilir (derbi serisi gibi önceden planlanan içerikler).
"""
import datetime
import json
import os
import time
import urllib.request

# cron -> (saat adı, video türü). Saatler UTC; Türkiye saati = UTC+3. Her saatin ikinci satırı yedektir.
SLOTS = {
    "5 4 * * *": ("07:15", "morning"), "30 4 * * *": ("07:15", "morning"),
    "50 6 * * *": ("10:00", "story"), "15 7 * * *": ("10:00", "story"),
    "50 8 * * *": ("12:00", "story"), "15 9 * * *": ("12:00", "story"),
    "20 10 * * *": ("13:30", "sports"), "45 10 * * *": ("13:30", "sports"),
    "50 11 * * *": ("15:00", "trend"), "15 12 * * *": ("15:00", "trend"),
    "50 12 * * *": ("16:00", "world"), "15 13 * * *": ("16:00", "world"),
    "50 15 * * *": ("19:00", "story"), "15 16 * * *": ("19:00", "story"),
    # 20:30 günün özeti yorum getirmiyordu: yerine "Sen ne dersin?" tartışma videosu
    "20 17 * * *": ("20:30", "debate"), "45 17 * * *": ("20:30", "debate"),
    # Tarih videosu ve haftalık derleme kendi iş akışlarında
    "0 18 * * *": ("21:00", "longform"), "30 18 * * *": ("21:00", "longform"),
    "50 7 * * 0": ("pazar 11:00", "weekly"), "15 8 * * 0": ("pazar 11:00", "weekly"),
}


def done_today(slot):
    """Bu saatin videosu bugün (UTC) kayda geçmiş mi? Kayıt okunamazsa üretime izin verilir."""
    from .report import read_feed
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    try:
        feed, _ = read_feed()
    except Exception as exc:
        print(f"Kayıt okunamadı ({exc}); video üretilecek")
        return False
    return any(e.get("slot") == slot and e.get("time", "").startswith(today) for e in feed)


def wait_for_running():
    """Aynı iş akışının başka bir zamanlanmış çalışması sürüyorsa (GitHub asıl çalışmayı geciktirmiş olabilir)
    bitmesini bekler; böylece kayda bakıldığında asıl çalışmanın sonucu görünür. En fazla 40 dakika."""
    repo, me = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    workflow = os.environ.get("WORKFLOW_FILE")
    if not (repo and workflow and os.environ.get("GITHUB_TOKEN")):
        return
    for _ in range(80):
        busy = []
        for status in ("in_progress", "queued"):
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?event=schedule&status={status}",
                headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                busy += [r["id"] for r in json.load(resp)["workflow_runs"] if str(r["id"]) != str(me)]
        if not busy:
            return
        print(f"Başka bir zamanlanmış çalışma sürüyor ({busy}); bitmesi bekleniyor")
        time.sleep(30)


SCHEDULED_DIR = "scripts/scheduled"


def scheduled_script(slot):
    """Bu saat için önceden yazılmış metin dosyası (yoksa boş)."""
    if not slot[:1].isdigit():
        return ""
    turkey = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    path = f"{SCHEDULED_DIR}/{turkey:%Y-%m-%d}-{slot.replace(':', '')}.json"
    return path if os.path.exists(path) else ""


def decide():
    """(üretilsin mi, tür, saat, önceden yazılmış metin)"""
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        mode = "custom" if os.environ.get("CUSTOM") else (os.environ.get("INPUT_MODE") or "story")
        return True, mode, "", ""
    slot, mode = SLOTS[os.environ["SCHEDULE"]]
    try:
        wait_for_running()
    except Exception as exc:  # bekleme yapılamasa da karar kayda göre verilir
        print(f"Süren çalışmalar okunamadı: {exc}")
    if done_today(slot):
        print(f"{slot} videosu bugün zaten üretildi; bu tetikleme atlanıyor.")
        return False, mode, slot, ""
    script = scheduled_script(slot)
    if script:
        print(f"{slot} için önceden yazılmış metin: {script}")
        return True, "custom", slot, script
    return True, mode, slot, ""


def main():
    run, mode, slot, script = decide()
    print(f"Üretim: {run}, tür: {mode}, saat: {slot or '-'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as out:
        out.write(f"run={'true' if run else 'false'}\nmode={mode}\nslot={slot}\nscript={script}\n")


if __name__ == "__main__":
    main()
