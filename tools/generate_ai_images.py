"""
generate_ai_images.py
Generates AI images for each documentary scene using fal.ai FLUX (paid)
or Pollinations.ai FLUX (free, no key needed) as fallback/default.

Usage:
  python tools/generate_ai_images.py --provider gemini  # Google Imagen (free key at ai.google.dev)
  python tools/generate_ai_images.py --provider fal     # fal.ai FLUX schnell (paid)
  python tools/generate_ai_images.py --quality dev      # fal.ai FLUX dev (higher quality)
  python tools/generate_ai_images.py /path/to/custom_script.json

Input:  .tmp/documentary_script.json
Output: .tmp/images/scene_001.jpg, scene_002.jpg, ...
Pollinations: free, no key — https://pollinations.ai
fal.ai: requires FAL_API_KEY in .env
"""

import json
import os
import sys
import requests

import urllib.parse

import fal_client
from dotenv import load_dotenv

load_dotenv()

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
IMAGES_DIR  = os.path.join(TMP, "images")
SCRIPT_FILE = os.path.join(TMP, "documentary_script.json")

FAL_API_KEY    = os.getenv("FAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FAL_MODELS = {
    "schnell": "fal-ai/flux/schnell",
    "dev":     "fal-ai/flux/dev",
}

# Pollinations.ai — free, no key, FLUX-powered
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=1280&height=720&model=flux&nologo=true&seed={seed}"


def download_image(url: str, path: str) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def _generate_via_pollinations(prompt: str, out_path: str, seed: int = 42) -> None:
    """Free image generation via Pollinations.ai (no API key needed)."""
    url = POLLINATIONS_URL.format(
        prompt=urllib.parse.quote(prompt),
        seed=seed
    )
    download_image(url, out_path)


def _generate_via_gemini(prompt: str, out_path: str) -> None:
    """Free image generation via Google Gemini Imagen (GEMINI_API_KEY from ai.google.dev)."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in .env — get free key at ai.google.dev")
    from google import genai as google_genai
    from google.genai import types as genai_types

    client = google_genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_images(
        model="imagen-3.0-generate-001",
        prompt=prompt,
        config=genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="16:9",
            safety_filter_level="block_only_high",
        ),
    )
    img_bytes = response.generated_images[0].image.image_bytes
    with open(out_path, "wb") as f:
        f.write(img_bytes)


def _generate_via_fal(prompt: str, out_path: str, quality: str = "schnell") -> None:
    """Paid image generation via fal.ai FLUX."""
    if not FAL_API_KEY:
        raise ValueError("FAL_API_KEY not found in .env")
    os.environ["FAL_KEY"] = FAL_API_KEY
    model  = FAL_MODELS.get(quality, FAL_MODELS["schnell"])
    result = fal_client.run(
        model,
        arguments={
            "prompt": prompt,
            "image_size": "landscape_16_9",
            "num_inference_steps": 4 if quality == "schnell" else 28,
            "num_images": 1,
            "enable_safety_checker": False,
            "guidance_scale": 3.5 if quality == "dev" else 0,
        }
    )
    download_image(result["images"][0]["url"], out_path)


def generate_images(script_path: str = SCRIPT_FILE,
                    quality: str = "schnell",
                    provider: str = "pollinations") -> dict:
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    os.makedirs(IMAGES_DIR, exist_ok=True)
    scenes    = script["scenes"]
    generated = []
    skipped   = 0

    print(f"Generating {len(scenes)} images via {provider}...", flush=True)

    for scene in scenes:
        n        = scene["scene_num"]
        prompt   = scene["image_prompt"]
        out_path = os.path.join(IMAGES_DIR, f"scene_{n:03d}.jpg")

        if os.path.exists(out_path):
            print(f"  [skip] scene_{n:03d}.jpg exists", flush=True)
            generated.append({"scene": n, "file": out_path, "skipped": True})
            skipped += 1
            continue

        print(f"  [{n}/{len(scenes)}] {prompt[:70]}...", flush=True)

        for attempt in range(1, 4):
            try:
                if provider == "fal":
                    _generate_via_fal(prompt, out_path, quality)
                elif provider == "gemini":
                    _generate_via_gemini(prompt, out_path)
                else:
                    _generate_via_pollinations(prompt, out_path, seed=n * 13)
                print(f"  [OK] scene_{n:03d}.jpg", flush=True)
                generated.append({"scene": n, "file": out_path, "prompt": prompt[:80]})
                break
            except Exception as e:
                print(f"  Error (attempt {attempt}): {e}", flush=True)
                if attempt == 3:
                    print(f"  [SKIP] scene_{n:03d} failed", flush=True)
                    generated.append({"scene": n, "file": None, "error": str(e)})

    successful = len([g for g in generated if g.get("file") and not g.get("skipped")])
    print(f"  Done: {successful} generated, {skipped} skipped", flush=True)

    return {
        "total_scenes": len(scenes),
        "images_dir":   IMAGES_DIR,
        "provider":     provider,
        "generated":    generated,
    }


if __name__ == "__main__":
    args     = sys.argv[1:]
    quality  = "schnell"
    provider = "pollinations"   # default: free
    script_path = SCRIPT_FILE

    for i, a in enumerate(args):
        if a in ("--quality", "-q") and i + 1 < len(args):
            quality = args[i + 1]
        elif a in ("--provider", "-p") and i + 1 < len(args):
            provider = args[i + 1]
        elif a == "--fal":
            provider = "fal"
        elif a.endswith(".json") and os.path.exists(a):
            script_path = a

    result = generate_images(script_path, quality, provider)
    print(json.dumps(result, indent=2))
