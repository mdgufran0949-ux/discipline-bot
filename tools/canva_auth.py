"""
canva_auth.py
Handles OAuth 2.0 authentication with the Canva Connect API.
Stores access token + refresh token in .tmp/disciplinefuel/canva_token.json.
On first run: opens browser for user login, captures token via local callback server.
On subsequent runs: auto-refreshes token silently.

Usage: python tools/canva_auth.py
Requires: CANVA_CLIENT_ID, CANVA_CLIENT_SECRET in .env
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("CANVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("CANVA_CLIENT_SECRET")

REDIRECT_URI   = "http://127.0.0.1:8000/callback"
AUTH_URL       = "https://www.canva.com/api/oauth/authorize"
TOKEN_URL      = "https://api.canva.com/rest/v1/oauth/token"
SCOPES         = "asset:read asset:write design:content:read design:content:write design:meta:read brandtemplate:meta:read brandtemplate:content:read"

TOKEN_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "canva_token.json")
)

# ── Token storage ──────────────────────────────────────────────────────────────

def _save_token(data: dict) -> None:
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    data["saved_at"] = time.time()
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, TOKEN_PATH)


def _load_token() -> dict | None:
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_expired(token_data: dict) -> bool:
    saved_at   = token_data.get("saved_at", 0)
    expires_in = token_data.get("expires_in", 3600)
    return (time.time() - saved_at) >= (expires_in - 60)   # 60s buffer


# ── PKCE helpers ───────────────────────────────────────────────────────────────

def _pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge)."""
    verifier  = secrets.token_urlsafe(64)
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ── OAuth flow ─────────────────────────────────────────────────────────────────

_captured_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _captured_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
                <h2 style='color:#6c47ff'>Canva auth successful!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing auth code.")

    def log_message(self, *_):
        pass   # suppress server logs


def _fetch_token_via_browser() -> dict:
    """Full browser OAuth flow with PKCE. Returns raw token response dict."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "client_id":             CLIENT_ID,
        "response_type":         "code",
        "redirect_uri":          REDIRECT_URI,
        "scope":                 SCOPES,
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print("Opening browser for Canva login...")
    webbrowser.open(auth_url)

    # Start local callback server
    server = HTTPServer(("127.0.0.1", 8000), _CallbackHandler)
    server.timeout = 120
    print("Waiting for Canva callback (timeout: 120s)...")
    while _captured_code is None:
        server.handle_request()
    server.server_close()

    code = _captured_code
    print("Auth code captured. Exchanging for token...")

    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "code_verifier": verifier,
    }, auth=(CLIENT_ID, CLIENT_SECRET), timeout=30)

    resp.raise_for_status()
    return resp.json()


def _refresh_token(refresh_tok: str) -> dict:
    """Exchange refresh token for a new access token."""
    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_tok,
    }, auth=(CLIENT_ID, CLIENT_SECRET), timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Public API ─────────────────────────────────────────────────────────────────

def get_access_token() -> str:
    """
    Returns a valid Canva access token.
    - First run: full browser OAuth flow.
    - Subsequent runs: refreshes automatically if expired.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("CANVA_CLIENT_ID and CANVA_CLIENT_SECRET must be set in .env")

    token_data = _load_token()

    if token_data is None:
        print("No Canva token found. Starting first-time OAuth flow...")
        token_data = _fetch_token_via_browser()
        _save_token(token_data)
        print("Canva token saved.")
    elif _is_expired(token_data):
        print("Canva token expired. Refreshing...")
        refresh_tok = token_data.get("refresh_token")
        if not refresh_tok:
            print("No refresh token. Re-running full OAuth flow...")
            token_data = _fetch_token_via_browser()
        else:
            try:
                new_data = _refresh_token(refresh_tok)
                # preserve refresh_token if not returned in new response
                if "refresh_token" not in new_data:
                    new_data["refresh_token"] = refresh_tok
                token_data = new_data
            except Exception as e:
                print(f"Refresh failed ({e}). Re-running full OAuth flow...")
                token_data = _fetch_token_via_browser()
        _save_token(token_data)
        print("Canva token refreshed.")

    return token_data["access_token"]


def get_auth_headers() -> dict:
    """Returns Authorization headers for Canva Connect API calls."""
    return {"Authorization": f"Bearer {get_access_token()}"}


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        token = get_access_token()
        print(json.dumps({"status": "ok", "token_preview": token[:12] + "..."}, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(1)
