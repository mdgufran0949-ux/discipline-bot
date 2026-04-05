"""
generate_visuals.py
Generates 6 AI scene images using Pollinations.ai FLUX (free, no API key needed).
Reads scene prompts from .tmp/script.json (output of generate_script.py).
Usage: python tools/generate_visuals.py [script_json_file]
Output: .tmp/scene_1.png through .tmp/scene_6.png + JSON summary.
Free tier: 1 req/5s with free account at pollinations.ai (1 req/15s anonymous).
"""

import json
import sys
import os
import time
import urllib.parse
import requests

OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "..", ".tmp")
SCRIPT_JSON = os.path.join(OUTPUT_DIR, "script.json")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?model=flux&width=1024&height=1024&seed={seed}&nologo=true"

STYLE_SUFFIX = (
    "dramatic lighting, vibrant colors, cinematic shot, photorealistic, "
    "ultra detailed, 4K, vertical portrait orientation, professional photography"
)

# Fallback color palettes if image gen fails for a scene
FALLBACK_COLORS = ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#e94560", "#2c3e50"]

# Rate limit: 5s between requests (free account). Increase to 15 if using anonymously.
REQUEST_INTERVAL = 5

def generate_image(prompt: str, scene_id: int) -> str:
    full_prompt = f"{prompt}, {STYLE_SUFFIX}"
    url = POLLINATIONS_URL.format(
        prompt=urllib.parse.quote(full_prompt),
        seed=scene_id * 42
    )
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    out_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"scene_{scene_id}.png"))
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path

def generate_fallback_image(scene_id: int, color: str) -> str:
    """Generate a solid color PNG as fallback using Pillow."""
    from PIL import Image
    img = Image.new("RGB", (1080, 1920), color)
    out_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"scene_{scene_id}.png"))
    img.save(out_path)
    return out_path

def generate_visuals(script_data: dict) -> dict:
    os.makedirs(os.path.abspath(OUTPUT_DIR), exist_ok=True)
    scenes = script_data.get("scenes", [])
    results = []

    for i, scene in enumerate(scenes):
        sid = scene["id"]
        prompt = scene["image_prompt"]
        print(f"  Generating scene {sid}/6: {prompt[:60]}...", flush=True)
        try:
            path = generate_image(prompt, sid)
            results.append({"id": sid, "file": path, "status": "ok"})
            print(f"  [OK] Scene {sid} saved", flush=True)
        except Exception as e:
            print(f"  [FAIL] Scene {sid} failed ({e}), using fallback color", flush=True)
            path = generate_fallback_image(sid, FALLBACK_COLORS[(sid - 1) % len(FALLBACK_COLORS)])
            results.append({"id": sid, "file": path, "status": "fallback"})
        # Rate limit: wait between requests (Pollinations free tier)
        if i < len(scenes) - 1:
            time.sleep(REQUEST_INTERVAL)

    return {"scenes": results, "total": len(results)}

if __name__ == "__main__":
    script_file = sys.argv[1] if len(sys.argv) > 1 else SCRIPT_JSON
    with open(script_file, "r", encoding="utf-8") as f:
        script_data = json.load(f)
    result = generate_visuals(script_data)
    print(json.dumps(result, indent=2))
