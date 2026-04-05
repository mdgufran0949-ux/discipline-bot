"""
fetch_trends.py
Fetches top trending searches from Google Trends daily RSS feed.
No API key needed.
Usage: python tools/fetch_trends.py [geo]
Output: JSON with top trending topics.
"""

import json
import sys
import requests
import xml.etree.ElementTree as ET

TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_trends(geo: str = "US", count: int = 10) -> dict:
    url = TRENDS_RSS.format(geo=geo)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    ns = {"ht": "https://trends.google.com/trending/rss"}

    topics = []
    for item in root.findall(".//item")[:count]:
        title = item.findtext("title", "")
        traffic = item.findtext("ht:approx_traffic", "?", namespaces=ns)
        topics.append({"topic": title, "approx_traffic": traffic})

    return {"trends": topics, "geo": geo}

if __name__ == "__main__":
    geo = sys.argv[1] if len(sys.argv) > 1 else "US"
    result = fetch_trends(geo=geo)
    print(json.dumps(result, indent=2))
