"""
fetch_motivation_trends.py
Fetches trending topics in the Motivation/Mindset niche from YouTube Shorts.
Uses yt-dlp to scan top motivation hashtags and extract common themes.
Also uses Google Trends RSS for broader trending signals.
Usage: python tools/fetch_motivation_trends.py [count]
Output: JSON with best_topic + ranked list of trending motivation topics.
"""

import json
import os
import re
import subprocess
import sys
import time
import requests
import xml.etree.ElementTree as ET
import random

YTDLP       = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"
TRENDS_RSS  = "https://trends.google.com/trending/rss?geo=US"
HEADERS     = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_DURATION = 90  # skip videos longer than 90s

MOTIVATION_HASHTAGS = [
    "motivation", "mindset", "discipline", "selfimprovement", "success"
]

MOTIVATION_KEYWORDS = [
    "success", "mindset", "discipline", "motivation", "habits", "goals",
    "focus", "growth", "confidence", "fear", "failure", "hustle", "grind",
    "money", "wealth", "productivity", "routine", "morning", "winning",
    "self", "improvement", "level", "life", "change", "achieve", "dream",
    "consistency", "sacrifice", "comfort", "zone", "mentality", "hard work",
    "resilience", "ambition", "purpose", "vision", "mindfulness", "action"
]

EVERGREEN_TOPICS = [
    "why most people never achieve their goals",
    "the discipline habit that changes everything",
    "how to stop being lazy and take action",
    "what separates successful people from everyone else",
    "why your morning routine determines your future",
    "the mindset shift that will change your life forever",
    "how to build unbreakable confidence",
    "why consistency beats motivation every time",
    "the one habit successful people never skip",
    "how to overcome fear and self-doubt for good",
    "why your comfort zone is your biggest enemy",
    "what nobody tells you about becoming successful",
    "how to rewire your brain for success",
    "the real reason you keep failing",
    "why hard work alone is not enough",
]


def _fetch_yt_titles(hashtag: str, limit: int = 20) -> list:
    """Fetch video titles from YouTube Shorts for a motivation hashtag."""
    url = f"https://www.youtube.com/hashtag/{hashtag}"
    result = subprocess.run(
        [YTDLP, url,
         "--flat-playlist",
         "--dump-single-json",
         "--playlist-items", f"1-{limit}",
         "--no-download",
         "--quiet",
         "--no-warnings"],
        capture_output=True, timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"  [WARN] #{hashtag}: {result.stderr[:100].strip()}", flush=True)
        return []
    try:
        data = json.loads(result.stdout)
        return [
            e.get("title", "").encode("ascii", "ignore").decode("ascii").strip()
            for e in data.get("entries", [])
            if e and (e.get("duration") or 99) <= MAX_DURATION
        ]
    except Exception as e:
        print(f"  [WARN] #{hashtag}: parse error — {e}", flush=True)
        return []


def _fetch_google_trends() -> list:
    """Fetch top Google Trends topics via RSS (no API key needed)."""
    try:
        resp = requests.get(TRENDS_RSS, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        return [item.findtext("title", "") for item in root.findall(".//item")[:10]]
    except Exception as e:
        print(f"  [WARN] Google Trends fetch failed: {e}", flush=True)
        return []


def _score_topic(text: str) -> int:
    """Score a title by motivation keyword density."""
    text_lower = text.lower()
    return sum(1 for kw in MOTIVATION_KEYWORDS if kw in text_lower)


def fetch_motivation_trends(count: int = 5) -> dict:
    all_titles = []

    # Step 1: Scan YouTube motivation hashtags (scan 3 to avoid rate limits)
    print("Scanning YouTube motivation hashtags...", flush=True)
    for tag in MOTIVATION_HASHTAGS[:3]:
        titles = _fetch_yt_titles(tag, limit=20)
        all_titles.extend(titles)
        print(f"  [#{tag}] {len(titles)} titles", flush=True)
        time.sleep(2)

    # Score and filter by motivation relevance
    scored = [(t, _score_topic(t)) for t in all_titles if t and len(t) > 10]
    scored.sort(key=lambda x: x[1], reverse=True)
    yt_topics = [t for t, score in scored[:count] if score > 0]

    # Step 2: Google Trends as context signal
    print("Checking Google Trends...", flush=True)
    google_trends = _fetch_google_trends()

    # Step 3: Fill remaining slots with evergreen topics
    topics = yt_topics[:]
    if len(topics) < count:
        shuffled = random.sample(EVERGREEN_TOPICS, len(EVERGREEN_TOPICS))
        for t in shuffled:
            if len(topics) >= count:
                break
            if t not in topics:
                topics.append(t)

    topics = topics[:count]
    best_topic = topics[0] if topics else EVERGREEN_TOPICS[0]

    print(f"\n[OK] Best topic for today: {best_topic}", flush=True)
    return {
        "best_topic": best_topic,
        "topics": topics,
        "google_trends": google_trends[:5],
        "source": "youtube_hashtags" if yt_topics else "evergreen"
    }


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    result = fetch_motivation_trends(count)
    print(json.dumps(result, indent=2))
