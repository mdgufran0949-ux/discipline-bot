"""
fetch_usecase_media.py
Fetches a use-case context clip for the product video.

Strategy:
  1. Read use_case_keywords from script.json
  2. Try Pexels video search for each keyword (portrait orientation preferred)
  3. If no good video found, generate a lifestyle image via FAL.ai FLUX Schnell
  4. Output JSON: {"type": "video"|"image", "file": "path", "keyword": "..."}

Usage:
  python tools/fetch_usecase_media.py --product .tmp/current_product.json --script .tmp/product_script.json
  python tools/fetch_usecase_media.py --product .tmp/current_product.json --script .tmp/product_script.json --output .tmp/usecase_media.json
"""

import json
import os
import sys
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
CLIPS_DIR = os.path.join(TMP, "usecase_clips")

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
FAL_API_KEY = os.getenv("FAL_API_KEY", "")


# ── Pexels ────────────────────────────────────────────────────────────────────

def search_pexels_video(keyword: str, per_page: int = 8) -> list:
    """Return list of video candidates from Pexels for the keyword."""
    if not PEXELS_API_KEY:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keyword, "per_page": per_page, "orientation": "portrait"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("videos", [])
    except Exception as e:
        print(f"[WARN] Pexels search failed for '{keyword}': {e}", file=sys.stderr)
        return []


def pick_best_video(videos: list) -> dict | None:
    """Pick the best video file: portrait, SD/HD, 5-45s duration."""
    best = None
    best_score = -1
    for v in videos:
        dur = v.get("duration", 0)
        if not (5 <= dur <= 45):
            continue
        width = v.get("width", 0)
        height = v.get("height", 0)
        is_portrait = height >= width
        score = (1 if is_portrait else 0) * 10 + min(dur, 30)
        if score > best_score:
            best_score = score
            best = v
    return best


def pick_video_file(video: dict) -> str | None:
    """Pick the best video file URL from a Pexels video object (prefer HD, avoid 4K)."""
    files = sorted(
        video.get("video_files", []),
        key=lambda f: f.get("width", 0),
    )
    # Prefer 720p-1080p range
    for f in files:
        w = f.get("width", 0)
        if 640 <= w <= 1920:
            return f.get("link")
    # Fall back to anything
    return files[-1].get("link") if files else None


def download_pexels_video(keyword: str, dest_dir: str) -> str | None:
    """Try Pexels for keyword, download best result. Returns local path or None."""
    videos = search_pexels_video(keyword)
    if not videos:
        return None
    best = pick_best_video(videos)
    if not best:
        return None
    url = pick_video_file(best)
    if not url:
        return None

    safe_kw = keyword.replace(" ", "_").replace("/", "_")[:30]
    dest = os.path.join(dest_dir, f"pexels_{safe_kw}.mp4")
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        print(f"  [OK] Pexels video: '{keyword}' -> {os.path.basename(dest)}", file=sys.stderr)
        return dest
    except Exception as e:
        print(f"[WARN] Pexels download failed: {e}", file=sys.stderr)
        return None


# ── FAL.ai fallback ───────────────────────────────────────────────────────────

def generate_fal_image(product_name: str, use_case: str, dest_dir: str) -> str | None:
    """Generate a lifestyle image via FAL.ai FLUX Schnell. Returns local path or None."""
    if not FAL_API_KEY:
        print("[WARN] FAL_API_KEY not set — skipping AI image generation", file=sys.stderr)
        return None
    try:
        import fal_client
    except ImportError:
        # Try direct HTTP API instead
        return _generate_fal_http(product_name, use_case, dest_dir)

    try:
        prompt = (
            f"lifestyle product photography, {product_name}, {use_case}, "
            "natural setting, commercial photography, photorealistic, "
            "warm lighting, person using product, 9:16 vertical format"
        )
        result = fal_client.run(
            "fal-ai/flux/schnell",
            arguments={
                "prompt": prompt,
                "image_size": {"width": 768, "height": 1344},
                "num_inference_steps": 4,
                "num_images": 1,
            },
        )
        img_url = result["images"][0]["url"]
        dest = os.path.join(dest_dir, "fal_lifestyle.jpg")
        r = requests.get(img_url, timeout=30)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        print(f"  [OK] FAL.ai lifestyle image generated -> {os.path.basename(dest)}", file=sys.stderr)
        return dest
    except Exception as e:
        print(f"[WARN] FAL.ai generation failed: {e}", file=sys.stderr)
        return None


def _generate_fal_http(product_name: str, use_case: str, dest_dir: str) -> str | None:
    """FAL.ai via direct HTTP (no fal_client SDK)."""
    try:
        prompt = (
            f"lifestyle product photography, {product_name}, {use_case}, "
            "natural setting, commercial photography, photorealistic, "
            "warm lighting, person using product, vertical format"
        )
        r = requests.post(
            "https://fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_size": {"width": 768, "height": 1344},
                "num_inference_steps": 4,
                "num_images": 1,
            },
            timeout=60,
        )
        r.raise_for_status()
        img_url = r.json()["images"][0]["url"]
        dest = os.path.join(dest_dir, "fal_lifestyle.jpg")
        img_r = requests.get(img_url, timeout=30)
        img_r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(img_r.content)
        print(f"  [OK] FAL.ai lifestyle image -> {os.path.basename(dest)}", file=sys.stderr)
        return dest
    except Exception as e:
        print(f"[WARN] FAL.ai HTTP failed: {e}", file=sys.stderr)
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_usecase_media(product: dict, script: dict) -> dict:
    os.makedirs(CLIPS_DIR, exist_ok=True)

    product_name = product.get("title", "product")[:60]
    keywords = script.get("use_case_keywords", [])

    # Normalise: keywords may be a list of strings or a single string description
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(k).strip() for k in keywords if str(k).strip()]

    # Fallback keywords from product title
    if not keywords:
        words = product_name.lower().split()[:4]
        keywords = [" ".join(words)]

    print(f"  Trying {len(keywords)} keyword(s): {keywords}", file=sys.stderr)

    # Try Pexels for each keyword
    for kw in keywords:
        path = download_pexels_video(kw, CLIPS_DIR)
        if path:
            return {"type": "video", "file": path, "keyword": kw}

    # Fallback: FAL.ai lifestyle image
    print("  [INFO] No Pexels video found — trying FAL.ai image generation", file=sys.stderr)
    use_case = keywords[0] if keywords else "everyday use"
    path = generate_fal_image(product_name, use_case, CLIPS_DIR)
    if path:
        return {"type": "image", "file": path, "keyword": use_case}

    print("  [WARN] No use-case media obtained — use-case scene will be skipped", file=sys.stderr)
    return {"type": None, "file": None, "keyword": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, help="Path to product JSON")
    parser.add_argument("--script",  required=True, help="Path to script JSON")
    parser.add_argument("--output",  default=None,  help="Save result JSON to file")
    args = parser.parse_args()

    with open(args.product, "r", encoding="utf-8") as f:
        product = json.load(f)
    if isinstance(product, list):
        product = product[0]

    with open(args.script, "r", encoding="utf-8") as f:
        script = json.load(f)

    result = fetch_usecase_media(product, script)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[OK] Saved to {args.output}", file=sys.stderr)
    else:
        print(output)
