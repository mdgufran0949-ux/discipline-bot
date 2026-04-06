"""
generate_discipline_image.py
Design Engine (Image Generation) for DisciplineFuel.
Generates dark-aesthetic AI images for quotes/posts.

Provider priority: fal.ai FLUX schnell → Pollinations.ai (free) → Gemini Imagen
Sizes: portrait_9_16 (image posts) | square_hd (carousel slides)

Usage: python tools/generate_discipline_image.py "dark cinematic discipline quote background"
Output: JSON with file path
"""

import json
import os
import random
import sys
import time
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

FAL_API_KEY    = os.getenv("FAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AIMLAPI_KEY    = os.getenv("AIMLAPI_KEY")

TMP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "images"))

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&model=flux&nologo=true&seed={seed}"

# fal.ai size → (width, height) for Pollinations fallback
SIZE_DIMS = {
    "portrait_9_16": (1080, 1920),
    "square_hd":     (1080, 1080),
    "landscape_16_9": (1920, 1080),
}

# Design style → cinematic scene pools (6 scenes per style, picked randomly each post)
SCENE_POOLS = {
    "dark": [
        "lone figure standing at edge of rooftop at night, city lights below, cinematic fog, dramatic backlighting, photorealistic",
        "person sitting alone at a desk in a dark room, single lamp light, shadows on wall, late night, cinematic",
        "silhouette of athlete running on empty road at 4am, streetlight glow, motion blur, dark sky",
        "close-up of clenched fist, dark gym background, dramatic side lighting, sweat, high contrast",
        "empty dark gym at night, single spotlight on bench press, iron plates, cinematic atmosphere",
        "person staring at reflection in dark window at night, city lights outside, contemplative mood",
    ],
    "minimal": [
        "clean white marble surface with single black coffee cup, morning light, overhead shot, minimal",
        "empty wooden desk with open notebook, soft natural window light, clean and simple composition",
        "single silhouette on white background, strong shadow, minimal composition, high contrast",
        "clean gymnasium floor with single dumbbell, harsh overhead light, minimal shadows",
        "bare concrete wall with single shaft of light, architectural minimalism, black and white",
        "person in white room standing at window, simple clean aesthetic, soft daylight",
    ],
    "bold": [
        "explosive athlete mid-sprint, stadium lights, dynamic motion, vibrant contrast, raw energy",
        "powerful boxer throwing punch, dramatic gym lighting, sweat droplets, raw energy, vivid colors",
        "person breaking through paper wall, dynamic explosion effect, bold colors, energy",
        "athlete lifting heavy barbell, veins visible, raw determination, vivid dramatic lighting",
        "runner crossing finish line, crowd blurred behind, triumph moment, bold warm colors",
        "person climbing steep mountain, dramatic sky above, powerful composition, vivid colors",
    ],
    "luxury": [
        "luxury penthouse office at night, floor to ceiling windows, city skyline, dark premium aesthetic",
        "expensive watch on black marble desk, soft gold lighting, premium close-up detail shot",
        "silhouette in front of private jet at night, runway lights, premium dark aesthetic",
        "luxury sports car interior at night, dashboard lights, cinematic dark premium feel",
        "person in tailored suit walking through dark empty corridor, gold accent lighting",
        "rooftop infinity pool overlooking city at night, dark luxury, atmospheric lighting",
    ],
}


def _download(url: str, path: str) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def _generate_via_aimlapi(prompt: str, out_path: str, size: str = "portrait_9_16") -> None:
    w, h = SIZE_DIMS.get(size, (1080, 1920))
    resp = requests.post(
        "https://api.aimlapi.com/v1/images/generations",
        headers={"Authorization": f"Bearer {AIMLAPI_KEY}", "Content-Type": "application/json"},
        json={
            "model": "flux/dev",
            "prompt": prompt,
            "width": w,
            "height": h,
            "steps": 28,
            "n": 1,
        },
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    # Handle both response formats
    images = data.get("images") or data.get("data") or []
    img_url = (images[0].get("url") or images[0].get("b64_json")) if images else None
    if not img_url:
        raise RuntimeError(f"No image URL in AIMLAPI response: {data}")
    if img_url.startswith("http"):
        _download(img_url, out_path)
    else:
        import base64
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(img_url))


def _generate_via_fal(prompt: str, out_path: str, size: str = "portrait_9_16") -> None:
    import fal_client
    os.environ["FAL_KEY"] = FAL_API_KEY
    result = fal_client.run(
        "fal-ai/flux/schnell",
        arguments={
            "prompt":                prompt,
            "image_size":            size,
            "num_inference_steps":   4,
            "num_images":            1,
            "enable_safety_checker": False,
            "guidance_scale":        0,
        }
    )
    _download(result["images"][0]["url"], out_path)


def _generate_via_pollinations(prompt: str, out_path: str, size: str = "portrait_9_16", seed: int = 42) -> None:
    w, h = SIZE_DIMS.get(size, (1080, 1920))
    url = POLLINATIONS_URL.format(
        prompt=urllib.parse.quote(prompt),
        w=w, h=h, seed=seed
    )
    _download(url, out_path)


def _generate_via_gemini(prompt: str, out_path: str, size: str = "portrait_9_16") -> None:
    from google import genai as google_genai
    from google.genai import types as genai_types
    # Map size to Gemini aspect ratio
    aspect_map = {
        "portrait_9_16":  "9:16",
        "square_hd":      "1:1",
        "landscape_16_9": "16:9",
    }
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_images(
        model="imagen-3.0-generate-001",
        prompt=prompt,
        config=genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_map.get(size, "9:16"),
            safety_filter_level="block_only_high",
        ),
    )
    img_bytes = response.generated_images[0].image.image_bytes
    with open(out_path, "wb") as f:
        f.write(img_bytes)


def generate_discipline_image(
    prompt: str,
    size: str = "portrait_9_16",
    design_style: str = "dark",
    output_path: str = None,
    seed: int = None
) -> dict:
    """
    Generate one image for a DisciplineFuel post.
    Appends design style suffix to prompt automatically.
    Returns: {file, provider, size, prompt}
    """
    os.makedirs(TMP_DIR, exist_ok=True)

    # Enhance prompt with a random cinematic scene for this design style
    scene_pool = SCENE_POOLS.get(design_style, SCENE_POOLS["dark"])
    scene_base = random.choice(scene_pool)
    full_prompt = f"{scene_base}, {prompt}, 9:16 vertical composition, no text, no words, ultra high quality, award-winning photography"

    if seed is None:
        seed = int(time.time()) % 9999

    if output_path is None:
        output_path = os.path.join(TMP_DIR, f"image_{int(time.time())}.jpg")

    print(f"Generating {size} image ({design_style} style)...", flush=True)
    print(f"  Prompt: {full_prompt[:80]}...", flush=True)

    errors = []

    # 1st: AIMLAPI FLUX dev (paid, high quality)
    if AIMLAPI_KEY:
        try:
            print(f"  [AIMLAPI/flux-dev]...", flush=True)
            _generate_via_aimlapi(full_prompt, output_path, size)
            print(f"  [OK] AIMLAPI → {output_path}", flush=True)
            return {"file": output_path, "provider": "aimlapi", "size": size, "prompt": full_prompt}
        except Exception as e:
            errors.append(f"AIMLAPI: {e}")
            print(f"  [AIMLAPI failed: {str(e)[:80]}] trying fal.ai...", flush=True)

    # 2nd: fal.ai FLUX schnell
    if FAL_API_KEY:
        for attempt in range(1, 3):
            try:
                print(f"  [fal.ai] attempt {attempt}...", flush=True)
                _generate_via_fal(full_prompt, output_path, size)
                print(f"  [OK] fal.ai → {output_path}", flush=True)
                return {"file": output_path, "provider": "fal.ai", "size": size, "prompt": full_prompt}
            except Exception as e:
                err_str = str(e)
                errors.append(f"fal.ai: {e}")
                print(f"  [fal.ai] failed: {err_str[:80]}", flush=True)
                if "Exhausted balance" in err_str or "locked" in err_str.lower():
                    print(f"  [fal.ai] balance exhausted — skipping", flush=True)
                    break
                time.sleep(2)

    # 2nd: Pollinations.ai (free, no key)
    for attempt in range(1, 3):
        try:
            print(f"  [Pollinations] attempt {attempt}...", flush=True)
            _generate_via_pollinations(full_prompt, output_path, size, seed=seed + attempt)
            print(f"  [OK] Pollinations → {output_path}", flush=True)
            return {"file": output_path, "provider": "pollinations", "size": size, "prompt": full_prompt}
        except Exception as e:
            errors.append(f"Pollinations: {e}")
            print(f"  [Pollinations] failed: {str(e)[:80]}", flush=True)
            time.sleep(3)

    # 3rd: Gemini Imagen
    if GEMINI_API_KEY:
        try:
            print("  [Gemini Imagen]...", flush=True)
            _generate_via_gemini(full_prompt, output_path, size)
            print(f"  [OK] Gemini → {output_path}", flush=True)
            return {"file": output_path, "provider": "gemini", "size": size, "prompt": full_prompt}
        except Exception as e:
            errors.append(f"Gemini: {e}")
            print(f"  [Gemini] failed: {str(e)[:80]}", flush=True)

    raise RuntimeError(f"All image providers failed: {'; '.join(errors)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/generate_discipline_image.py "prompt here" [size] [style]')
        print("  size:  portrait_9_16 (default) | square_hd | landscape_16_9")
        print("  style: dark (default) | minimal | bold | luxury")
        sys.exit(1)
    prompt = sys.argv[1]
    size   = sys.argv[2] if len(sys.argv) > 2 else "portrait_9_16"
    style  = sys.argv[3] if len(sys.argv) > 3 else "dark"
    result = generate_discipline_image(prompt, size=size, design_style=style)
    print(json.dumps(result, indent=2))
