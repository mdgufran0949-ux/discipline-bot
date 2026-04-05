"""
generate_did_avatar.py
Creates a talking avatar video from a celebrity image + voiceover.
Uses fal.ai MuseTalk (replaces D-ID — higher quality, no credit limit).

Usage: python tools/generate_did_avatar.py
Inputs:  .tmp/celebrity.jpg, .tmp/voiceover.mp3
Output:  .tmp/avatar_raw.mp4
Requires: FAL_API_KEY in .env (free credits at fal.ai)
"""

import base64
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TMP            = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
CELEBRITY_IMG  = os.path.join(TMP, "celebrity.jpg")
VOICEOVER_MP3  = os.path.join(TMP, "voiceover.mp3")
OUTPUT_VIDEO   = os.path.join(TMP, "avatar_raw.mp4")

FAL_API_KEY = os.getenv("FAL_API_KEY")


def generate_did_avatar() -> dict:
    try:
        import fal_client
    except ImportError:
        raise ImportError("fal-client not installed. Run: pip install fal-client")

    if not FAL_API_KEY:
        raise ValueError("FAL_API_KEY not found in .env — get free credits at fal.ai")

    if not os.path.exists(CELEBRITY_IMG):
        raise FileNotFoundError(f"Missing: {CELEBRITY_IMG} — run fetch_celebrity_image.py first")
    if not os.path.exists(VOICEOVER_MP3):
        raise FileNotFoundError(f"Missing: {VOICEOVER_MP3} — run generate_tts.py first")

    os.makedirs(TMP, exist_ok=True)
    os.environ["FAL_KEY"] = FAL_API_KEY

    print("Encoding celebrity image and audio...", flush=True)
    with open(CELEBRITY_IMG, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    with open(VOICEOVER_MP3, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    print("Running MuseTalk lip-sync via fal.ai (30-60s)...", flush=True)
    result = fal_client.run(
        "fal-ai/musetalk",
        arguments={
            "source_image_url": f"data:image/jpeg;base64,{img_b64}",
            "audio_url":        f"data:audio/mpeg;base64,{audio_b64}"
        }
    )

    video_url = (result.get("video") or {}).get("url") or result.get("video_url")
    if not video_url:
        raise RuntimeError(f"fal.ai returned no video URL. Response: {result}")

    print(f"Downloading avatar video...", flush=True)
    resp = requests.get(video_url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(OUTPUT_VIDEO, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)

    size_mb = os.path.getsize(OUTPUT_VIDEO) / (1024 * 1024)
    print(f"  [OK] Avatar saved: {OUTPUT_VIDEO} ({size_mb:.1f} MB)", flush=True)

    return {
        "file":          OUTPUT_VIDEO,
        "source_image":  CELEBRITY_IMG,
        "source_audio":  VOICEOVER_MP3
    }


if __name__ == "__main__":
    result = generate_did_avatar()
    print(json.dumps(result, indent=2))
