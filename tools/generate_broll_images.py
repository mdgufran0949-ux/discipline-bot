"""
generate_broll_images.py
Generates AI images from script narration (Together AI FLUX free)
and converts each to a Ken Burns animated video clip.

Usage: python tools/generate_broll_images.py "narration text" [num_clips=3]
Output: .tmp/broll_1.mp4, .tmp/broll_2.mp4, .tmp/broll_3.mp4
        .tmp/ai_images/broll_1.jpg, ...
"""

import base64, glob, json, os, re, subprocess, sys
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP               = os.path.join(PROJECT_ROOT, ".tmp")
IMAGES_DIR        = os.path.join(TMP, "ai_images")

KIMI_API_KEY      = os.getenv("KIMI_API_KEY")
TOGETHER_API_KEY  = os.getenv("TOGETHER_API_KEY")
KIMI_BASE_URL     = "https://integrate.api.nvidia.com/v1"
KIMI_MODEL        = "moonshotai/kimi-k2-instruct"
TOGETHER_IMG_URL  = "https://api.together.xyz/v1/images/generations"
TOGETHER_MODEL    = "black-forest-labs/FLUX.1-schnell-Free"

FFMPEG       = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
CLIP_FPS     = 25
CLIP_SECONDS = 9   # seconds per image clip


# Ken Burns directions: (z_expr, x_expr, y_expr)
DIRECTIONS = [
    # zoom in — center
    ("min(zoom+0.0008,1.12)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # zoom out — center
    ("if(eq(on,1),1.12,max(zoom-0.0008,1.0))", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # slow pan right + slight zoom
    ("min(zoom+0.0005,1.08)", "iw/2-(iw/zoom/2)+on*0.35", "ih/2-(ih/zoom/2)"),
]


def _get_image_prompts(narration: str, num: int) -> list:
    """Use Kimi K2 to generate cinematic AI image prompts from narration."""
    prompt = (
        f'Narration: "{narration}"\n\n'
        f"Generate exactly {num} cinematic image prompts for a dark motivation short video.\n"
        f"Rules:\n"
        f"- Each prompt must match a distinct emotional moment from the narration\n"
        f"- Dark, moody, cinematic, high-contrast — no stock photo vibes\n"
        f"- Include: subject + setting + lighting + mood, 15-25 words each\n"
        f"- Use terms like: cinematic 35mm, dramatic rim lighting, film grain, shallow DOF, dark background\n"
        f"- Examples: 'Person staring at glowing phone screen in dark room, dramatic rim lighting, film grain, 35mm cinematic'\n"
        f"Return ONLY a JSON array. No explanation."
    )
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=400,
    )
    raw = resp.choices[0].message.content.strip()
    # Try greedy match (handles multi-line arrays with special chars)
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Fallback: extract quoted strings line by line
    items = re.findall(r'"([^"]{15,})"', raw)
    if len(items) >= num:
        return items[:num]
    raise ValueError(f"Could not parse prompts from: {raw[:200]}")


def _generate_image(prompt: str, out_path: str, idx: int) -> None:
    """Generate image via Together AI FLUX.1-schnell-Free (free tier).
    Get a free API key at: https://api.together.ai/settings/api-keys
    """
    if not TOGETHER_API_KEY:
        raise ValueError(
            "TOGETHER_API_KEY not set in .env\n"
            "Get a FREE key at: https://api.together.ai/settings/api-keys\n"
            "Free tier includes FLUX.1-schnell-Free image generation."
        )

    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model":  TOGETHER_MODEL,
        "prompt": prompt,
        "width":  768,
        "height": 1344,
        "steps":  4,
        "n":      1,
        "seed":   idx * 137
    }
    resp = requests.post(TOGETHER_IMG_URL, headers=headers, json=payload, timeout=90)

    if resp.status_code == 401:
        raise ValueError(
            "Together AI key invalid. Get a new FREE key at:\n"
            "https://api.together.ai/settings/api-keys\n"
            "Then update TOGETHER_API_KEY in .env"
        )
    resp.raise_for_status()

    data   = resp.json()
    result = (data.get("data") or [{}])[0]

    if "url" in result:
        img_bytes = requests.get(result["url"], timeout=30).content
    elif "b64_json" in result:
        img_bytes = base64.b64decode(result["b64_json"])
    else:
        raise ValueError(f"No image in Together AI response: {json.dumps(data)[:300]}")

    with open(out_path, "wb") as f:
        f.write(img_bytes)


def _image_to_clip(image_path: str, out_path: str, direction_idx: int) -> None:
    """Convert static image to Ken Burns animated clip (CLIP_SECONDS long)."""
    z, x, y = DIRECTIONS[direction_idx % len(DIRECTIONS)]
    total_frames = CLIP_SECONDS * CLIP_FPS

    # Scale up 2x before zoompan to avoid blurry/blocky artifacts
    vf = (
        f"scale=1536:2688,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={total_frames}:fps={CLIP_FPS}:s=1080x1920,"
        f"format=yuv420p"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", vf,
        "-t", str(CLIP_SECONDS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-an",
        out_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Ken Burns failed:\n{r.stderr[-800:]}")


def generate_broll_images(narration: str, num_clips: int = 3) -> dict:
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # Clean old broll clips
    for old in glob.glob(os.path.join(TMP, "broll_*.mp4")):
        os.remove(old)

    print(f"Generating {num_clips} AI image prompts via Kimi K2...", flush=True)
    prompts = _get_image_prompts(narration, num_clips)
    print(f"  Prompts: {prompts}", flush=True)

    clip_paths = []
    for i, prompt in enumerate(prompts[:num_clips], start=1):
        img_path  = os.path.join(IMAGES_DIR, f"broll_{i}.jpg")
        clip_path = os.path.join(TMP, f"broll_{i}.mp4")

        print(f"  [{i}/{num_clips}] Generating: {prompt[:70]}...", flush=True)
        try:
            _generate_image(prompt, img_path, i)
            print(f"  [OK] broll_{i}.jpg", flush=True)
        except Exception as e:
            print(f"  [FAIL] Image: {e}", flush=True)
            continue

        print(f"  [{i}/{num_clips}] Ken Burns animation...", flush=True)
        try:
            _image_to_clip(img_path, clip_path, i - 1)
            clip_paths.append(clip_path)
            print(f"  [OK] broll_{i}.mp4", flush=True)
        except Exception as e:
            print(f"  [FAIL] Ken Burns: {e}", flush=True)

    return {
        "clips":      clip_paths,
        "prompts":    prompts[:num_clips],
        "provider":   "together_ai_flux_free",
        "images_dir": IMAGES_DIR
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/generate_broll_images.py "narration text" [num_clips]')
        sys.exit(1)
    narration = sys.argv[1]
    num       = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    result    = generate_broll_images(narration, num)
    print(json.dumps(result, indent=2))
