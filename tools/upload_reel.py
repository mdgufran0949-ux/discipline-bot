"""
upload_reel.py
Uploads a local .mp4 file to Instagram as a Reel via the official Meta Graph API.
Uses Cloudinary as temporary video host (Graph API requires a public HTTPS URL).
Usage: python tools/upload_reel.py ".tmp/reels/reel_id_branded.mp4" "Caption text #hashtag"
Output: JSON with ig_media_id, permalink, and status.
Requires: IG_USER_ID, IG_ACCESS_TOKEN, CLOUDINARY_* in .env
Install:  pip install cloudinary
"""

import json
import os
import sys
import time
import requests
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

_ENV_IG_USER_ID      = os.getenv("IG_USER_ID")
_ENV_IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
GRAPH_BASE           = "https://graph.facebook.com/v19.0"

POLL_INTERVAL   = 10   # seconds between status checks
POLL_TIMEOUT    = 300  # max seconds to wait for container


def _check_creds(ig_user_id, ig_access_token):
    missing = []
    if not ig_user_id:
        missing.append("IG_USER_ID")
    if not ig_access_token:
        missing.append("IG_ACCESS_TOKEN")
    for key in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"):
        if not os.getenv(key):
            missing.append(key)
    if missing:
        raise ValueError(f"Missing credentials: {', '.join(missing)}. Check .env and account config.")


def _configure_cloudinary():
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True
    )


def upload_to_cloudinary(video_path: str) -> tuple[str, str]:
    """Upload video to Cloudinary. Returns (public_https_url, public_id)."""
    print("Uploading video to Cloudinary (temporary host)...", flush=True)
    result = cloudinary.uploader.upload(
        video_path,
        resource_type="video",
        folder="ig_reels_tmp",
        overwrite=True
    )
    url       = result["secure_url"]
    public_id = result["public_id"]
    print(f"  [OK] Cloudinary URL: {url}", flush=True)
    return url, public_id


def delete_from_cloudinary(public_id: str) -> None:
    """Delete video from Cloudinary after successful Instagram publish."""
    try:
        cloudinary.uploader.destroy(public_id, resource_type="video")
        print(f"  [OK] Deleted from Cloudinary: {public_id}", flush=True)
    except Exception as e:
        print(f"  [WARN] Could not delete Cloudinary asset: {e}", flush=True)


def create_media_container(video_url: str, caption: str, ig_user_id: str, ig_access_token: str) -> str:
    """Step 1: Create Instagram media container. Returns container_id."""
    print("Creating Instagram media container...", flush=True)
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        params={
            "media_type":    "REELS",
            "video_url":     video_url,
            "caption":       caption,
            "share_to_feed": "true",
            "access_token":  ig_access_token
        },
        timeout=30
    )
    data = resp.json()
    if not resp.ok or "error" in data:
        err = data.get("error", data)
        if isinstance(err, dict) and err.get("code") == 190:
            raise RuntimeError(
                "Instagram access token expired (error 190). "
                "Refresh at developers.facebook.com/tools/explorer and update the account config."
            )
        raise RuntimeError(f"Container creation failed: {err}")
    container_id = data.get("id")
    print(f"  [OK] Container ID: {container_id}", flush=True)
    return container_id


def poll_container(container_id: str, ig_access_token: str) -> None:
    """Step 2: Poll until container status is FINISHED."""
    print("Waiting for Instagram to process video...", flush=True)
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": ig_access_token},
            timeout=30
        )
        data = resp.json()
        status = data.get("status_code")

        if status == "FINISHED":
            print(f"  [OK] Container ready ({elapsed}s)", flush=True)
            return
        elif status == "ERROR":
            raise RuntimeError(
                "Instagram container processing failed (ERROR status). "
                "The video may need re-encoding: ffmpeg -i input.mp4 -c:v libx264 -c:a aac output.mp4"
            )
        elif status == "EXPIRED":
            raise RuntimeError("Instagram container expired. Re-run the upload.")
        else:
            print(f"  Status: {status} ({elapsed}s elapsed)...", flush=True)
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

    raise TimeoutError(f"Instagram container did not finish within {POLL_TIMEOUT}s.")


def publish_container(container_id: str, ig_user_id: str, ig_access_token: str) -> str:
    """Step 3: Publish the container. Returns ig_media_id."""
    print("Publishing Reel to Instagram...", flush=True)
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        params={
            "creation_id":  container_id,
            "access_token": ig_access_token
        },
        timeout=30
    )
    data = resp.json()
    if not resp.ok or "error" in data:
        raise RuntimeError(f"Publish failed: {data.get('error', data)}")
    ig_media_id = data.get("id")
    print(f"  [OK] Published! Media ID: {ig_media_id}", flush=True)
    return ig_media_id


def get_permalink(ig_media_id: str, ig_access_token: str) -> str:
    """Fetch the public permalink of the published Reel."""
    resp = requests.get(
        f"{GRAPH_BASE}/{ig_media_id}",
        params={"fields": "permalink", "access_token": ig_access_token},
        timeout=30
    )
    return resp.json().get("permalink", "")


def upload_reel(video_path: str, caption: str, ig_user_id: str = None, ig_access_token: str = None) -> dict:
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    ig_user_id      = ig_user_id      or _ENV_IG_USER_ID
    ig_access_token = ig_access_token or _ENV_IG_ACCESS_TOKEN

    _check_creds(ig_user_id, ig_access_token)
    _configure_cloudinary()

    # Step 1: Upload to Cloudinary for public URL
    video_url, public_id = upload_to_cloudinary(video_path)

    try:
        # Step 2: Create Instagram container
        container_id = create_media_container(video_url, caption, ig_user_id, ig_access_token)

        # Step 3: Poll until container is ready
        poll_container(container_id, ig_access_token)

        # Step 4: Publish
        ig_media_id = publish_container(container_id, ig_user_id, ig_access_token)

        # Step 5: Get permalink
        permalink = get_permalink(ig_media_id, ig_access_token)
        print(f"  [OK] Reel live at: {permalink}", flush=True)

    finally:
        # Always clean up Cloudinary asset to conserve free-tier bandwidth
        delete_from_cloudinary(public_id)

    return {
        "ig_media_id": ig_media_id,
        "permalink":   permalink,
        "caption":     caption[:80] + "..." if len(caption) > 80 else caption,
        "status":      "published"
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tools/upload_reel.py \".tmp/reels/reel_id_branded.mp4\" \"Caption #hashtag\" [--out result.json]")
        sys.exit(1)
    video_path = sys.argv[1]
    caption    = sys.argv[2]
    out_path   = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            out_path = sys.argv[idx + 1]
    result = upload_reel(video_path, caption)
    print(json.dumps(result, indent=2))
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as _f:
            json.dump(result, _f, indent=2)
