"""Dikey videoyu Instagram'a Reels olarak yükler (Instagram Graph API, dosyadan doğrudan yükleme).

Gerekli ortam değişkeni: IG_ACCESS_TOKEN (instagram_business_content_publish ya da instagram_content_publish izinli)
İsteğe bağlı: IG_USER_ID (yoksa anahtardan bulunur), IG_GRAPH_HOST (Facebook ile giriş yapılmış anahtar için
graph.facebook.com; varsayılan graph.instagram.com)

Kullanım: python -m pipeline.instagram out/short.mp4 out/metadata.json
"""
import json
import os
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
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).replace("#shorts", "#reels")
    tags = [w for w in text.split() if w.startswith("#")]
    for extra in tags[HASHTAG_LIMIT:]:
        text = text.replace(" " + extra, "")
    if len(text) > CAPTION_LIMIT:
        body, _, hashtags = text.rpartition("\n")
        text = body[:CAPTION_LIMIT - len(hashtags) - 2].rstrip() + "…\n" + hashtags
    return text[:CAPTION_LIMIT]


def upload(video_path, meta):
    user = _user_id()
    container = _post(f"{user}/media", {"media_type": "REELS", "upload_type": "resumable",
                                        "caption": caption(meta), "share_to_feed": "true"})
    _send_file(container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{VERSION}/{container['id']}",
               video_path)
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
    if meta.get("instagram_url"):  # aynı video iki kez paylaşılmasın
        print(f"Instagram'da zaten var: {meta['instagram_url']}")
        return
    try:
        url = upload(video_path, meta)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if "OAuthException" in body and ("expired" in body.lower() or "session" in body.lower()):
            sys.exit("Instagram anahtarının süresi dolmuş; yeni anahtar alıp IG_ACCESS_TOKEN secret'ını güncelleyin. "
                     f"Instagram yanıtı: {body[:300]}")
        sys.exit(f"Instagram yüklemeyi reddetti (HTTP {exc.code}): {body[:800]}")
    meta["instagram_url"] = url
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Instagram'a yüklendi: {url}")


if __name__ == "__main__":
    main()
