"""YouTube yükleme izni için bir kerelik refresh token alır. Kendi bilgisayarında çalıştır.

python3 scripts/get_refresh_token.py CLIENT_ID CLIENT_SECRET [--save]

Tarayıcı açılır, kanalın bağlı olduğu Google hesabıyla izin ver.
Çıkan refresh token'ı GitHub'da YT_REFRESH_TOKEN secret'ı olarak kaydet.
--save verilirse token ekrana yazılmaz; client id/secret ile birlikte doğrudan
gh CLI üzerinden GitHub secret'larına kaydedilir (kopyalama hatası olmaz).
"""
import http.server
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

# upload: video yükleme; force-ssl: videonun altına kanal adına ilk yorumu (videodaki soru) yazma
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl"
PORT = 8765
REPO = "Akyaz/faceless-shorts"


def main():
    client_id, client_secret = sys.argv[1], sys.argv[2]
    redirect = f"http://127.0.0.1:{PORT}"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
    })
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result["code"] = query.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Tamam, bu pencereyi kapatabilirsin.".encode())

        def log_message(self, *args):
            pass

    print("Tarayıcıda izin sayfası açılıyor. Açılmazsa bu adresi kopyala:\n" + auth_url)
    webbrowser.open(auth_url)
    with http.server.HTTPServer(("127.0.0.1", PORT), Handler) as server:
        server.handle_request()
    if not result.get("code"):
        sys.exit("İzin verilmedi.")

    body = urllib.parse.urlencode({
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body) as resp:
        tokens = json.load(resp)
    if "--save" not in sys.argv:
        print("\nYT_REFRESH_TOKEN:\n" + tokens["refresh_token"])
        return
    # Üçü aynı istemciden gelmeli; biri eskiyse Google invalid_grant döner
    for name, value in [("YT_CLIENT_ID", client_id), ("YT_CLIENT_SECRET", client_secret),
                        ("YT_REFRESH_TOKEN", tokens["refresh_token"])]:
        subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value.encode(), check=True)
    print("Secret'lar GitHub'a kaydedildi.")


if __name__ == "__main__":
    main()
