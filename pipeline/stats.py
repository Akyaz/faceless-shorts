"""Kanal istatistikleri: her videonun izlenme, beğeni, yorum sayısı ve açıklaması (YouTube Data API).

Anahtarda YouTube Analytics izni (yt-analytics.readonly) varsa paylaşım, izlenme yüzdesi ve kazanılan abone de
alınır; yoksa bu kısım atlanır (scripts/get_refresh_token.py ile yeniden izin verilince gelir).
Video türü panel kaydından (panel-data dalı, feed.json) eşlenir.

Kullanım: python -m pipeline.stats out/stats.json
"""
import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from .upload import access_token

API = "https://www.googleapis.com/youtube/v3"


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def videos(token):
    channel = _get(f"{API}/channels?part=contentDetails,statistics&mine=true", token)["items"][0]
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], ""
    while True:
        data = _get(f"{API}/playlistItems?part=contentDetails&maxResults=50&playlistId={uploads}&pageToken={page}", token)
        ids += [i["contentDetails"]["videoId"] for i in data["items"]]
        page = data.get("nextPageToken")
        if not page:
            break
    out = []
    for i in range(0, len(ids), 50):
        data = _get(f"{API}/videos?part=snippet,statistics,contentDetails&id={','.join(ids[i:i + 50])}", token)
        for v in data["items"]:
            s = v["statistics"]
            out.append({"id": v["id"], "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                        "description": v["snippet"]["description"], "duration": v["contentDetails"]["duration"],
                        "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                        "comments": int(s.get("commentCount", 0))})
    return channel["statistics"], out


def analytics(token, start):
    """Video başına paylaşım, ortalama izlenme yüzdesi, abone; izin yoksa None."""
    q = urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": start, "endDate": datetime.date.today().isoformat(),
        "dimensions": "video", "maxResults": 200, "sort": "-views",
        "metrics": "views,shares,likes,comments,averageViewDuration,averageViewPercentage,subscribersGained,engagedViews"})
    try:
        data = _get(f"https://youtubeanalytics.googleapis.com/v2/reports?{q}", token)
    except urllib.error.HTTPError as exc:
        print(f"Analytics alınamadı (HTTP {exc.code}): {exc.read().decode('utf-8', 'replace')[:300]}")
        return None
    names = [h["name"] for h in data["columnHeaders"]]
    return {row[0]: dict(zip(names[1:], row[1:])) for row in data.get("rows", [])}


def modes():
    """Video kimliği → panel kaydındaki tür ve saat."""
    from .report import BRANCH, FEED, _github
    try:
        feed = json.loads(base64.b64decode(_github(
            "GET", f"/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{FEED}?ref={BRANCH}")["content"]))
    except Exception as exc:
        print(f"Panel kaydı okunamadı: {exc}")
        return {}
    out = {}
    for entry in feed:
        for v in entry.get("videos", []):
            if v.get("url"):
                out[v["url"].rstrip("/").split("/")[-1]] = {"mode": entry.get("mode"), "slot": entry.get("slot")}
    return out


def main():
    token = access_token()
    channel, items = videos(token)
    found = modes()
    start = min((v["published"][:10] for v in items), default=datetime.date.today().isoformat())
    extra = analytics(token, start) or {}
    for v in items:
        v.update(found.get(v["id"], {}))
        v["analytics"] = extra.get(v["id"])
    os.makedirs(os.path.dirname(sys.argv[1]) or ".", exist_ok=True)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump({"channel": channel, "analytics": bool(extra), "videos": items}, f, ensure_ascii=False, indent=1)
    print(f"{len(items)} video; abone {channel.get('subscriberCount')}; analytics {'var' if extra else 'yok'}")


if __name__ == "__main__":
    main()
