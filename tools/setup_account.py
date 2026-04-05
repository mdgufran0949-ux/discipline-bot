"""
setup_account.py
Creates a new account config with auto-generated niche hashtags.
Run this when adding a new Instagram page to the pipeline.

Usage: python tools/setup_account.py
"""

import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(__file__))

from find_hashtags import find_hashtags

CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))


def setup_account():
    print("\n" + "=" * 55)
    print("  New Account Setup")
    print("=" * 55 + "\n")

    account_name    = input("  Account name (slug, e.g. fitnessfacts):     ").strip().lower()
    ig_user_id      = input("  Instagram User ID:                           ").strip()
    ig_access_token = input("  Instagram Access Token (60-day preferred):   ").strip()
    ig_page_name    = input("  Page name with @ (e.g. @FitnessFacts):       ").strip()
    niche           = input("  Niche description (e.g. fitness body facts):  ").strip()
    min_views       = input("  Min reel views (default 300000):             ").strip()
    reels_per_day   = input("  Reels per day (default 10):                  ").strip()
    caption_extra   = input("  Extra caption hashtags (optional):           ").strip()

    min_views     = int(min_views)     if min_views.isdigit()     else 300_000
    reels_per_day = int(reels_per_day) if reels_per_day.isdigit() else 10
    page_slug     = ig_page_name.lstrip("@")

    print(f"\n  Finding best hashtags for niche: '{niche}'...")
    hashtags = find_hashtags(niche, top_n=12)
    if not hashtags:
        print("  [WARN] Could not auto-fetch hashtags. Using niche words as fallback.")
        hashtags = [w.lower() for w in niche.split() if len(w) >= 4][:8]

    caption_tmpl = (
        f"Follow @{page_slug} for daily facts! \U0001f92f\n\n"
        f"#{page_slug.lower()} #facts #viral #trending #didyouknow"
    )
    if caption_extra:
        caption_tmpl += " " + caption_extra

    cfg = {
        "account_name":         account_name,
        "niche":                niche,
        "ig_user_id":           ig_user_id,
        "ig_access_token":      ig_access_token,
        "ig_page_name":         ig_page_name,
        "hashtag_pool":         hashtags,
        "hashtag_last_updated": datetime.datetime.now().isoformat(),
        "caption_template":     caption_tmpl,
        "reels_per_day":        reels_per_day,
        "min_reel_views":       min_views
    }

    os.makedirs(CONFIG_DIR, exist_ok=True)
    path = os.path.join(CONFIG_DIR, f"{account_name}.json")

    if os.path.exists(path):
        overwrite = input(f"\n  Config already exists for '{account_name}'. Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            print("  Cancelled.")
            return

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"\n  Account config saved: {path}")
    print(f"\n  Hashtag pool ({len(hashtags)}):")
    for tag in hashtags:
        print(f"    #{tag}")
    print(f"\n  Run pipeline:")
    print(f"    python tools/run_pipeline.py --account {account_name} --count 10")
    print("\n" + "=" * 55)


if __name__ == "__main__":
    setup_account()
