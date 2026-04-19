"""
learn_account_patterns.py
Reads performance.json + uploaded_log.json for an account, extracts feature
patterns (hook type, topic, hashtags, image style) from strong vs weak posts,
and writes them back into memory via AccountMemory.update_scores().

Usage:
  python tools/learn_account_patterns.py --account factsflash
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from account_memory import AccountMemory, TMP_BASE


# ── Hook classifier ────────────────────────────────────────────────────────

QUESTION_WORDS = ("what", "why", "how", "when", "where", "who", "did", "is", "are", "can", "do", "does")
IMPERATIVE_VERBS = ("stop", "start", "never", "always", "watch", "listen", "try", "don't", "do", "remember")


def classify_hook(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    first = t.split()[0] if t else ""
    if "?" in t or first in QUESTION_WORDS:
        return "question"
    if first in IMPERATIVE_VERBS:
        return "imperative"
    if re.search(r"\d+", t[:40]) or any(w in t[:40] for w in ("fact", "did you know", "the truth")):
        return "fact"
    return "story"


# ── Orchestration ──────────────────────────────────────────────────────────

def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_uploaded_log(account: str) -> list:
    candidates = [os.path.join(TMP_BASE, account, "uploaded_log.json")]
    # Kids pipeline writes to a non-standard location; check it when applicable.
    if account == "biscuit_zara":
        candidates.insert(0, os.path.join(TMP_BASE, "kids_channel", "upload_log.json"))
    candidates.append(os.path.join(TMP_BASE, "uploaded_log.json"))

    data = None
    for path in candidates:
        data = _load_json(path, None)
        if data is not None:
            break
    if data is None:
        data = []
    return data.get("uploaded", data) if isinstance(data, dict) else data


def _ensure_posts_in_memory(mem: AccountMemory, log_posts: list) -> None:
    """
    Make sure every upload-log entry exists as a post in memory.
    Pipelines that predate the memory system will have gaps — backfill them
    with whatever fields are available.
    """
    raw = mem._load()
    existing_ids = set()
    for p in raw["posts"]:
        for k in (p.get("ig_media_id"), p.get("yt_video_id"), p.get("id")):
            if k:
                existing_ids.add(k)

    added = 0
    for entry in log_posts:
        post_id = (entry.get("ig_media_id")
                   or entry.get("yt_video_id")
                   or entry.get("id")
                   or entry.get("post_id"))
        if not post_id or post_id in existing_ids:
            continue

        hook_text = entry.get("hook") or entry.get("narration", "")[:60]
        mem.add_post({
            "id":            post_id,
            "ig_media_id":   entry.get("ig_media_id", ""),
            "yt_video_id":   entry.get("yt_video_id", ""),
            "topic":         entry.get("topic", ""),
            "hook":          hook_text,
            "hook_type":     classify_hook(hook_text),
            "hook_keyword":  entry.get("hook_keyword", ""),
            "quote_type":    entry.get("quote_type", ""),
            "design_style":  entry.get("design_style", ""),
            "format":        entry.get("format", "video"),
            "series":        entry.get("series", ""),
            "caption":       entry.get("caption", ""),
            "hashtags":      entry.get("hashtags", []),
            "scene_prompts": entry.get("scene_prompts", []),
            "posted_at":     entry.get("posted_at") or entry.get("uploaded_at", ""),
        })
        added += 1

    if added:
        print(f"  [backfill] Added {added} posts from uploaded_log into memory", flush=True)


def learn_account_patterns(account: str) -> dict:
    mem = AccountMemory(account)

    log_posts = _load_uploaded_log(account) or []
    _ensure_posts_in_memory(mem, log_posts)

    perf_path = os.path.join(TMP_BASE, account, "performance.json")
    perf = _load_json(perf_path, {})

    if not perf:
        print(f"[{account}] No performance data yet; nothing to learn.", flush=True)
        return {"status": "no_data"}

    mem.update_scores(perf)
    report = mem.get_memory_report()
    print(f"[{account}] Patterns rebuilt. "
          f"strong={len(report.get('top_performing', []))} "
          f"weak={len(report.get('worst_performing', []))} "
          f"avoid_topics={len(report.get('avoid_topics', []))}", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    result = learn_account_patterns(args.account)
    print(json.dumps(result, indent=2, default=str)[:2000])
