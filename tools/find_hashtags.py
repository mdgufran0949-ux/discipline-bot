"""
find_hashtags.py
Finds the best YouTube hashtags for a niche by analyzing viral Shorts in that space.

Usage: python tools/find_hashtags.py "bodybuilding facts" [top_n]
Output: Ranked hashtag list ready to paste into account config hashtag_pool
"""

import json
import re
import subprocess
import sys
from collections import Counter

from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0

YTDLP       = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"


def _is_english(text: str) -> bool:
    """Return True if text is English. Short/ambiguous text → allow."""
    if not text or len(text.split()) < 3:
        return True
    try:
        return detect(text) == "en"
    except LangDetectException:
        return True
MAX_DURATION = 90   # Shorts only


def _search_videos(query: str, limit: int = 25) -> list:
    """Search YouTube, return list of video IDs for short-form content."""
    result = subprocess.run([
        YTDLP, f"ytsearch{limit}:{query}",
        "--flat-playlist", "--dump-single-json",
        "--no-download", "--quiet", "--no-warnings"
    ], capture_output=True, timeout=60)

    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data    = json.loads(result.stdout)
        entries = data.get("entries") or []
        return [
            e["id"] for e in entries
            if e and e.get("id") and (e.get("duration") or 0) <= MAX_DURATION
        ]
    except Exception:
        return []


def _get_video_tags(video_id: str) -> list:
    """Fetch full metadata for one video and extract all hashtags."""
    try:
        result = subprocess.run([
            YTDLP, f"https://www.youtube.com/shorts/{video_id}",
            "--dump-json", "--no-download", "--quiet", "--no-warnings"
        ], capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except Exception:
        return []

    hashtags = []

    # From tags array
    for tag in (data.get("tags") or []):
        clean = tag.lower().strip().replace(" ", "").lstrip("#")
        if 3 <= len(clean) <= 30:
            hashtags.append(clean)

    # From description — inline #hashtags
    desc = data.get("description") or ""
    for match in re.findall(r'#(\w+)', desc):
        clean = match.lower().strip()
        if 3 <= len(clean) <= 30:
            hashtags.append(clean)

    return hashtags


# Generic terms that appear everywhere and don't help target a niche
_GENERIC = {
    "shorts", "short", "youtube", "viral", "trending", "fyp", "foryou",
    "reels", "tiktok", "instagram", "explore", "video", "subscribe",
    "like", "comment", "share", "follow", "new", "best", "top"
}


def _validate_hashtag(tag: str, niche_keywords: list, min_relevance: float = 0.35) -> bool:
    """
    Fetch top 10 videos from a YouTube hashtag page.
    Return True if >=35% of video titles contain a niche keyword.
    This ensures the hashtag actually delivers niche-relevant content.
    """
    result = subprocess.run([
        YTDLP, f"https://www.youtube.com/hashtag/{tag}",
        "--flat-playlist", "--dump-single-json",
        "--playlist-items", "1-10",
        "--no-download", "--quiet", "--no-warnings"
    ], capture_output=True, timeout=30)

    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        data    = json.loads(result.stdout)
        entries = [e for e in (data.get("entries") or []) if e]
    except Exception:
        return False

    if not entries:
        return False

    # English check: reject if <60% of titles are English
    english_count = sum(1 for e in entries if _is_english(e.get("title") or ""))
    if english_count / len(entries) < 0.60:
        return False

    matches = sum(
        1 for e in entries
        if any(kw in (e.get("title") or "").lower() for kw in niche_keywords)
    )
    return (matches / len(entries)) >= min_relevance


def find_hashtags(niche: str, top_n: int = 15) -> list:
    """
    Analyze viral Shorts for a niche, then validate each candidate hashtag
    to ensure it actually delivers niche-relevant content.

    Parameters
    ----------
    niche  : natural-language niche description e.g. "bodybuilding facts"
    top_n  : how many hashtags to return (default 15)
    """
    print(f"\n  Niche: '{niche}'", flush=True)
    print(f"  Searching YouTube Shorts...", flush=True)

    # Niche keywords used for validation
    niche_keywords = [w.lower() for w in niche.split() if len(w) >= 4]

    # Multiple query variants to cast a wider net
    queries = [niche, f"{niche} shorts", f"{niche} facts"]

    seen      = set()
    video_ids = []
    for query in queries:
        for vid_id in _search_videos(query, limit=20):
            if vid_id not in seen:
                seen.add(vid_id)
                video_ids.append(vid_id)
        if len(video_ids) >= 25:
            break
    video_ids = video_ids[:20]

    print(f"  Found {len(video_ids)} Shorts to analyze\n", flush=True)

    counter = Counter()
    for i, vid_id in enumerate(video_ids, 1):
        tags = _get_video_tags(vid_id)
        for tag in tags:
            counter[tag] += 1
        print(f"  [{i:2}/{len(video_ids)}] {vid_id} — {len(tags)} hashtags", flush=True)

    # Step 2: Validate each candidate — only keep niche-relevant hashtags
    print(f"\n  Validating hashtags (keywords: {niche_keywords})...", flush=True)
    candidates = [
        tag for tag, _ in counter.most_common(top_n * 4)
        if tag not in _GENERIC
    ]

    validated = []
    for tag in candidates:
        if len(validated) >= top_n:
            break
        ok = _validate_hashtag(tag, niche_keywords)
        status = "[OK]  " if ok else "[SKIP]"
        print(f"  {status} #{tag}", flush=True)
        if ok:
            validated.append(tag)

    return validated


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/find_hashtags.py \"bodybuilding facts\" [top_n]")
        print("       python tools/find_hashtags.py \"daily life facts\" 20")
        sys.exit(1)

    niche  = sys.argv[1]
    top_n  = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    tags = find_hashtags(niche, top_n)

    print(f"\n  Top {len(tags)} hashtags for '{niche}':")
    print("  " + "-" * 40)
    for i, tag in enumerate(tags, 1):
        print(f"  {i:2}. #{tag}")

    print(f"\n  Paste into hashtag_pool in account config:")
    print(json.dumps(tags, indent=2))
