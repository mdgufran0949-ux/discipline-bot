"""
brand_reel.py
Removes original creator's branding from a reel and adds your page branding.

Steps:
1. Download owner's profile pic → template-match it in video frames → find exact position
2. Delogo that position (content-aware fill)
3. Overlay your page's circular profile pic at the same position, same size
4. Find owner's username text via OCR → delogo + replace with your page name
5. Add your page name at bottom center (always)

Usage: python tools/brand_reel.py "video.mp4" "@YourPage" "owner_username" [owner_pic] [my_pic]
"""

import json
import os
import re
import sys
import subprocess
from dotenv import load_dotenv

load_dotenv()

import cv2
import easyocr
import numpy as np

FFMPEG_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG     = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE    = os.path.join(FFMPEG_BIN, "ffprobe.exe")
FONT_BOLD  = r"C:\Windows\Fonts\arialbd.ttf"
YTDLP_BIN  = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe"


def _font_path_for_ffmpeg(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:")


def _escape_text(text: str) -> str:
    return text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")


def _extract_frames(video_path: str):
    cap          = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    video_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_ms  = (total_frames / fps) * 1000 if fps > 0 else 10000

    frames = []
    for t in [500, int(duration_ms * 0.33), int(duration_ms * 0.66)]:
        cap.set(cv2.CAP_PROP_POS_MSEC, t)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    cap.release()
    return frames, video_w, video_h


def _match_profile_pic(frames, owner_pic_path: str, video_w: int, video_h: int):
    """
    Multi-scale template matching to find owner's profile pic in video.
    Returns (x, y, w, h) of best match, or None if not found.
    """
    template = cv2.imread(owner_pic_path)
    if template is None:
        return None

    th, tw = template.shape[:2]
    best_val   = 0
    best_match = None

    for scale in [0.25, 0.35, 0.5, 0.65, 0.8, 1.0]:
        rw = max(10, int(tw * scale))
        rh = max(10, int(th * scale))
        resized = cv2.resize(template, (rw, rh))

        for frame in frames:
            if frame.shape[0] < rh or frame.shape[1] < rw:
                continue
            result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val:
                best_val   = max_val
                best_match = (max_loc[0], max_loc[1], rw, rh)

    if best_val >= 0.55:
        x, y, w, h = best_match
        pad = 8
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(video_w - x, w + 2 * pad)
        h = min(video_h - y, h + 2 * pad)
        print(f"  [MATCH] Profile pic found at ({x},{y}) {w}x{h} (confidence {best_val:.2f})", flush=True)
        return x, y, w, h

    print(f"  [MATCH] Profile pic not matched (best confidence {best_val:.2f}). Using fixed corner.", flush=True)
    return None


def _make_circular_png(src_path: str, width: int, height: int, out_path: str) -> bool:
    """Resize image to (width, height) and apply circular transparency mask. Saves as PNG."""
    img = cv2.imread(src_path)
    if img is None:
        return False
    img = cv2.resize(img, (width, height))
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, (width // 2, height // 2), min(width, height) // 2, 255, -1)
    img_rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    img_rgba[:, :, 3] = mask
    cv2.imwrite(out_path, img_rgba)
    return True


def _matches_owner(text: str, owner_username: str) -> bool:
    text_clean  = text.strip().lower().lstrip('@')
    owner_clean = owner_username.strip().lower().lstrip('@')
    if not owner_clean or len(owner_clean) < 3:
        return False
    return owner_clean in text_clean or text_clean in owner_clean


def _detect_owner_text(frames, video_w, video_h, owner_username: str) -> list:
    """OCR scan — returns list of (x, y, w, h, cx, cy) for owner username text regions."""
    if not owner_username or len(owner_username.strip().lstrip('@')) < 3:
        return []

    print(f"  [OCR] Scanning for '@{owner_username}' text...", flush=True)
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    seen, regions = set(), []

    for frame in frames:
        for (bbox, text, conf) in reader.readtext(frame):
            if conf < 0.3 or not _matches_owner(text, owner_username):
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - x), int(max(ys) - y)
            pad = 12
            rx = max(0, x - pad)
            ry = max(0, y - pad)
            rw = min(video_w - rx, w + 2 * pad)
            rh = min(video_h - ry, h + 2 * pad)
            key = (rx // 20, ry // 20)
            if key not in seen:
                seen.add(key)
                regions.append((rx, ry, rw, rh, rx + rw // 2, ry + rh // 2))
                print(f"  [OCR] Found '{text}' at ({rx},{ry}) {rw}x{rh}", flush=True)

    if not regions:
        print(f"  [OCR] '{owner_username}' not found in video.", flush=True)
    return regions


def _detect_any_handle(frames, video_w, video_h) -> list:
    """
    Scan frames for ANY @handle watermark text — works for unknown owners too.
    Returns list of (x, y, w, h, cx, cy) regions to delogo.
    """
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    seen, regions = set(), []
    handle_pat = re.compile(r'@[\w.]+', re.IGNORECASE)

    for frame in frames:
        for (bbox, text, conf) in reader.readtext(frame):
            if conf < 0.25:
                continue
            if not handle_pat.search(text):
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - x), int(max(ys) - y)
            pad = 15
            rx = max(1, x - pad)
            ry = max(1, y - pad)
            rw = min(video_w - rx - 1, w + 2 * pad)
            rh = min(video_h - ry - 1, h + 2 * pad)
            key = (rx // 20, ry // 20)
            if key not in seen:
                seen.add(key)
                regions.append((rx, ry, rw, rh, rx + rw // 2, ry + rh // 2))
                print(f"  [OCR] Watermark found: '{text}' at ({rx},{ry})", flush=True)
    return regions


def _download_subtitles(post_url: str, base_path: str) -> "str | None":
    """Download YouTube auto-subtitles for a Short. Returns .vtt path or None."""
    vtt_path = f"{base_path}.en.vtt"
    if os.path.exists(vtt_path):
        return vtt_path
    try:
        subprocess.run([
            YTDLP_BIN,
            "--write-auto-subs", "--sub-lang", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "--quiet", "--no-warnings",
            "-o", base_path,
            post_url
        ], capture_output=True, text=True, timeout=30)
    except Exception:
        pass
    return vtt_path if os.path.exists(vtt_path) else None


def _find_cta_timestamp(vtt_path: str, owner_username: str) -> "float | None":
    """
    Parse VTT subtitles. Return start time (seconds) of the creator's CTA, or None.
    Only matches CTAs in the last 15 seconds of the video.
    """
    import re
    try:
        with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return None

    cue_pattern = re.compile(
        r'(\d+):(\d+):(\d+\.\d+)\s*-->\s*\S.*?\n([\s\S]*?)(?=\n\n|\Z)'
    )
    cues = []
    for m in cue_pattern.finditer(content):
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        start_sec = h * 3600 + mn * 60 + s
        text = re.sub(r'<[^>]+>', '', m.group(4)).strip()
        if text:
            cues.append((start_sec, text))

    if not cues:
        return None

    last_time = cues[-1][0]
    search_from = max(0.0, last_time - 15.0)

    owner_clean = owner_username.strip().lower().lstrip('@').replace('_', ' ')

    cta_patterns = [
        r'\bfollow\b.{0,40}for more\b',
        r'\bfollow\b.{0,40}subscribe\b',
        r'\blike and follow\b',
        r'\bfollow me\b',
        r'\bfollow us\b',
    ]
    if owner_clean and len(owner_clean) >= 3:
        cta_patterns.insert(0, r'\bfollow\b.{0,60}' + re.escape(owner_clean))

    for start_sec, text in cues:
        if start_sec < search_from:
            continue
        text_lower = text.lower()
        for pat in cta_patterns:
            if re.search(pat, text_lower):
                return start_sec

    return None


def _get_video_duration(video_path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 30.0  # safe fallback


def brand_reel(input_path: str, page_name: str, owner_username: str = "",
               owner_pic_path: str = None, my_pic_path: str = None,
               post_url: str = None) -> dict:
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    base      = os.path.splitext(input_path)[0]
    out_path  = f"{base}_branded.mp4"
    font_esc  = _font_path_for_ffmpeg(FONT_BOLD)
    page_esc  = _escape_text(page_name)

    print(f"Branding: {os.path.basename(input_path)}", flush=True)
    print(f"  Owner   : @{owner_username}", flush=True)
    print(f"  Rebrand : {page_name}", flush=True)

    frames, video_w, video_h = _extract_frames(input_path)
    if not frames:
        raise RuntimeError("Could not extract frames from video")

    # --- CTA detection via YouTube subtitles ---
    cta_timestamp = None
    if post_url:
        vtt_path = _download_subtitles(post_url, base)
        if vtt_path:
            cta_timestamp = _find_cta_timestamp(vtt_path, owner_username)
            if cta_timestamp:
                print(f"  [CTA] Found creator CTA at {cta_timestamp:.1f}s — trimming", flush=True)
            try:
                os.remove(vtt_path)
            except Exception:
                pass

    def _clamp(x, y, w, h):
        """Ensure delogo region is strictly within video bounds."""
        x = max(0, min(x, video_w - 2))
        y = max(0, min(y, video_h - 2))
        w = max(1, min(w, video_w - x - 1))
        h = max(1, min(h, video_h - y - 1))
        return x, y, w, h

    # --- Profile picture: detect position ---
    pic_region = None
    known_owner = owner_username and owner_username.strip().lower() not in ("", "unknown")

    if known_owner and owner_pic_path and os.path.exists(owner_pic_path):
        pic_region = _match_profile_pic(frames, owner_pic_path, video_w, video_h)

    # Delogo corners only when we have a matched position or known owner
    # Skip fixed-corner delogo when owner is unknown — avoids FFmpeg border errors
    filters_vf = []
    if pic_region:
        pic_x, pic_y, pic_w, pic_h = _clamp(*pic_region)
        filters_vf.append(f"delogo=x={pic_x}:y={pic_y}:w={pic_w}:h={pic_h}")
        # top-right corner (only delogo when we have a real match)
        tr_x, tr_y, tr_w, tr_h = _clamp(max(1, video_w - 210), 1, min(208, video_w - 2), 128)
        filters_vf.append(f"delogo=x={tr_x}:y={tr_y}:w={tr_w}:h={tr_h}")
    else:
        # No owner pic — set fallback position for overlay placement only (no delogo)
        pic_x, pic_y, pic_w, pic_h = 5, 5, 120, 120

    # --- OCR: find watermark text ---
    # Known owner: specific scan for their username (more accurate)
    text_regions = _detect_owner_text(frames, video_w, video_h, owner_username) if known_owner else []
    # Fallback: generic @handle scan (catches unknown owner watermarks)
    if not text_regions:
        text_regions = _detect_any_handle(frames, video_w, video_h)

    # Always delogo bottom-right area (YouTube standard @handle position)
    br_x = max(1, video_w - 350)
    br_y = max(1, video_h - 120)
    br_w = min(348, video_w - br_x - 1)
    br_h = min(118, video_h - br_y - 1)
    filters_vf.append(f"delogo=x={br_x}:y={br_y}:w={br_w}:h={br_h}")

    # Owner text: delogo + replace with your page name
    for (x, y, w, h, cx, cy) in text_regions:
        x, y, w, h = _clamp(x, y, w, h)
        filters_vf.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
        font_size = max(16, min(h + 4, 28))
        filters_vf.append(
            f"drawtext=fontfile='{font_esc}':text='{page_esc}':"
            f"fontcolor=white@0.9:fontsize={font_size}:"
            f"x={cx}-text_w/2:y={cy}-text_h/2:"
            f"shadowcolor=black@0.9:shadowx=1:shadowy=1"
        )

    # Always add page name at bottom center
    filters_vf.append(
        f"drawtext=fontfile='{font_esc}':text='{page_esc}':"
        f"fontcolor=white@0.85:fontsize=32:"
        f"x=(w-text_w)/2:y=h-45:"
        f"shadowcolor=black@0.9:shadowx=2:shadowy=2"
    )

    # Centered "Follow @PageName" for last 2.5 seconds
    end_time   = cta_timestamp if cta_timestamp else _get_video_duration(input_path)
    cta_start  = max(0.0, end_time - 2.5)
    filters_vf.append(
        f"drawtext=fontfile='{font_esc}':text='Follow {page_esc}':"
        f"fontcolor=white@0.95:fontsize=40:"
        f"x=(w-text_w)/2:y=(h/2)-20:"
        f"enable='gte(t,{cta_start})':"
        f"shadowcolor=black@0.9:shadowx=2:shadowy=2"
    )

    # --- Build FFmpeg command ---
    # Case A: overlay user's circular logo at profile pic position
    if my_pic_path and os.path.exists(my_pic_path):
        circular_path = f"{base}_logo_circle.png"
        if _make_circular_png(my_pic_path, pic_w, pic_h, circular_path):
            print(f"  [OVERLAY] Placing your logo at ({pic_x},{pic_y}) {pic_w}x{pic_h}", flush=True)
            vf_chain = ",".join(filters_vf)
            complex_filter = f"[0:v]{vf_chain}[v];[v][1:v]overlay={pic_x}:{pic_y}"
            cmd = [
                FFMPEG, "-y",
                "-i", input_path,
                "-i", circular_path,
                "-filter_complex", complex_filter,
                "-c:v", "libx264", "-preset", "slow", "-crf", "17",
                "-c:a", "copy", "-movflags", "+faststart",
                out_path
            ]
        else:
            # circular PNG creation failed — fall back to vf only
            my_pic_path = None

    # Case B: no overlay — just delogo + text
    if not my_pic_path or not os.path.exists(my_pic_path):
        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
            "-vf", ",".join(filters_vf),
            "-c:v", "libx264", "-preset", "slow", "-crf", "17",
            "-c:a", "copy", "-movflags", "+faststart",
            out_path
        ]

    # Insert trim flag if CTA was detected
    if cta_timestamp:
        idx = cmd.index(out_path)
        cmd.insert(idx, "-t")
        cmd.insert(cmd.index(out_path), str(cta_timestamp))

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup temp circular logo
    if os.path.exists(f"{base}_logo_circle.png"):
        os.remove(f"{base}_logo_circle.png")

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg branding failed:\n{result.stderr[-800:]}")

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"  [OK] Done: {out_path} ({size_mb:.1f} MB)", flush=True)
    return {"input": input_path, "output": out_path, "page_name": page_name, "size_mb": round(size_mb, 2)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tools/brand_reel.py video.mp4 @YourPage owner_username [owner_pic] [my_pic]")
        sys.exit(1)
    result = brand_reel(
        sys.argv[1], sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "",
        sys.argv[4] if len(sys.argv) > 4 else None,
        sys.argv[5] if len(sys.argv) > 5 else None,
    )
    print(json.dumps(result, indent=2))
