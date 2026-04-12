"""
generate_sync_avatar.py
Uploads celebrity source video + voiceover to sync.so API and downloads the lip-synced avatar video.
Usage: python tools/generate_sync_avatar.py
Inputs:  .tmp/celebrity_source.mp4, .tmp/voiceover.mp3   (audio must be < 20 seconds on free plan)
Output:  .tmp/avatar_raw.mp4 + JSON with path and job ID.
Requires: SYNC_API_KEY in .env
"""

import json
import os
import sys
import time
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

TMP             = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
SOURCE_VIDEO    = os.path.join(TMP, "celebrity_source.mp4")
VOICEOVER_MP3   = os.path.join(TMP, "voiceover.mp3")
OUTPUT_VIDEO    = os.path.join(TMP, "avatar_raw.mp4")
import shutil as _ss; FFMPEG_BIN = _ss.which("ffmpeg") or "ffmpeg"; FFPROBE = _ss.which("ffprobe") or "ffprobe"

SYNC_API_KEY    = os.getenv("SYNC_API_KEY")
SYNC_BASE_URL   = "https://api.sync.so/v2"
MODEL           = "lipsync-2"
POLL_INTERVAL   = 5    # seconds
POLL_TIMEOUT    = 300  # seconds


def _headers() -> dict:
    if not SYNC_API_KEY:
        raise ValueError("SYNC_API_KEY not found in .env. Add it and retry.")
    return {"x-api-key": SYNC_API_KEY}


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def submit_job(video_path: str, audio_path: str) -> str:
    """Submit lip-sync job via multipart upload. Returns job ID."""
    audio_dur = get_duration(audio_path)
    if audio_dur > 19.5:
        raise ValueError(
            f"Audio is {audio_dur:.1f}s. Free plan limit is 20s. "
            "Shorten your script to ~35 words and re-run generate_tts.py."
        )

    print(f"Submitting lip-sync job (audio: {audio_dur:.1f}s, model: {MODEL})...", flush=True)
    with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
        resp = requests.post(
            f"{SYNC_BASE_URL}/generate",
            headers=_headers(),
            files={
                "video": (os.path.basename(video_path), vf, "video/mp4"),
                "audio": (os.path.basename(audio_path), af, "audio/mpeg"),
            },
            data={"model": MODEL},
            timeout=120
        )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("id")
    if not job_id:
        raise RuntimeError(f"sync.so job submission failed. Response: {data}")
    print(f"  [OK] Job ID: {job_id}", flush=True)
    return job_id


def poll_job(job_id: str) -> str:
    """Poll until job is COMPLETED. Returns result video URL."""
    print("Waiting for sync.so to render lip-sync...", flush=True)
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        resp = requests.get(
            f"{SYNC_BASE_URL}/generate/{job_id}",
            headers=_headers(),
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status == "COMPLETED":
            # Result URL can be in different fields depending on API version
            result_url = (
                data.get("outputUrl") or
                data.get("output", {}).get("url") or
                f"{SYNC_BASE_URL}/generations/{job_id}/result?token={data.get('token', '')}"
            )
            print(f"  [OK] Render complete.", flush=True)
            return result_url
        elif status in ("FAILED", "ERROR", "REJECTED"):
            raise RuntimeError(f"sync.so job failed: {data.get('error', data)}")
        else:
            print(f"  Status: {status} ({elapsed}s elapsed)...", flush=True)
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

    raise TimeoutError(f"sync.so did not finish within {POLL_TIMEOUT}s. Try again later.")


def download_result(url: str, output_path: str) -> None:
    """Download the rendered avatar video."""
    print("Downloading lip-synced avatar video...", flush=True)
    resp = requests.get(url, headers=_headers(), stream=True, timeout=120)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [OK] Saved to {output_path} ({size_mb:.1f} MB)", flush=True)


def generate_sync_avatar() -> dict:
    os.makedirs(TMP, exist_ok=True)

    if not os.path.exists(SOURCE_VIDEO):
        raise FileNotFoundError(
            f"Missing: {SOURCE_VIDEO} -- run fetch_celebrity_image.py first, "
            "then convert to video with ffmpeg (see workflow)."
        )
    if not os.path.exists(VOICEOVER_MP3):
        raise FileNotFoundError(f"Missing: {VOICEOVER_MP3} -- run generate_tts.py first")

    job_id     = submit_job(SOURCE_VIDEO, VOICEOVER_MP3)
    result_url = poll_job(job_id)
    download_result(result_url, OUTPUT_VIDEO)

    return {
        "file": OUTPUT_VIDEO,
        "job_id": job_id,
        "source_video": SOURCE_VIDEO,
        "source_audio": VOICEOVER_MP3
    }


if __name__ == "__main__":
    result = generate_sync_avatar()
    print(json.dumps(result, indent=2))
