"""
mark_posted.py
CLI to mark a manually-posted reel as published in the local logs.

After posting a queued reel in the IG app, run:
    python tools/mark_posted.py --queue-id <id> --ig-media-id <id> [--permalink <url>]

What it does (no network calls):
1. Finds queue/pending_audio/<queue_id>.json  — errors if not found
2. Stamps posted_at, ig_media_id, permalink into the queue JSON
3. Moves the file to queue/posted/<queue_id>.json
4. Finds the matching entry in .tmp/disciplinefuel/uploaded_log.json by queue_id
5. Updates that entry: status -> "published", ig_media_id -> real ID, permalink -> URL
6. Saves both files and prints a confirmation

Use --dry-run to preview changes without writing.
"""

import argparse
import json
import os
import shutil
from datetime import datetime

_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QUEUE_DIR = os.path.join(_ROOT, "queue", "pending_audio")
_POSTED_DIR = os.path.join(_ROOT, "queue", "posted")
_TMP_BASE  = os.path.join(_ROOT, ".tmp")


def _log_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "uploaded_log.json")


def _load_json(path: str) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict | list, dry_run: bool) -> None:
    if dry_run:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _find_queue_file(queue_id: str) -> str:
    """Return path to the queue JSON for this queue_id, or raise."""
    # Primary: exact filename match
    candidate = os.path.join(_QUEUE_DIR, f"{queue_id}.json")
    if os.path.exists(candidate):
        return candidate

    # Fallback: scan all JSONs in case naming diverged
    if os.path.isdir(_QUEUE_DIR):
        for fn in os.listdir(_QUEUE_DIR):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(_QUEUE_DIR, fn)
            try:
                d = _load_json(path)
                if isinstance(d, dict) and d.get("queue_id") == queue_id:
                    return path
            except Exception:
                continue

    raise FileNotFoundError(
        f"No queue file found for queue_id={queue_id!r}\n"
        f"  Expected: {candidate}\n"
        f"  Searched: {_QUEUE_DIR}"
    )


def run(queue_id: str, ig_media_id: str, permalink: str, account: str, dry_run: bool) -> None:
    posted_at = datetime.now().isoformat()

    # ── 1. Find and load queue JSON ────────────────────────────────────────────
    queue_path = _find_queue_file(queue_id)
    queue_data = _load_json(queue_path)
    print(f"\n[1/4] Found queue file: {os.path.relpath(queue_path, _ROOT)}", flush=True)

    # ── 2. Stamp queue JSON ────────────────────────────────────────────────────
    queue_data["posted_at"]   = posted_at
    queue_data["ig_media_id"] = ig_media_id
    queue_data["permalink"]   = permalink or ""
    queue_data["status"]      = "posted"

    dest_path = os.path.join(_POSTED_DIR, os.path.basename(queue_path))

    if dry_run:
        print(f"  [DRY RUN] Would update queue JSON:")
        _print_json_diff(queue_path, queue_data)
        print(f"  [DRY RUN] Would move -> {os.path.relpath(dest_path, _ROOT)}")
    else:
        os.makedirs(_POSTED_DIR, exist_ok=True)
        _save_json(queue_path, queue_data, dry_run=False)
        shutil.move(queue_path, dest_path)
        print(f"  Moved -> {os.path.relpath(dest_path, _ROOT)}", flush=True)

    # ── 3. Update uploaded_log.json ────────────────────────────────────────────
    log_path = _log_path(account)
    if not os.path.exists(log_path):
        print(f"\n[WARN] No uploaded_log.json at {log_path} — skipping log update")
        log_data = None
    else:
        log_data = _load_json(log_path)
        posts    = log_data.get("uploaded", [])
        match    = None

        for post in posts:
            if post.get("queue_id") == queue_id:
                match = post
                break

        if match is None:
            print(f"\n[WARN] No log entry with queue_id={queue_id!r} found in uploaded_log.json")
            print(f"       (This can happen if the log was written before Fix 1 was deployed)")
        else:
            before = {k: match[k] for k in ("ig_media_id", "permalink", "status") if k in match}
            match["ig_media_id"] = ig_media_id
            match["permalink"]   = permalink or "pending_manual_post"
            match["status"]      = "published"
            match["posted_at"]   = posted_at
            after  = {k: match[k] for k in ("ig_media_id", "permalink", "status")}

            print(f"\n[3/4] Memory log update (queue_id={queue_id}):")
            for key in after:
                old = before.get(key, "(not set)")
                new = after[key]
                marker = "  " if old == new else "->"
                print(f"       {key}: {old!r} {marker} {new!r}")

            if not dry_run:
                _save_json(log_path, log_data, dry_run=False)
                print(f"  Saved: {os.path.relpath(log_path, _ROOT)}", flush=True)
            else:
                print(f"  [DRY RUN] Would save: {os.path.relpath(log_path, _ROOT)}")

    # ── 4. Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*55}", flush=True)
    print(f"  {'[DRY RUN] ' if dry_run else ''}Mark-posted complete", flush=True)
    print(f"  Queue ID    : {queue_id}", flush=True)
    print(f"  IG Media ID : {ig_media_id}", flush=True)
    print(f"  Permalink   : {permalink or '(not provided)'}", flush=True)
    print(f"  Posted at   : {posted_at}", flush=True)
    print(f"{'='*55}\n", flush=True)


def _print_json_diff(path: str, updated: dict) -> None:
    try:
        original = _load_json(path)
    except Exception:
        original = {}
    changed_keys = [k for k in updated if original.get(k) != updated.get(k)]
    for k in changed_keys:
        print(f"       {k}: {original.get(k)!r} -> {updated.get(k)!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mark a queued reel as manually posted")
    parser.add_argument("--queue-id",    required=True,  help="queue_id from queue/pending_audio/<id>.json")
    parser.add_argument("--ig-media-id", required=True,  help="Real IG media ID from Instagram app")
    parser.add_argument("--permalink",   default="",     help="Full IG post URL (optional)")
    parser.add_argument("--account",     default="disciplinefuel")
    parser.add_argument("--dry-run",     action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    run(
        queue_id    = args.queue_id,
        ig_media_id = args.ig_media_id,
        permalink   = args.permalink,
        account     = args.account,
        dry_run     = args.dry_run,
    )
