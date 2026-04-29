"""
generate_ai_images.py
Generates AI images for each documentary scene using fal.ai FLUX (paid)
or Pollinations.ai FLUX (free, no key needed) as fallback/default.

Usage:
  python tools/generate_ai_images.py --provider muapi   # Muapi.ai Flux Dev (free tier — sign up at muapi.ai)
  python tools/generate_ai_images.py --provider gemini  # Google Imagen (free key at ai.google.dev)
  python tools/generate_ai_images.py --provider fal     # fal.ai FLUX schnell (paid)
  python tools/generate_ai_images.py --quality dev      # fal.ai FLUX dev (higher quality)
  python tools/generate_ai_images.py /path/to/custom_script.json

Muapi.ai model options via --quality:
  flux-dev (default), flux-schnell, midjourney, hidream-fast

Input:  .tmp/documentary_script.json
Output: .tmp/images/scene_001.jpg, scene_002.jpg, ...
Pollinations: free, no key — https://pollinations.ai
fal.ai: requires FAL_API_KEY in .env
muapi.ai: requires MUAPI_API_KEY in .env — free tier at https://muapi.ai
"""

import json
import os
import sys
import time
import requests

import urllib.parse

import fal_client
from dotenv import load_dotenv

load_dotenv()

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
IMAGES_DIR  = os.path.join(TMP, "images")
SCRIPT_FILE = os.path.join(TMP, "documentary_script.json")

def resolve_dirs(out_dir: str | None) -> tuple[str, str]:
    """Return (images_dir, script_file) based on optional --out-dir."""
    if out_dir:
        images = os.path.join(out_dir, "images")
        script = os.path.join(out_dir, "script.json")
        return images, script
    return IMAGES_DIR, SCRIPT_FILE

FAL_API_KEY    = os.getenv("FAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MUAPI_API_KEY  = os.getenv("MUAPI_API_KEY")

MUAPI_BASE     = "https://api.muapi.ai/api/v1"
# model slug → endpoint name on muapi.ai
MUAPI_IMAGE_MODELS = {
    "flux-dev":      "flux-dev-image",
    "flux-schnell":  "flux-schnell-image",
    "flux-2-dev":    "flux-2-dev",
    "midjourney":    "midjourney-v7-text-to-image",
    "hidream-fast":  "hidream_i1_fast_image",
    "hidream-dev":   "hidream_i1_dev_image",
    "nano-banana":   "nano-banana",
    "nano-banana-2": "nano-banana-2",
    "imagen4":       "google-imagen4",
    "imagen4-fast":  "google-imagen4-fast",
    "ideogram":      "ideogram-v3-t2i",
    "reve":          "reve-text-to-image",
}

FAL_MODELS = {
    "schnell": "fal-ai/flux/schnell",
    "dev":     "fal-ai/flux/dev",
}

# Pollinations.ai — free, no key, FLUX-powered. Portrait 9:16 for Shorts/Reels.
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=720&height=1280&model=flux&nologo=true&seed={seed}"


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


GEMINI_IMAGE_MODELS = [
    "imagen-3.0-generate-002",
    "imagen-3.0-generate-001",
]


def _generate_via_gemini(prompt: str, out_path: str, aspect_ratio: str = "9:16") -> None:
    """Free image generation via Google Gemini Imagen (GEMINI_API_KEY from ai.google.dev)."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in .env — get free key at ai.google.dev")
    from google import genai as google_genai
    from google.genai import types as genai_types

    client = google_genai.Client(api_key=GEMINI_API_KEY)
    last_err = None
    for model in GEMINI_IMAGE_MODELS:
        try:
            response = client.models.generate_images(
                model=model,
                prompt=prompt,
                config=genai_types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=aspect_ratio,
                    safety_filter_level="block_only_high",
                ),
            )
            img_bytes = response.generated_images[0].image.image_bytes
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            return
        except Exception as e:
            last_err = e
            continue
    raise last_err


def _generate_via_muapi(prompt: str, out_path: str, model: str = "flux-dev") -> None:
    """Free-tier image generation via muapi.ai (MUAPI_API_KEY from muapi.ai)."""
    if not MUAPI_API_KEY:
        raise ValueError("MUAPI_API_KEY not found in .env — sign up free at https://muapi.ai")
    endpoint = MUAPI_IMAGE_MODELS.get(model, "flux-dev")
    headers  = {"x-api-key": MUAPI_API_KEY, "Content-Type": "application/json"}

    # Step 1: submit generation job
    resp = requests.post(
        f"{MUAPI_BASE}/{endpoint}",
        headers=headers,
        json={"prompt": prompt, "aspect_ratio": "9:16"},
        timeout=60,
    )
    resp.raise_for_status()
    data       = resp.json()
    request_id = data.get("request_id") or data.get("id")
    if not request_id:
        raise ValueError(f"No request_id in muapi response: {data}")

    # Step 2: poll until completed (max 3 minutes)
    for _ in range(90):
        time.sleep(2)
        poll = requests.get(
            f"{MUAPI_BASE}/predictions/{request_id}/result",
            headers={"x-api-key": MUAPI_API_KEY},
            timeout=30,
        )
        poll.raise_for_status()
        result = poll.json()
        status = result.get("status", "")
        if status == "completed":
            output = result.get("output") or result.get("url") or result.get("image_url")
            if isinstance(output, list):
                output = output[0]
            if not output:
                raise ValueError(f"muapi completed but no output URL: {result}")
            download_image(output, out_path)
            return
        if status in ("failed", "error"):
            raise ValueError(f"muapi generation failed: {result}")

    raise TimeoutError(f"muapi timed out for request_id={request_id}")


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
                    provider: str = "gemini",
                    images_dir: str = IMAGES_DIR) -> dict:
    # Graceful downgrade: requested provider but no key → use Pollinations
    if provider == "muapi" and not MUAPI_API_KEY:
        print("  [warn] MUAPI_API_KEY missing — falling back to Pollinations", flush=True)
        provider = "pollinations"
    if provider == "gemini" and not GEMINI_API_KEY:
        print("  [warn] GEMINI_API_KEY missing — falling back to Pollinations", flush=True)
        provider = "pollinations"
    if provider == "fal" and not FAL_API_KEY:
        print("  [warn] FAL_API_KEY missing — falling back to Pollinations", flush=True)
        provider = "pollinations"

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    os.makedirs(images_dir, exist_ok=True)
    scenes    = script["scenes"]
    generated = []
    skipped   = 0

    print(f"Generating {len(scenes)} images via {provider}...", flush=True)

    for scene in scenes:
        n        = scene["scene_num"]
        prompt   = scene["image_prompt"]
        out_path = os.path.join(images_dir, f"scene_{n:03d}.jpg")

        if os.path.exists(out_path):
            print(f"  [skip] scene_{n:03d}.jpg exists", flush=True)
            generated.append({"scene": n, "file": out_path, "skipped": True})
            skipped += 1
            continue

        print(f"  [{n}/{len(scenes)}] {prompt[:70]}...", flush=True)

        for attempt in range(1, 4):
            try:
                # On attempt 3, if primary is Gemini/fal, fall back to Pollinations
                effective = provider if attempt < 3 else ("pollinations" if provider != "pollinations" else provider)
                if effective == "muapi":
                    muapi_model = quality if quality in MUAPI_IMAGE_MODELS else "flux-dev"
                    _generate_via_muapi(prompt, out_path, muapi_model)
                elif effective == "fal":
                    _generate_via_fal(prompt, out_path, quality)
                elif effective == "gemini":
                    _generate_via_gemini(prompt, out_path)
                else:
                    _generate_via_pollinations(prompt, out_path, seed=n * 13)
                tag = f" (fallback={effective})" if effective != provider else ""
                print(f"  [OK] scene_{n:03d}.jpg{tag}", flush=True)
                generated.append({"scene": n, "file": out_path, "prompt": prompt[:80]})
                break
            except Exception as e:
                print(f"  Error (attempt {attempt}, {provider}): {e}", flush=True)
                if attempt == 3:
                    print(f"  [SKIP] scene_{n:03d} failed", flush=True)
                    generated.append({"scene": n, "file": None, "error": str(e)})

    successful = len([g for g in generated if g.get("file") and not g.get("skipped")])
    print(f"  Done: {successful} generated, {skipped} skipped", flush=True)

    return {
        "total_scenes": len(scenes),
        "images_dir":   images_dir,
        "provider":     provider,
        "generated":    generated,
    }


if __name__ == "__main__":
    args     = sys.argv[1:]
    quality  = "flux-dev"
    provider = "muapi"    # default: muapi.ai Flux Dev (falls back to Pollinations if no key)
    script_path = SCRIPT_FILE
    out_dir  = None

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--quality", "-q") and i + 1 < len(args):
            quality = args[i + 1]; i += 2
        elif a in ("--provider", "-p") and i + 1 < len(args):
            provider = args[i + 1]; i += 2
        elif a == "--fal":
            provider = "fal"; i += 1
        elif a == "--out-dir" and i + 1 < len(args):
            out_dir = args[i + 1]; i += 2
        elif a.endswith(".json") and os.path.exists(a):
            script_path = a; i += 1
        else:
            i += 1

    if out_dir:
        imgs_dir, script_path = resolve_dirs(out_dir)
    else:
        imgs_dir = IMAGES_DIR

    result = generate_images(script_path, quality, provider, images_dir=imgs_dir)
    print(json.dumps(result, indent=2))
