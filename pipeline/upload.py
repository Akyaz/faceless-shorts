"""Videoyu YouTube Data API ile kanala yükler.

Gerekli ortam değişkenleri: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
İsteğe bağlı: YT_PRIVACY (public | unlisted | private, varsayılan public)

Kullanım: python -m pipeline.upload out/short.mp4 out/metadata.json
"""
import json
import os
import sys
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
    size = os.path.getsize(video_path)
    init = urllib.request.Request(UPLOAD_URL, data=json.dumps(resource).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size),
    })
    with urllib.request.urlopen(init, timeout=60) as resp:
        session_url = resp.headers["Location"]

    with open(video_path, "rb") as f:
        put = urllib.request.Request(session_url, data=f.read(), method="PUT", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
    with urllib.request.urlopen(put, timeout=600) as resp:
        video = json.load(resp)
    return video["id"]


def main():
    video_path, meta_path = sys.argv[1], sys.argv[2]
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    try:
        video_id = upload(video_path, meta)
    except urllib.error.HTTPError as exc:
        # YouTube ret sebebini yanıtın gövdesinde söyler (kota, günlük yükleme sınırı, geçersiz alan...)
        sys.exit(f"YouTube yüklemeyi reddetti (HTTP {exc.code}): {exc.read().decode('utf-8', 'replace')[:800]}")
    # Bildirim ve yönetim paneli bağlantıyı buradan okur
    meta["youtube_url"] = f"https://youtu.be/{video_id}"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Yüklendi: {meta['youtube_url']}")


if __name__ == "__main__":
    main()
