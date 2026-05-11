"""
reply_bot.py
Self-reply engagement bot for DisciplineFuel.

Fetches comments on our own posts (last 48h), generates 5-15 word replies,
and posts them via Instagram Graph API.

Usage:
  python tools/reply_bot.py --account disciplinefuel [--dry-run]

Output:
  .tmp/<account>/engagement_log.json  — append-mode log of replies sent
"""

import argparse
import json
import os
import re
import sys
import time
import random
import datetime
import unicodedata
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

try:
    import requests
except ImportError:
    print("[FATAL] requests not installed", flush=True)
    sys.exit(1)

GRAPH_BASE = "https://graph.facebook.com/v19.0"
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

KILL_SWITCH_PATH = os.path.join(REPO_ROOT, "PAUSE_ENGAGEMENT")

# Reply ramp schedule: (days_since_start, daily_cap)
RAMP_SCHEDULE = [
    (7,  5),
    (14, 8),
    (21, 12),
    (999, 15),
]
HARD_CAP = 50

NEAR_DUP_WINDOW  = 50   # compare against last N replies
NEAR_DUP_THRESH  = 0.80 # similarity ratio for near-duplicate
CONSEC_FAIL_MAX  = 3    # abort cycle after N consecutive API failures
SLEEP_MIN_SEC    = 60   # 1 min between replies
SLEEP_MAX_SEC    = 240  # 4 min between replies
COMMENT_LOOKBACK_H = 48 # only process comments from last 48h


def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _log_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "engagement_log.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"replies": [], "stats": {}}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"replies": [], "stats": {}}


def _save_log(account: str, log: dict) -> None:
    path = _log_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, path)


def _daily_cap(ramp_start: str) -> int:
    if not ramp_start:
        return RAMP_SCHEDULE[0][1]
    start = datetime.datetime.fromisoformat(ramp_start)
    days  = (datetime.datetime.now() - start).days
    for threshold, cap in RAMP_SCHEDULE:
        if days < threshold:
            return cap
    return RAMP_SCHEDULE[-1][1]


def _replies_today(log: dict) -> int:
    today = datetime.date.today().isoformat()
    return sum(
        1 for r in log.get("replies", [])
        if r.get("timestamp", "")[:10] == today and r.get("status") == "sent"
    )


def _replied_comment_ids(log: dict) -> set:
    return {r["comment_id"] for r in log.get("replies", []) if r.get("comment_id")}


def _recent_reply_texts(log: dict) -> list:
    sent = [r for r in log.get("replies", []) if r.get("status") == "sent"]
    return [r["reply_text"] for r in sent[-NEAR_DUP_WINDOW:]]


def _is_near_duplicate(text: str, recent: list) -> bool:
    for prev in recent:
        ratio = SequenceMatcher(None, text.lower(), prev.lower()).ratio()
        if ratio >= NEAR_DUP_THRESH:
            return True
    return False


def _is_spam_comment(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) <= 2:
        return True
    all_emoji = all(
        unicodedata.category(c) in ("So", "Sm", "Sk", "Zs") or c in ("❤", "🔥", "💯")
        for c in stripped if not c.isspace()
    )
    if all_emoji:
        return True
    word_count = len(stripped.split())
    if word_count == 1 and not stripped.startswith("@"):
        return True
    spam_patterns = [
        r"follow\s*(back|me|for)",
        r"check\s*(out\s*)?my",
        r"f4f",
        r"l4l",
        r"dm\s*(me|for)",
        r"link\s*in\s*(bio|my)",
    ]
    low = stripped.lower()
    for pat in spam_patterns:
        if re.search(pat, low):
            return True
    return False


def _is_mention(text: str, our_username: str) -> bool:
    return f"@{our_username.lstrip('@').lower()}" in text.lower()


# ── LLM call ─────────────────────────────────────────────────────────────────

_REPLY_SYSTEM = (
    "You write short Instagram replies for @DisciplineFuel, a dark-aesthetic "
    "discipline/motivation page. Replies must be 5-15 words, lowercase except "
    "proper nouns, no hashtags, no emojis, no filler. Sound like a real human "
    "who lives by the grind — brief, direct, authentic."
)

_PROVIDERS = [
    {"name": "openrouter", "key_env": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "meta-llama/llama-3.3-70b-instruct"},
    {"name": "groq",       "key_env": "GROQ_API_KEY",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": "llama-3.3-70b-versatile"},
    {"name": "gemini",     "key_env": "GEMINI_API_KEY",
     "url": None,  # handled separately
     "model": "gemini-2.0-flash"},
]


def _llm_reply(post_caption: str, comment_text: str) -> str:
    prompt = (
        f"Post caption (context only): \"{post_caption[:120]}\"\n"
        f"Comment to reply to: \"{comment_text[:200]}\"\n\n"
        "Write ONE reply, 5-15 words, no hashtags, no emojis. "
        "Output ONLY the reply text, nothing else."
    )

    for provider in _PROVIDERS:
        key = os.getenv(provider["key_env"], "")
        if not key:
            continue
        try:
            if provider["name"] == "gemini":
                import google.generativeai as genai
                genai.configure(api_key=key)
                model = genai.GenerativeModel(
                    provider["model"],
                    system_instruction=_REPLY_SYSTEM,
                )
                resp = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.75, "max_output_tokens": 60},
                )
                text = resp.text.strip()
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {
                    "model":       provider["model"],
                    "messages":    [
                        {"role": "system", "content": _REPLY_SYSTEM},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.75,
                    "max_tokens":  60,
                }
                r = requests.post(provider["url"], headers=headers, json=payload, timeout=20)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"].strip()

            text = re.sub(r'^["\'](.*)["\']$', r'\1', text).strip()
            words = text.split()
            if 5 <= len(words) <= 20:
                return text
        except Exception as exc:
            print(f"[WARN] LLM provider {provider['name']} failed: {exc}", flush=True)
            continue

    return "keep showing up. every rep counts."


def generate_reply(my_post_text: str, commenter_text: str) -> str:
    """Generate a 5-15 word reply. Public API for testing."""
    return _llm_reply(my_post_text, commenter_text)


# ── Instagram API helpers ─────────────────────────────────────────────────────

def _ig_get(path: str, params: dict, token: str) -> dict:
    params["access_token"] = token
    r = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("RATE_LIMITED")
    r.raise_for_status()
    return r.json()


def _ig_post(path: str, params: dict, token: str) -> dict:
    params["access_token"] = token
    r = requests.post(f"{GRAPH_BASE}/{path}", params=params, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("RATE_LIMITED")
    r.raise_for_status()
    return r.json()


def _fetch_recent_media(user_id: str, token: str) -> list:
    data = _ig_get(
        f"{user_id}/media",
        {"fields": "id,caption,timestamp", "limit": 20},
        token,
    )
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=COMMENT_LOOKBACK_H)
    results = []
    for item in data.get("data", []):
        ts_str = item.get("timestamp", "")
        try:
            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                results.append(item)
        except ValueError:
            results.append(item)
    return results


def _fetch_comments(media_id: str, token: str) -> list:
    data = _ig_get(
        f"{media_id}/comments",
        {"fields": "id,text,timestamp,username,replies{id,username}", "limit": 50},
        token,
    )
    return data.get("data", [])


def _post_reply(comment_id: str, message: str, token: str) -> dict:
    return _ig_post(
        f"{comment_id}/replies",
        {"message": message},
        token,
    )


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_reply_cycle(account: str, dry_run: bool = False) -> dict:
    """
    Main entry point. Returns a summary dict:
      {"sent": int, "skipped": int, "errors": int, "dry_run": bool}
    """
    # Kill switch check
    if os.path.exists(KILL_SWITCH_PATH):
        print(f"[PAUSED] Kill switch active: {KILL_SWITCH_PATH}", flush=True)
        return {"sent": 0, "skipped": 0, "errors": 0, "dry_run": dry_run, "paused": True}

    cfg = _load_config(account)
    eng = cfg.get("engagement", {})

    if not eng.get("enabled", False):
        print("[SKIP] Engagement bot disabled in config (engagement.enabled = false)", flush=True)
        return {"sent": 0, "skipped": 0, "errors": 0, "dry_run": dry_run, "disabled": True}

    token      = cfg.get("ig_access_token", "")
    user_id    = cfg.get("ig_user_id", "")
    page_name  = cfg.get("ig_page_name", "@DisciplineFuel")
    our_handle = page_name.lstrip("@").lower()

    ramp_start  = eng.get("ramp_start_date")
    reply_min   = eng.get("reply_min_words", 5)
    reply_max   = eng.get("reply_max_words", 15)
    cap         = min(_daily_cap(ramp_start), HARD_CAP)

    log         = _load_log(account)
    sent_today  = _replies_today(log)
    replied_ids = _replied_comment_ids(log)
    recent_texts = _recent_reply_texts(log)

    print(f"[START] reply_bot — account={account} cap={cap} sent_today={sent_today} dry_run={dry_run}", flush=True)

    if sent_today >= cap:
        print(f"[DONE] Daily cap reached ({sent_today}/{cap})", flush=True)
        return {"sent": 0, "skipped": 0, "errors": 0, "dry_run": dry_run, "cap_reached": True}

    sent      = 0
    skipped   = 0
    errors    = 0
    consec_fail = 0

    try:
        media_list = _fetch_recent_media(user_id, token)
    except RuntimeError as e:
        if "RATE_LIMITED" in str(e):
            print("[ABORT] Rate limited on media fetch", flush=True)
        else:
            print(f"[ABORT] Media fetch failed: {e}", flush=True)
        return {"sent": 0, "skipped": 0, "errors": 1, "dry_run": dry_run}
    except Exception as e:
        print(f"[ABORT] Media fetch failed: {e}", flush=True)
        return {"sent": 0, "skipped": 0, "errors": 1, "dry_run": dry_run}

    for media in media_list:
        if sent_today + sent >= cap:
            break
        if os.path.exists(KILL_SWITCH_PATH):
            print("[PAUSED] Kill switch detected mid-cycle", flush=True)
            break

        media_id      = media["id"]
        post_caption  = (media.get("caption") or "")[:200]

        try:
            comments = _fetch_comments(media_id, token)
        except RuntimeError as e:
            if "RATE_LIMITED" in str(e):
                print(f"[ABORT] Rate limited on comments for {media_id}", flush=True)
                break
            errors += 1
            consec_fail += 1
            if consec_fail >= CONSEC_FAIL_MAX:
                print(f"[ABORT] {CONSEC_FAIL_MAX} consecutive failures — stopping cycle", flush=True)
                break
            continue
        except Exception as e:
            print(f"[WARN] Comment fetch failed for {media_id}: {e}", flush=True)
            errors += 1
            consec_fail += 1
            if consec_fail >= CONSEC_FAIL_MAX:
                print(f"[ABORT] {CONSEC_FAIL_MAX} consecutive failures — stopping cycle", flush=True)
                break
            continue

        consec_fail = 0

        # Sort oldest-first so we reply in chronological order
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=COMMENT_LOOKBACK_H)
        for comment in sorted(comments, key=lambda c: c.get("timestamp", "")):
            if sent_today + sent >= cap:
                break

            comment_id   = comment["id"]
            comment_text = (comment.get("text") or "").strip()
            commenter    = (comment.get("username") or "").lower()

            # Skip: already replied
            if comment_id in replied_ids:
                skipped += 1
                continue

            # Skip: own account comment
            if commenter == our_handle:
                skipped += 1
                continue

            # Skip: already has a reply from us in nested replies
            nested = comment.get("replies", {}).get("data", [])
            if any(r.get("username", "").lower() == our_handle for r in nested):
                replied_ids.add(comment_id)
                skipped += 1
                continue

            # Skip: spam / pure emoji / single word
            if _is_spam_comment(comment_text):
                skipped += 1
                continue

            # Skip: too old
            ts_str = comment.get("timestamp", "")
            try:
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    skipped += 1
                    continue
            except ValueError:
                pass

            # Generate reply
            reply_text = generate_reply(post_caption, comment_text)

            # Word count guardrail
            word_count = len(reply_text.split())
            if word_count < reply_min or word_count > reply_max + 5:
                words = reply_text.split()
                reply_text = " ".join(words[:reply_max])

            # Near-duplicate check
            if _is_near_duplicate(reply_text, recent_texts):
                reply_text = generate_reply(post_caption, comment_text + " [vary]")
                if _is_near_duplicate(reply_text, recent_texts):
                    print(f"[SKIP] Near-duplicate reply for comment {comment_id}", flush=True)
                    skipped += 1
                    continue

            is_mention = _is_mention(comment_text, our_handle)

            log_entry = {
                "comment_id":     comment_id,
                "media_id":       media_id,
                "commenter":      commenter,
                "comment_text":   comment_text[:200],
                "reply_text":     reply_text,
                "is_mention":     is_mention,
                "timestamp":      datetime.datetime.now().isoformat(),
                "status":         "sent" if not dry_run else "dry_run",
                "ig_reply_id":    None,
            }

            if dry_run:
                print(f"[DRY-RUN] Would reply to @{commenter}: \"{reply_text}\"", flush=True)
                sent += 1
                replied_ids.add(comment_id)
                recent_texts.append(reply_text)
                log["replies"].append(log_entry)
            else:
                try:
                    resp = _post_reply(comment_id, reply_text, token)
                    log_entry["ig_reply_id"] = resp.get("id")
                    log_entry["status"] = "sent"
                    sent += 1
                    consec_fail = 0
                    replied_ids.add(comment_id)
                    recent_texts.append(reply_text)
                    log["replies"].append(log_entry)
                    print(f"[SENT] @{commenter}: \"{reply_text}\"", flush=True)

                    _save_log(account, log)

                    # Sleep between replies (1-4 min)
                    if sent_today + sent < cap:
                        sleep_s = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
                        print(f"[SLEEP] {sleep_s}s before next reply", flush=True)
                        time.sleep(sleep_s)

                except RuntimeError as e:
                    if "RATE_LIMITED" in str(e):
                        print("[ABORT] Rate limited on reply post — stopping cycle", flush=True)
                        log_entry["status"] = "rate_limited"
                        log["replies"].append(log_entry)
                        break
                    errors += 1
                    consec_fail += 1
                    log_entry["status"] = "error"
                    log_entry["error"]  = str(e)
                    log["replies"].append(log_entry)
                    if consec_fail >= CONSEC_FAIL_MAX:
                        print(f"[ABORT] {CONSEC_FAIL_MAX} consecutive failures — stopping cycle", flush=True)
                        break
                except Exception as e:
                    errors += 1
                    consec_fail += 1
                    log_entry["status"] = "error"
                    log_entry["error"]  = str(e)
                    log["replies"].append(log_entry)
                    print(f"[ERROR] Reply to {comment_id} failed: {e}", flush=True)
                    if consec_fail >= CONSEC_FAIL_MAX:
                        print(f"[ABORT] {CONSEC_FAIL_MAX} consecutive failures — stopping cycle", flush=True)
                        break

    # Update stats
    stats = log.setdefault("stats", {})
    stats["total_sent"]   = sum(1 for r in log["replies"] if r.get("status") == "sent")
    stats["last_run"]     = datetime.datetime.now().isoformat()
    stats["last_run_sent"] = sent

    _save_log(account, log)

    print(
        f"[DONE] sent={sent} skipped={skipped} errors={errors} "
        f"total_today={sent_today + sent}/{cap}",
        flush=True,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors, "dry_run": dry_run}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DisciplineFuel self-reply engagement bot")
    parser.add_argument("--account",  default="disciplinefuel")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Generate replies but do not POST to Instagram")
    args = parser.parse_args()

    summary = run_reply_cycle(args.account, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))
