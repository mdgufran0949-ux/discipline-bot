"""
fetch_kids_trends.py
Fetches trending topics for kids animation content (ages 3-10).
Uses yt-dlp to scan top kids hashtags + Google Trends RSS.
Falls back to an evergreen topics list if live fetch fails.

Usage: python tools/fetch_kids_trends.py [count]
Output: JSON with best_topic + ranked list of kids topics.
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

import shutil as _shutil
YTDLP = _shutil.which("yt-dlp") or "yt-dlp"
TRENDS_RSS   = "https://trends.google.com/trending/rss?geo=US"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_DURATION = 120  # skip videos longer than 2 min

KIDS_HASHTAGS = [
    "kidslearning", "nurseryrhymes", "animalsforchildren",
    "abcforkids", "scienceforkids", "kidssongs",
    "colorsforkids", "numbersforkids", "kidsstories"
]

KIDS_KEYWORDS = [
    "animals", "colors", "numbers", "alphabet", "abc", "dinosaur",
    "ocean", "space", "rainbow", "counting", "shapes", "nursery",
    "fairy", "princess", "dragon", "farm", "jungle", "underwater",
    "butterfly", "elephant", "lion", "tiger", "bear", "owl", "bunny",
    "planets", "stars", "volcano", "rainbow", "seasons", "weather",
    "fruits", "vegetables", "birds", "fish", "insects", "flowers",
    "letters", "rhyme", "song", "story", "tales", "adventure", "learn",
    "kids", "children", "toddler", "preschool", "baby"
]

KIDS_TOPIC_CATEGORIES = {
    "animals":   ["animals", "dinosaur", "elephant", "lion", "tiger", "bear", "owl",
                  "bunny", "butterfly", "birds", "fish", "insects", "farm", "jungle",
                  "ocean", "underwater", "pets"],
    "numbers":   ["numbers", "counting", "count", "math", "addition", "shapes"],
    "alphabet":  ["alphabet", "abc", "letters", "words", "reading", "spelling"],
    "science":   ["space", "planets", "stars", "volcano", "seasons", "weather",
                  "science", "experiment", "nature", "rainbow", "ocean"],
    "stories":   ["fairy", "princess", "dragon", "story", "tales", "adventure",
                  "nursery", "rhyme", "fable"],
    "colors":    ["colors", "rainbow", "red", "blue", "green", "yellow", "painting"],
    "nature":    ["flowers", "fruits", "vegetables", "trees", "forest", "garden"],
    "songs":     ["song", "rhyme", "music", "dance", "sing", "baby"],
}

EVERGREEN_KIDS_TOPICS = [
    "counting farm animals 1 to 10",
    "the color song for kids",
    "what do dinosaurs eat",
    "learning the alphabet with animals",
    "shapes all around us",
    "animals that live in the ocean",
    "how butterflies grow and change",
    "planets in our solar system for kids",
    "learning to count with fruit",
    "animal sounds for toddlers",
    "what animals live in the jungle",
    "the life cycle of a frog",
    "colors of the rainbow song",
    "numbers 1 to 20 with Biscuit and Zara",
    "what do baby animals look like",
    "how do volcanoes work for kids",
    "farm animals and what they give us",
    "learning about weather for kids",
    "insects and bugs for children",
    "why do leaves change color in fall",
    "the biggest animals in the world",
    "how do fish breathe underwater",
    "what is inside a seed",
    "animals that sleep all winter",
    "how do birds build nests",
    "the fastest animals on earth",
    "animals that glow in the dark",
    "learning about the seasons",
    "what do penguins eat",
    "friendly deep sea creatures for kids",
]


def _fetch_yt_titles(hashtag: str, limit: int = 20) -> list:
    """Fetch video titles from YouTube for a kids hashtag."""
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
            if e and (e.get("duration") or 999) <= MAX_DURATION
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


def _get_category(text: str) -> str:
    """Classify a topic text into a kids content category."""
    text_lower = text.lower()
    for cat, keywords in KIDS_TOPIC_CATEGORIES.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "educational"


def _score_topic(text: str) -> int:
    """Score a title by kids keyword density."""
    text_lower = text.lower()
    return sum(1 for kw in KIDS_KEYWORDS if kw in text_lower)


def _is_kids_safe(text: str) -> bool:
    """Basic check that the topic looks kid-appropriate (not adult news)."""
    adult_signals = [
        "war", "kill", "death", "murder", "crime", "attack", "election",
        "trump", "biden", "politics", "stock", "crypto", "bitcoin",
        "dating", "divorce", "salary", "lawsuit", "shooting"
    ]
    text_lower = text.lower()
    return not any(sig in text_lower for sig in adult_signals)


def fetch_kids_trends(count: int = 5) -> dict:
    all_titles = []

    # Step 1: Scan YouTube kids hashtags (scan 3 to avoid rate limits)
    print("Scanning YouTube kids hashtags...", flush=True)
    for tag in KIDS_HASHTAGS[:3]:
        titles = _fetch_yt_titles(tag, limit=20)
        all_titles.extend(titles)
        print(f"  [#{tag}] {len(titles)} titles", flush=True)
        time.sleep(2)

    # Filter for kids safety and score by keyword density
    safe_titles = [t for t in all_titles if t and len(t) > 8 and _is_kids_safe(t)]
    scored = [(t, _score_topic(t)) for t in safe_titles]
    scored.sort(key=lambda x: x[1], reverse=True)
    yt_topics = [t for t, score in scored[:count] if score > 0]

    # Step 2: Google Trends as a context signal
    print("Checking Google Trends...", flush=True)
    google_trends = _fetch_google_trends()
    kids_trends = [t for t in google_trends if _score_topic(t) > 0 and _is_kids_safe(t)]
    for gt in kids_trends:
        if gt not in yt_topics:
            yt_topics.append(gt)

    # Step 3: Fill remaining slots with evergreen topics
    topics = yt_topics[:]
    if len(topics) < count:
        shuffled = random.sample(EVERGREEN_KIDS_TOPICS, len(EVERGREEN_KIDS_TOPICS))
        for t in shuffled:
            if len(topics) >= count:
                break
            if t not in topics:
                topics.append(t)

    # Build ranked output with category labels
    topics = topics[:count]
    ranked = []
    for i, topic in enumerate(topics, 1):
        ranked.append({
            "rank": i,
            "topic": topic,
            "category": _get_category(topic),
            "viral_score": max(0, 100 - (i - 1) * 15),
            "source": "youtube_trending" if topic in yt_topics[:3] else "evergreen"
        })

    best_topic = topics[0] if topics else EVERGREEN_KIDS_TOPICS[0]
    print(f"\n[OK] Best kids topic: {best_topic}", flush=True)

    return {
        "best_topic": best_topic,
        "topics": ranked,
        "google_trends": google_trends[:5],
        "source": "youtube_hashtags" if yt_topics else "evergreen"
    }


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    result = fetch_kids_trends(count)
    print(json.dumps(result, indent=2))
