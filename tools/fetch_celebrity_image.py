"""
fetch_celebrity_image.py
Downloads a high-resolution, front-facing celebrity photo for use with D-ID API.
Uses a curated list of Wikipedia public-domain image URLs per celebrity name.
Usage: python tools/fetch_celebrity_image.py "Elon Musk"
Output: .tmp/celebrity.jpg + JSON with path and dimensions.
"""

import json
import os
import sys
import requests
from PIL import Image

TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
OUTPUT_IMAGE = os.path.join(TMP, "celebrity.jpg")
MIN_SIZE = 512  # minimum width or height in pixels

# Curated public-domain front-facing images per celebrity
CELEBRITY_IMAGES = {
    "elon musk": "https://upload.wikimedia.org/wikipedia/commons/3/34/Elon_Musk_Royal_Society_%28crop2%29.jpg",
    "jeff bezos": "https://upload.wikimedia.org/wikipedia/commons/6/6c/Jeff_Bezos_at_Amazon_Spheres_Grand_Opening_in_Seattle_-_2018_%2839074799225%29_%28cropped%29.jpg",
    "mark zuckerberg": "https://upload.wikimedia.org/wikipedia/commons/1/18/Mark_Zuckerberg_F8_2019_Keynote_%2832830578717%29_%28cropped%29.jpg",
    "bill gates": "https://upload.wikimedia.org/wikipedia/commons/a/a0/Bill_Gates_2018.jpg",
    "cristiano ronaldo": "https://upload.wikimedia.org/wikipedia/commons/8/8c/Cristiano_Ronaldo_2018.jpg",
    "virat kohli": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Virat_Kohli_in_ICC_World_Test_Championship_Final_in_2023_%28cropped%29.jpg/800px-Virat_Kohli_in_ICC_World_Test_Championship_Final_in_2023_%28cropped%29.jpg",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ShortsBot/1.0)"
}


def fetch_celebrity_image(name: str) -> dict:
    os.makedirs(TMP, exist_ok=True)
    key = name.strip().lower()

    if key not in CELEBRITY_IMAGES:
        available = ", ".join(k.title() for k in CELEBRITY_IMAGES)
        raise ValueError(f"Celebrity '{name}' not in curated list. Available: {available}")

    url = CELEBRITY_IMAGES[key]
    print(f"Downloading image for '{name}' from Wikipedia...", flush=True)

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    with open(OUTPUT_IMAGE, "wb") as f:
        f.write(response.content)

    img = Image.open(OUTPUT_IMAGE)
    w, h = img.size

    if w < MIN_SIZE or h < MIN_SIZE:
        raise ValueError(f"Image too small: {w}x{h}. Minimum required: {MIN_SIZE}px on each side.")

    # Ensure saved as JPEG (D-ID requires JPEG or PNG)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
        img.save(OUTPUT_IMAGE, "JPEG", quality=95)

    print(f"  [OK] Saved to {OUTPUT_IMAGE} ({w}x{h})", flush=True)
    return {
        "file": OUTPUT_IMAGE,
        "celebrity": name,
        "width": w,
        "height": h,
        "source_url": url
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_celebrity_image.py \"Celebrity Name\"")
        print("Available celebrities:", ", ".join(k.title() for k in CELEBRITY_IMAGES))
        sys.exit(1)
    name = " ".join(sys.argv[1:])
    result = fetch_celebrity_image(name)
    print(json.dumps(result, indent=2))
