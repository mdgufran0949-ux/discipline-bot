"""
generate_kids_thumbnail.py
Generates a YouTube thumbnail for kids animation.
Primary: AIMLAPI FLUX Pro v1.1.

Usage: python tools/generate_kids_thumbnail.py [path/to/kids_script.json]
Input:  .tmp/kids_script.json
Output: .tmp/kids_thumbnail.png + JSON result
"""

import json
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

AIMLAPI_KEY  = os.getenv("AIMLAPI_KEY", "")
AIMLAPI_URL  = "https://api.aimlapi.com/v1/images/generations"
MODEL        = "flux-pro/v1.1"

TMP            = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
SCRIPT_FILE    = os.path.join(TMP, "kids_script.json")
THUMBNAIL_FILE = os.path.join(TMP, "kids_thumbnail.png")

BISCUIT_DESC = (
    "BISCUIT the chubby cheerful yellow bear cub, big round dark brown eyes, "
    "small pink nose, rounded ears with light pink inner ear, soft fluffy fur, tiny red bowtie"
)

ZARA_DESC = (
    "ZARA the small wise purple owl, large yellow eyes behind round spectacles, "
    "tiny orange beak, soft purple feathered wings, small blue graduation cap"
)

THUMBNAIL_STYLE = (
    "YouTube thumbnail, 2D cartoon illustration, Pixar Disney quality, "
    "extremely vibrant saturated colors, child-friendly, high contrast, "
    "exaggerated happy excited expressions, large empty space at top for text, "
    "16:9 aspect ratio, no text in image, "
)


def _download_image(url: str, path: str) -> None:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def generate_kids_thumbnail(script: dict, output_path: str = THUMBNAIL_FILE) -> dict:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    concept = script.get("thumbnail_concept", "")
    topic   = script.get("topic", "learning")

    prompt = (
        f"{THUMBNAIL_STYLE}"
        f"{BISCUIT_DESC} and {ZARA_DESC}, both with huge smiles, "
        f"{concept}, bright yellow and purple background, topic: {topic}, "
        f"cartoon educational thumbnail for young children"
    )

    print(f"Generating thumbnail via AIMLAPI {MODEL}...", flush=True)

    headers = {
        "Authorization": f"Bearer {AIMLAPI_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model":  MODEL,
        "prompt": prompt,
        "width":  1280,
        "height": 720,
        "n":      1,
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(AIMLAPI_URL, headers=headers, json=body, timeout=120)
            resp.raise_for_status()
            image_url = resp.json()["data"][0]["url"]
            _download_image(image_url, output_path)
            print(f"  [OK] Thumbnail saved: {output_path}", flush=True)
            return {
                "file":         output_path,
                "prompt_used":  prompt[:150],
                "provider":     f"aimlapi/{MODEL}",
                "aspect_ratio": "16:9"
            }
        except Exception as e:
            print(f"  [attempt {attempt}] Error: {e}", flush=True)
            if attempt == 3:
                raise

    return {}


if __name__ == "__main__":
    script_path = sys.argv[1] if len(sys.argv) > 1 else SCRIPT_FILE
    if not os.path.exists(script_path):
        print(f"[ERROR] Script file not found: {script_path}")
        sys.exit(1)
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    result = generate_kids_thumbnail(script)
    print(json.dumps(result, indent=2))
