"""
analyze_instagram_reel.py
Analyze any public Instagram reel by URL using yt-dlp.
Extracts metadata: views, likes, caption, duration, hashtags, hooks.

Usage: python tools/analyze_instagram_reel.py "https://www.instagram.com/reel/ABC123/"
Output: JSON with full reel analysis
"""

import json
import os
import re
import subprocess
import sys

import shutil as _s; YTDLP = _s.which("yt-dlp") or "yt-dlp"


def extract_hashtags(text: str) -> list:
    return re.findall(r"#(\w+)", text or "")


def extract_hook(caption: str) -> str:
    if not caption:
        return ""
    first_line = caption.strip().split("\n")[0]
    return first_line[:120]


def analyze_reel(url: str) -> dict:
    print(f"Fetching reel metadata: {url}", flush=True)

    result = subprocess.run(
        [YTDLP, "--dump-single-json", "--no-download", "--no-warnings", url],
        capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        error = result.stderr.strip()
        if "login" in error.lower() or "private" in error.lower():
            raise RuntimeError("Reel is private or requires login.")
        raise RuntimeError(f"yt-dlp failed: {error[-300:]}")

    if not result.stdout.strip():
        raise RuntimeError("yt-dlp returned empty output. Reel may be unavailable.")

    data = json.loads(result.stdout)

    caption   = data.get("description") or data.get("title") or ""
    duration  = data.get("duration") or 0
    views     = data.get("view_count") or 0
    likes     = data.get("like_count") or 0
    comments  = data.get("comment_count") or 0
    uploader  = data.get("uploader") or data.get("channel") or ""
    upload_ts = data.get("timestamp") or 0
    reel_id   = data.get("id") or ""

    hashtags  = extract_hashtags(caption)
    hook      = extract_hook(caption)
    words     = len(caption.split()) if caption else 0

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
        "caption_words":   words,
        "uploaded_ts":     upload_ts,
    }

    print(f"  [OK] @{uploader} | {duration}s | {views:,} views | {likes:,} likes | ER: {engagement_rate}%", flush=True)
    return analysis


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/analyze_instagram_reel.py "https://www.instagram.com/reel/ABC123/"')
        sys.exit(1)
    result = analyze_reel(sys.argv[1])
    print(json.dumps(result, indent=2))
