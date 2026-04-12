"""
fetch_account_analytics.py
Fetches performance metrics for all posts in an account's uploaded_log.json.

Sources:
  - Instagram Graph API (saves, shares, comments, likes)
  - YouTube Data API + Analytics API (views, watchtime, CTR)

Output: .tmp/<account>/performance.json
  {
    "<post_id>": {
      "platform": "instagram" | "youtube",
      "saves": int, "shares": int, "comments": int, "likes": int,
      "yt_views": int, "yt_watchtime_min": float, "yt_ctr": float,
      "score": float, "fetched_at": iso
    },
    ...
  }

Usage:
  python tools/fetch_account_analytics.py --account factsflash
"""

import argparse
import json
import os
import pickle
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from account_memory import compute_score

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP_BASE     = os.path.join(PROJECT_ROOT, ".tmp")
CONFIG_DIR   = os.path.join(PROJECT_ROOT, "config", "accounts")
TOKEN_FILE   = os.path.join(TMP_BASE, "youtube_token.pkl")

GRAPH_BASE = "https://graph.facebook.com/v19.0"

# Combined scopes for upload + analytics read
YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_uploaded_log(account: str) -> list:
    for candidate in (
        os.path.join(TMP_BASE, account, "uploaded_log.json"),
        os.path.join(TMP_BASE, "uploaded_log.json"),
    ):
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("uploaded", data) if isinstance(data, dict) else data
    return []


# ── Instagram ──────────────────────────────────────────────────────────────

def fetch_ig_metrics(ig_media_id: str, ig_access_token: str) -> dict:
    """Fetch saves, shares, comments, likes for one IG post."""
    basic_resp = requests.get(
        f"{GRAPH_BASE}/{ig_media_id}",
        params={"fields": "like_count,comments_count", "access_token": ig_access_token},
        timeout=20,
    )
    if not basic_resp.ok:
        return {}
    basic = basic_resp.json()
    result = {
        "saves":    0,
        "shares":   0,
        "comments": basic.get("comments_count", 0),
        "likes":    basic.get("like_count", 0),
    }

    try:
        ins_resp = requests.get(
            f"{GRAPH_BASE}/{ig_media_id}/insights",
            params={"metric": "saved,shares", "access_token": ig_access_token},
            timeout=20,
        )
        if ins_resp.ok:
            for item in ins_resp.json().get("data", []):
                name = item.get("name", "")
                vals = item.get("values", [{}])
                val = vals[0].get("value", 0) if vals else 0
                if name == "saved":
                    result["saves"] = val
                elif name == "shares":
                    result["shares"] = val
    except Exception:
        pass

    return result


# ── YouTube ────────────────────────────────────────────────────────────────

def _get_youtube_services():
    """Return (youtube_data, youtube_analytics) clients or (None, None) if unavailable."""
    try:
        from google.oauth2.credentials import Credentials  # noqa
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        print("  [WARN] google-api-python-client not installed; skipping YT", flush=True)
        return None, None

    if not os.path.exists(TOKEN_FILE):
        print(f"  [WARN] No YouTube token at {TOKEN_FILE}; skipping YT metrics", flush=True)
        return None, None

    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"  [WARN] YT token refresh failed: {e}", flush=True)
            return None, None

    try:
        yt_data = build("youtube", "v3", credentials=creds, cache_discovery=False)
        yt_analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        return yt_data, yt_analytics
    except Exception as e:
        print(f"  [WARN] YT service build failed: {e}", flush=True)
        return None, None


def fetch_yt_metrics(video_ids: list) -> dict:
    """
    Batch-fetch YouTube stats + analytics for a list of video IDs.
    Returns {video_id: {yt_views, yt_watchtime_min, yt_ctr, likes, comments}}
    """
    if not video_ids:
        return {}

    yt_data, yt_analytics = _get_youtube_services()
    if not yt_data:
        return {}

    result = {}

    # Data API: batch stats in chunks of 50
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        try:
            resp = yt_data.videos().list(
                part="statistics",
                id=",".join(chunk),
            ).execute()
            for item in resp.get("items", []):
                stats = item.get("statistics", {})
                result[item["id"]] = {
                    "yt_views":     int(stats.get("viewCount", 0)),
                    "likes":        int(stats.get("likeCount", 0)),
                    "comments":     int(stats.get("commentCount", 0)),
                }
        except Exception as e:
            print(f"  [WARN] YT stats fetch failed: {e}", flush=True)

    # Analytics API: watchtime + CTR per video (one query, filter by video)
    if yt_analytics:
        end_date   = datetime.now().date().isoformat()
        start_date = (datetime.now() - timedelta(days=60)).date().isoformat()
        for vid in video_ids:
            try:
                resp = yt_analytics.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="estimatedMinutesWatched,averageViewPercentage",
                    filters=f"video=={vid}",
                ).execute()
                rows = resp.get("rows", [])
                if rows:
                    row = rows[0]
                    result.setdefault(vid, {})
                    result[vid]["yt_watchtime_min"] = float(row[0] or 0)
                    # averageViewPercentage proxies CTR engagement when impressions unavailable
                    result[vid]["yt_ctr"] = float(row[1] or 0) / 100.0
            except Exception as e:
                # Analytics often fails for very new videos — skip silently
                if "forbidden" in str(e).lower():
                    print(f"  [WARN] YT analytics forbidden (check scopes): {e}", flush=True)
                    break

    return result


# ── Main ───────────────────────────────────────────────────────────────────

def fetch_account_analytics(account: str, force: bool = False) -> dict:
    cfg = _load_config(account)
    ig_token = cfg.get("ig_access_token", "")

    posts = _load_uploaded_log(account)
    if not posts:
        print(f"[{account}] No uploaded posts yet.", flush=True)
        return {}

    print(f"[{account}] Fetching metrics for {len(posts)} posts...", flush=True)

    performance = {}
    yt_ids = [p.get("yt_video_id") for p in posts if p.get("yt_video_id")]
    yt_metrics = fetch_yt_metrics(yt_ids) if yt_ids else {}

    for post in posts:
        metrics = {}
        key = None

        # IG branch
        ig_id = post.get("ig_media_id")
        if ig_id and ig_token:
            metrics.update(fetch_ig_metrics(ig_id, ig_token))
            key = ig_id

        # YouTube branch
        yt_id = post.get("yt_video_id")
        if yt_id and yt_id in yt_metrics:
            ytm = yt_metrics[yt_id]
            for k, v in ytm.items():
                # Don't clobber IG likes/comments with YT ones if we already have them
                if k in metrics and metrics[k]:
                    continue
                metrics[k] = v
            key = key or yt_id

        if not key or not metrics:
            continue

        metrics["score"]      = compute_score(metrics)
        metrics["fetched_at"] = datetime.now().isoformat()
        metrics["platform"]   = "instagram" if ig_id else "youtube"
        performance[key] = metrics

        print(f"  [OK] {key[:16]}: score={metrics['score']:.0f}", flush=True)

    # Save
    out_path = os.path.join(TMP_BASE, account, "performance.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(performance, f, indent=2)
    os.replace(tmp, out_path)
    print(f"[{account}] Saved {len(performance)} records to {out_path}", flush=True)

    return performance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    fetch_account_analytics(args.account, force=args.force)
