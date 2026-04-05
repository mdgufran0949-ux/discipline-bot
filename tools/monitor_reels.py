"""
monitor_reels.py
Fetches Instagram performance metrics for uploaded reels and updates the
account's content strategy based on results.

Scoring fix: when IG metrics are unavailable (0), falls back to yt_views
so keyword analysis and hashtag ranking still work from day one.

Also generates a weekly strategy report at .tmp/<account>/strategy_report.json

Runs automatically weekly from run_pipeline.py, or manually:
    python tools/monitor_reels.py --account factsflash
"""

import argparse
import json
import os
import re
import sys
import datetime
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(__file__))

CONFIG_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE     = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
MONITOR_DAYS = 7    # re-run every 7 days

STOPWORDS = {
    "this", "that", "with", "from", "have", "will", "your", "what", "when",
    "they", "them", "their", "more", "been", "into", "some", "just", "like",
    "also", "about", "would", "could", "which", "then", "than", "only",
    "very", "most", "over", "such", "even", "after", "before", "because",
    "these", "those", "here", "there", "where", "been", "were", "does",
    "make", "made", "know", "dont", "cant", "isnt", "arent", "wasnt",
}


def _log_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "uploaded_log.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(data: dict, account: str) -> None:
    path = _log_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: dict, account: str) -> None:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _fetch_ig_metrics(ig_media_id: str, ig_access_token: str) -> dict:
    """Fetch likes, comments, and video_views for one IG media."""
    likes = comments = views = 0
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{ig_media_id}",
            params={"fields": "like_count,comments_count",
                    "access_token": ig_access_token},
            timeout=10
        )
        data     = r.json()
        likes    = data.get("like_count", 0)
        comments = data.get("comments_count", 0)
    except Exception:
        pass

    # Try insights (needs instagram_manage_insights — graceful fallback)
    try:
        r2 = requests.get(
            f"https://graph.facebook.com/v19.0/{ig_media_id}/insights",
            params={"metric": "video_views", "access_token": ig_access_token},
            timeout=10
        )
        for item in r2.json().get("data", []):
            if item["name"] == "video_views":
                views = item.get("values", [{}])[0].get("value", 0)
    except Exception:
        pass

    return {"likes": likes, "comments": comments, "views": views}


def _keywords_from_title(title: str) -> list:
    """Extract meaningful words from a video title."""
    if not title or len(title) < 10 or (title.isalnum() and ' ' not in title):
        return []
    words = re.findall(r'\b[a-zA-Z]{4,}\b', title.lower())
    return [w for w in words if w not in STOPWORDS]


def _compute_score(ig_likes: int, ig_comments: int, ig_views: int, yt_views: int) -> int:
    """
    Compute engagement score. Falls back to yt_views when IG metrics are all 0
    (common when instagram_manage_insights permission is not granted).
    """
    ig_score = ig_likes + ig_comments * 3 + ig_views // 1000
    if ig_score > 0:
        return ig_score
    # Fallback: normalise yt_views to a comparable scale
    return yt_views // 10_000


def _save_strategy_report(account: str, log: dict, cfg: dict,
                           scored: list, top_reels: list, bottom_reels: list,
                           good_kws: list, avoid_kws: list) -> None:
    """Write .tmp/<account>/strategy_report.json with actionable weekly recommendations."""
    uploaded = log.get("uploaded", [])
    hashtag_stats = log.get("hashtag_stats", {})

    # Sort hashtags by avg_views descending
    sorted_tags = sorted(
        hashtag_stats.items(),
        key=lambda x: x[1].get("avg_views", 0),
        reverse=True
    )
    best_tags  = [{"tag": t, **v} for t, v in sorted_tags[:5]]
    worst_tags = [{"tag": t, **v} for t, v in sorted_tags[-3:] if v.get("runs", 0) > 0]

    # Date range of uploads
    dates = [e.get("uploaded_at", "")[:10] for e in uploaded if e.get("uploaded_at")]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"

    # Average yt_views across all uploads
    yt_view_list = [e.get("yt_views", 0) for e in uploaded if e.get("yt_views", 0) > 0]
    avg_yt_views = round(sum(yt_view_list) / len(yt_view_list)) if yt_view_list else 0

    # Top 3 best-performing reels
    top3 = [
        {
            "reel_id":   x["entry"].get("reel_id", ""),
            "caption":   (x["entry"].get("caption") or "")[:120],
            "yt_views":  x["entry"].get("yt_views", 0),
            "ig_likes":  x["entry"].get("ig_likes", 0),
            "ig_views":  x["entry"].get("ig_views", 0),
            "score":     x["score"],
        }
        for x in top_reels[:3]
    ]

    # Build plain-language recommendations
    recs = []
    if best_tags:
        top_tag = best_tags[0]
        recs.append(
            f"Priority hashtag: #{top_tag['tag']} "
            f"({top_tag.get('avg_views', 0):,} avg source views, {top_tag.get('runs', 0)} runs)"
        )
    if worst_tags and len(sorted_tags) > 3:
        recs.append(
            f"Reduce use of: {', '.join('#' + t['tag'] for t in worst_tags)} — low source view counts"
        )
    if good_kws:
        recs.append(f"Content themes that perform well: {', '.join(good_kws[:5])}")
    if avoid_kws:
        recs.append(f"Content themes to avoid: {', '.join(avoid_kws)}")
    if avg_yt_views > 0:
        suggested_min = max(500_000, round(avg_yt_views * 0.3 / 100_000) * 100_000)
        current_min   = cfg.get("min_reel_views", 200_000)
        if suggested_min != current_min:
            recs.append(
                f"Consider adjusting min_reel_views from {current_min:,} to {suggested_min:,} "
                f"based on avg source views of {avg_yt_views:,}"
            )

    report = {
        "account":        account,
        "generated_at":   datetime.datetime.now().isoformat(),
        "data_summary": {
            "total_uploads":  len(uploaded),
            "total_analyzed": len(scored),
            "avg_yt_views":   avg_yt_views,
            "date_range":     date_range,
        },
        "best_hashtags":  best_tags,
        "worst_hashtags": worst_tags,
        "top_performers": top3,
        "content_insights": {
            "good_keywords":  good_kws,
            "avoid_keywords": avoid_kws,
            "top_score_avg":  round(sum(x["score"] for x in top_reels) / len(top_reels)) if top_reels else 0,
            "bottom_score_avg": round(sum(x["score"] for x in bottom_reels) / len(bottom_reels)) if bottom_reels else 0,
        },
        "recommendations": recs,
    }

    out_path = os.path.join(TMP_BASE, account, "strategy_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def monitor_reels(account_name: str, cfg: dict, ig_user_id: str,
                  ig_access_token: str, silent: bool = False) -> None:
    """
    Check performance of uploaded reels. Update content_preferences in config.
    Generate strategy report at .tmp/<account>/strategy_report.json.
    If silent=True, skip if already run within MONITOR_DAYS.
    """
    prefs     = cfg.get("content_preferences", {})
    last_run  = prefs.get("last_analyzed", "")
    needs_run = True

    if silent and last_run:
        try:
            last_dt   = datetime.datetime.fromisoformat(last_run)
            days_old  = (datetime.datetime.now() - last_dt).days
            needs_run = days_old >= MONITOR_DAYS
        except Exception:
            pass

    if not needs_run:
        return

    log     = _load_log(account_name)
    entries = log.get("uploaded", [])

    # Only process reels that have an ig_media_id
    checkable = [e for e in entries if e.get("ig_media_id")]
    if not checkable:
        if not silent:
            print(f"  [MONITOR] No reels with ig_media_id yet — upload some reels first.", flush=True)
        return

    print(f"\n  [MONITOR] Checking {len(checkable)} uploaded reels...", flush=True)

    scored = []
    for i, entry in enumerate(checkable, 1):
        media_id = entry["ig_media_id"]
        metrics  = _fetch_ig_metrics(media_id, ig_access_token)

        entry["ig_likes"]           = metrics["likes"]
        entry["ig_comments"]        = metrics["comments"]
        entry["ig_views"]           = metrics["views"]
        entry["metrics_checked_at"] = datetime.datetime.now().isoformat()

        score = _compute_score(
            metrics["likes"], metrics["comments"], metrics["views"],
            entry.get("yt_views", 0)
        )

        title = entry.get("caption") or ""
        scored.append({"entry": entry, "score": score, "title": title})

        if not silent:
            ig_str = f"likes={metrics['likes']} comments={metrics['comments']} views={metrics['views']}"
            yt_str = f"yt_views={entry.get('yt_views', 0):,}"
            print(f"  [{i:2}/{len(checkable)}] {media_id[:15]}... "
                  f"{ig_str} | {yt_str} → score={score}", flush=True)

    _save_log(log, account_name)

    if len(scored) < 3:
        if not silent:
            print("  [MONITOR] Not enough data yet (need 3+ reels). Check back later.", flush=True)
        return

    scored.sort(key=lambda x: x["score"], reverse=True)
    cutoff       = max(1, len(scored) // 3)
    top_reels    = scored[:cutoff]
    bottom_reels = scored[-cutoff:] if len(scored) >= cutoff * 2 else []

    good_counter  = Counter()
    avoid_counter = Counter()

    for item in top_reels:
        for kw in _keywords_from_title(item["title"]):
            good_counter[kw] += 1

    for item in bottom_reels:
        for kw in _keywords_from_title(item["title"]):
            avoid_counter[kw] += 1

    good_kws  = [kw for kw, _ in good_counter.most_common(10)]
    avoid_kws = [kw for kw, _ in avoid_counter.most_common(5) if kw not in good_counter]

    top_avg    = sum(x["score"] for x in top_reels) / len(top_reels)
    bottom_avg = sum(x["score"] for x in bottom_reels) / len(bottom_reels) if bottom_reels else 0

    cfg["content_preferences"] = {
        "good_keywords":    good_kws,
        "avoid_keywords":   avoid_kws,
        "last_analyzed":    datetime.datetime.now().isoformat(),
        "total_analyzed":   len(scored),
        "top_avg_score":    round(top_avg),
        "bottom_avg_score": round(bottom_avg),
    }
    _save_config(cfg, account_name)

    # Save strategy report
    _save_strategy_report(account_name, log, cfg, scored, top_reels, bottom_reels, good_kws, avoid_kws)

    # Hashtag pool health check
    hashtag_stats = log.get("hashtag_stats", {})
    active_tags   = [t for t, v in hashtag_stats.items() if v.get("runs", 0) > 0]
    if len(cfg.get("hashtag_pool", [])) < 6 or len(active_tags) < 3:
        if cfg.get("niche"):
            cfg["hashtag_last_updated"] = ""
            _save_config(cfg, account_name)
            print("  [HASHTAGS] Pool too small — will auto-refresh on next run", flush=True)

    report_path = os.path.join(TMP_BASE, account_name, "strategy_report.json")

    if not silent:
        print(f"\n  Top performers ({len(top_reels)}) — score avg {top_avg:.0f}")
        print(f"    Good keywords : {good_kws}")
        print(f"  Low performers ({len(bottom_reels)}) — score avg {bottom_avg:.0f}")
        print(f"    Avoid keywords: {avoid_kws}")
        print(f"  [OK] content_preferences updated in {account_name} config")
        print(f"  [OK] Strategy report saved to {report_path}\n", flush=True)
    else:
        if good_kws or avoid_kws:
            print(f"  [MONITOR] Updated preferences — good: {good_kws[:3]} | avoid: {avoid_kws[:3]}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="Account name")
    args = parser.parse_args()

    cfg             = _load_config(args.account)
    ig_user_id      = cfg["ig_user_id"]
    ig_access_token = cfg["ig_access_token"]

    monitor_reels(args.account, cfg, ig_user_id, ig_access_token, silent=False)
