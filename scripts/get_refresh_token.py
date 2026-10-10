"""YouTube yükleme izni için bir kerelik refresh token alır. Kendi bilgisayarında çalıştır.

python3 scripts/get_refresh_token.py CLIENT_ID CLIENT_SECRET

Tarayıcı açılır, kanalın bağlı olduğu Google hesabıyla izin ver.
Çıkan refresh token'ı GitHub'da YT_REFRESH_TOKEN secret'ı olarak kaydet.
"""
import http.server
import json
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PORT = 8765


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
    print("\nYT_REFRESH_TOKEN:\n" + tokens["refresh_token"])


if __name__ == "__main__":
    main()
