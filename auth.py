#!/usr/bin/env python3
"""One-time authorization. Run this on your own machine, signed in (in the browser
it opens) as the bot's Google account.

    pip3 install requests
    python3 auth.py path/to/client_secret_....json

It prints the three values to put in the GitHub repo's Actions secrets:
YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN. It also writes them to ./.env
(gitignored) so `python3 sync.py` works locally too.
"""
import http.server
import json
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

SCOPE = "https://www.googleapis.com/auth/youtube"
PORT = 8765


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 auth.py client_secret.json")
    cfg = json.loads(Path(sys.argv[1]).read_text())
    cfg = cfg.get("installed") or cfg.get("web") or cfg
    client_id, client_secret = cfg["client_id"], cfg["client_secret"]
    redirect = f"http://localhost:{PORT}/"

    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", PORT), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("Opening browser. Pick the BOT account when Google asks.\n", url, "\n")
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        threading.Event().wait(0.2)
    if "error" in got:
        sys.exit(f"auth failed: {got['error']}")

    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": got["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    r.raise_for_status()
    tok = r.json()
    if "refresh_token" not in tok:
        sys.exit("No refresh token returned. Revoke the app at myaccount.google.com/permissions and rerun.")

    env = (
        f"YT_CLIENT_ID={client_id}\n"
        f"YT_CLIENT_SECRET={client_secret}\n"
        f"YT_REFRESH_TOKEN={tok['refresh_token']}\n"
    )
    Path(".env").write_text(env)
    print("Saved to .env. Add these three as repository secrets in GitHub:\n")
    print(env)


if __name__ == "__main__":
    main()
