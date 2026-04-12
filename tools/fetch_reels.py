"""
fetch_reels.py
Fetches trending viral Shorts from YouTube hashtag pages via yt-dlp.
No API key required. Returns actual view counts for quality filtering.

Usage: python tools/fetch_reels.py "techfacts,amazingfacts" [count]
Output: JSON with list of Reels (id, post_url, view_count, owner_username, caption)
"""

import json
import os
import sys
import subprocess
import time

from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0  # deterministic language detection

import shutil as _s; YTDLP = _s.which("yt-dlp") or "yt-dlp"C:\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"
MAX_DURATION = 90   # seconds — skip anything longer than 90s


def _is_english(text: str) -> bool:
    """Return True if text is detected as English. Short titles → allow (benefit of doubt)."""
    if not text or len(text.split()) < 3:
        return True
    try:
        return detect(text) == "en"
    except LangDetectException:
        return True


def _fetch_hashtag(tag: str, limit: int = 50) -> list:
    """Fetch top Shorts from a YouTube hashtag page. Returns list of entry dicts."""
    url = f"https://www.youtube.com/hashtag/{tag}"
    result = subprocess.run(
        [YTDLP, url,
         "--flat-playlist",
         "--dump-single-json",
         "--playlist-items", f"1-{limit}",
         "--no-download",
         "--quiet",
         "--no-warnings"],
        capture_output=True, timeout=90
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"  [WARN] #{tag}: {result.stderr[:120].strip()}", flush=True)
        return []
    try:
        data = json.loads(result.stdout)
        return [e for e in data.get("entries", []) if e]
    except Exception as e:
        print(f"  [WARN] #{tag}: JSON parse error — {e}", flush=True)
        return []


def fetch_reels(hashtags, count: int = 10, **kwargs) -> dict:
    """
    Fetch trending viral Shorts across YouTube hashtags.

    Parameters
    ----------
    hashtags : str or list of str  — YouTube hashtag names (without #)
    count    : max reels to return
    **kwargs : ignored (accepts ig_user_id / ig_access_token for API compat)
    """
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    hashtags = [h.lstrip("#").strip() for h in hashtags if h.strip()]

    print(f"  Scanning {len(hashtags)} YouTube hashtag(s) for viral Shorts...", flush=True)

    all_reels = []
    seen_ids  = set()

    for tag in hashtags:
        print(f"  [#{tag}] Fetching...", flush=True)
        entries = _fetch_hashtag(tag, limit=50)
        time.sleep(2)   # avoid YouTube rate-limiting

        for e in entries:
            vid_id   = e.get("id") or ""
            duration = e.get("duration") or 0
            if not vid_id or vid_id in seen_ids:
                continue
            if duration > MAX_DURATION:
                continue   # skip long videos — want Shorts only

            seen_ids.add(vid_id)
            yt_url    = f"https://www.youtube.com/shorts/{vid_id}"
            title     = (e.get("title") or "")
            view_count = e.get("view_count") or 0

            # Skip non-English titles using language detection
            if title and not _is_english(title):
                continue

            all_reels.append({
                "id":             vid_id,
                "shortcode":      vid_id,
                "post_url":       yt_url,
                "video_url":      yt_url,
                "thumbnail_url":  e.get("thumbnail", ""),
                "caption":        title[:300],
                "view_count":     view_count,
                "like_count":     0,
                "owner_username": (e.get("uploader") or "unknown").replace(" ", "_"),
                "duration":       duration,
            })

        print(f"  [#{tag}] {len([e for e in entries if (e.get('duration') or 0) <= MAX_DURATION])} short videos found", flush=True)

    # Sort by view count descending, take top N
    all_reels.sort(key=lambda x: x["view_count"], reverse=True)
    reels = all_reels[:count]

    if not reels:
        raise RuntimeError(
            f"No viral Shorts found for hashtags: {hashtags}. "
            "Try different hashtags or check yt-dlp is installed."
        )

    top_views = reels[0]["view_count"] if reels else 0
    print(f"  [OK] Found {len(reels)} Shorts | top: {top_views:,} views", flush=True)
    return {"hashtags": hashtags, "reels": reels}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_reels.py \"techfacts,amazingfacts\" [count]")
        sys.exit(1)
    tag_list = [h.strip() for h in sys.argv[1].split(",")]
    n        = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    result   = fetch_reels(tag_list, n)
    print(json.dumps(result, indent=2))
