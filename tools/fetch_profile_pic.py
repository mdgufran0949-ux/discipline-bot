"""
fetch_profile_pic.py
Downloads Instagram profile pictures and caches them locally.

- get_owner_pic(username)         → original creator's pic (scraped from Instagram)
- get_my_pic(ig_user_id, token, account_name) → your page's pic (via Graph API)

Cache location: .tmp/profile_pics/{username}.jpg
"""

import os
import requests

TMP_PICS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "profile_pics"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _download_image(url: str, dest_path: str) -> bool:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return os.path.getsize(dest_path) > 1000
    except Exception:
        return False


def get_owner_pic(username: str) -> str | None:
    """
    Download the original creator's Instagram profile picture.
    Returns local path if successful, None on failure.
    Caches to .tmp/profile_pics/{username}.jpg — only fetches once per username.
    """
    if not username:
        return None

    os.makedirs(TMP_PICS, exist_ok=True)
    cache_path = os.path.join(TMP_PICS, f"{username}.jpg")

    if os.path.exists(cache_path):
        return cache_path

    print(f"  [PROFILE] Fetching @{username} profile pic...", flush=True)

    try:
        url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        user = data.get("data", {}).get("user", {})
        pic_url = user.get("profile_pic_url_hd") or user.get("profile_pic_url")

        if pic_url and _download_image(pic_url, cache_path):
            print(f"  [PROFILE] Saved → {cache_path}", flush=True)
            return cache_path
    except Exception as e:
        print(f"  [PROFILE] Could not fetch @{username} profile pic: {e}", flush=True)

    return None


def get_my_pic(ig_user_id: str, access_token: str, account_name: str) -> str | None:
    """
    Download your own page's profile picture via the Instagram Graph API.
    Returns local path if successful, None on failure.
    Caches to .tmp/profile_pics/{account_name}.jpg.
    """
    if not ig_user_id or not access_token:
        return None

    os.makedirs(TMP_PICS, exist_ok=True)
    cache_path = os.path.join(TMP_PICS, f"{account_name}.jpg")

    if os.path.exists(cache_path):
        return cache_path

    print(f"  [PROFILE] Fetching {account_name} page profile pic...", flush=True)

    try:
        url = f"https://graph.facebook.com/v17.0/{ig_user_id}"
        resp = requests.get(url, params={
            "fields": "profile_picture_url",
            "access_token": access_token
        }, timeout=15)
        resp.raise_for_status()
        pic_url = resp.json().get("profile_picture_url")

        if pic_url and _download_image(pic_url, cache_path):
            print(f"  [PROFILE] Saved → {cache_path}", flush=True)
            return cache_path
    except Exception as e:
        print(f"  [PROFILE] Could not fetch {account_name} profile pic: {e}", flush=True)

    return None
