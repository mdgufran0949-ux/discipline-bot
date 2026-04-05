"""
generate_kids_visuals.py
Generates 6 cartoon scene images for kids animation.
Primary: AIMLAPI FLUX Pro v1.1 (best cartoon quality).

Usage: python tools/generate_kids_visuals.py [path/to/kids_script.json]
Input:  .tmp/kids_script.json
Output: .tmp/kids_images/scene_001.png ... scene_006.png + JSON result
"""

import json
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

AIMLAPI_KEY  = os.getenv("AIMLAPI_KEY", "")
AIMLAPI_URL  = "https://api.aimlapi.com/v1/images/generations"
MODEL        = "flux-pro/v1.1"

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
IMAGES_DIR  = os.path.join(TMP, "kids_images")
SCRIPT_FILE = os.path.join(TMP, "kids_script.json")


def _download_image(url: str, path: str) -> None:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def _generate_scene_image(prompt: str, out_path: str) -> None:
    headers = {
        "Authorization": f"Bearer {AIMLAPI_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model":  MODEL,
        "prompt": prompt,
        "width":  768,
        "height": 1024,
        "n":      1,
    }
    resp = requests.post(AIMLAPI_URL, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    image_url = resp.json()["data"][0]["url"]
    _download_image(image_url, out_path)


def generate_kids_visuals(script_path: str = SCRIPT_FILE) -> dict:
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    os.makedirs(IMAGES_DIR, exist_ok=True)
    scenes    = script["scenes"]
    generated = []
    skipped   = 0

    print(f"Generating {len(scenes)} scene images via AIMLAPI {MODEL}...", flush=True)

    for scene in scenes:
        n        = scene["id"]
        prompt   = scene.get("image_prompt", "")
        out_path = os.path.join(IMAGES_DIR, f"scene_{n:03d}.png")

        if os.path.exists(out_path):
            print(f"  [skip] scene_{n:03d}.png exists", flush=True)
            generated.append({"scene": n, "file": out_path, "skipped": True})
            skipped += 1
            continue

        print(f"  [{n}/{len(scenes)}] {prompt[:70]}...", flush=True)

        for attempt in range(1, 4):
            try:
                _generate_scene_image(prompt, out_path)
                print(f"  [OK] scene_{n:03d}.png", flush=True)
                generated.append({"scene": n, "file": out_path, "prompt": prompt[:80]})
                break
            except Exception as e:
                print(f"    [attempt {attempt}] Error: {e}", flush=True)
                if attempt == 3:
                    generated.append({"scene": n, "file": None, "error": str(e)})
                else:
                    time.sleep(3)

    successful = len([g for g in generated if g.get("file") and not g.get("skipped")])
    print(f"  Done: {successful} generated, {skipped} skipped", flush=True)

    return {
        "total_scenes": len(scenes),
        "images_dir":   IMAGES_DIR,
        "provider":     f"aimlapi/{MODEL}",
        "generated":    generated
    }


if __name__ == "__main__":
    script_path = sys.argv[1] if len(sys.argv) > 1 else SCRIPT_FILE
    if not os.path.exists(script_path):
        print(f"[ERROR] Script file not found: {script_path}")
        sys.exit(1)
    result = generate_kids_visuals(script_path)
    print(json.dumps(result, indent=2))
