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
import sys
import time
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

FAL_API_KEY    = os.getenv("FAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TMP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "images"))

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&model=flux&nologo=true&seed={seed}"

# fal.ai size → (width, height) for Pollinations fallback
SIZE_DIMS = {
    "portrait_9_16": (1080, 1920),
    "square_hd":     (1080, 1080),
    "landscape_16_9": (1920, 1080),
}

# Design style → image prompt suffix
STYLE_SUFFIXES = {
    "dark":    "dark cinematic, deep dramatic shadows, black background, moody atmospheric lighting, high contrast, cinematic film grain",
    "minimal": "clean minimal composition, white space, simple geometric shapes, high contrast black and white",
    "bold":    "bold vivid colors, high saturation, strong visual contrast, powerful graphic design aesthetic",
    "luxury":  "luxury dark aesthetic, deep black marble texture, gold accents, premium editorial photography feel",
}


def _download(url: str, path: str) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


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

    # Enhance prompt with design style
    style_suffix = STYLE_SUFFIXES.get(design_style, STYLE_SUFFIXES["dark"])
    full_prompt = f"{prompt}, {style_suffix}, no text, no words, photorealistic"

    if seed is None:
        seed = int(time.time()) % 9999

    if output_path is None:
        output_path = os.path.join(TMP_DIR, f"image_{int(time.time())}.jpg")

    print(f"Generating {size} image ({design_style} style)...", flush=True)
    print(f"  Prompt: {full_prompt[:80]}...", flush=True)

    errors = []

    # 1st: fal.ai FLUX schnell
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
                    print(f"  [fal.ai] balance exhausted — skipping to Pollinations", flush=True)
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
