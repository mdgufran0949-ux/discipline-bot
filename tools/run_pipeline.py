"""
run_pipeline.py
Master orchestrator — finds trending Reels, brands them, uploads to Instagram.
Auto-selects the best-performing hashtag based on past view counts.

Usage:
  python tools/run_pipeline.py                              # uses factsflash account
  python tools/run_pipeline.py --account factsflash
  python tools/run_pipeline.py --account fitness --count 5
  python tools/run_pipeline.py --hashtag "amazingfacts" --count 10

Account configs live in: config/accounts/<account_name>.json
"""

import json
import os
import sys
import argparse
import datetime
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import requests
import subprocess as _subprocess
from fetch_reels        import fetch_reels
from download_reel      import download_reel
from brand_reel         import brand_reel, FFPROBE
from check_duplicate    import is_duplicate, mark_uploaded
from upload_reel        import upload_reel
from fetch_profile_pic  import get_owner_pic, get_my_pic
from find_hashtags      import find_hashtags
from monitor_reels      import monitor_reels
from quality_gate       import quality_gate_check

MIN_DURATION = 10

CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))


# ── Account config ─────────────────────────────────────────────

def load_account(account_name: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account_name}.json")
    if not os.path.exists(path):
        print(f"  [FATAL] Account config not found: {path}", flush=True)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Token validation ───────────────────────────────────────────

def check_token(ig_user_id: str, ig_access_token: str, account_name: str) -> None:
    if not ig_access_token or not ig_user_id:
        print(f"  [FATAL] Missing IG credentials in config/accounts/{account_name}.json", flush=True)
        sys.exit(1)
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{ig_user_id}",
        params={"fields": "id", "access_token": ig_access_token},
        timeout=10
    )
    data = resp.json()
    if "error" in data:
        code = data["error"].get("code")
        if code == 190:
            print(f"\n  [FATAL] Token EXPIRED for account: {account_name}", flush=True)
            print(f"  Fix: Generate a new token at developers.facebook.com/tools/explorer", flush=True)
            print(f"       Update ig_access_token in config/accounts/{account_name}.json\n", flush=True)
            sys.exit(1)


# ── Log helpers ────────────────────────────────────────────────

def log_path(account_name: str) -> str:
    return os.path.join(TMP_BASE, account_name, "uploaded_log.json")


def load_log(account_name: str) -> dict:
    path = log_path(account_name)
    if not os.path.exists(path):
        return {"uploaded": [], "hashtag_stats": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "hashtag_stats" not in data:
        data["hashtag_stats"] = {}
    return data


def save_log(data: dict, account_name: str) -> None:
    path = log_path(account_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def update_hashtag_stats(log: dict, hashtag: str, view_counts: list) -> None:
    if not view_counts:
        return
    stats    = log.setdefault("hashtag_stats", {})
    existing = stats.get(hashtag, {"runs": 0, "avg_views": 0})
    old_runs, old_avg = existing["runs"], existing["avg_views"]
    new_avg      = sum(view_counts) / len(view_counts)
    combined_avg = ((old_avg * old_runs) + new_avg) / (old_runs + 1)
    stats[hashtag] = {"runs": old_runs + 1, "avg_views": round(combined_avg)}


# ── Cleanup ────────────────────────────────────────────────────

def cleanup(file_path: str) -> None:
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass


# ── Hashtag auto-refresh ───────────────────────────────────────

HASHTAG_REFRESH_DAYS = 7   # re-fetch hashtags every 7 days


def _refresh_hashtags_if_needed(cfg: dict, account_name: str) -> list:
    """
    If account has a 'niche' field and hashtags are >7 days old (or missing),
    auto-refresh hashtag_pool using find_hashtags and save back to config.
    """
    niche = cfg.get("niche", "").strip()
    if not niche:
        return cfg.get("hashtag_pool", [])

    last_updated = cfg.get("hashtag_last_updated", "")
    needs_refresh = True
    if last_updated:
        try:
            last_dt   = datetime.datetime.fromisoformat(last_updated)
            days_old  = (datetime.datetime.now() - last_dt).days
            needs_refresh = days_old >= HASHTAG_REFRESH_DAYS
        except Exception:
            pass

    if not needs_refresh:
        return cfg.get("hashtag_pool", [])

    print(f"  [HASHTAGS] Refreshing for niche: '{niche}' ...", flush=True)
    tags = find_hashtags(niche, top_n=12)
    if not tags:
        print("  [HASHTAGS] Could not fetch hashtags — using existing pool.", flush=True)
        return cfg.get("hashtag_pool", [])

    cfg["hashtag_pool"]         = tags
    cfg["hashtag_last_updated"] = datetime.datetime.now().isoformat()

    path = os.path.join(CONFIG_DIR, f"{account_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"  [HASHTAGS] Updated pool: {tags}\n", flush=True)
    return tags


# ── Caption rotation ───────────────────────────────────────────

def _pick_caption(cfg: dict) -> str:
    """Pick caption by day of week from caption_templates, or fall back to caption_template."""
    templates = cfg.get("caption_templates")
    if templates and isinstance(templates, list) and len(templates) > 0:
        day_index = datetime.datetime.now().weekday()  # 0=Monday, 6=Sunday
        return templates[day_index % len(templates)]
    return cfg.get("caption_template", "")


# ── Main pipeline ──────────────────────────────────────────────

def run_pipeline(account_name: str, hashtag: str | None, count: int) -> None:
    cfg = load_account(account_name)

    ig_user_id      = cfg["ig_user_id"]
    ig_access_token = cfg["ig_access_token"]
    page_name       = cfg["ig_page_name"]
    hashtag_pool    = _refresh_hashtags_if_needed(cfg, account_name)
    caption_tmpl    = _pick_caption(cfg)
    min_reel_views  = cfg.get("min_reel_views", 200_000)

    check_token(ig_user_id, ig_access_token, account_name)

    # Weekly performance monitor — updates content_preferences in config
    monitor_reels(account_name, cfg, ig_user_id, ig_access_token, silent=True)

    # Fetch user's own page profile pic once (cached after first run)
    my_pic_path = get_my_pic(ig_user_id, ig_access_token, account_name)

    log = load_log(account_name)

    min_views      = min_reel_views
    total_uploaded = 0
    total_skipped  = 0
    total_failed   = 0
    total_views    = []

    MAX_VIEW_ROUNDS = 3   # round 1: full threshold, round 2: half, round 3: 50k floor

    for view_round in range(MAX_VIEW_ROUNDS):
        if view_round > 0:
            min_views = max(50_000, min_views // 2)
            print(f"  [AUTO-FIX] Lowering min views to {min_views:,}\n", flush=True)

        tags_to_try = [hashtag] if hashtag is not None else hashtag_pool

        print(f"\n{'='*55}", flush=True)
        print(f"  {account_name} | {len(tags_to_try)} hashtag(s) | min {min_views:,} views", flush=True)
        print(f"  Target: {count} Reels | Page: {page_name}", flush=True)
        print(f"{'='*55}\n", flush=True)

        print("[1] Fetching trending Reels...", flush=True)
        try:
            result = fetch_reels(tags_to_try, max(count * 6, 50),
                                 ig_user_id=ig_user_id, ig_access_token=ig_access_token)
        except Exception as e:
            print(f"  [AUTO-FIX] Fetch failed ({e}). Trying next round...\n", flush=True)
            continue
        reels = result["reels"]
        print(f"    Found {len(reels)} Reels\n", flush=True)

        # Strict niche filter — require at least one keyword, exclude wrong-niche keywords
        require_kws = [k.lower() for k in cfg.get("niche_require", [])]
        exclude_kws = [k.lower() for k in cfg.get("niche_exclude", [])]
        if require_kws or exclude_kws:
            before   = len(reels)
            filtered = []
            for r in reels:
                caption = (r.get("caption") or "").lower()
                if require_kws and not any(kw in caption for kw in require_kws):
                    continue
                if exclude_kws and any(kw in caption for kw in exclude_kws):
                    continue
                filtered.append(r)
            if filtered:
                print(f"    Niche filter: {before} -> {len(filtered)} relevant reels\n", flush=True)
                reels = filtered

        # Apply learned avoid keywords from performance monitoring (sanity-checked)
        avoid_learned = [
            k.lower() for k in cfg.get("content_preferences", {}).get("avoid_keywords", [])
            if k.isalpha() and len(k) >= 4
        ]
        if avoid_learned and reels:
            before = len(reels)
            reels = [r for r in reels
                     if not any(kw in (r.get("caption") or "").lower() for kw in avoid_learned)]
            if len(reels) < before:
                print(f"    Learned filter: {before} -> {len(reels)} reels\n", flush=True)

        batch_label = tags_to_try[0] if len(tags_to_try) == 1 else "batch"
        uploaded, skipped, failed, view_counts = _process_reels(
            reels, count - total_uploaded, batch_label, log, min_views,
            page_name, caption_tmpl, account_name, ig_user_id, ig_access_token,
            my_pic_path, cfg
        )

        total_uploaded += uploaded
        total_skipped  += skipped
        total_failed   += failed
        total_views    += view_counts

        log = load_log(account_name)
        update_hashtag_stats(log, batch_label, view_counts)
        save_log(log, account_name)

        if total_uploaded >= count:
            break

        print(f"  [INFO] {total_uploaded}/{count} uploaded after round {view_round + 1}.\n", flush=True)

    _print_summary(account_name, total_uploaded, count, total_skipped, total_failed, total_views)


def _process_reels(reels, count, hashtag, log, min_views,
                   page_name, caption_tmpl, account_name, ig_user_id, ig_access_token,
                   my_pic_path=None, cfg=None):
    uploaded    = 0
    skipped     = 0
    failed      = 0
    view_counts = []

    for i, reel in enumerate(reels, 1):
        if uploaded >= count:
            break

        reel_id   = reel["id"]
        video_url = reel["video_url"]
        post_url  = reel.get("post_url")
        owner     = reel.get("owner_username", "")
        views     = reel.get("view_count", 0)

        print(f"-- Reel {i}/{len(reels)} ---------------------------------", flush=True)
        print(f"   @{owner} | {views:,} views", flush=True)

        if views < min_views:
            print(f"   [SKIP] Only {views:,} views (min {min_views:,})\n", flush=True)
            skipped += 1
            continue

        caption_text = reel.get("caption", "")
        if caption_text:
            non_ascii = sum(1 for c in caption_text if ord(c) > 127)
            if len(caption_text) > 20 and non_ascii / len(caption_text) > 0.4:
                print(f"   [SKIP] Non-English content detected.\n", flush=True)
                skipped += 1
                continue

        duration = reel.get("duration", 999)
        if duration < MIN_DURATION:
            print(f"   [SKIP] Too short ({duration}s)\n", flush=True)
            skipped += 1
            continue

        # Duplicate check last — only for reels that pass all quality filters
        if is_duplicate(reel_id, account_name):
            print(f"   [SKIP] Already uploaded.\n", flush=True)
            skipped += 1
            continue

        raw_path = brand_path = None
        try:
            print(f"   [2] Downloading...", flush=True)
            dl       = download_reel(video_url, reel_id, post_url)
            raw_path = dl["file"]

            # Resolution check — skip videos below 720p
            try:
                _probe   = _subprocess.run(
                    [FFPROBE, "-v", "quiet", "-print_format", "json",
                     "-show_streams", raw_path],
                    capture_output=True, text=True, timeout=10
                )
                _streams = json.loads(_probe.stdout).get("streams", [])
                _height  = next(
                    (s.get("height", 0) for s in _streams if s.get("codec_type") == "video"), 0
                )
                if _height > 0 and _height < 720:
                    print(f"   [SKIP] Low resolution ({_height}p < 720p)\n", flush=True)
                    skipped += 1
                    cleanup(raw_path)
                    raw_path = None
                    continue
            except Exception:
                pass   # ffprobe failed — proceed anyway

            # Quality gate — AI check: audio language + visual energy + creator diversity
            print(f"   [QG] Checking content quality...", flush=True)
            qg = quality_gate_check(raw_path, reel, cfg or {}, account_name, log)
            if not qg["passed"]:
                print(f"   [SKIP] Quality gate: {qg['reason']}\n", flush=True)
                skipped += 1
                cleanup(raw_path)
                raw_path = None
                continue
            print(f"   [QG] Passed (score {qg['score']}/100)\n", flush=True)

            print(f"   [3] Adding {page_name} branding...", flush=True)
            owner_pic_path = get_owner_pic(owner)
            br             = brand_reel(raw_path, page_name, owner, owner_pic_path, my_pic_path, post_url=post_url)
            brand_path = br["output"]

            # Quality check — skip suspiciously small branded files
            brand_size_mb = os.path.getsize(brand_path) / (1024 * 1024)
            if brand_size_mb < 0.5:
                print(f"   [SKIP] Branded file too small ({brand_size_mb:.1f}MB) — likely corrupt\n", flush=True)
                skipped += 1
                cleanup(brand_path)
                brand_path = None
                continue

            post_caption = caption_tmpl.format(page=page_name.lstrip("@")).strip()

            print(f"   [4] Uploading to Instagram...", flush=True)
            up = upload_reel(brand_path, post_caption, ig_user_id, ig_access_token)
            print(f"   [OK] Live: {up.get('permalink', 'N/A')}\n", flush=True)

            mark_uploaded(reel_id, hashtag, account_name,
                          ig_media_id=up.get("ig_media_id", ""),
                          yt_views=views,
                          caption=reel.get("caption", ""),
                          owner_username=owner)
            view_counts.append(views)
            uploaded += 1

            if uploaded < count:
                print(f"   [WAIT] Pausing 3 minutes before next upload...", flush=True)
                time.sleep(180)

        except Exception as e:
            print(f"   [ERROR] {e}\n", flush=True)
            failed += 1
        finally:
            cleanup(raw_path)
            cleanup(brand_path)

    return uploaded, skipped, failed, view_counts


def _print_summary(account_name, uploaded, count, skipped, failed, view_counts=[]):
    avg = round(sum(view_counts) / len(view_counts)) if view_counts else 0
    print(f"\n{'='*55}", flush=True)
    print(f"  [{account_name}] Done!", flush=True)
    print(f"  Uploaded  : {uploaded}/{count}", flush=True)
    print(f"  Skipped   : {skipped}", flush=True)
    print(f"  Failed    : {failed}", flush=True)
    print(f"  Avg views : {avg:,}", flush=True)
    print(f"{'='*55}\n", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram Reels Pipeline")
    parser.add_argument("--account", default="factsflash", help="Account name (config/accounts/<name>.json)")
    parser.add_argument("--hashtag", default=None,         help="Force a specific hashtag (default: auto-select)")
    parser.add_argument("--count",   default=None, type=int, help="Reels to upload (default: from account config)")
    args = parser.parse_args()

    cfg   = load_account(args.account)
    count = args.count or cfg.get("reels_per_day", 10)
    run_pipeline(args.account, args.hashtag, count)
