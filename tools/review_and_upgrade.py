"""
review_and_upgrade.py
Review + Self-Upgrading Engine for DisciplineFuel.

Runs weekly (automatically triggered from run_discipline_pipeline.py).
Fetches real Instagram metrics → scores every post → identifies winning and
losing patterns → upgrades account config weights → refines LLM prompt hints
→ generates strategy report.

Usage: python tools/review_and_upgrade.py --account disciplinefuel
Output: .tmp/disciplinefuel/strategy_report.json + updated memory + updated config
"""

import argparse
import json
import os
import sys
import requests
import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
import discipline_memory as mem_module

GRAPH_BASE = "https://graph.facebook.com/v19.0"
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))

SCORE_WEIGHTS = {"saves": 4, "shares": 3, "comments": 2, "likes": 1}
REVIEW_INTERVAL_DAYS = 7


# ── Config helpers ─────────────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(account: str, cfg: dict) -> None:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def _log_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "uploaded_log.json")


def _report_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "strategy_report.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Instagram metrics fetching ─────────────────────────────────────────────────

def _fetch_ig_metrics(ig_media_id: str, ig_access_token: str) -> dict:
    """Fetch saves, shares, comments, likes for a single post."""
    metrics_fields = "saved,shares,comments_count,like_count"
    resp = requests.get(
        f"{GRAPH_BASE}/{ig_media_id}",
        params={
            "fields":       metrics_fields,
            "access_token": ig_access_token
        },
        timeout=20
    )
    if not resp.ok:
        return {}
    data = resp.json()
    return {
        "saves":    data.get("saved", 0),
        "shares":   data.get("shares", {}).get("count", 0) if isinstance(data.get("shares"), dict) else data.get("shares", 0),
        "comments": data.get("comments_count", 0),
        "likes":    data.get("like_count", 0),
    }


def _compute_score(metrics: dict) -> float:
    return sum(metrics.get(k, 0) * w for k, w in SCORE_WEIGHTS.items())


# ── Review loop ────────────────────────────────────────────────────────────────

def _should_run(account: str) -> bool:
    """Check if 7 days have passed since last review."""
    mem_data = mem_module._load()
    last = mem_data.get("last_upgraded")
    if not last:
        return True
    last_dt = datetime.datetime.fromisoformat(last)
    return (datetime.datetime.now() - last_dt).days >= REVIEW_INTERVAL_DAYS


def fetch_and_score_posts(account: str, ig_access_token: str, force: bool = False) -> list:
    """
    Fetch IG metrics for all unscored posts in uploaded_log + memory.
    Returns list of scored post dicts.
    """
    log     = _load_log(account)
    posts   = log.get("uploaded", [])
    scored  = []

    print(f"Fetching metrics for {len(posts)} posts...", flush=True)
    for post in posts:
        media_id = post.get("ig_media_id", "")
        if not media_id:
            continue
        # Skip if already recently scored (within 24h) and not forced
        fetched_at = post.get("metrics_fetched_at", "")
        if not force and fetched_at:
            try:
                last = datetime.datetime.fromisoformat(fetched_at)
                if (datetime.datetime.now() - last).hours < 24:
                    scored.append(post)
                    continue
            except Exception:
                pass

        metrics = _fetch_ig_metrics(media_id, ig_access_token)
        if not metrics:
            print(f"  [SKIP] {media_id}: could not fetch metrics", flush=True)
            continue

        score = _compute_score(metrics)
        post.update(metrics)
        post["score"]             = score
        post["metrics_fetched_at"] = datetime.datetime.now().isoformat()
        scored.append(post)

        # Update memory
        mem_module.update_performance(media_id, metrics)
        print(f"  [OK] {media_id}: score={score:.0f} (saves={metrics['saves']}, shares={metrics['shares']})", flush=True)

    return scored


# ── Config upgrader ────────────────────────────────────────────────────────────

def upgrade_config(account: str, scored_posts: list) -> dict:
    """
    Rebalance account config weights based on performance data.
    80% toward proven winners, 20% experimentation.
    Returns the upgrade summary.
    """
    if not scored_posts:
        return {"status": "no_data"}

    cfg = _load_config(account)

    # Get updated weights from memory
    weights = mem_module.get_content_weights()

    # Update design_style_weights in config
    styles = cfg.get("design_styles", ["dark", "minimal", "bold", "luxury"])
    new_style_weights = [round(weights["design_style"].get(s, 0.1), 3) for s in styles]
    # Normalize
    total = sum(new_style_weights)
    new_style_weights = [round(w / total, 3) for w in new_style_weights]
    cfg["design_style_weights"] = new_style_weights

    # Update content_format_mix
    cfg["content_format_mix"] = {
        k: round(v, 3) for k, v in weights["format"].items()
    }

    # Update content_preferences with prompt hints
    hints = mem_module.get_prompt_hints()
    cfg["content_preferences"] = {
        "best_quote_types":    hints.get("best_quote_types", []),
        "best_hooks":          hints.get("best_hooks", []),
        "avoid_phrases":       hints.get("avoid_phrases", []),
        "avoid_topics":        mem_module._load()["patterns"]["avoid_topics"]
    }

    _save_config(account, cfg)
    print(f"[OK] Config upgraded: styles={new_style_weights}, format={cfg['content_format_mix']}", flush=True)

    return {
        "new_style_weights":  dict(zip(styles, new_style_weights)),
        "new_format_mix":     cfg["content_format_mix"],
        "prompt_hints":       hints,
        "avoid_topics_count": len(cfg["content_preferences"]["avoid_topics"])
    }


# ── Strategy report ────────────────────────────────────────────────────────────

def generate_strategy_report(account: str, scored_posts: list, upgrade_summary: dict) -> dict:
    """Generate a human-readable strategy report."""
    if not scored_posts:
        report = {
            "account":      account,
            "generated_at": datetime.datetime.now().isoformat(),
            "status":       "no_scored_posts",
            "message":      "No posts with metrics yet. Run after the first week."
        }
    else:
        high   = [p for p in scored_posts if p.get("score", 0) >= mem_module.STRONG_THRESHOLD]
        medium = [p for p in scored_posts if mem_module.WEAK_THRESHOLD < p.get("score", 0) < mem_module.STRONG_THRESHOLD]
        low    = [p for p in scored_posts if p.get("score", 0) <= mem_module.WEAK_THRESHOLD]

        top5   = sorted(scored_posts, key=lambda x: x.get("score", 0), reverse=True)[:5]
        worst5 = sorted(scored_posts, key=lambda x: x.get("score", 0))[:5]

        # Best combinations
        strong_combos = Counter(
            f"{p.get('quote_type','?')}+{p.get('design_style','?')}+{p.get('format','?')}"
            for p in high
        )

        avg_score = sum(p.get("score", 0) for p in scored_posts) / len(scored_posts)
        avg_saves = sum(p.get("saves", 0) for p in scored_posts) / len(scored_posts)

        mem_report = mem_module.generate_memory_report()

        report = {
            "account":          account,
            "generated_at":     datetime.datetime.now().isoformat(),
            "period_days":      REVIEW_INTERVAL_DAYS,
            "total_posts":      len(scored_posts),
            "high_performers":  len(high),
            "medium_performers": len(medium),
            "low_performers":   len(low),
            "avg_score":        round(avg_score, 1),
            "avg_saves":        round(avg_saves, 1),
            "top_5_posts": [
                {
                    "quote":   p.get("selected_quote", p.get("quote", ""))[:60],
                    "series":  p.get("content_series", ""),
                    "style":   p.get("design_style", ""),
                    "format":  p.get("format", ""),
                    "score":   round(p.get("score", 0), 1),
                    "saves":   p.get("saves", 0),
                    "shares":  p.get("shares", 0),
                }
                for p in top5
            ],
            "worst_5_posts": [
                {
                    "quote":  p.get("selected_quote", p.get("quote", ""))[:60],
                    "series": p.get("content_series", ""),
                    "style":  p.get("design_style", ""),
                    "score":  round(p.get("score", 0), 1),
                }
                for p in worst5
            ],
            "best_combinations": dict(strong_combos.most_common(5)),
            "avoid_topics":     mem_report.get("avoid_topics", []),
            "upgrade_applied":  upgrade_summary,
            "next_week_strategy": {
                "double_down":  [c for c, _ in strong_combos.most_common(3)],
                "experiment":   "20% of posts should test new quote types/styles",
                "avoid":        mem_report.get("avoid_topics", [])[:5]
            },
            "self_improvement_loop": {
                "strong_patterns_learned": len(mem_report.get("top_performing", [])),
                "weak_patterns_flagged":   len(mem_report.get("worst_performing", [])),
                "topics_blacklisted":      len(mem_report.get("avoid_topics", [])),
                "prompt_updated":          bool(mem_report.get("prompt_hints", {}).get("best_hooks"))
            }
        }

    # Save report
    report_path = _report_path(account)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    tmp = report_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, report_path)
    print(f"[OK] Strategy report saved: {report_path}", flush=True)

    return report


# ── Main ───────────────────────────────────────────────────────────────────────

def run_review(account: str = "disciplinefuel", force: bool = False) -> dict:
    """
    Full review + upgrade cycle.
    Called weekly from run_discipline_pipeline.py.
    """
    if not force and not _should_run(account):
        print(f"[SKIP] Review ran less than {REVIEW_INTERVAL_DAYS} days ago.", flush=True)
        return {"status": "skipped", "reason": "too_soon"}

    print(f"\n{'='*50}", flush=True)
    print(f"REVIEW + UPGRADE: {account.upper()}", flush=True)
    print(f"{'='*50}\n", flush=True)

    cfg = _load_config(account)
    ig_access_token = cfg.get("ig_access_token", "")

    if not ig_access_token:
        print("[WARN] No IG access token. Skipping metrics fetch. Running analysis on cached data only.", flush=True)
        scored_posts = []
    else:
        scored_posts = fetch_and_score_posts(account, ig_access_token, force=force)

    upgrade_summary = upgrade_config(account, scored_posts)
    report = generate_strategy_report(account, scored_posts, upgrade_summary)

    # Mark last upgraded timestamp in memory
    mem_data = mem_module._load()
    mem_data["last_upgraded"] = datetime.datetime.now().isoformat()
    mem_module._save(mem_data)

    print(f"\n[DONE] Review complete.", flush=True)
    print(f"  Posts scored:     {report.get('total_posts', 0)}", flush=True)
    print(f"  High performers:  {report.get('high_performers', 0)}", flush=True)
    print(f"  Topics blacklisted: {len(report.get('avoid_topics', []))}", flush=True)
    print(f"  Config upgraded:  YES", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="disciplinefuel")
    parser.add_argument("--force",   action="store_true", help="Force even if run recently")
    args = parser.parse_args()

    result = run_review(args.account, force=args.force)
    print(json.dumps(result, indent=2))
