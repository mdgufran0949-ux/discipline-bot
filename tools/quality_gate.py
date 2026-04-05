"""
quality_gate.py
AI-powered quality gate for downloaded reels.

Checks (in order):
  1. Creator diversity  — rejects if same creator appears 3+ times in last 30 uploads
  2. Audio language     — rejects non-English audio with no English text overlay
  3. Visual energy      — rejects static slideshows, text-on-plain-bg, low-energy content

Uses Gemini 1.5 Flash via REST API (GEMINI_API_KEY in .env).
Fails open: if Gemini is unavailable, only creator check applies.

Usage (standalone test):
  python tools/quality_gate.py video.mp4 --niche "amazing facts" --creator "someuser"
"""

import os
import sys
import json
import base64
import tempfile
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL     = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-1.5-flash:generateContent"
)

FFMPEG  = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")


# ── Media extraction ───────────────────────────────────────────────────────────

def _video_duration(path: str) -> float:
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=10
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 30))
    except Exception:
        return 30.0


def _extract_frames(path: str, count: int = 3) -> list:
    """Return list of temp JPEG paths extracted at evenly-spaced timestamps."""
    duration   = _video_duration(path)
    timestamps = [duration * i / (count + 1) for i in range(1, count + 1)]
    frames = []
    for i, ts in enumerate(timestamps):
        out = os.path.join(tempfile.gettempdir(), f"qg_frame_{os.getpid()}_{i}.jpg")
        try:
            subprocess.run(
                [FFMPEG, "-ss", str(ts), "-i", path,
                 "-frames:v", "1", "-q:v", "3", out, "-y", "-loglevel", "quiet"],
                timeout=15, capture_output=True
            )
            if os.path.exists(out) and os.path.getsize(out) > 5_000:
                frames.append(out)
        except Exception:
            pass
    return frames


def _extract_audio(path: str, seconds: int = 15) -> str | None:
    """Extract first N seconds as low-bitrate mono MP3. Returns path or None."""
    out = os.path.join(tempfile.gettempdir(), f"qg_audio_{os.getpid()}.mp3")
    try:
        subprocess.run(
            [FFMPEG, "-i", path, "-t", str(seconds),
             "-vn", "-ar", "16000", "-ac", "1", "-b:a", "48k",
             out, "-y", "-loglevel", "quiet"],
            timeout=30, capture_output=True
        )
        if os.path.exists(out) and os.path.getsize(out) > 2_000:
            return out
    except Exception:
        pass
    return None


def _cleanup(paths: list) -> None:
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


# ── Gemini call ────────────────────────────────────────────────────────────────

def _gemini_check(frames: list, audio_path: str | None, niche: str) -> dict | None:
    """
    Single Gemini multimodal call: audio language + visual energy.
    Returns parsed dict or None on any failure.
    """
    import requests

    prompt = f"""You are a quality checker for Instagram Reels.
The account posts about: "{niche}"

Analyze the provided video frames and audio sample, then answer ONLY with valid JSON:
{{
  "audio_language": "english or hindi or other",
  "has_english_text_overlay": true or false,
  "is_static_slideshow": true or false,
  "is_text_on_plain_background": true or false,
  "is_talking_head_only": true or false,
  "has_visual_variety": true or false,
  "energy_score": 1 to 10
}}

Definitions:
- audio_language: primary spoken language detected in the audio
- has_english_text_overlay: English words/captions/subtitles visible on screen
- is_static_slideshow: content is mostly still images with no real motion footage
- is_text_on_plain_background: text shown on a solid color background with no footage
- is_talking_head_only: just a person talking to camera with minimal visual cuts
- has_visual_variety: multiple scenes, cuts, footage changes, or motion graphics
- energy_score: 1=completely static and boring, 10=highly dynamic and engaging"""

    parts = [{"text": prompt}]

    for fp in frames[:3]:
        try:
            with open(fp, "rb") as f:
                parts.append({"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(f.read()).decode()
                }})
        except Exception:
            pass

    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                parts.append({"inline_data": {
                    "mime_type": "audio/mpeg",
                    "data": base64.b64encode(f.read()).decode()
                }})
        except Exception:
            pass

    if len(parts) == 1:
        return None  # Nothing to send

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300}
    }

    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=30
        )
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception:
        return None


# ── Main check ─────────────────────────────────────────────────────────────────

def quality_gate_check(video_path: str, reel: dict, account_cfg: dict,
                       account_name: str, upload_log: dict) -> dict:
    """
    Run all quality checks on a downloaded reel.

    Args:
        video_path  : Path to downloaded .mp4 file
        reel        : Reel metadata (id, caption, owner_username, view_count, ...)
        account_cfg : Account config dict (niche, ...)
        account_name: Account name string
        upload_log  : Current upload log dict (for creator diversity check)

    Returns:
        {
            "passed"       : bool,
            "score"        : int  (0-100),
            "failed_checks": list[str],
            "reason"       : str
        }
    """
    failed = []
    score  = 100

    # ── Check 1: Creator diversity ─────────────────────────────
    creator = (reel.get("owner_username") or "").strip()
    if creator:
        recent       = upload_log.get("uploaded", [])[-30:]
        creator_hits = sum(1 for u in recent if u.get("owner_username", "") == creator)
        if creator_hits >= 3:
            failed.append(f"creator @{creator} already posted {creator_hits}x in last 30 uploads")
            score -= 40

    # ── Check 2 & 3: AI vision (audio language + visual energy) ─
    if not GEMINI_API_KEY:
        passed = score >= 60
        reason = " | ".join(failed) if failed else "passed (Gemini key not set — AI checks skipped)"
        return {"passed": passed, "score": max(0, score), "failed_checks": failed, "reason": reason}

    niche      = account_cfg.get("niche", "general content")
    frames     = _extract_frames(video_path, count=3)
    audio      = _extract_audio(video_path, seconds=15)
    temp_files = frames + ([audio] if audio else [])

    ai = _gemini_check(frames, audio, niche)
    _cleanup(temp_files)

    if ai:
        # Audio language gate
        lang            = (ai.get("audio_language") or "english").lower()
        has_eng_overlay = ai.get("has_english_text_overlay", True)

        if lang not in ("english", "en") and not has_eng_overlay:
            failed.append(f"non-English audio ({lang}) with no English text overlay")
            score -= 50

        # Visual energy gate
        energy       = ai.get("energy_score", 7)
        is_slideshow = ai.get("is_static_slideshow", False)
        is_text_bg   = ai.get("is_text_on_plain_background", False)
        is_head_only = ai.get("is_talking_head_only", False)

        if energy < 4:
            failed.append(f"low visual energy ({energy}/10)")
            score -= 35
        elif is_slideshow:
            failed.append("static image slideshow")
            score -= 30
        elif is_text_bg and energy < 5:
            failed.append("text on plain background with no real footage")
            score -= 25
        elif is_head_only and energy < 5:
            failed.append(f"talking head only, low energy ({energy}/10)")
            score -= 20
    else:
        # Gemini call failed — fail open, don't penalise the reel
        pass

    passed = len(failed) == 0 and score >= 60
    reason = " | ".join(failed) if failed else "all checks passed"
    return {"passed": passed, "score": max(0, score), "failed_checks": failed, "reason": reason}


# ── CLI test ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test quality gate on a local video file")
    parser.add_argument("video",    help="Path to .mp4 video file")
    parser.add_argument("--niche",   default="amazing facts", help="Account niche")
    parser.add_argument("--creator", default="",              help="Creator username")
    args = parser.parse_args()

    result = quality_gate_check(
        video_path   = args.video,
        reel         = {"owner_username": args.creator, "caption": "test"},
        account_cfg  = {"niche": args.niche},
        account_name = "test",
        upload_log   = {"uploaded": []}
    )
    print(json.dumps(result, indent=2))
