"""
generate_latsync_avatar.py
Creates a talking avatar video from the character face image + voiceover.
Uses LatentSync (ByteDance, MIT license) for best face identity preservation.

The SAME config/character/face.jpg is used every single run.
This guarantees 100% face consistency across all videos — no re-uploading.

Setup (one-time, choose one option):

  Option A — Local GPU (best quality, fully offline):
    git clone https://github.com/bytedance/LatentSync  (inside project root)
    cd LatentSync && pip install -r requirements.txt
    Download checkpoints per LatentSync/README.md
    Requires: NVIDIA GPU with 8GB+ VRAM

  Option B — fal.ai cloud (no GPU needed, uses free credits):
    pip install fal-client
    Add FAL_API_KEY to .env (free credits at fal.ai)

Usage: python tools/generate_latsync_avatar.py
Inputs:  config/character/face.jpg, .tmp/voiceover.mp3
Output:  .tmp/avatar_raw.mp4
"""

import json
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP           = os.path.join(PROJECT_ROOT, ".tmp")
CHARACTER_IMG = os.path.join(PROJECT_ROOT, "config", "character", "face.jpg")
VOICEOVER_MP3 = os.path.join(TMP, "voiceover.mp3")
BASE_VIDEO    = os.path.join(TMP, "base_video.mp4")
OUTPUT_VIDEO  = os.path.join(TMP, "avatar_raw.mp4")
LATSYNC_DIR   = os.path.join(PROJECT_ROOT, "LatentSync")

import shutil as _sl; FFMPEG_BIN = _sl.which("ffmpeg") or "ffmpeg"; FFPROBE_BIN = _sl.which("ffprobe") or "ffprobe"

FAL_API_KEY = os.getenv("FAL_API_KEY")
D_ID_API_KEY = os.getenv("D_ID_API_KEY")


def _get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _create_base_video(image_path: str, duration: float, output_path: str) -> None:
    """Loop a static image into a video — LatentSync requires video input."""
    print(f"Creating {duration:.1f}s base video from character face...", flush=True)
    subprocess.run([
        FFMPEG_BIN, "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        "-vf", "scale=512:512",  # LatentSync input size
        output_path
    ], capture_output=True, check=True)
    print(f"  [OK] Base video: {output_path}", flush=True)


def _run_latsync_local(base_video: str, audio: str, output: str) -> None:
    """Run LatentSync locally via its inference script."""
    unet_config  = os.path.join(LATSYNC_DIR, "configs", "unet", "second_stage.yaml")
    ckpt_path    = os.path.join(LATSYNC_DIR, "checkpoints", "latentsync_unet.pt")
    config_path  = os.path.join(TMP, "latsync_config.yaml")

    if not os.path.exists(unet_config):
        raise FileNotFoundError(
            f"LatentSync config not found: {unet_config}\n"
            "Make sure you followed setup instructions in LatentSync/README.md"
        )
    if not os.path.exists(ckpt_path):
        raise FileNotFoundError(
            f"LatentSync checkpoint not found: {ckpt_path}\n"
            "Download model weights per LatentSync/README.md"
        )

    # Write inference YAML config
    with open(config_path, "w") as f:
        f.write(f"video_path: '{base_video}'\n")
        f.write(f"audio_path: '{audio}'\n")
        f.write(f"video_out_path: '{output}'\n")

    print("Running LatentSync lip sync (this takes ~30-120s on GPU)...", flush=True)
    result = subprocess.run([
        sys.executable, "-m", "scripts.inference",
        "--unet_config_path", unet_config,
        "--inference_ckpt_path", ckpt_path,
        "--inference_steps", "20",
        "--guidance_scale", "1.5",
        config_path
    ], cwd=LATSYNC_DIR, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(
            "LatentSync failed. Check:\n"
            "1. NVIDIA GPU is available (nvidia-smi)\n"
            "2. All model checkpoints are downloaded\n"
            "3. LatentSync dependencies are installed (pip install -r LatentSync/requirements.txt)"
        )
    print(f"  [OK] LatentSync done: {output}", flush=True)


def _run_did(image_path: str, audio_path: str, output_path: str) -> None:
    """Generate talking avatar via D-ID API (already integrated, 20 free credits)."""
    import base64
    import time
    import requests as req

    if not D_ID_API_KEY:
        raise ValueError("D_ID_API_KEY not set in .env")

    print("Running D-ID talking avatar...", flush=True)
    token = base64.b64encode(f"{D_ID_API_KEY}:".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Upload image
    with open(image_path, "rb") as f:
        up = req.post(
            "https://api.d-id.com/images",
            headers={k: v for k, v in headers.items() if k != "Content-Type"},
            files={"image": (os.path.basename(image_path), f, "image/jpeg")},
            timeout=60
        )
    up.raise_for_status()
    image_url = up.json().get("url") or up.json().get("id")
    print(f"  [OK] Image uploaded: {image_url}", flush=True)

    # Encode audio
    with open(audio_path, "rb") as f:
        audio_b64 = f"data:audio/mpeg;base64,{base64.b64encode(f.read()).decode()}"

    # Upload audio to Cloudinary to get a public URL (D-ID requires hosted URL)
    import cloudinary
    import cloudinary.uploader
    from dotenv import load_dotenv
    load_dotenv()
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET")
    )
    print("  Uploading audio to Cloudinary for D-ID...", flush=True)
    cl_result = cloudinary.uploader.upload(
        audio_path,
        resource_type="video",
        folder="did_audio",
        public_id=f"voiceover_{int(time.time())}"
    )
    audio_url_hosted = cl_result["secure_url"]
    print(f"  [OK] Audio URL: {audio_url_hosted}", flush=True)

    # Create talk
    talk_resp = req.post(
        "https://api.d-id.com/talks",
        headers=headers,
        json={"source_url": image_url, "script": {"type": "audio", "audio_url": audio_url_hosted},
              "config": {"fluent": True, "pad_audio": 0.0}},
        timeout=60
    )
    if not talk_resp.ok:
        raise RuntimeError(f"D-ID talk creation failed ({talk_resp.status_code}): {talk_resp.text}")
    talk_id = talk_resp.json().get("id")
    print(f"  [OK] Talk ID: {talk_id}", flush=True)

    # Poll until done
    for _ in range(36):  # max 180s
        time.sleep(5)
        status_resp = req.get(f"https://api.d-id.com/talks/{talk_id}", headers=headers, timeout=30)
        status_resp.raise_for_status()
        data = status_resp.json()
        status = data.get("status")
        print(f"  Status: {status}", flush=True)
        if status == "done":
            video_url = data.get("result_url")
            break
        if status == "error":
            raise RuntimeError(f"D-ID error: {data.get('error', data)}")
    else:
        raise TimeoutError("D-ID did not finish within 180s")

    # Download
    dl = req.get(video_url, stream=True, timeout=120)
    dl.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in dl.iter_content(8192):
            f.write(chunk)
    print(f"  [OK] Avatar saved: {output_path}", flush=True)


def _run_fal_cloud(image_path: str, audio_path: str, output_path: str) -> None:
    """Run MuseTalk via fal.ai cloud API (free credits available)."""
    try:
        import fal_client
    except ImportError:
        raise ImportError("fal-client not installed. Run: pip install fal-client")

    import base64
    import requests as req

    if not FAL_API_KEY:
        raise ValueError(
            "FAL_API_KEY not set in .env\n"
            "Get free credits at: fal.ai"
        )

    print("Running MuseTalk via fal.ai cloud (no GPU needed)...", flush=True)
    os.environ["FAL_KEY"] = FAL_API_KEY

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

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

    print(f"  Downloading from fal.ai...", flush=True)
    resp = req.get(video_url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    print(f"  [OK] Avatar saved: {output_path}", flush=True)


def generate_latsync_avatar() -> dict:
    os.makedirs(TMP, exist_ok=True)

    if not os.path.exists(CHARACTER_IMG):
        raise FileNotFoundError(
            f"Character face image not found: {CHARACTER_IMG}\n"
            "One-time setup:\n"
            "  1. Generate a realistic human face (Leonardo.ai free / Adobe Firefly free)\n"
            "  2. Save it as: config/character/face.jpg\n"
            "  3. Use the SAME image every run — this ensures 100% face consistency"
        )
    if not os.path.exists(VOICEOVER_MP3):
        raise FileNotFoundError(
            f"Missing voiceover: {VOICEOVER_MP3}\n"
            "Run generate_kokoro_tts.py first."
        )

    duration = _get_audio_duration(VOICEOVER_MP3)

    if os.path.isdir(LATSYNC_DIR):
        # Option A: Local GPU with LatentSync (best quality)
        _create_base_video(CHARACTER_IMG, duration, BASE_VIDEO)
        _run_latsync_local(BASE_VIDEO, VOICEOVER_MP3, OUTPUT_VIDEO)
    elif D_ID_API_KEY:
        # Option B: D-ID cloud (20 free credits), fallback to fal.ai on error
        try:
            _run_did(CHARACTER_IMG, VOICEOVER_MP3, OUTPUT_VIDEO)
        except Exception as e:
            print(f"  [D-ID failed] {str(e)[:80]} — trying fal.ai...", flush=True)
            if FAL_API_KEY:
                _run_fal_cloud(CHARACTER_IMG, VOICEOVER_MP3, OUTPUT_VIDEO)
            else:
                raise
    elif FAL_API_KEY:
        # Option C: fal.ai cloud (requires balance)
        _run_fal_cloud(CHARACTER_IMG, VOICEOVER_MP3, OUTPUT_VIDEO)
    else:
        raise RuntimeError(
            "No avatar generation method configured.\n"
            "Add D_ID_API_KEY to .env (free at d-id.com, 20 credits)"
        )

    if not os.path.exists(OUTPUT_VIDEO):
        raise RuntimeError(f"Avatar video was not created at {OUTPUT_VIDEO}")

    size_mb = os.path.getsize(OUTPUT_VIDEO) / (1024 * 1024)
    print(f"  [OK] Avatar video ready: {OUTPUT_VIDEO} ({size_mb:.1f} MB)", flush=True)

    return {
        "file":             OUTPUT_VIDEO,
        "source_image":     CHARACTER_IMG,
        "source_audio":     VOICEOVER_MP3,
        "duration_seconds": round(duration, 2)
    }


if __name__ == "__main__":
    result = generate_latsync_avatar()
    print(json.dumps(result, indent=2))
