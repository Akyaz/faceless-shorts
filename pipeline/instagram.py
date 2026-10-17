"""Dikey videoyu Instagram'a Reels olarak yükler (Instagram Graph API, dosyadan doğrudan yükleme).

Gerekli ortam değişkeni: IG_ACCESS_TOKEN (instagram_business_content_publish ya da instagram_content_publish izinli)
İsteğe bağlı: IG_USER_ID (yoksa anahtardan bulunur), IG_GRAPH_HOST (Facebook ile giriş yapılmış anahtar için
graph.facebook.com; varsayılan graph.instagram.com)

Kullanım: python -m pipeline.instagram out/short.mp4 out/metadata.json
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = os.environ.get("IG_API_VERSION") or "v23.0"
CAPTION_LIMIT = 2200  # Instagram açıklama sınırı
HASHTAG_LIMIT = 30


def _host():
    """Instagram ile giriş anahtarı (IGAA...) graph.instagram.com'a, Facebook anahtarı (EAA...) graph.facebook.com'a
    gider; yanlış adres "Cannot parse access token" hatası verir."""
    token = os.environ["IG_ACCESS_TOKEN"]
    if token.startswith("IG"):
        return "graph.instagram.com"
    if token.startswith("EA"):
        return "graph.facebook.com"
    return os.environ.get("IG_GRAPH_HOST") or "graph.instagram.com"


def _request(req):
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.load(resp)


def _get(path, params=None):
    query = urllib.parse.urlencode({**(params or {}), "access_token": os.environ["IG_ACCESS_TOKEN"]})
    return _request(urllib.request.Request(f"https://{_host()}/{VERSION}/{path}?{query}"))


def _post(path, params):
    body = urllib.parse.urlencode({**params, "access_token": os.environ["IG_ACCESS_TOKEN"]}).encode()
    return _request(urllib.request.Request(f"https://{_host()}/{VERSION}/{path}", data=body, method="POST"))


def _send_file(url, video_path):
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        data = f.read()
    return _request(urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"OAuth {os.environ['IG_ACCESS_TOKEN']}", "offset": "0", "file_size": str(size)}))


def _user_id():
    """Instagram ile giriş anahtarında hesap kimliği anahtardan okunur (IG_USER_ID yanlış girilse de çalışsın);
    Facebook anahtarında Instagram işletme hesabının kimliği IG_USER_ID'den gelir."""
    if _host() == "graph.instagram.com" or not os.environ.get("IG_USER_ID"):
        me = _get("me", {"fields": "user_id,username"})
        print(f"Instagram hesabı: @{me.get('username')}")
        return me.get("user_id") or me["id"]
    return os.environ["IG_USER_ID"]


def caption(meta):
    """YouTube açıklamasından Reels açıklaması: başlık, videoda söylenenler, kaynaklar ve etiketler."""
    text = meta["description"]
    # YouTube'a özel satırlar çıkar; #shorts yerine #reels
    lines = [line for line in text.splitlines() if "abone ol" not in line.lower() and "subscribe" not in line.lower()]
    # YouTube açıklamasındaki kanal satırı zaten başlığın altında; eski videolarda yoksa eklenir
    if not any("youtube.com/@QuickRecapChannel" in line for line in lines):
        lines.insert(1, "\nYouTube: https://www.youtube.com/@QuickRecapChannel")
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).replace("#shorts", "#reels #quickrecapchannel")
    tags = [w for w in text.split() if w.startswith("#")]
    for extra in tags[HASHTAG_LIMIT:]:
        text = text.replace(" " + extra, "")
    if len(text) > CAPTION_LIMIT:
        body, _, hashtags = text.rpartition("\n")
        text = body[:CAPTION_LIMIT - len(hashtags) - 2].rstrip() + "…\n" + hashtags
    return text[:CAPTION_LIMIT]


# Instagram ile giriş anahtarında Instagram videoyu kendisi indirir: dosya, herkese açık panel deposunda geçici
# bir sürüm dosyası olarak durur ve video işlendikten sonra silinir.
MEDIA_REPO = os.environ.get("MEDIA_REPO") or "Akyaz/faceless-shorts-panel"
MEDIA_TAG = "instagram-temp"


def _github(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {os.environ['MEDIA_TOKEN']}", "Accept": "application/vnd.github+json",
        **(headers or {})})
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def _host_video(video_path):
    """(herkese açık adres, silme işlevi) döner."""
    api = f"https://api.github.com/repos/{MEDIA_REPO}/releases"
    try:
        release = _github("GET", f"{api}/tags/{MEDIA_TAG}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = _github("POST", api, json.dumps({
            "tag_name": MEDIA_TAG, "name": "Instagram geçici dosyaları", "prerelease": True,
            "body": "Reels yüklenirken videolar burada birkaç dakika durur ve sonra silinir."}).encode(),
            {"Content-Type": "application/json"})
    name = f"reel-{int(time.time())}.mp4"
    with open(video_path, "rb") as f:
        asset = _github("POST", f"https://uploads.github.com/repos/{MEDIA_REPO}/releases/{release['id']}/assets"
                                f"?name={name}", f.read(), {"Content-Type": "video/mp4"})

    def remove():
        try:
            _github("DELETE", f"{api}/assets/{asset['id']}")
        except urllib.error.HTTPError as exc:
            print(f"Geçici video silinemedi ({exc.code}); {name} elle silinmeli")
    return asset["browser_download_url"], remove


def _create_container(user, video_path, meta):
    """Yayın kabı ve (varsa) geçici dosyayı silme işlevi."""
    params = {"media_type": "REELS", "caption": caption(meta), "share_to_feed": "true"}
    if _host() == "graph.instagram.com":
        if not os.environ.get("MEDIA_TOKEN"):
            raise RuntimeError("Instagram ile giriş anahtarında video herkese açık bir adresten verilmeli; "
                               "MEDIA_TOKEN secret'ı (panel deposuna yazma izni olan GitHub anahtarı) gerekli.")
        try:
            url, remove = _host_video(video_path)
        except urllib.error.HTTPError as exc:
            needed = exc.headers.get("X-Accepted-GitHub-Permissions", "?")
            try:  # anahtarın bu depodaki izinleri (secret'a doğru anahtar mı kaydedilmiş?)
                perms = _github("GET", f"https://api.github.com/repos/{MEDIA_REPO}").get("permissions")
            except urllib.error.HTTPError as inner:
                perms = f"depo okunamadı (HTTP {inner.code})"
            raise RuntimeError(f"Geçici video panel deposuna konamadı (GitHub HTTP {exc.code}): "
                               f"{exc.read().decode('utf-8', 'replace')[:160]}. GitHub'ın beklediği izin: {needed}; "
                               f"anahtarın {MEDIA_REPO} izinleri: {perms}. MEDIA_TOKEN'ın bu depoda "
                               f"Contents: Read and write izni olmalı.")
        try:
            return _post(f"{user}/media", {**params, "video_url": url}), remove
        except Exception:
            remove()
            raise
    container = _post(f"{user}/media", {**params, "upload_type": "resumable"})
    _send_file(container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{VERSION}/{container['id']}",
               video_path)
    return container, lambda: None


def upload(video_path, meta):
    user = _user_id()
    container, remove = _create_container(user, video_path, meta)
    try:
        # Instagram videoyu işledikten sonra yayınlanabilir
        for _ in range(60):
            status = _get(container["id"], {"fields": "status_code,status"})
            if status.get("status_code") == "FINISHED":
                break
            if status.get("status_code") in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram videoyu işleyemedi: {status}")
            time.sleep(10)
        else:
            raise RuntimeError("Instagram videoyu 10 dakikada işlemedi")
    finally:
        remove()
    media = _post(f"{user}/media_publish", {"creation_id": container["id"]})
    link = _get(media["id"], {"fields": "permalink"})
    return link.get("permalink") or media["id"]


def main():
    if not os.environ.get("IG_ACCESS_TOKEN"):
        print("IG_ACCESS_TOKEN yok; Instagram atlanıyor.")
        return
    token = os.environ["IG_ACCESS_TOKEN"].strip()
    os.environ["IG_ACCESS_TOKEN"] = token  # kopyalarken gelen boşluk ve satır sonu anahtarı bozar
    # Teşhis için yalnızca anahtarın türünü gösteren ilk karakterler yazılır
    print(f"Instagram anahtarı: {token[:4]}… ({len(token)} karakter), adres: {_host()}")
    video_path, meta_path = sys.argv[1], sys.argv[2]
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    run = os.environ.get("SOURCE_RUN_ID") or os.environ.get("GITHUB_RUN_ID")
    can_record = bool(run and os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"))
    if not meta.get("instagram_url") and can_record:  # elle tekrar tetiklenince de kayda bakılır
        from .report import find_link
        meta["instagram_url"] = find_link(run, meta.get("title"), "instagram")
    if meta.get("instagram_url"):  # aynı video iki kez paylaşılmasın
        print(f"Instagram'da zaten var: {meta['instagram_url']}")
        return
    try:
        # Instagram kopyasında YouTube kanalının adresi videonun altında görünür (açıklamadaki bağlantı tıklanmıyor)
        from . import render
        linked = str(Path(video_path).with_suffix(".instagram.mp4"))
        render.add_link(video_path, linked)
        url = upload(linked, meta)
    except RuntimeError as exc:
        sys.exit(str(exc))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if "OAuthException" in body and ("expired" in body.lower() or "session" in body.lower()):
            sys.exit("Instagram anahtarının süresi dolmuş; yeni anahtar alıp IG_ACCESS_TOKEN secret'ını güncelleyin. "
                     f"Instagram yanıtı: {body[:300]}")
        sys.exit(f"Instagram yüklemeyi reddetti (HTTP {exc.code}): {body[:800]}")
    meta["instagram_url"] = url
    if can_record and os.environ.get("SOURCE_RUN_ID"):  # elle yüklemede kayıt bu çalışmanın raporuyla yazılmaz
        from .report import add_link
        try:
            add_link(run, meta.get("title"), "instagram", url)
        except Exception as exc:  # kayıt yazılamasa da paylaşım yapıldı
            print(f"Instagram bağlantısı panel kaydına yazılamadı: {exc}")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Instagram'a yüklendi: {url}")


if __name__ == "__main__":
    main()
