"""
run_product_pipeline.py
Master orchestrator for the Amazon/Flipkart product review Shorts pipeline.

Flow per product:
  1.   fetch_product_deals     -> products.json
  2.   generate_product_script -> script.json   (Groq English)
  2.5. fetch_usecase_media     -> usecase_media.json (Pexels video / FAL.ai image)
  3.   generate_kokoro_tts     -> voiceover.mp3 + captions.srt
  4.   compose_product_video   -> product_video.mp4 (360-degree + use-case + animations)
  5.   quality gate            -> file size + existence check
  6.   upload_reel             -> Instagram Reels
  7.   upload_youtube_short    -> YouTube Shorts

Usage:
  python tools/run_product_pipeline.py --source both --count 2
  python tools/run_product_pipeline.py --source amazon --count 1 --dry-run
"""

import json
import sys
import os
import argparse
import shutil
import subprocess
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = os.path.join(ROOT, ".tmp")
TOOLS = os.path.join(ROOT, "tools")
UPLOAD_LOG = os.path.join(TMP, "product_upload_log.json")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_log() -> dict:
    if os.path.exists(UPLOAD_LOG):
        with open(UPLOAD_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"uploaded": [], "runs": []}


def save_log(log: dict):
    os.makedirs(TMP, exist_ok=True)
    with open(UPLOAD_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def is_duplicate(product: dict, log: dict) -> bool:
    pid = product.get("asin") or product.get("product_url", "")
    return bool(pid) and pid in log.get("uploaded", [])


def mark_uploaded(product: dict, log: dict):
    pid = product.get("asin") or product.get("product_url", "")
    if pid and pid not in log.get("uploaded", []):
        log.setdefault("uploaded", []).append(pid)


def run_tool(script_name: str, args: list) -> dict:
    """Run a tool and return its parsed JSON stdout."""
    cmd = [sys.executable, os.path.join(TOOLS, script_name)] + [str(a) for a in args]
    print(f"  -> {script_name} {' '.join(str(a) for a in args)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        stderr = (result.stderr or "")[-600:]
        raise RuntimeError(f"{script_name} exited {result.returncode}:\n{stderr}")
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout[:200]}
    return {}


def banner(text: str):
    print(f"\n{'='*60}\n{text}\n{'='*60}", flush=True)


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(source: str, count: int, max_price: int,
                 dry_run: bool, skip_instagram: bool, skip_youtube: bool):
    os.makedirs(TMP, exist_ok=True)
    log = load_log()
    mode = "DRY RUN" if dry_run else "LIVE"
    banner(f"PRODUCT PIPELINE  |  source={source}  count={count}  mode={mode}")

    # ── 1. Fetch products ─────────────────────────────────────────────────────
    print("\n[1/7] Fetching trending products...", flush=True)
    products_path = os.path.join(TMP, "products.json")
    run_tool("fetch_product_deals.py", [
        "--source", source,
        "--count", count + 3,       # fetch extra to cover duplicates
        "--max-price", max_price,
        "--output", products_path,
    ])

    with open(products_path, "r", encoding="utf-8") as f:
        all_products = json.load(f)

    print(f"  [OK] {len(all_products)} products fetched", flush=True)

    if not all_products:
        print("[ERROR] No products fetched. Check RAPIDAPI_KEY and internet connection.", flush=True)
        return []

    # Filter duplicates
    fresh = [p for p in all_products if not is_duplicate(p, log)]
    if not fresh:
        print("[WARN] All fetched products were already uploaded. Clearing log to retry...", flush=True)
        log["uploaded"] = []
        save_log(log)
        fresh = all_products

    products = fresh[:count]
    print(f"  [OK] {len(products)} new products to process", flush=True)

    results = []

    for idx, product in enumerate(products):
        print(f"\n{'-'*55}", flush=True)
        print(
            f"Product {idx+1}/{len(products)}: {product['title'][:65]}\n"
            f"Price: Rs.{product['price']}  "
            f"Rating: {product['rating']}  "
            f"Source: {product['source']}  "
            f"Images: {len(product.get('images', {}).get('all', []))}",
            flush=True,
        )

        product_path = os.path.join(TMP, "current_product.json")
        with open(product_path, "w", encoding="utf-8") as f:
            json.dump(product, f, indent=2, ensure_ascii=False)

        try:
            # ── 2. Generate script ────────────────────────────────────────────
            print("\n[2/7] Generating English script...", flush=True)
            script_path = os.path.join(TMP, "product_script.json")
            run_tool("generate_product_script.py", [
                "--product", product_path,
                "--output", script_path,
            ])
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            print(f"  [OK] Hook: {script.get('hook', '')[:70]}", flush=True)

            # ── 2.5. Fetch use-case media (Pexels / FAL.ai) ──────────────────
            print("\n[2.5/7] Fetching use-case media...", flush=True)
            usecase_path = os.path.join(TMP, "usecase_media.json")
            try:
                run_tool("fetch_usecase_media.py", [
                    "--product", product_path,
                    "--script",  script_path,
                    "--output",  usecase_path,
                ])
                with open(usecase_path, "r", encoding="utf-8") as f:
                    _um = json.load(f)
                if _um.get("type"):
                    print(f"  [OK] {_um['type']}: {os.path.basename(_um.get('file',''))} ('{_um.get('keyword','')}')", flush=True)
                else:
                    print("  [INFO] No use-case media — use-case scene will be skipped", flush=True)
            except Exception as e:
                print(f"  [WARN] fetch_usecase_media failed: {e} — skipping", flush=True)
                usecase_path = None

            # ── 3. TTS ────────────────────────────────────────────────────────
            print("\n[3/7] Generating English TTS (Kokoro af_sarah)...", flush=True)
            full_script = script.get("full_script", "")
            tts_result = run_tool(
                "generate_kokoro_tts.py",
                [full_script, "af_sarah"],
            )
            audio_path = tts_result.get("file", os.path.join(TMP, "voiceover.mp3"))

            # generate_kokoro_tts writes captions.srt; compose looks for voiceover.srt
            srt_src = tts_result.get("srt", os.path.join(TMP, "captions.srt"))
            srt_dst = os.path.join(TMP, "voiceover.srt")
            if os.path.exists(srt_src) and srt_src != srt_dst:
                shutil.copy2(srt_src, srt_dst)

            print(f"  [OK] Audio: {tts_result.get('duration_seconds', '?')}s", flush=True)

            # ── 4. Compose video ──────────────────────────────────────────────
            print("\n[4/7] Composing 360-degree product video...", flush=True)
            out_name = f"product_{idx+1}_{product['source']}.mp4"
            compose_args = [
                "--product", product_path,
                "--script",  script_path,
                "--audio",   audio_path,
                "--output",  out_name,
            ]
            if usecase_path and os.path.exists(usecase_path):
                compose_args += ["--usecase", usecase_path]
            video_result = run_tool("compose_product_video.py", compose_args)
            video_path = video_result.get("file", os.path.join(TMP, out_name))
            print(
                f"  [OK] Video: {video_result.get('duration_seconds', '?')}s  "
                f"Angles: {video_result.get('angle_images', '?')}",
                flush=True,
            )

            # ── 5. Quality gate ───────────────────────────────────────────────
            print("\n[5/7] Quality gate...", flush=True)
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video not found: {video_path}")
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            if size_mb < 0.5:
                raise ValueError(f"Video too small ({size_mb:.1f}MB) — likely empty")
            print(f"  [OK] {size_mb:.1f}MB — passed", flush=True)

            caption = script.get("caption", product["title"])

            ig_result = {"status": "skipped"}
            yt_result = {"status": "skipped"}

            if not dry_run:
                # ── 6. Instagram ──────────────────────────────────────────────
                if not skip_instagram:
                    print("\n[6/7] Uploading to Instagram Reels...", flush=True)
                    try:
                        ig_result = run_tool("upload_reel.py", [video_path, caption])
                        print(f"  [OK] {ig_result.get('permalink', '?')}", flush=True)
                    except Exception as e:
                        print(f"  [WARN] Instagram failed: {e}", file=sys.stderr)
                        ig_result = {"status": "failed", "error": str(e)}
                else:
                    print("\n[6/7] Instagram skipped (--skip-instagram)", flush=True)

                # ── 7. YouTube ────────────────────────────────────────────────
                if not skip_youtube:
                    print("\n[7/7] Uploading to YouTube Shorts...", flush=True)
                    try:
                        yt_result = run_tool("upload_youtube_short.py", [
                            "--video",  video_path,
                            "--script", script_path,
                        ])
                        print(f"  [OK] {yt_result.get('url', '?')}", flush=True)
                    except Exception as e:
                        print(f"  [WARN] YouTube failed: {e}", file=sys.stderr)
                        yt_result = {"status": "failed", "error": str(e)}
                else:
                    print("\n[7/7] YouTube skipped (--skip-youtube)", flush=True)
            else:
                print("\n[6/7] DRY RUN — Instagram skipped", flush=True)
                print("[7/7] DRY RUN — YouTube skipped", flush=True)
                ig_result = {"status": "dry_run"}
                yt_result = {"status": "dry_run"}

            mark_uploaded(product, log)
            save_log(log)

            results.append({
                "product": product["title"][:80],
                "price": product["price"],
                "source": product["source"],
                "video": video_path,
                "instagram": ig_result,
                "youtube": yt_result,
                "status": "success",
            })

        except Exception as e:
            print(f"\n[ERROR] Product {idx+1} failed: {e}", file=sys.stderr)
            results.append({
                "product": product.get("title", "unknown")[:80],
                "status": "failed",
                "error": str(e),
            })

    # ── Summary ───────────────────────────────────────────────────────────────
    ok = sum(1 for r in results if r["status"] == "success")
    banner(f"Done: {ok}/{len(results)} succeeded  |  {datetime.now().strftime('%H:%M:%S')}")

    # Log this run
    log.setdefault("runs", []).append({
        "ts": datetime.now().isoformat(),
        "source": source,
        "count": len(products),
        "success": ok,
        "dry_run": dry_run,
    })
    save_log(log)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Product review Shorts pipeline")
    parser.add_argument("--source", choices=["amazon", "flipkart", "both"], default="both")
    parser.add_argument("--count",      type=int, default=2)
    parser.add_argument("--max-price",  type=int, default=999, dest="max_price")
    parser.add_argument("--dry-run",    action="store_true", help="Skip uploads")
    parser.add_argument("--skip-instagram", action="store_true")
    parser.add_argument("--skip-youtube",   action="store_true")
    args = parser.parse_args()

    run_pipeline(
        source=args.source,
        count=args.count,
        max_price=args.max_price,
        dry_run=args.dry_run,
        skip_instagram=args.skip_instagram,
        skip_youtube=args.skip_youtube,
    )
