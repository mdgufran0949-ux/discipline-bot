"""
run_kids_pipeline.py
Master orchestrator for the Biscuit & Zara kids animation channel.
Produces 1-5 fully automated kids videos per run and uploads to YouTube.

Pipeline:
  1. Fetch trending kids topics
  2. Generate script (Groq Llama 3.3)
  3. Safety check (Gemini Flash) — HARD STOP on fail
  4. Generate TTS voiceover (edge-tts AnaNeural)
  5. Generate 6 scene images (kie.ai Ideogram V3)
  6. Compose video (ffmpeg Ken Burns + captions)
  7. Generate thumbnail (kie.ai Ideogram V3)
  8. Upload to YouTube (selfDeclaredMadeForKids: True — COPPA required)
  9. Set custom thumbnail

Usage:
  python tools/run_kids_pipeline.py                    # 1 video, auto topic
  python tools/run_kids_pipeline.py --count 3          # 3 videos
  python tools/run_kids_pipeline.py --topic "dinosaurs for kids" --series "Animals ABC"
  python tools/run_kids_pipeline.py --dry-run          # full pipeline, no upload
  python tools/run_kids_pipeline.py --no-upload        # compose only
"""

import json
import os
import sys
import argparse
import datetime
import time
import pickle

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from fetch_kids_trends        import fetch_kids_trends
from generate_kids_script     import generate_kids_script
from kids_safety_check        import kids_safety_check
from generate_kids_tts        import generate_kids_tts
from generate_kids_visuals    import generate_kids_visuals
from generate_kids_thumbnail  import generate_kids_thumbnail
from generate_kids_bg_music   import generate_kids_bg_music
from compose_kids_video       import compose_kids_video

try:
    from daily_review   import daily_review
    from account_memory import AccountMemory
except Exception:
    daily_review  = None
    AccountMemory = None

KIDS_ACCOUNT = "biscuit_zara"

TMP      = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR  = os.path.join(TMP, "kids_channel")
LOG_FILE = os.path.join(LOG_DIR, "upload_log.json")

SCRIPT_FILE    = os.path.join(TMP, "kids_script.json")
TOKEN_FILE     = os.path.join(TMP, "youtube_token.pkl")
CREDENTIALS    = os.path.join(ROOT, "credentials.json")
SCOPES         = ["https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube"]

COST_PER_VIDEO_USD = 0.056   # 7 Ideogram images × ~$0.008 avg


# ── Log helpers ────────────────────────────────────────────────────────────────

def load_log() -> dict:
    if not os.path.exists(LOG_FILE):
        return {"uploaded": [], "safety_fails": [], "stats": {"total_uploaded": 0, "total_safety_fails": 0}}
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_log(data: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = LOG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LOG_FILE)


# ── Step runner with retry ─────────────────────────────────────────────────────

def run_step(name: str, func, *args, max_retries: int = 1, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            result = func(*args, **kwargs)
            print(f"  [OK] {name}", flush=True)
            return result
        except Exception as e:
            if attempt < max_retries:
                print(f"  [RETRY] {name} failed ({e}), retrying in 5s...", flush=True)
                time.sleep(5)
            else:
                print(f"  [FAIL] {name}: {e}", flush=True)
                raise


# ── YouTube helpers ────────────────────────────────────────────────────────────

def get_youtube_service():
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
            if not os.path.exists(CREDENTIALS):
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS}\n"
                    "Enable YouTube Data API v3 and download OAuth credentials."
                )
            flow  = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(TMP, exist_ok=True)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def upload_kids_video(youtube, video_path: str, script: dict) -> dict:
    """Upload video with selfDeclaredMadeForKids: True (COPPA compliance)."""
    from googleapiclient.http import MediaFileUpload

    title       = script.get("seo_title", script.get("title", "Biscuit and Zara"))[:100]
    if "#Shorts" not in title and "#shorts" not in title:
        title = title[:92] + " #Shorts"

    hashtags    = script.get("hashtags", [])
    description = script.get("description", "")
    hashtag_str = " ".join(hashtags[:10])
    full_desc   = f"{description}\n\n{hashtag_str}\n\n#Shorts #KidsLearning #BiscuitAndZara"

    tags = [h.lstrip("#") for h in hashtags]
    tags += ["kids learning", "educational for kids", "preschool", "Biscuit and Zara",
             "cartoon for kids", "animation for kids", "Shorts"]

    body = {
        "snippet": {
            "title":           title,
            "description":     full_desc[:5000],
            "tags":            tags[:500],
            "categoryId":      "27",    # Education
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":          "public",
            "selfDeclaredMadeForKids": True,   # COPPA — required for kids content
        },
    }

    media   = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    print(f"  Uploading: {title}", flush=True)

    request  = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload: {pct}%", end="\r", flush=True)

    video_id = response["id"]
    url      = f"https://youtube.com/shorts/{video_id}"
    print(f"\n  [OK] Uploaded: {url}", flush=True)
    return {"video_id": video_id, "url": url, "title": title}


def set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
    """Set custom thumbnail for uploaded video."""
    from googleapiclient.http import MediaFileUpload
    try:
        media = MediaFileUpload(thumbnail_path, mimetype="image/png")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print(f"  [OK] Thumbnail set", flush=True)
    except Exception as e:
        print(f"  [WARN] Thumbnail upload failed: {e}", flush=True)


# ── Pipeline cleanup helpers ────────────────────────────────────────────────────

def _cleanup_tmp_files():
    """Remove per-video temp files to keep .tmp clean between runs."""
    import glob
    patterns = [
        os.path.join(TMP, "kids_kb_*.mp4"),
        os.path.join(TMP, "kids_cap_*.png"),
        os.path.join(TMP, "kids_badge.png"),
        os.path.join(TMP, "kids_background_full.mp4"),
        os.path.join(TMP, "kids_intro.mp4"),
        os.path.join(TMP, "kids_outro.mp4"),
    ]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except Exception:
                pass


# ── Summary ────────────────────────────────────────────────────────────────────

def _print_summary(produced, requested, safety_fails, uploads, dry_run):
    cost = produced * COST_PER_VIDEO_USD
    print(f"\n{'='*55}", flush=True)
    print(f"  Biscuit & Zara Pipeline — Done!", flush=True)
    print(f"  Videos produced  : {produced}/{requested}", flush=True)
    print(f"  Safety fails     : {safety_fails}", flush=True)
    print(f"  Uploaded         : {'(dry run)' if dry_run else len(uploads)}", flush=True)
    print(f"  Est. API cost    : ${cost:.3f}", flush=True)
    for up in uploads:
        print(f"    → {up.get('url', 'N/A')} | {up.get('topic', '')}", flush=True)
    print(f"{'='*55}\n", flush=True)


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_kids_pipeline(count: int = 1, topic: str = None,
                      series: str = None, dry_run: bool = False,
                      no_upload: bool = False) -> dict:

    os.makedirs(LOG_DIR, exist_ok=True)
    log           = load_log()
    uploads       = []
    safety_fails  = 0
    videos_done   = 0

    # Step 0: Daily review (self-improvement loop)
    if daily_review is not None:
        try:
            print("[0] Daily review (self-improvement)...", flush=True)
            daily_review(KIDS_ACCOUNT)
        except Exception as e:
            print(f"  [WARN] daily review failed: {e}", flush=True)

    memory = AccountMemory(KIDS_ACCOUNT) if AccountMemory else None

    # ── Get topic pool ─────────────────────────────────────────
    if topic:
        topic_pool = [{"topic": topic, "category": "manual", "rank": 1}]
    else:
        print("[1] Fetching trending kids topics...", flush=True)
        trends    = fetch_kids_trends(count=max(count * 3, 10))
        topic_pool = trends.get("topics", [])
        print(f"  [OK] {len(topic_pool)} topics fetched\n", flush=True)

    # Lazy YouTube auth (skip if dry run or no-upload)
    youtube = None
    if not dry_run and not no_upload:
        try:
            print("[AUTH] Authenticating YouTube...", flush=True)
            youtube = get_youtube_service()
            print("  [OK] YouTube ready\n", flush=True)
        except Exception as e:
            print(f"  [WARN] YouTube auth failed: {e} — will compose only\n", flush=True)
            no_upload = True

    # ── Process each topic ─────────────────────────────────────
    for topic_entry in topic_pool:
        if videos_done >= count:
            break

        current_topic  = topic_entry["topic"] if isinstance(topic_entry, dict) else topic_entry
        current_series = series or "standalone"
        current_cat    = topic_entry.get("category", "educational") if isinstance(topic_entry, dict) else "educational"

        print(f"\n{'─'*55}", flush=True)
        print(f"  Topic: {current_topic}", flush=True)
        print(f"  Series: {current_series} | Category: {current_cat}", flush=True)
        print(f"{'─'*55}\n", flush=True)

        try:
            # Step 2: Script
            print("[2] Generating script...", flush=True)
            script = run_step("Script generation",
                              generate_kids_script,
                              current_topic, current_series,
                              max_retries=1)

            # Save script to .tmp for other tools
            with open(SCRIPT_FILE, "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2, ensure_ascii=False)

            # Step 3: Safety check — HARD STOP, no retry
            print("[3] Safety check...", flush=True)
            safety = kids_safety_check(script)
            if safety["result"] == "FAIL":
                print(f"  [BLOCKED] Safety check failed: {safety['flags']}", flush=True)
                safety_fails += 1
                log["safety_fails"].append({
                    "topic":     current_topic,
                    "flags":     safety["flags"],
                    "timestamp": datetime.datetime.now().isoformat()
                })
                log["stats"]["total_safety_fails"] = log["stats"].get("total_safety_fails", 0) + 1
                save_log(log)
                continue
            print(f"  [OK] Safety check passed (confidence: {safety['confidence']})", flush=True)

            # Step 4: TTS voiceover
            print("[4] Generating voiceover...", flush=True)
            tts = run_step("TTS voiceover",
                           generate_kids_tts,
                           script["narration"],
                           max_retries=1)
            print(f"  Duration: {tts['duration_seconds']}s", flush=True)

            # Step 5: Scene images
            print("[5] Generating scene images (AIMLAPI FLUX Pro)...", flush=True)
            visuals = run_step("Scene images",
                               generate_kids_visuals,
                               SCRIPT_FILE,
                               max_retries=1)

            # Step 5b: Background music
            print("[5b] Generating background music...", flush=True)
            run_step("Background music", generate_kids_bg_music, max_retries=1)

            # Step 6: Compose video
            print("[6] Composing video...", flush=True)
            video_filename = f"kids_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            video = run_step("Video composition",
                             compose_kids_video,
                             script.get("title", current_topic),
                             video_filename,
                             tts["duration_seconds"],
                             max_retries=1)

            # Step 7: Thumbnail
            print("[7] Generating thumbnail...", flush=True)
            thumb = run_step("Thumbnail generation",
                             generate_kids_thumbnail,
                             script,
                             max_retries=1)

            videos_done += 1

            # Step 8: Upload
            if dry_run:
                print("[8] DRY RUN — skipping upload", flush=True)
                uploads.append({"topic": current_topic, "url": "(dry run)", "video_id": None})

            elif no_upload or youtube is None:
                print("[8] NO UPLOAD — video saved locally", flush=True)
                uploads.append({"topic": current_topic, "url": video["file"], "video_id": None})

            else:
                print("[8] Uploading to YouTube...", flush=True)
                up = upload_kids_video(youtube, video["file"], script)

                # Step 9: Set thumbnail
                if thumb.get("file") and os.path.exists(thumb["file"]):
                    set_thumbnail(youtube, up["video_id"], thumb["file"])

                upload_entry = {
                    "video_id":         up["video_id"],
                    "yt_video_id":      up["video_id"],
                    "url":              up["url"],
                    "topic":            current_topic,
                    "category":         current_cat,
                    "series":           current_series,
                    "safety_passed":    True,
                    "duration_seconds": video["duration_seconds"],
                    "upload_timestamp": datetime.datetime.now().isoformat(),
                    "title":            up["title"]
                }
                log["uploaded"].append(upload_entry)
                log["stats"]["total_uploaded"] = log["stats"].get("total_uploaded", 0) + 1
                save_log(log)
                uploads.append(upload_entry)

                # Log to memory for self-improvement loop
                if memory:
                    try:
                        memory.add_post({
                            "yt_video_id":  up["video_id"],
                            "topic":        current_topic,
                            "hook":         script.get("narration", "")[:60],
                            "hook_type":    "question" if "?" in script.get("narration", "")[:60] else "fact",
                            "caption":      script.get("description", ""),
                            "hashtags":     script.get("hashtags", []),
                            "scene_prompts":[s.get("image_prompt", "") for s in script.get("scenes", [])],
                            "series":       current_series,
                            "format":       "video",
                            "posted_at":    datetime.datetime.now().isoformat(),
                        })
                    except Exception as _me:
                        print(f"  [WARN] memory log failed: {_me}", flush=True)

            # Cleanup temp files between videos
            _cleanup_tmp_files()

        except Exception as e:
            print(f"\n  [ERROR] Topic failed: {e}\n", flush=True)
            _cleanup_tmp_files()
            continue

    _print_summary(videos_done, count, safety_fails, uploads, dry_run)

    return {
        "videos_produced":         videos_done,
        "videos_requested":        count,
        "safety_fails":            safety_fails,
        "uploads":                 uploads,
        "total_cost_estimate_usd": round(videos_done * COST_PER_VIDEO_USD, 4)
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Biscuit & Zara Kids Animation Pipeline")
    parser.add_argument("--count",     default=1,    type=int,  help="Videos to produce (default: 1)")
    parser.add_argument("--topic",     default=None,            help="Manual topic override")
    parser.add_argument("--series",    default=None,            help="Content series name")
    parser.add_argument("--dry-run",   action="store_true",     help="Run pipeline without uploading")
    parser.add_argument("--no-upload", action="store_true",     help="Compose only, skip YouTube upload")
    args = parser.parse_args()

    result = run_kids_pipeline(
        count     = args.count,
        topic     = args.topic,
        series    = args.series,
        dry_run   = args.dry_run,
        no_upload = args.no_upload
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
