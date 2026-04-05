"""
fetch_discipline_trends.py
Trend Awareness System for DisciplineFuel.
Scans YouTube Shorts for trending discipline/motivation content.
Uses Google Trends RSS for broader signals.
Caches results for 24h to avoid hammering APIs.

Usage: python tools/fetch_discipline_trends.py [count]
Output: JSON with best_topic, trending_topics, hot_keywords, timestamp
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
from datetime import datetime, timedelta

YTDLP        = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"
TRENDS_RSS   = "https://trends.google.com/trending/rss?geo=US"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_DURATION = 90
CACHE_HOURS  = 24

CACHE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "trends.json")
)

# ── Discipline-specific keyword bank ──────────────────────────────────────────

DISCIPLINE_HASHTAGS = [
    "discipline", "focus", "grind", "noexcuses", "sacrifice",
    "selfimprovement", "hardwork", "success", "accountability", "mentalstrength"
]

# High-performing keywords for the niche (used for scoring + image prompts)
HIGH_PERFORMING_KEYWORDS = [
    "discipline", "focus", "lonely", "success", "grind", "sacrifice",
    "procrastination", "lazy", "comfort", "weak", "regret", "clock",
    "broke", "scared", "quit", "mirror", "chosen", "soft", "buried",
    "accountability", "winning", "routine", "consistent", "delayed",
    "distraction", "excuses", "fear", "pain", "price", "earn"
]

DISCIPLINE_KEYWORDS = [
    "discipline", "focus", "grind", "sacrifice", "success", "procrastination",
    "lazy", "comfort zone", "accountability", "hard work", "mental strength",
    "consistent", "routine", "excuses", "fear", "hustle", "winning", "regret",
    "distraction", "phone", "sleep", "wasted", "potential", "broke", "weak",
    "soft", "real", "truth", "mirror", "chosen", "quit", "clock", "price"
]

EVERGREEN_TOPICS = [
    "you keep choosing comfort over growth",
    "procrastination is self-betrayal",
    "your laziness has a price",
    "discipline is the only shortcut",
    "nobody is coming to save you",
    "your future self is watching you right now",
    "stop waiting for motivation to start",
    "every delay is a vote against yourself",
    "the version of you that quit still lives here",
    "your phone is stealing your future",
    "you are not busy you are avoiding",
    "comfort is the enemy of growth",
    "you already know what you need to do",
    "pain now or regret later",
    "the clock does not care about your excuses",
    "discipline is doing it when you do not feel like it",
    "winners do not wait for the right moment",
    "you are not unlucky you are undisciplined",
    "fear is just comfort in disguise",
    "wake up before your competition does"
]


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _load_cache() -> dict | None:
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    cached_at = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
    if datetime.now() - cached_at < timedelta(hours=CACHE_HOURS):
        return data
    return None


def _save_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CACHE_PATH)


# ── YouTube scraping ───────────────────────────────────────────────────────────

def _fetch_yt_titles(hashtag: str, limit: int = 20) -> list[str]:
    url = f"https://www.youtube.com/hashtag/{hashtag}"
    result = subprocess.run(
        [YTDLP, url,
         "--flat-playlist",
         "--dump-single-json",
         f"--playlist-items", f"1-{limit}",
         "--no-download", "--quiet", "--no-warnings"],
        capture_output=True, timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"  [WARN] #{hashtag}: yt-dlp failed", flush=True)
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


# ── Google Trends ──────────────────────────────────────────────────────────────

def _fetch_google_trends() -> list[str]:
    try:
        resp = requests.get(TRENDS_RSS, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        return [item.findtext("title", "") for item in root.findall(".//item")[:10]]
    except Exception as e:
        print(f"  [WARN] Google Trends: {e}", flush=True)
        return []


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score_title(text: str) -> int:
    """Score a YouTube title by discipline keyword density."""
    text_lower = text.lower()
    return sum(1 for kw in DISCIPLINE_KEYWORDS if kw in text_lower)


def _extract_hot_keywords(titles: list[str]) -> list[str]:
    """Find which HIGH_PERFORMING_KEYWORDS appear most in trending titles."""
    counts = {}
    for kw in HIGH_PERFORMING_KEYWORDS:
        count = sum(1 for t in titles if kw in t.lower())
        if count > 0:
            counts[kw] = count
    sorted_kw = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, _ in sorted_kw[:10]]


def _title_to_topic(title: str) -> str:
    """Convert a YouTube title to a discipline-framed content topic."""
    title = title.strip().lower()
    # Remove common YouTube fluff
    for fluff in ["#shorts", "#short", "motivation", "| watch this", "(watch this)",
                  "watch this", "must watch", "life changing", "2024", "2025", "2026"]:
        title = title.replace(fluff, "").strip()
    title = re.sub(r'\s+', ' ', title).strip(" -|:")
    return title if len(title) > 10 else ""


# ── Main ───────────────────────────────────────────────────────────────────────

def fetch_discipline_trends(count: int = 5, force: bool = False) -> dict:
    """
    Returns trending discipline topics and hot keywords.
    Caches for 24h. Pass force=True to bypass cache.
    """
    if not force:
        cached = _load_cache()
        if cached:
            print("[OK] Using cached trends (< 24h old)", flush=True)
            return cached

    all_titles = []

    # Scan 4 discipline-specific hashtags
    print("Scanning YouTube discipline hashtags...", flush=True)
    for tag in DISCIPLINE_HASHTAGS[:4]:
        titles = _fetch_yt_titles(tag, limit=15)
        all_titles.extend(titles)
        print(f"  [#{tag}] {len(titles)} titles", flush=True)
        time.sleep(2)

    # Score and filter
    scored = [(t, _score_title(t)) for t in all_titles if t and len(t) > 10]
    scored.sort(key=lambda x: x[1], reverse=True)
    yt_topics_raw = [t for t, s in scored[:count * 2] if s > 0]
    yt_topics = [t for t in (_title_to_topic(t) for t in yt_topics_raw) if t][:count]

    # Extract hot keywords from all collected titles
    hot_keywords = _extract_hot_keywords(all_titles) if all_titles else HIGH_PERFORMING_KEYWORDS[:8]

    # Google Trends context
    print("Checking Google Trends...", flush=True)
    google_trends = _fetch_google_trends()

    # Fill remaining slots with evergreen topics
    topics = yt_topics[:]
    if len(topics) < count:
        shuffled = random.sample(EVERGREEN_TOPICS, len(EVERGREEN_TOPICS))
        for t in shuffled:
            if len(topics) >= count:
                break
            if t not in topics:
                topics.append(t)
    topics = topics[:count]

    best_topic = topics[0] if topics else random.choice(EVERGREEN_TOPICS)

    result = {
        "best_topic":       best_topic,
        "trending_topics":  topics,
        "hot_keywords":     hot_keywords if hot_keywords else HIGH_PERFORMING_KEYWORDS[:8],
        "google_trends":    google_trends[:5],
        "source":           "youtube" if yt_topics else "evergreen",
        "timestamp":        datetime.now().isoformat()
    }

    _save_cache(result)
    print(f"\n[OK] Best topic: {best_topic}", flush=True)
    return result


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    force = "--force" in sys.argv
    result = fetch_discipline_trends(count, force=force)
    print(json.dumps(result, indent=2))
