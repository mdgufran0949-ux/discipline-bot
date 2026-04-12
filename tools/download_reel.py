"""
download_reel.py
Downloads a single Instagram Reel at the best available quality.
Tries yt-dlp first (selects highest resolution stream), falls back to direct CDN download.
Output: .tmp/reels/{reel_id}.mp4
"""

import json
import os
import subprocess
import sys
import requests

TMP_REELS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "reels"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.instagram.com/",
}

MIN_FILE_SIZE = 100 * 1024  # 100 KB
import shutil as _sy; YTDLP = _sy.which("yt-dlp") or "yt-dlp"\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"


def _download_ytdlp(post_url: str, reel_id: str, output_path: str) -> dict:
    cmd = [
        YTDLP,
        "-f", "bestvideo[height>=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=720]+bestaudio/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", output_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        post_url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-300:].strip() or "yt-dlp returned non-zero exit code")
    if not os.path.exists(output_path) or os.path.getsize(output_path) < MIN_FILE_SIZE:
        raise RuntimeError("yt-dlp produced no usable output file")
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [OK] Saved {output_path} ({size_mb:.1f} MB) [yt-dlp]", flush=True)
    return {"reel_id": reel_id, "file": output_path, "size_mb": round(size_mb, 2)}


def _download_direct(video_url: str, reel_id: str, output_path: str) -> dict:
    resp = requests.get(video_url, headers=HEADERS, stream=True, timeout=120)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size = os.path.getsize(output_path)
    if size < MIN_FILE_SIZE:
        os.remove(output_path)
        raise RuntimeError(
            f"Downloaded file is only {size} bytes — CDN likely returned an error page. "
            "The video URL may have expired. Re-run fetch_reels.py."
        )
    size_mb = size / (1024 * 1024)
    print(f"  [OK] Saved {output_path} ({size_mb:.1f} MB) [direct]", flush=True)
    return {"reel_id": reel_id, "file": output_path, "size_mb": round(size_mb, 2)}


def download_reel(video_url: str, reel_id: str, post_url: str = None) -> dict:
    os.makedirs(TMP_REELS, exist_ok=True)
    output_path = os.path.join(TMP_REELS, f"{reel_id}.mp4")

    print(f"Downloading Reel {reel_id}...", flush=True)

    if post_url:
        try:
            print(f"  [DL] Trying yt-dlp for best quality...", flush=True)
            return _download_ytdlp(post_url, reel_id, output_path)
        except Exception as e:
            print(f"  [WARN] yt-dlp failed ({e}). Falling back to direct download...", flush=True)
            if os.path.exists(output_path):
                os.remove(output_path)

    return _download_direct(video_url, reel_id, output_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tools/download_reel.py \"https://video-url\" \"reel_id\" [post_url]")
        sys.exit(1)
    result = download_reel(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print(json.dumps(result, indent=2))
