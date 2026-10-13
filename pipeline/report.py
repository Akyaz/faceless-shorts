"""Çalışmanın sonucunu duyurur: Telegram mesajı ve yönetim panelinin okuduğu kayıt.

Kullanım: python -m pipeline.report out
Kayıt, deponun panel-data dalındaki feed.json dosyasına eklenir (ana dalın geçmişi kirlenmesin diye ayrı dal).
TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlı değilse mesaj atlanır. Hiçbir hata çalışmayı başarısız saymaz.
"""
import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
BRANCH = "panel-data"
FEED = "feed.json"
KEEP = 300


def collect(out_dir):
    """Üretilen videolar: [{title, url}]; url yalnızca YouTube'a yüklendiyse dolu."""
    out = Path(out_dir)
    videos = []
    for path in [out / "metadata.json"] + sorted(out.glob("*/metadata.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        videos.append({"title": meta.get("title", ""), "url": meta.get("youtube_url")})
    return videos


def _github(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
        "User-Agent": "faceless-shorts"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def append_feed(entry):
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        _github("GET", f"/repos/{repo}/git/ref/heads/{BRANCH}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        default = _github("GET", f"/repos/{repo}")["default_branch"]
        sha = _github("GET", f"/repos/{repo}/git/ref/heads/{default}")["object"]["sha"]
        _github("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": sha})
    for _ in range(4):  # aynı anda biten başka bir çalışma dosyayı değiştirmiş olabilir
        feed, sha = [], None
        try:
            current = _github("GET", f"/repos/{repo}/contents/{FEED}?ref={BRANCH}")
            feed, sha = json.loads(base64.b64decode(current["content"])), current["sha"]
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        # Aynı çalışmanın önceki kaydı (yeniden deneme, yeniden yükleme) yenisiyle değiştirilir
        previous = [e for e in feed if e["run"] == entry["run"]]
        if previous and entry["mode"] == "retry":
            entry["mode"] = previous[-1]["mode"]
        feed = [e for e in feed if e["run"] != entry["run"]]
        content = json.dumps((feed + [entry])[-KEEP:], ensure_ascii=False, indent=1)
        body = {"message": f"feed: {entry['run']}", "branch": BRANCH,
                "content": base64.b64encode(content.encode()).decode(), **({"sha": sha} if sha else {})}
        try:
            _github("PUT", f"/repos/{repo}/contents/{FEED}", body)
            return
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422):
                raise
    raise RuntimeError("feed.json güncellenemedi")


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram ayarlı değil, mesaj atlandı.")
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30):
        pass


def message(entry):
    lines = []
    uploaded = [v for v in entry["videos"] if v["url"]]
    held = [v for v in entry["videos"] if not v["url"]]
    if uploaded:
        lines.append(f"✅ Yüklendi ({entry['mode']})")
        lines += [f"• {v['title']}\n  {v['url']}" for v in uploaded]
    if held:
        lines.append(f"🎬 Üretildi, yüklenmedi ({entry['mode']})")
        lines += [f"• {v['title']}" for v in held]
    if entry["status"] != "success":
        lines.append(f"❌ Çalışma başarısız ({entry['mode']}): {entry['link']}")
    return "\n".join(lines)


def main():
    videos = collect(sys.argv[1] if len(sys.argv) > 1 else "out")
    status = os.environ.get("JOB_STATUS", "success")
    if not videos and status == "success":
        print("Bildirilecek video yok.")  # örneğin maç olmayan gün
        return
    repo, run = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", "")
    # Yeniden yüklemede kayıt, videoları üreten asıl çalışmanın numarasıyla tutulur
    entry = {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "run": os.environ.get("SOURCE_RUN_ID") or run,
             "event": os.environ.get("GITHUB_EVENT_NAME", ""), "mode": os.environ.get("MODE", ""), "status": status,
             "link": f"https://github.com/{repo}/actions/runs/{run}", "videos": videos}
    for name, step in (("Kayıt", lambda: append_feed(entry)), ("Telegram", lambda: telegram(message(entry)))):
        try:
            step()
        except Exception as exc:
            print(f"{name} yapılamadı: {exc}")


if __name__ == "__main__":
    main()
