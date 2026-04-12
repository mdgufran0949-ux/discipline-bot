"""
daily_review.py
Generic daily review orchestrator for any account.

Flow:
  1. fetch_account_analytics  → performance.json
  2. learn_account_patterns   → memory.json
  3. write_strategy_report    → strategy_report.json
  4. upgrade_account_config   → config/accounts/<account>.json

Runs at the start of each pipeline invocation. Skips if last run < 24h unless
--force is passed.

Usage:
  python tools/daily_review.py --account factsflash [--force]
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from account_memory import AccountMemory, TMP_BASE
from fetch_account_analytics import fetch_account_analytics
from learn_account_patterns import learn_account_patterns

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR   = os.path.join(PROJECT_ROOT, "config", "accounts")

REVIEW_INTERVAL_HOURS = 24


# ── Config I/O ─────────────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(account: str, cfg: dict) -> None:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


# ── Upgrade config ─────────────────────────────────────────────────────────

def upgrade_account_config(account: str, mem: AccountMemory) -> dict:
    cfg = _load_config(account)
    if not cfg:
        return {"status": "no_config"}

    hints = mem.get_prompt_hints()
    weights = mem.get_content_weights()

    prefs = cfg.get("content_preferences", {}) or {}
    prefs["good_keywords"]  = hints.get("best_hooks", [])[:10]
    prefs["best_topics"]    = hints.get("best_topics", [])[:10]
    prefs["avoid_keywords"] = hints.get("avoid_phrases", [])[:10]
    prefs["avoid_topics"]   = hints.get("avoid_topics", [])[:20]
    prefs["top_hooks"]      = hints.get("best_hooks", [])[:5]
    prefs["hook_weights"]   = {k: round(v, 3) for k, v in weights.get("hook_type", {}).items()}
    prefs["last_analyzed"]  = datetime.now().isoformat()

    cfg["content_preferences"] = prefs
    _save_config(account, cfg)
    return prefs


# ── Strategy report ────────────────────────────────────────────────────────

def write_strategy_report(account: str, mem: AccountMemory, upgrade_summary: dict) -> dict:
    raw = mem._load()
    scored = [p for p in raw["posts"] if p.get("performance", {}).get("score") is not None]

    if not scored:
        report = {
            "account":      account,
            "generated_at": datetime.now().isoformat(),
            "status":       "no_scored_posts",
            "message":      "No posts with metrics yet. Wait for first performance data.",
        }
    else:
        strong = [p for p in scored if p["performance"]["score"] >= 70]
        weak   = [p for p in scored if p["performance"]["score"] <= 30]
        medium = [p for p in scored if 30 < p["performance"]["score"] < 70]

        top5   = sorted(scored, key=lambda x: x["performance"]["score"], reverse=True)[:5]
        worst5 = sorted(scored, key=lambda x: x["performance"]["score"])[:5]

        strong_combos = Counter(
            f"{p.get('hook_type','?')}+{p.get('topic','?')[:20]}+{p.get('format','?')}"
            for p in strong
        )

        avg_score = sum(p["performance"]["score"] for p in scored) / len(scored)

        mem_report = mem.get_memory_report()

        report = {
            "account":            account,
            "generated_at":       datetime.now().isoformat(),
            "total_posts_scored": len(scored),
            "high_performers":    len(strong),
            "medium_performers":  len(medium),
            "low_performers":     len(weak),
            "avg_score":          round(avg_score, 1),
            "top_5_posts": [
                {
                    "topic":    p.get("topic", ""),
                    "hook":     p.get("hook", "")[:60],
                    "format":   p.get("format", ""),
                    "score":    round(p["performance"]["score"], 1),
                    "saves":    p["performance"].get("saves", 0),
                    "shares":   p["performance"].get("shares", 0),
                    "yt_views": p["performance"].get("yt_views", 0),
                }
                for p in top5
            ],
            "worst_5_posts": [
                {
                    "topic": p.get("topic", ""),
                    "hook":  p.get("hook", "")[:60],
                    "score": round(p["performance"]["score"], 1),
                }
                for p in worst5
            ],
            "best_combinations": dict(strong_combos.most_common(5)),
            "avoid_topics":      mem_report.get("avoid_topics", []),
            "upgrade_applied":   upgrade_summary,
            "next_strategy": {
                "double_down": [c for c, _ in strong_combos.most_common(3)],
                "experiment":  "20% of posts should test new hook/topic combos",
                "avoid":       mem_report.get("avoid_topics", [])[:5],
            },
        }

    out_path = os.path.join(TMP_BASE, account, "strategy_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, out_path)
    print(f"[{account}] Strategy report saved: {out_path}", flush=True)
    return report


# ── Main ───────────────────────────────────────────────────────────────────

def _should_run(account: str) -> bool:
    mem = AccountMemory(account)
    raw = mem._load()
    last = raw.get("last_reviewed")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() >= REVIEW_INTERVAL_HOURS * 3600
    except Exception:
        return True


def daily_review(account: str, force: bool = False) -> dict:
    if not force and not _should_run(account):
        print(f"[{account}] Review ran <{REVIEW_INTERVAL_HOURS}h ago. Skipping.", flush=True)
        return {"status": "skipped"}

    print(f"\n{'='*55}", flush=True)
    print(f"  DAILY REVIEW: {account}", flush=True)
    print(f"{'='*55}", flush=True)

    # 1. Fetch analytics
    try:
        fetch_account_analytics(account)
    except Exception as e:
        print(f"  [WARN] analytics fetch failed: {e}", flush=True)

    # 2. Learn patterns
    mem = AccountMemory(account)
    try:
        learn_account_patterns(account)
    except Exception as e:
        print(f"  [WARN] pattern learning failed: {e}", flush=True)

    # 3. Upgrade config
    try:
        upgrade = upgrade_account_config(account, mem)
    except Exception as e:
        print(f"  [WARN] config upgrade failed: {e}", flush=True)
        upgrade = {"status": "failed", "error": str(e)}

    # 4. Strategy report
    report = write_strategy_report(account, mem, upgrade)

    mem.mark_upgraded()
    raw = mem._load()
    raw["last_reviewed"] = datetime.now().isoformat()
    mem._save(raw)

    print(f"[{account}] Review complete.", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--force",   action="store_true")
    args = parser.parse_args()
    result = daily_review(args.account, force=args.force)
    print(json.dumps(result, indent=2, default=str)[:3000])
