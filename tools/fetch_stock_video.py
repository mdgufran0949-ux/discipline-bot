"""
fetch_stock_video.py
Downloads a relevant stock video clip from Pexels API.
Usage: python tools/fetch_stock_video.py "search query" [duration_seconds]
Output: .tmp/stock_clip.mp4 + JSON with file path and metadata.
"""

import json
import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "stock_clip.mp4")

FALLBACK_QUERIES = ["city timelapse", "space stars", "nature landscape", "technology abstract"]

def search_pexels(query: str, min_duration: int = 10) -> dict | None:
    headers = {"Authorization": PEXELS_API_KEY}
    url = "https://api.pexels.com/videos/search"
    params = {"query": query, "per_page": 10, "orientation": "portrait", "size": "medium"}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    for video in data.get("videos", []):
        if video.get("duration", 0) >= min_duration:
            files = video.get("video_files", [])
            # prefer HD portrait
            for f in sorted(files, key=lambda x: x.get("height", 0), reverse=True):
                if f.get("height", 0) >= 720:
                    return {"url": f["link"], "width": f["width"], "height": f["height"], "duration": video["duration"]}
    return None

def download_video(url: str, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

def fetch_stock_video(query: str, min_duration: int = 10) -> dict:
    abs_path = os.path.abspath(OUTPUT_PATH)

    # Try main query, then fallbacks
    queries = [query] + FALLBACK_QUERIES
    meta = None
    used_query = query
    for q in queries:
        meta = search_pexels(q, min_duration)
        if meta:
            used_query = q
            break

    if not meta:
        raise RuntimeError("No suitable stock video found on Pexels after fallbacks.")

    download_video(meta["url"], abs_path)
    return {
        "file": abs_path,
        "query_used": used_query,
        "width": meta["width"],
        "height": meta["height"],
        "source_duration": meta["duration"]
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_stock_video.py \"search query\" [min_duration_sec]")
        sys.exit(1)
    query = sys.argv[1]
    min_dur = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    result = fetch_stock_video(query, min_dur)
    print(json.dumps(result, indent=2))
