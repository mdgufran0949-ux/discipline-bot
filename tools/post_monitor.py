"""
post_monitor.py
First-hour reach monitor for DisciplineFuel reels.

Runs every 30 minutes via GitHub Actions.
Finds posts whose posted_at is 50-90 minutes ago, fetches metrics once,
stamps them as views_t1h / likes_t1h / shares_t1h / saves_t1h in uploaded_log.json.
Skips QUEUED_, DRY_, and pending_manual_post entries — only polls real IG media IDs.

This gives the self-improvement loop a leading signal: first-hour performance
is a strong predictor of algorithmic reach before the 24h score is available.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TMP_BASE  = os.path.join(_ROOT, ".tmp")
_CFG_DIR   = os.path.join(_ROOT, "config", "accounts")
GRAPH_BASE = "https://graph.facebook.com/v19.0"

WINDOW_MIN_MIN = 50   # poll posts that are at least this many minutes old
WINDOW_MAX_MIN = 90   # but no older than this (avoids double-counting)


# ── Config / log helpers ──────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(_CFG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _log_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "uploaded_log.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"uploaded": []}
    except Exception:
        return {"uploaded": []}


def _save_log(account: str, log: dict) -> None:
    path = _log_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ── IG metrics fetch ──────────────────────────────────────────────────────────

def _fetch_metrics(media_id: str, access_token: str) -> dict | None:
    """
    Fetch first-hour metrics for a single reel.
    Returns dict with likes, comments, shares, saves, plays (plays may be None on free tier).
    """
    result = {"likes": 0, "comments": 0, "shares": 0, "saves": 0, "plays": None}

    # Basic fields (always available)
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/{media_id}",
            params={"fields": "like_count,comments_count", "access_token": access_token},
            timeout=15,
        )
        if resp.ok:
            d = resp.json()
            result["likes"]    = d.get("like_count", 0)
            result["comments"] = d.get("comments_count", 0)
    except Exception as exc:
        print(f"  [WARN] Basic fetch failed for {media_id}: {exc}", flush=True)

    # Insights endpoint (saves, shares)
    try:
        ins_resp = requests.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={"metric": "saved,shares", "access_token": access_token},
            timeout=15,
        )
        if ins_resp.ok:
            for item in ins_resp.json().get("data", []):
                name = item.get("name", "")
                val  = (item.get("values", [{}])[0].get("value", 0)
                        if item.get("values") else item.get("value", 0))
                if name == "saved":
                    result["saves"]  = val
                elif name == "shares":
                    result["shares"] = val
    except Exception:
        pass

    # Plays (Reels only — may 403 on non-business accounts)
    try:
        plays_resp = requests.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={"metric": "plays", "access_token": access_token},
            timeout=15,
        )
        if plays_resp.ok:
            for item in plays_resp.json().get("data", []):
                if item.get("name") == "plays":
                    val = (item.get("values", [{}])[0].get("value")
                           if item.get("values") else item.get("value"))
                    result["plays"] = val
    except Exception:
        pass

    return result


# ── Main monitor ──────────────────────────────────────────────────────────────

def run_monitor(account: str) -> int:
    """
    Poll for posts in the 50-90 minute window and stamp first-hour metrics.
    Returns number of posts updated.
    """
    cfg             = _load_config(account)
    ig_access_token = cfg.get("ig_access_token", "")
    if not ig_access_token:
        print(f"[ERROR] No ig_access_token for {account}", flush=True)
        sys.exit(1)

    log_data = _load_log(account)
    posts    = log_data.get("uploaded", [])
    now      = datetime.now()
    updated  = 0

    print(f"\n[MONITOR] {account} — {now.strftime('%Y-%m-%d %H:%M')} UTC", flush=True)
    print(f"  Checking {len(posts)} posts for first-hour window ({WINDOW_MIN_MIN}-{WINDOW_MAX_MIN} min)...",
          flush=True)

    for post in posts:
        media_id = post.get("ig_media_id", "")

        # Skip non-real posts
        if not media_id or media_id.startswith(("QUEUED_", "DRY_")):
            continue
        if post.get("status") in ("pending_manual_post", "dry_run"):
            continue
        if post.get("views_t1h") is not None:
            continue  # already stamped

        # Check age window
        posted_at_str = post.get("posted_at", "")
        if not posted_at_str:
            continue
        try:
            posted_at = datetime.fromisoformat(posted_at_str)
        except Exception:
            continue

        age_min = (now - posted_at).total_seconds() / 60
        if not (WINDOW_MIN_MIN <= age_min <= WINDOW_MAX_MIN):
            continue

        print(f"  -> {media_id} (age {age_min:.0f} min)...", flush=True)
        metrics = _fetch_metrics(media_id, ig_access_token)
        if metrics is None:
            continue

        post["likes_t1h"]    = metrics["likes"]
        post["comments_t1h"] = metrics["comments"]
        post["shares_t1h"]   = metrics["shares"]
        post["saves_t1h"]    = metrics["saves"]
        post["plays_t1h"]    = metrics["plays"]
        post["views_t1h"]    = metrics["plays"]  # alias for reporting
        post["metrics_t1h_fetched_at"] = now.isoformat()

        score_t1h = (
            metrics["saves"]    * 4 +
            metrics["shares"]   * 3 +
            metrics["comments"] * 2 +
            metrics["likes"]    * 1
        )
        post["score_t1h"] = score_t1h

        print(
            f"     likes={metrics['likes']} saves={metrics['saves']} "
            f"shares={metrics['shares']} plays={metrics['plays']} "
            f"score_t1h={score_t1h}",
            flush=True,
        )
        updated += 1
        time.sleep(1)  # IG API rate limiting

    if updated:
        _save_log(account, log_data)
        print(f"\n[MONITOR] Stamped {updated} post(s) with first-hour metrics.", flush=True)
    else:
        print(f"\n[MONITOR] No posts in window — nothing to update.", flush=True)

    return updated


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DisciplineFuel first-hour reach monitor")
    parser.add_argument("--account", default="disciplinefuel")
    args = parser.parse_args()
    run_monitor(args.account)
