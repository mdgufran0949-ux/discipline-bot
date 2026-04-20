"""
analyze_instagram_reel.py
Analyze any public Instagram reel by URL.
Uses yt-dlp with cookies if available, falls back to Instagram oEmbed API.

Cookies file (optional, enables views/likes): .tmp/instagram_cookies.txt
To get cookies: in Chrome go to instagram.com, open DevTools → Application →
Cookies, or use "Get cookies.txt LOCALLY" extension, save to .tmp/instagram_cookies.txt

Usage: python tools/analyze_instagram_reel.py "https://www.instagram.com/reel/ABC123/"
Output: JSON with reel analysis
"""

import json
import os
import re
import subprocess
import sys

import requests
import shutil as _s

YTDLP        = _s.which("yt-dlp") or "yt-dlp"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_FILE = os.path.join(PROJECT_ROOT, ".tmp", "instagram_cookies.txt")


def extract_hashtags(text: str) -> list:
    return re.findall(r"#(\w+)", text or "")


def extract_hook(caption: str) -> str:
    if not caption:
        return ""
    return caption.strip().split("\n")[0][:120]


def _ytdlp_fetch(url: str) -> dict:
    cmd = [YTDLP, "--dump-single-json", "--no-download", "--no-warnings"]
    if os.path.exists(COOKIES_FILE):
        cmd += ["--cookies", COOKIES_FILE]
        print("  [cookies] Using instagram_cookies.txt", flush=True)
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-300:])
    if not result.stdout.strip():
        raise RuntimeError("yt-dlp returned empty output")
    return json.loads(result.stdout)


def _oembed_fetch(url: str) -> dict:
    """Fallback: Instagram oEmbed — gives caption + author, no stats."""
    print("  [fallback] Using oEmbed (no cookies → views/likes unavailable)", flush=True)
    resp = requests.get(
        "https://api.instagram.com/oembed/",
        params={"url": url, "hidecaption": 0},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "id":           url.rstrip("/").split("/")[-1],
        "description":  data.get("title", ""),
        "uploader":     data.get("author_name", ""),
        "view_count":   None,
        "like_count":   None,
        "comment_count": None,
        "duration":     None,
        "timestamp":    None,
        "_source":      "oembed",
    }


def analyze_reel(url: str) -> dict:
    print(f"Fetching reel metadata: {url}", flush=True)

    source = "yt-dlp"
    try:
        data = _ytdlp_fetch(url)
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ["login", "cookie", "private", "sign in"]):
            print(f"  [WARN] yt-dlp needs login → falling back to oEmbed", flush=True)
            data   = _oembed_fetch(url)
            source = "oembed"
        else:
            raise RuntimeError(f"yt-dlp failed: {e}")

    caption  = data.get("description") or data.get("title") or ""
    duration = data.get("duration")
    views    = data.get("view_count")
    likes    = data.get("like_count")
    comments = data.get("comment_count")
    uploader = data.get("uploader") or data.get("channel") or ""
    reel_id  = data.get("id") or ""

    hashtags = extract_hashtags(caption)
    hook     = extract_hook(caption)

    engagement_rate = None
    if views and likes is not None and comments is not None:
        engagement_rate = round((likes + comments) / views * 100, 2) if views > 0 else 0

    analysis = {
        "reel_id":         reel_id,
        "url":             url,
        "uploader":        uploader,
        "duration_sec":    duration,
        "views":           views,
        "likes":           likes,
        "comments":        comments,
        "engagement_rate": engagement_rate,
        "caption":         caption,
        "hook":            hook,
        "hashtags":        hashtags,
        "hashtag_count":   len(hashtags),
        "caption_words":   len(caption.split()) if caption else 0,
        "uploaded_ts":     data.get("timestamp"),
        "_source":         source,
    }

    stats = f"{views:,} views" if views else "views unavailable"
    print(f"  [OK] @{uploader} | {duration}s | {stats} | source: {source}", flush=True)

    if source == "oembed":
        print(
            "\n  [NOTE] To get views/likes, add cookies:\n"
            "  1. Chrome → instagram.com → install 'Get cookies.txt LOCALLY' extension\n"
            "  2. Export cookies → save as shorts/.tmp/instagram_cookies.txt\n"
            "  3. Re-run this script",
            flush=True
        )

    return analysis


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/analyze_instagram_reel.py "https://www.instagram.com/reel/ABC123/"')
        sys.exit(1)
    result = analyze_reel(sys.argv[1])
    print(json.dumps(result, indent=2))
