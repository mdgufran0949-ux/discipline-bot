"""
backfill_pillar_hook.py
Classifies existing uploaded_log.json entries that lack pillar/hook_template fields.

Makes one LLM call per post (fast=True -> Groq first) asking for classification
into pillar + hook_template. Updates log entries in place. Adds
pillar_hook_source: "backfill" to distinguish from picker-assigned entries.

Usage:
  python tools/backfill_pillar_hook.py --account disciplinefuel --dry-run
  python tools/backfill_pillar_hook.py --account disciplinefuel
  python tools/backfill_pillar_hook.py --account disciplinefuel --limit 20
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv

load_dotenv()

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
_TMP_BASE  = os.path.join(_ROOT, ".tmp")

PILLARS        = ["hard_truth", "tactical", "reframe", "story_proof"]
HOOK_TEMPLATES = ["question", "contrarian", "stat_shock", "story", "command"]
BATCH_SIZE     = 20
BATCH_DELAY    = 1.0  # seconds between batches


CLASSIFY_PROMPT = """You are classifying an Instagram quote into a content pillar and hook template.

PILLARS (pick exactly one):
- hard_truth: uncomfortable realities about effort, comfort, failure, or complacency. Blunt, no sugar.
- tactical: specific habits, frameworks, numbered systems. Practical, instructional.
- reframe: flips a common belief on its head. Insight-driven, contrarian.
- story_proof: narrative or quote-based, references a person, scene, or moment. Vivid, anchored.

HOOK TEMPLATES (pick exactly one based on how the quote OPENS):
- question: opens with a question
- contrarian: opens by directly contradicting a common belief
- stat_shock: opens with a number, statistic, or precise timeframe
- story: opens with a scene, person, or vivid moment
- command: opens with a direct instruction (imperative verb)

Quote to classify:
"{quote}"

Return ONLY valid JSON, no markdown:
{{"pillar": "<one of the 4 pillars>", "hook_template": "<one of the 5 templates>", "confidence": "high|medium|low"}}"""


def _log_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "uploaded_log.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(account: str, log: dict) -> None:
    path = _log_path(account)
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _classify_one(quote: str) -> dict | None:
    """Call LLM to classify one quote. Returns dict or None on failure."""
    import generate_discipline_quote as qt
    import re

    prompt = CLASSIFY_PROMPT.format(quote=quote[:300])
    try:
        raw = qt._call(prompt, system="You are a content classifier. Return only valid JSON.", fast=True)
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if data.get("pillar") in PILLARS and data.get("hook_template") in HOOK_TEMPLATES:
            return data
        return None
    except Exception as e:
        print(f"    [WARN] classify failed: {str(e)[:60]}", flush=True)
        return None


def run_backfill(account: str, dry_run: bool = False, limit: int = None) -> None:
    log   = _load_log(account)
    posts = log.get("uploaded", [])

    to_backfill = [
        (i, p) for i, p in enumerate(posts)
        if not p.get("pillar") and (p.get("selected_quote") or p.get("quote"))
    ]

    if limit:
        to_backfill = to_backfill[:limit]

    total = len(to_backfill)
    if total == 0:
        print("All posts already have pillar/hook_template tags.")
        return

    print(f"\nBackfill: {total} posts need classification (dry_run={dry_run})\n")

    updated   = 0
    failed    = 0
    batch_num = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch     = to_backfill[batch_start:batch_start + BATCH_SIZE]
        batch_num += 1

        if batch_num > 1:
            time.sleep(BATCH_DELAY)

        for idx, (post_idx, post) in enumerate(batch):
            quote = (post.get("selected_quote") or post.get("quote", "")).strip()
            if not quote:
                continue

            snippet = quote[:60] + ("..." if len(quote) > 60 else "")
            print(f"  [{batch_start + idx + 1}/{total}] \"{snippet}\"", flush=True)

            result = _classify_one(quote)
            if not result:
                print(f"    -> FAILED (skipping)", flush=True)
                failed += 1
                continue

            pillar   = result["pillar"]
            hook     = result["hook_template"]
            conf     = result.get("confidence", "?")
            print(f"    -> {pillar} + {hook} (confidence: {conf})", flush=True)

            if not dry_run:
                posts[post_idx]["pillar"]            = pillar
                posts[post_idx]["hook_template"]     = hook
                posts[post_idx]["pillar_hook_source"] = "backfill"
            updated += 1

    if not dry_run:
        _save_log(account, log)
        print(f"\nSaved: {updated} posts tagged, {failed} failed.")
    else:
        print(f"\nDry run complete: {updated} would be tagged, {failed} would fail.")
        print("Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill pillar/hook_template for existing posts")
    parser.add_argument("--account",  default="disciplinefuel")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--limit",    type=int, default=None,
                        help="Only process first N untagged posts")
    args = parser.parse_args()
    run_backfill(args.account, dry_run=args.dry_run, limit=args.limit)
