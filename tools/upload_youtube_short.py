"""
upload_youtube_short.py
Uploads a video as a YouTube Short via YouTube Data API v3 (OAuth 2.0).

First run: opens a browser window for Google OAuth authorization.
Subsequent runs: auto-refreshes the stored token.

Usage:
  python tools/upload_youtube_short.py --video .tmp/product_video.mp4 --script .tmp/product_script.json
Output: JSON with video_id, url, title, status

Requirements (if not installed):
  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

import json
import sys
import os
import argparse
import pickle
from dotenv import load_dotenv

load_dotenv()

TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Separate token file from the Sheets token to avoid scope conflicts
TOKEN_FILE = os.path.join(TMP, "youtube_token.pkl")
CREDENTIALS_FILE = os.path.join(ROOT, "credentials.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _check_deps():
    missing = []
    for pkg in ("googleapiclient", "google_auth_oauthlib", "google.auth"):
        try:
            __import__(pkg.replace(".", "_") if "." in pkg else pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("[ERROR] Missing Google API libraries. Run:", file=sys.stderr)
        print(
            "  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
            file=sys.stderr,
        )
        sys.exit(1)


def get_authenticated_service():
    _check_deps()
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(
                    f"[ERROR] credentials.json not found at {CREDENTIALS_FILE}",
                    file=sys.stderr,
                )
                print(
                    "Enable YouTube Data API v3 in your Google Cloud project,\n"
                    "then download OAuth credentials and save as credentials.json",
                    file=sys.stderr,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(TMP, exist_ok=True)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
        print("[OK] YouTube token saved", file=sys.stderr)

    return build("youtube", "v3", credentials=creds)


def upload_youtube_short(video_path: str, script: dict) -> dict:
    from googleapiclient.http import MediaFileUpload

    youtube = get_authenticated_service()

    title = script.get("title", "Tech Gadget Review #Shorts")[:100]
    if "#Shorts" not in title and "#shorts" not in title:
        title = title[:92] + " #Shorts"

    hashtags = script.get("hashtags", [])
    caption = script.get("caption", "")
    hashtag_str = " ".join(hashtags[:10])
    description = f"{caption}\n\n{hashtag_str}\n\n#Shorts"

    tags = [h.lstrip("#") for h in hashtags] + ["Shorts", "Short", "TechUnder999"]

    body = {
        "snippet": {
            "title": title,
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": "28",         # Science & Technology
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path, chunksize=-1, resumable=True, mimetype="video/mp4"
    )
    print(f"[INFO] Uploading: {title}", file=sys.stderr)

    request = youtube.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload: {pct}%", end="\r", flush=True, file=sys.stderr)

    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    print(f"\n  [OK] {url}", file=sys.stderr)

    return {"video_id": video_id, "url": url, "title": title, "status": "uploaded"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",  required=True, help="Path to video file")
    parser.add_argument("--script", required=True, help="Path to script JSON")
    parser.add_argument("--output", default=None, help="Save result JSON to file")
    args = parser.parse_args()

    with open(args.script, "r", encoding="utf-8") as f:
        script = json.load(f)

    result = upload_youtube_short(args.video, script)
    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)
