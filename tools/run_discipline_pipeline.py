"""
run_discipline_pipeline.py
Master Orchestrator for DisciplineFuel Instagram Growth Pipeline.

Runs the full content loop N times per execution:
  Trend Awareness → Memory Check → Quote Engine → Image Gen → Canva Design → Upload → Log → Learn

Usage:
  python tools/run_discipline_pipeline.py --count 3
  python tools/run_discipline_pipeline.py --count 1 --dry-run
  python tools/run_discipline_pipeline.py --count 9 --account disciplinefuel

Scheduled 3x/day via run_disciplinefuel.bat
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

# Import all pipeline tools
import fetch_discipline_trends  as trends_tool
import discipline_memory        as memory_tool
import generate_discipline_quote as quote_tool
import generate_discipline_image as image_tool
import generate_canva_post       as canva_tool
import upload_image_post         as upload_tool
import review_and_upgrade        as review_tool

SLEEP_BETWEEN_POSTS = 180   # 3 minutes (same as run_pipeline.py)
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))


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


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(account: str, log: dict) -> None:
    path = _log_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, path)


def _pick_caption(cfg: dict, page_name: str, hashtags: list, llm_caption: str) -> str:
    """Use the LLM-generated caption if available, else pick from templates."""
    if llm_caption and len(llm_caption) > 20:
        # Append hashtags if not already in caption
        hashtag_str = " ".join(f"#{h}" for h in hashtags[:15])
        if "#" not in llm_caption:
            return llm_caption.strip() + f"\n\n{hashtag_str}"
        return llm_caption.strip()
    templates = cfg.get("caption_templates", [])
    if templates:
        return random.choice(templates)
    return f"Save this. @{page_name.lstrip('@')}\n\n" + " ".join(f"#{h}" for h in hashtags[:10])


def _series_label(series_type: str, series_number: int) -> str:
    labels = {
        "discipline_rule":     f"Discipline Rule #{series_number}",
        "wake_up_call":        f"Wake Up Call #{series_number}",
        "day_becoming_better": f"Day {series_number} of Becoming Better"
    }
    return labels.get(series_type, f"#{series_number}")


def _check_token(ig_user_id: str, ig_access_token: str) -> bool:
    if not ig_user_id or not ig_access_token:
        return False
    return True


# ── Main pipeline loop ─────────────────────────────────────────────────────────

def run_pipeline(account: str = "disciplinefuel", count: int = 3, dry_run: bool = False) -> None:
    print(f"\n{'='*55}", flush=True)
    print(f"DISCIPLINEFUEL PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    print(f"Posts: {count} | Dry run: {dry_run}", flush=True)
    print(f"{'='*55}\n", flush=True)

    cfg = _load_config(account)
    ig_user_id      = cfg.get("ig_user_id", "")
    ig_access_token = cfg.get("ig_access_token", "")

    if not dry_run and not _check_token(ig_user_id, ig_access_token):
        print("[ERROR] No IG credentials. Add ig_user_id + ig_access_token to disciplinefuel.json and re-run.", flush=True)
        sys.exit(1)

    # ── Step 1: Daily review (runs silently if < 1 day since last run)
    print("[1/8] Checking weekly review...", flush=True)
    review_tool.run_review(account, force=False)

    # ── Step 2: Fetch trends (cached 24h)
    print("\n[2/8] Fetching discipline trends...", flush=True)
    try:
        trend_data   = trends_tool.fetch_discipline_trends(count=10)
        hot_keywords = trend_data.get("hot_keywords", [])
        trend_topics = trend_data.get("trending_topics", [])
    except Exception as e:
        print(f"  [WARN] Trends fetch failed: {e}. Using evergreen topics.", flush=True)
        hot_keywords = ["discipline", "scared", "comfort", "clock", "broke"]
        trend_topics = []

    # ── Step 3: Get memory weights (self-improving)
    print("\n[3/8] Loading memory + content weights...", flush=True)
    weights      = memory_tool.get_content_weights()
    prompt_hints = memory_tool.get_prompt_hints()

    log = _load_log(account)
    results = []
    used_topics = set()

    # Clean trend topics — strip hashtags/symbols that bleed in from YouTube titles
    def _clean_topic(t: str) -> str:
        import re
        # Cut off at first hashtag or @ symbol
        t = re.split(r'[#@]', t)[0]
        # Remove punctuation noise, normalize spaces
        t = re.sub(r'[^\w\s]', ' ', t).strip()
        t = re.sub(r'\s+', ' ', t).strip().lower()
        return t

    clean_trend_topics = [_clean_topic(t) for t in trend_topics if _clean_topic(t)]

    for i in range(count):
        print(f"\n{'─'*45}", flush=True)
        print(f"POST {i+1}/{count}", flush=True)
        print(f"{'─'*45}", flush=True)

        # ── Step 4: Pick topic — rotate, never repeat within same run
        avoid_topics = memory_tool._load()["patterns"]["avoid_topics"]
        topic_pool = clean_trend_topics + cfg.get("content_topics", [])
        topic = ""
        for t in topic_pool:
            if t.lower() not in [a.lower() for a in avoid_topics] and t.lower() not in used_topics:
                topic = t
                break
        if not topic:
            # All topics used — pick least-recently used from config
            for t in cfg.get("content_topics", []):
                if t.lower() not in used_topics:
                    topic = t
                    break
        if not topic:
            topic = random.choice(cfg.get("content_topics", ["discipline is the only shortcut"]))
        used_topics.add(topic.lower())

        # ── Step 5: Pick series + design style
        series_rotation = cfg.get("series_rotation", ["discipline_rule", "wake_up_call", "day_becoming_better"])
        series_idx      = cfg.get("series_index", 0) % len(series_rotation)
        series_type     = series_rotation[series_idx]
        series_num      = cfg["series_counters"][series_type] + 1

        design_style = memory_tool.weighted_choice(weights["design_style"])
        fmt          = memory_tool.weighted_choice(weights["format"])

        # Skip recently-used topic (check last 30 posts in memory)
        if memory_tool.should_avoid(topic=topic):
            for t in topic_pool[1:]:
                if t != topic and t.lower() not in [a.lower() for a in avoid_topics]:
                    topic = t
                    break

        print(f"  Topic:        {topic}", flush=True)
        print(f"  Series:       {_series_label(series_type, series_num)}", flush=True)
        print(f"  Style:        {design_style}", flush=True)
        print(f"  Format:       {fmt}", flush=True)

        try:
            # ── Step 6: Generate quote payload
            print("\n[4/8] Generating quotes...", flush=True)
            payload = quote_tool.generate_discipline_quote(
                topic=topic,
                series_type=series_type,
                series_number=series_num,
                design_style=design_style,
                hot_keywords=hot_keywords,
                prompt_hints=prompt_hints
            )

            selected_quote = payload["selected_quote"]
            fmt            = payload.get("format", fmt)  # LLM may suggest format
            series_label   = _series_label(series_type, series_num)  # Always use formatted label, not LLM text
            image_prompt   = payload["image_prompt"]

            print(f"  Quote: {selected_quote[:70]}...", flush=True)

            # ── Step 7: Generate image(s)
            print("\n[5/8] Generating image(s)...", flush=True)
            bg_image_paths = []
            if fmt == "carousel":
                # Generate 4 slides
                carousel_slides = [{"quote": payload["selected_quote"], "series_label": series_label}]
                # Generate 3 more quotes fast (Groq) for remaining slides
                for j in range(3):
                    try:
                        extra = quote_tool.generate_discipline_quote(
                            topic=topic, series_type=series_type,
                            series_number=series_num, design_style=design_style,
                            hot_keywords=hot_keywords
                        )
                        carousel_slides.append({"quote": extra["selected_quote"], "series_label": series_label})
                    except Exception:
                        break

                for slide in carousel_slides:
                    img = image_tool.generate_discipline_image(
                        prompt=image_prompt, size="portrait_9_16",
                        design_style=design_style
                    )
                    bg_image_paths.append(img["file"])
            else:
                img = image_tool.generate_discipline_image(
                    prompt=image_prompt, size="portrait_9_16",
                    design_style=design_style
                )
                bg_image_paths = [img["file"]]

            # ── Step 8: Design (Canva + Pillow fallback)
            print("\n[6/8] Composing post design...", flush=True)
            if fmt == "carousel":
                composed = canva_tool.generate_canva_carousel(
                    slides=carousel_slides,
                    design_style=design_style,
                    bg_image_paths=bg_image_paths
                )
                output_files = composed["files"]
            else:
                composed = canva_tool.generate_canva_post(
                    quote=selected_quote,
                    series_label=series_label,
                    design_style=design_style,
                    bg_image_path=bg_image_paths[0] if bg_image_paths else None
                )
                output_files = [composed["file"]]

            # ── Step 9: Build caption
            caption = _pick_caption(cfg, cfg.get("ig_page_name", "@DisciplineFuel"),
                                    payload.get("hashtags", []), payload.get("caption", ""))

            # ── Step 10: Upload (skip in dry run)
            print("\n[7/8] Uploading to Instagram...", flush=True)
            ig_media_id = ""
            permalink   = ""

            if dry_run:
                print(f"  [DRY RUN] Would upload {fmt} post: {output_files}", flush=True)
                ig_media_id = f"DRY_{int(time.time())}"
                permalink   = "https://instagram.com/p/dry_run"
            else:
                if fmt == "carousel":
                    result = upload_tool.upload_carousel_post(
                        image_paths=output_files,
                        caption=caption,
                        ig_user_id=ig_user_id,
                        ig_access_token=ig_access_token
                    )
                else:
                    result = upload_tool.upload_image_post(
                        image_path=output_files[0],
                        caption=caption,
                        ig_user_id=ig_user_id,
                        ig_access_token=ig_access_token
                    )
                ig_media_id = result["ig_media_id"]
                permalink   = result["permalink"]

            # ── Step 11: Log to memory + uploaded_log
            print("\n[8/8] Logging to memory...", flush=True)
            log_entry = {
                "id":              f"{series_type}_{series_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "ig_media_id":     ig_media_id,
                "permalink":       permalink,
                "format":          fmt,
                "series":          series_type,
                "series_number":   series_num,
                "content_series":  series_label,
                "topic":           topic,
                "selected_quote":  selected_quote,
                "quote_type":      payload.get("selected_type", ""),
                "hook_keyword":    payload.get("hook_keyword", ""),
                "design_style":    design_style,
                "predicted":       payload.get("predicted_performance", ""),
                "posted_at":       datetime.now().isoformat(),
                "dry_run":         dry_run
            }

            memory_tool.log_post(log_entry)
            log["uploaded"].append(log_entry)
            _save_log(account, log)

            # ── Step 12: Increment counters atomically
            cfg["series_counters"][series_type] = series_num
            cfg["series_index"] = (series_idx + 1) % len(series_rotation)
            cfg["topic_index"]  = (cfg.get("topic_index", 0) + 1) % len(cfg.get("content_topics", [1]))
            _save_config(account, cfg)
            # Reload for next iteration
            cfg = _load_config(account)

            results.append({
                "post": i + 1,
                "status": "dry_run" if dry_run else "published",
                "series": series_label,
                "quote":  selected_quote[:50] + "...",
                "permalink": permalink
            })

            print(f"\n[OK] Post {i+1}/{count} complete — {permalink}", flush=True)

        except Exception as e:
            print(f"\n[ERROR] Post {i+1} failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            results.append({"post": i + 1, "status": "failed", "error": str(e)})

        # ── Rate limit pause between posts
        if i < count - 1:
            print(f"\nWaiting {SLEEP_BETWEEN_POSTS}s before next post...", flush=True)
            time.sleep(SLEEP_BETWEEN_POSTS)

    # ── Summary
    print(f"\n{'='*55}", flush=True)
    print("PIPELINE COMPLETE", flush=True)
    published = sum(1 for r in results if r["status"] in ("published", "dry_run"))
    failed    = sum(1 for r in results if r["status"] == "failed")
    print(f"  Published: {published}/{count}  |  Failed: {failed}", flush=True)
    for r in results:
        status = "✓" if r["status"] in ("published", "dry_run") else "✗"
        print(f"  {status} Post {r['post']}: {r.get('quote','')}", flush=True)
    print(f"{'='*55}\n", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DisciplineFuel Instagram Pipeline")
    parser.add_argument("--account",  default="disciplinefuel")
    parser.add_argument("--count",    type=int, default=3, help="Number of posts to generate")
    parser.add_argument("--dry-run",  action="store_true", help="Generate content but skip upload")
    args = parser.parse_args()

    run_pipeline(
        account=args.account,
        count=args.count,
        dry_run=args.dry_run
    )
