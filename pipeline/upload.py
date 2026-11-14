"""Videoyu YouTube Data API ile kanala yükler.

Gerekli ortam değişkenleri: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
İsteğe bağlı: YT_PRIVACY (public | unlisted | private, varsayılan public)

Kullanım: python -m pipeline.upload out/short.mp4 out/metadata.json
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"


def access_token():
    body = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=30) as resp:
        return json.load(resp)["access_token"]


def upload(video_path, meta):
    token = access_token()
    resource = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"][:5000],
            "tags": meta.get("tags", []),
            "categoryId": meta.get("category", "25"),  # 25: Haber ve Politika, 17: Spor
            "defaultLanguage": meta.get("language", "tr"),
            "defaultAudioLanguage": meta.get("language", "tr"),
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    if os.environ.get("YT_PUBLISH_AT"):
        # YouTube'un kendi zamanlayıcısı: video özel yüklenir, verilen anda (UTC, ISO 8601) herkese açılır.
        # GitHub zamanlaması saatlerce gecikebildiği için kesin saatli videolar (bayram tebriği) böyle yüklenir.
        resource["status"].update({"privacyStatus": "private", "publishAt": os.environ["YT_PUBLISH_AT"]})
        print(f"Yayın zamanı: {os.environ['YT_PUBLISH_AT']}")
    with open(video_path, "rb") as f:
        data = f.read()
    for attempt in range(RETRIES):  # oturum açılmadan düşen istek videoyu oluşturmaz; tekrarı güvenli
        init = urllib.request.Request(UPLOAD_URL, data=json.dumps(resource).encode(), method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(data)),
        })
        try:
            with urllib.request.urlopen(init, timeout=60) as resp:
                session_url = resp.headers["Location"]
            break
        except Exception as exc:
            if not _transient(exc) or attempt == RETRIES - 1:
                raise
            print(f"Yükleme oturumu açılamadı ({exc}); yeniden deneniyor")
            time.sleep(20 * (attempt + 1))
    return _send(session_url, token, data)["id"]


RETRIES = 4


def _transient(exc):
    """Sunucu ya da ağ kaynaklı geçici hata mı (kota ve izin hataları değil)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _send(session_url, token, data):
    """Videoyu aynı yükleme oturumuna gönderir. Bağlantı yarıda koparsa YouTube'a ne kadarının ulaştığı sorulur ve
    kalandan devam edilir; baştan yeni oturum açmak, ilk gönderim aslında tamamlandıysa videoyu ikinci kez çıkarırdı."""
    size, offset = len(data), 0
    for attempt in range(RETRIES):
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}
        if attempt:
            headers["Content-Range"] = f"bytes {offset}-{size - 1}/{size}"
        try:
            req = urllib.request.Request(session_url, data=data[offset:], method="PUT", headers=headers)
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.load(resp)
        except Exception as exc:
            if not _transient(exc) or attempt == RETRIES - 1:
                raise
            print(f"Video gönderimi yarıda kaldı ({exc}); YouTube'a ulaşan kısım soruluyor")
        time.sleep(20 * (attempt + 1))
        probe = urllib.request.Request(session_url, data=b"", method="PUT", headers={
            "Authorization": f"Bearer {token}", "Content-Range": f"bytes */{size}"})
        try:
            with urllib.request.urlopen(probe, timeout=60) as resp:
                return json.load(resp)  # gönderim aslında tamamlanmış
        except urllib.error.HTTPError as exc:
            if exc.code != 308:  # 308: eksik; Range başlığı ulaşan baytları söyler
                if not _transient(exc):
                    raise
                continue
            received = exc.headers.get("Range")  # "bytes=0-12345"
            offset = int(received.split("-")[1]) + 1 if received else 0
            print(f"YouTube'a {offset}/{size} bayt ulaşmış; kalandan devam ediliyor")
        except Exception as exc:
            if not _transient(exc):
                raise
    raise RuntimeError("Video gönderilemedi")


def check():
    """Sadece izni dener; video üretmeden secret'ların doğru olup olmadığını gösterir."""
    try:
        access_token()
    except urllib.error.HTTPError as exc:
        sys.exit(f"YouTube izni çalışmıyor (HTTP {exc.code}): {exc.read().decode('utf-8', 'replace')[:300]}")
    print("YouTube izni çalışıyor.")


def post_comment(video_id, text):
    """Videonun altına kanal adına ilk yorum: videodaki soru (yorum başlatır). Sabitleme API'de yok, Studio'dan yapılır.
    Anahtarda yorum izni (youtube.force-ssl) yoksa sessizce atlanır; yükleme başarılı sayılır."""
    body = json.dumps({"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}})
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
                                 data=body.encode(), method="POST", headers={
                                     "Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60):
            print(f"Yorum yazıldı: {text}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 403 and ("insufficient" in detail.lower() or "scope" in detail.lower()):
            print("Yorum atlandı: YouTube anahtarında yorum izni yok (get_refresh_token.py ile yeniden izin verilmeli)")
        else:
            print(f"Yorum yazılamadı (HTTP {exc.code}): {detail[:300]}")


API = "https://www.googleapis.com/youtube/v3"


def _call(method, url, token, body=None, data=None, content_type="application/json"):
    req = urllib.request.Request(url, method=method, data=data if data is not None else
                                 (json.dumps(body).encode() if body is not None else None),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def add_captions(token, video_id, text, lang="tr"):
    """Seslendirme metnini altyazı olarak ekler (pipeline/captions.py). Hata yüklemeyi bozmaz.
    Kota: 400 birim (video yüklemesinin yanında küçük)."""
    boundary = "faceless-shorts-captions"
    snippet = {"snippet": {"videoId": video_id, "language": lang, "name": "", "isDraft": False}}
    data = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(snippet)}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n{text}\r\n--{boundary}--\r\n").encode()
    try:
        _call("POST", "https://www.googleapis.com/upload/youtube/v3/captions?part=snippet&uploadType=multipart",
              token, data=data, content_type=f"multipart/related; boundary={boundary}")
        print(f"Altyazı eklendi ({text.count(chr(10) + chr(10))} satır)")
    except Exception as exc:
        detail = exc.read().decode("utf-8", "replace")[:300] if isinstance(exc, urllib.error.HTTPError) else exc
        print(f"Altyazı eklenemedi: {detail}")


def _playlist_id(token, title):
    """Kanalın bu adlı oynatma listesi; yoksa açılır (herkese açık, açıklamasıyla)."""
    page = ""
    while True:
        data = _call("GET", f"{API}/playlists?part=snippet&mine=true&maxResults=50&pageToken={page}", token)
        for item in data.get("items", []):
            if item["snippet"]["title"] == title:
                return item["id"]
        page = data.get("nextPageToken")
        if not page:
            break
    from .playlists import PLAYLISTS
    made = _call("POST", f"{API}/playlists?part=snippet,status", token, {
        "snippet": {"title": title, "description": PLAYLISTS.get(title, ""), "defaultLanguage": "tr"},
        "status": {"privacyStatus": "public"}})
    print(f"Oynatma listesi açıldı: {title}")
    return made["id"]


def add_to_playlist(token, video_id, title):
    """Videoyu türünün oynatma listesine ekler (pipeline/playlists.py). Hata yüklemeyi bozmaz."""
    try:
        playlist = _playlist_id(token, title)
        _call("POST", f"{API}/playlistItems?part=snippet", token, {"snippet": {
            "playlistId": playlist, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        print(f"Oynatma listesine eklendi: {title}")
    except Exception as exc:
        detail = exc.read().decode("utf-8", "replace")[:300] if isinstance(exc, urllib.error.HTTPError) else exc
        print(f"Oynatma listesine eklenemedi ({title}): {detail}")


def uploaded_before(meta):
    """Aynı çalışmanın aynı videosu panel kaydında YouTube bağlantısıyla duruyorsa o bağlantı.
    Yeniden yükleme çalışmanın kendi dosyasını güncelleyemediği için tekrar yüklemeyi bu kayıt önler."""
    run = os.environ.get("SOURCE_RUN_ID") or os.environ.get("GITHUB_RUN_ID")
    if not (run and os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return None
    from .report import find_link
    return find_link(run, meta.get("title"), "url")


def main():
    if sys.argv[1:] == ["--check"]:
        return check()
    video_path, meta_path = sys.argv[1], sys.argv[2]
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    if not meta.get("youtube_url"):
        meta["youtube_url"] = uploaded_before(meta)
    if meta.get("youtube_url"):  # yeniden yükleme denemesinde aynı video iki kez çıkmasın
        with open(meta_path, "w", encoding="utf-8") as f:  # bildirim bağlantıyı buradan okur
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"Zaten yüklenmiş: {meta['youtube_url']}")
        return
    try:
        video_id = upload(video_path, meta)
    except urllib.error.HTTPError as exc:
        # YouTube ret sebebini yanıtın gövdesinde söyler (kota, günlük yükleme sınırı, geçersiz alan...)
        body = exc.read().decode("utf-8", "replace")
        if "invalid_grant" in body:  # yükleme değil, Google izni reddedildi
            sys.exit("YouTube izni geçersiz: refresh token'ın süresi dolmuş ya da iptal edilmiş. "
                     "KURULUM.md'deki 2. ve 4. adımlarla yeni token alıp YT_REFRESH_TOKEN secret'ını güncelleyin. "
                     f"Google yanıtı: {body[:300]}")
        sys.exit(f"YouTube yüklemeyi reddetti (HTTP {exc.code}): {body[:800]}")
    # Bildirim ve yönetim paneli bağlantıyı buradan okur
    meta["youtube_url"] = f"https://youtu.be/{video_id}"
    if meta.get("comment"):
        post_comment(video_id, meta["comment"])
    # Zamanlanmış (özel) videoya da eklenir: yayın anında altyazısı ve listesi hazır olur
    if meta.get("captions") or meta.get("playlist"):
        token = access_token()
        if meta.get("captions"):
            add_captions(token, video_id, meta["captions"], meta.get("language", "tr"))
        if meta.get("playlist"):
            add_to_playlist(token, video_id, meta["playlist"])
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Yüklendi: {meta['youtube_url']}")


if __name__ == "__main__":
    main()
