"""
upload_image_post.py
Uploads static images and carousels to Instagram via Meta Graph API v19.0.
Uses Cloudinary as temporary image host (same pattern as upload_reel.py).

Single image:  media_type=IMAGE
Carousel:      multi-step — child containers → parent CAROUSEL → publish

Usage:
  python tools/upload_image_post.py image  path/to/image.jpg "Caption #hashtag"
  python tools/upload_image_post.py carousel "slide1.jpg,slide2.jpg,slide3.jpg" "Caption"

Output: JSON with ig_media_id, permalink, status
Requires: IG_USER_ID, IG_ACCESS_TOKEN, CLOUDINARY_* in .env
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

POLL_INTERVAL = 5
POLL_TIMEOUT  = 120

# Reuse shared helpers from upload_reel.py
sys.path.insert(0, os.path.dirname(__file__))
from upload_reel import (
    _check_creds,
    _configure_cloudinary,
    delete_from_cloudinary,
    publish_container,
    get_permalink,
)


# ── Cloudinary image upload ────────────────────────────────────────────────────

def upload_image_to_cloudinary(image_path: str) -> tuple[str, str]:
    """Upload image to Cloudinary. Returns (public_https_url, public_id)."""
    print(f"Uploading image to Cloudinary: {os.path.basename(image_path)}...", flush=True)
    result = cloudinary.uploader.upload(
        image_path,
        resource_type="image",
        folder="disciplinefuel_posts",
        overwrite=False
    )
    url       = result["secure_url"]
    public_id = result["public_id"]
    print(f"  [OK] Cloudinary URL: {url}", flush=True)
    return url, public_id


def delete_image_from_cloudinary(public_id: str) -> None:
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image")
        print(f"  [OK] Deleted from Cloudinary: {public_id}", flush=True)
    except Exception as e:
        print(f"  [WARN] Could not delete Cloudinary image: {e}", flush=True)


# ── Single image post ──────────────────────────────────────────────────────────

def _create_image_container(image_url: str, caption: str, ig_user_id: str, ig_access_token: str) -> str:
    """Create a single IMAGE media container. Returns container_id."""
    print("Creating IMAGE container...", flush=True)
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        params={
            "media_type":   "IMAGE",
            "image_url":    image_url,
            "caption":      caption,
            "access_token": ig_access_token
        },
        timeout=30
    )
    data = resp.json()
    if not resp.ok or "error" in data:
        err = data.get("error", data)
        if isinstance(err, dict) and err.get("code") == 190:
            raise RuntimeError("Instagram access token expired. Refresh and update config.")
        raise RuntimeError(f"IMAGE container creation failed: {err}")
    container_id = data["id"]
    print(f"  [OK] Container ID: {container_id}", flush=True)
    return container_id


def _poll_image_container(container_id: str, ig_access_token: str) -> None:
    """Poll until image container is FINISHED."""
    print("Waiting for container to be ready...", flush=True)
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": ig_access_token},
            timeout=30
        )
        status = resp.json().get("status_code", "")
        if status == "FINISHED":
            print(f"  [OK] Container ready ({elapsed}s)", flush=True)
            return
        if status == "ERROR":
            raise RuntimeError("Image container processing failed.")
        print(f"  Status: {status} ({elapsed}s)...", flush=True)
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError("Image container did not finish in time.")


def upload_image_post(
    image_path: str,
    caption: str,
    ig_user_id: str = None,
    ig_access_token: str = None
) -> dict:
    """
    Upload a single image to Instagram feed.
    Returns: {ig_media_id, permalink, status}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    ig_user_id      = ig_user_id      or _ENV_IG_USER_ID
    ig_access_token = ig_access_token or _ENV_IG_ACCESS_TOKEN
    _check_creds(ig_user_id, ig_access_token)
    _configure_cloudinary()

    image_url, public_id = upload_image_to_cloudinary(image_path)
    cloudinary_ids = [public_id]

    try:
        container_id = _create_image_container(image_url, caption, ig_user_id, ig_access_token)
        _poll_image_container(container_id, ig_access_token)
        ig_media_id = publish_container(container_id, ig_user_id, ig_access_token)
        permalink   = get_permalink(ig_media_id, ig_access_token)
        print(f"  [OK] Post live: {permalink}", flush=True)
    finally:
        for cid in cloudinary_ids:
            delete_image_from_cloudinary(cid)

    return {"ig_media_id": ig_media_id, "permalink": permalink, "status": "published", "type": "image"}


# ── Carousel post ──────────────────────────────────────────────────────────────

def _create_carousel_child(image_url: str, ig_user_id: str, ig_access_token: str) -> str:
    """Create one carousel child container (no caption). Returns child_id."""
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        params={
            "media_type":        "IMAGE",
            "image_url":         image_url,
            "is_carousel_item":  "true",
            "access_token":      ig_access_token
        },
        timeout=30
    )
    data = resp.json()
    if not resp.ok or "error" in data:
        raise RuntimeError(f"Carousel child creation failed: {data.get('error', data)}")
    child_id = data["id"]
    print(f"  [OK] Child container: {child_id}", flush=True)
    return child_id


def _create_carousel_parent(child_ids: list, caption: str, ig_user_id: str, ig_access_token: str) -> str:
    """Create the CAROUSEL parent container. Returns parent_id."""
    print(f"Creating CAROUSEL parent container ({len(child_ids)} slides)...", flush=True)
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        params={
            "media_type":   "CAROUSEL",
            "children":     ",".join(child_ids),
            "caption":      caption,
            "access_token": ig_access_token
        },
        timeout=30
    )
    data = resp.json()
    if not resp.ok or "error" in data:
        raise RuntimeError(f"Carousel parent creation failed: {data.get('error', data)}")
    parent_id = data["id"]
    print(f"  [OK] Parent container: {parent_id}", flush=True)
    return parent_id


def upload_carousel_post(
    image_paths: list,
    caption: str,
    ig_user_id: str = None,
    ig_access_token: str = None
) -> dict:
    """
    Upload a carousel post (2-10 slides) to Instagram.
    Returns: {ig_media_id, permalink, status, slide_count}
    """
    if not image_paths:
        raise ValueError("No image paths provided for carousel.")
    if len(image_paths) < 2:
        raise ValueError("Carousel requires at least 2 images.")
    if len(image_paths) > 10:
        image_paths = image_paths[:10]
        print(f"  [WARN] Carousel capped at 10 slides.", flush=True)

    for p in image_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Carousel image not found: {p}")

    ig_user_id      = ig_user_id      or _ENV_IG_USER_ID
    ig_access_token = ig_access_token or _ENV_IG_ACCESS_TOKEN
    _check_creds(ig_user_id, ig_access_token)
    _configure_cloudinary()

    cloudinary_ids = []
    child_ids      = []

    try:
        # Step 1: Upload all images to Cloudinary + create child containers
        print(f"Creating {len(image_paths)} carousel child containers...", flush=True)
        for i, path in enumerate(image_paths):
            image_url, public_id = upload_image_to_cloudinary(path)
            cloudinary_ids.append(public_id)
            child_id = _create_carousel_child(image_url, ig_user_id, ig_access_token)
            child_ids.append(child_id)
            time.sleep(1)  # brief pause between child creations

        # Step 2: Create parent CAROUSEL container
        parent_id = _create_carousel_parent(child_ids, caption, ig_user_id, ig_access_token)

        # Step 3: Poll parent container
        _poll_image_container(parent_id, ig_access_token)

        # Step 4: Publish
        ig_media_id = publish_container(parent_id, ig_user_id, ig_access_token)

        # Step 5: Get permalink
        permalink = get_permalink(ig_media_id, ig_access_token)
        print(f"  [OK] Carousel live: {permalink}", flush=True)

    finally:
        for cid in cloudinary_ids:
            delete_image_from_cloudinary(cid)

    return {
        "ig_media_id":  ig_media_id,
        "permalink":    permalink,
        "status":       "published",
        "type":         "carousel",
        "slide_count":  len(image_paths)
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage:")
        print('  python tools/upload_image_post.py image  "path.jpg" "Caption"')
        print('  python tools/upload_image_post.py carousel "s1.jpg,s2.jpg,s3.jpg" "Caption"')
        sys.exit(1)

    mode    = sys.argv[1]
    paths   = sys.argv[2]
    caption = sys.argv[3]

    if mode == "image":
        result = upload_image_post(paths, caption)
    elif mode == "carousel":
        path_list = [p.strip() for p in paths.split(",")]
        result = upload_carousel_post(path_list, caption)
    else:
        print(f"Unknown mode: {mode}. Use 'image' or 'carousel'.")
        sys.exit(1)

    print(json.dumps(result, indent=2))
