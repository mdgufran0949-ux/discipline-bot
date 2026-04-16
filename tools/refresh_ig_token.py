"""
refresh_ig_token.py
Auto-refresh Instagram long-lived access token before it expires.

Instagram long-lived tokens are valid for 60 days and can be refreshed
any time while they're still valid. This script:
  1. Reads the current token from config/accounts/{account}.json
  2. Calls GET /refresh_access_token (no app secret needed — token only)
  3. Writes the new token + timestamp back to the config
  4. Prints a warning if the token looks close to expiry

Run weekly via GitHub Actions to keep the token perpetually fresh.

Usage:
  python tools/refresh_ig_token.py --account disciplinefuel
  python tools/refresh_ig_token.py --account disciplinefuel --check-only
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.facebook.com/v19.0"
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TOKEN_LIFETIME_DAYS = 60
REFRESH_WARN_DAYS   = 10   # warn if less than 10 days until expiry


def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(account: str, cfg: dict) -> None:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def _days_until_expiry(refreshed_at_iso: str | None) -> int | None:
    """Return days remaining before the 60-day token window closes, or None if unknown."""
    if not refreshed_at_iso:
        return None
    try:
        refreshed_at = datetime.fromisoformat(refreshed_at_iso)
        expiry       = refreshed_at + timedelta(days=TOKEN_LIFETIME_DAYS)
        return max(0, (expiry - datetime.now()).days)
    except Exception:
        return None


def refresh_token(account: str, check_only: bool = False) -> dict:
    """
    Refresh the Instagram long-lived token for the given account.
    Returns {"status": "refreshed|skipped|error", "days_remaining": N, "message": "..."}
    """
    cfg = _load_config(account)
    current_token = cfg.get("ig_access_token", "")

    if not current_token:
        print(f"[ERROR] No ig_access_token in {account}.json", flush=True)
        return {"status": "error", "message": "no token in config"}

    refreshed_at = cfg.get("token_refreshed_at")
    days_left    = _days_until_expiry(refreshed_at)

    if days_left is not None:
        print(f"[INFO] Token last refreshed: {refreshed_at}", flush=True)
        print(f"[INFO] Days until expiry:    {days_left}", flush=True)
        if days_left <= 0:
            print("[WARN] Token may already be EXPIRED.", flush=True)
        elif days_left <= REFRESH_WARN_DAYS:
            print(f"[WARN] Token expires in {days_left} days — refreshing now.", flush=True)
    else:
        print("[INFO] No token_refreshed_at recorded — treating as first refresh.", flush=True)

    if check_only:
        print("[INFO] --check-only mode, skipping actual refresh.", flush=True)
        return {"status": "skipped", "days_remaining": days_left, "message": "check-only"}

    # ── Refresh call ──────────────────────────────────────────────────────────
    print("Refreshing Instagram long-lived token...", flush=True)
    resp = requests.get(
        f"{GRAPH_BASE}/refresh_access_token",
        params={
            "grant_type":   "ig_refresh_token",
            "access_token": current_token
        },
        timeout=20
    )

    data = resp.json()

    if not resp.ok or "error" in data:
        err = data.get("error", data)
        code = err.get("code", "") if isinstance(err, dict) else ""
        msg  = err.get("message", str(err)) if isinstance(err, dict) else str(err)

        if code == 190:
            print(f"[ERROR] Token is expired (code 190). You must generate a new long-lived token manually.", flush=True)
            print("[ERROR] 1. Go to: https://developers.facebook.com/tools/explorer/", flush=True)
            print("[ERROR] 2. Generate a new user token with instagram_basic + instagram_content_publish permissions", flush=True)
            print("[ERROR] 3. Exchange for long-lived token, update ig_access_token in config", flush=True)
        else:
            print(f"[ERROR] Refresh failed: {msg}", flush=True)
        return {"status": "error", "message": msg}

    new_token    = data.get("access_token", "")
    expires_in   = data.get("expires_in", TOKEN_LIFETIME_DAYS * 86400)
    new_days     = expires_in // 86400

    if not new_token:
        print("[ERROR] API returned no access_token in response.", flush=True)
        return {"status": "error", "message": "empty token in response"}

    # ── Write back ────────────────────────────────────────────────────────────
    cfg["ig_access_token"]   = new_token
    cfg["token_refreshed_at"] = datetime.now().isoformat()
    _save_config(account, cfg)

    print(f"[OK] Token refreshed. New expiry: ~{new_days} days from now.", flush=True)
    return {
        "status":        "refreshed",
        "days_remaining": new_days,
        "refreshed_at":   cfg["token_refreshed_at"],
        "message":        "success"
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Instagram long-lived access token")
    parser.add_argument("--account",    default="disciplinefuel")
    parser.add_argument("--check-only", action="store_true",
                        help="Only check expiry status, do not refresh")
    args = parser.parse_args()

    result = refresh_token(args.account, check_only=args.check_only)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("refreshed", "skipped") else 1)
