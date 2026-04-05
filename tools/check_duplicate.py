"""
check_duplicate.py
Checks whether a Reel has already been uploaded. Optionally marks it as uploaded.
Usage (check):  python tools/check_duplicate.py "reel_id"
Usage (mark):   python tools/check_duplicate.py "reel_id" --mark-uploaded [--hashtag "facts"]
Log file: .tmp/uploaded_log.json
"""

import json
import os
import sys
from datetime import datetime, timezone

TMP_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))


def _log_path(account: str = "default") -> str:
    return os.path.join(TMP_BASE, account, "uploaded_log.json")


def _load_log(account: str = "default") -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(data: dict, account: str = "default") -> None:
    """Atomic write: write to .tmp file then rename."""
    path = _log_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def is_duplicate(reel_id: str, account: str = "default") -> bool:
    log = _load_log(account)
    uploaded_ids = {entry["reel_id"] for entry in log.get("uploaded", [])}
    return reel_id in uploaded_ids


def mark_uploaded(reel_id: str, hashtag: str = "", account: str = "default",
                  ig_media_id: str = "", yt_views: int = 0,
                  caption: str = "", owner_username: str = "") -> None:
    log = _load_log(account)
    log["uploaded"].append({
        "reel_id":        reel_id,
        "uploaded_at":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hashtag":        hashtag,
        "ig_media_id":    ig_media_id,
        "yt_views":       yt_views,
        "caption":        caption,
        "owner_username": owner_username,
    })
    _save_log(log, account)


def check_duplicate(reel_id: str, do_mark: bool = False, hashtag: str = "", account: str = "default") -> dict:
    log_file = _log_path(account)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    already = is_duplicate(reel_id, account)

    if do_mark and not already:
        mark_uploaded(reel_id, hashtag, account)
        log = _load_log(account)
        total = len(log["uploaded"])
        print(f"  [OK] Marked as uploaded: {reel_id}", flush=True)
    else:
        log = _load_log(account)
        total = len(log.get("uploaded", []))

    if already:
        print(f"  [SKIP] Already uploaded: {reel_id}", flush=True)

    return {
        "reel_id":          reel_id,
        "already_uploaded": already,
        "log_file":         log_file,
        "total_uploaded":   total
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/check_duplicate.py \"reel_id\" [--mark-uploaded] [--hashtag \"facts\"] [--account \"factsflash\"]")
        sys.exit(1)

    reel_id = sys.argv[1]
    do_mark = "--mark-uploaded" in sys.argv
    hashtag = ""
    account = "default"
    if "--hashtag" in sys.argv:
        idx = sys.argv.index("--hashtag")
        if idx + 1 < len(sys.argv):
            hashtag = sys.argv[idx + 1]
    if "--account" in sys.argv:
        idx = sys.argv.index("--account")
        if idx + 1 < len(sys.argv):
            account = sys.argv[idx + 1]

    result = check_duplicate(reel_id, do_mark, hashtag, account)
    print(json.dumps(result, indent=2))
