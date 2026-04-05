"""
compose_avatar_video.py
Composes the final 1080x1920 YouTube Short from a D-ID talking avatar video.
- Scales and centers avatar video on a blurred background
- Adds synced yellow captions from SRT file
- Adds celebrity name badge overlay (top)
- Mixes original audio from avatar video

Usage: python tools/compose_avatar_video.py "ELON MUSK" [output_filename]
Inputs:  .tmp/avatar_raw.mp4, .tmp/captions.srt
Output:  .tmp/output_short.mp4 (1080x1920 @ 30fps)
"""

import json
import os
import re
import sys
import subprocess
from PIL import Image, ImageDraw, ImageFont

TMP        = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
AVATAR_RAW = os.path.join(TMP, "avatar_raw.mp4")
SRT_FILE   = os.path.join(TMP, "captions.srt")

FFMPEG_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG     = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE    = os.path.join(FFMPEG_BIN, "ffprobe.exe")
FONT_BOLD  = r"C:\Windows\Fonts\arialbd.ttf"

W, H       = 1080, 1920   # target vertical resolution


def run(cmd, label=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error [{label}]:\n{result.stderr[-800:]}")
    return result


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def get_video_size(path: str) -> tuple:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams",
         "-select_streams", "v:0", path],
        capture_output=True, text=True
    )
    stream = json.loads(r.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def make_vertical_avatar(avatar_path: str, output_path: str) -> str:
    """
    Scale avatar to fit vertically in 1080x1920 frame.
    Fills background with a blurred + darkened version of the avatar.
    Avatar is placed in the upper 60% of the frame (face-forward area).
    """
    print("Step 1/4 -- Converting avatar to vertical 1080x1920...", flush=True)

    # Strategy:
    # 1. Scale blurred avatar to fill full 1080x1920 (background layer)
    # 2. Scale avatar to fit width=1080, keeping aspect ratio (foreground layer)
    # 3. Position foreground centered vertically in upper portion

    fc = (
        # Background: scale to fill, blur, darken
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "boxblur=20:1,"
        "eq=brightness=-0.3[bg];"

        # Foreground: scale width to 1080, keep aspect ratio
        "[0:v]scale=1080:-2[fg];"

        # Overlay fg centered horizontally, positioned at 10% from top
        "[bg][fg]overlay=(W-w)/2:H*0.05[out]"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", avatar_path,
        "-filter_complex", fc,
        "-map", "[out]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",  # strip audio here; we'll add it back in final composite
        output_path
    ]
    run(cmd, "make_vertical_avatar")
    print(f"  [OK] Vertical avatar -> {output_path}", flush=True)
    return output_path


def parse_srt(srt_path: str) -> list:
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    def ts_to_sec(ts):
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

    entries = []
    for block in re.split(r"\n\n+", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            times = lines[1].split(" --> ")
            entries.append({
                "start": ts_to_sec(times[0].strip()),
                "end":   ts_to_sec(times[1].strip()),
                "text":  " ".join(lines[2:])
            })
    return entries


def render_caption_png(text: str, idx: int) -> str:
    """Render a single caption as a transparent PNG (same style as compose_video.py)."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 80)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    x    = (W - tw) // 2
    y    = int(H * 0.76)

    pad  = 20
    pill = Image.new("RGBA", (tw + pad*2, th + pad), (0, 0, 0, 160))
    img.paste(pill, (x - pad, y - pad//2), pill)

    outline = 6
    for dx in range(-outline, outline+1):
        for dy in range(-outline, outline+1):
            if dx or dy:
                draw.text((x+dx, y+dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 215, 0, 255))

    path = os.path.join(TMP, f"cap_{idx:04d}.png")
    img.save(path)
    return path


def make_badge_png(celebrity_name: str) -> str:
    """Render celebrity name badge as transparent PNG."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_tag = ImageFont.truetype(FONT_BOLD, 44)
    tag      = f" {celebrity_name.upper()} "
    bbox     = draw.textbbox((0, 0), tag, font=font_tag)
    tw       = bbox[2] - bbox[0]
    th       = bbox[3] - bbox[1]
    tx       = (W - tw) // 2
    ty       = 60

    # Red pill background
    pill = Image.new("RGBA", (tw + 48, th + 24), (220, 20, 20, 220))
    img.paste(pill, (tx - 24, ty - 12), pill)

    # Outline + white text
    for dx in [-2, 0, 2]:
        for dy in [-2, 0, 2]:
            if dx or dy:
                draw.text((tx+dx, ty+dy), tag, font=font_tag, fill=(0, 0, 0, 255))
    draw.text((tx, ty), tag, font=font_tag, fill=(255, 255, 255, 255))

    path = os.path.join(TMP, "badge.png")
    img.save(path)
    return path


def composite_final(vertical_video: str, avatar_audio_src: str, srt_entries: list,
                    badge_png: str, output_path: str, duration: float) -> str:
    """Overlay badge + timed captions onto vertical video, mix original audio."""

    cap_files = []
    for i, entry in enumerate(srt_entries):
        p = render_caption_png(entry["text"], i)
        cap_files.append((p, entry["start"], entry["end"]))

    inputs = ["-i", vertical_video, "-i", badge_png]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]
    # Original audio from the D-ID avatar video
    inputs += ["-i", avatar_audio_src]

    audio_idx = len(cap_files) + 2

    filter_parts = [f"[0:v][1:v]overlay=0:0[b0]"]
    prev = "b0"
    for idx, (_, start, end) in enumerate(cap_files):
        inp_idx  = idx + 2
        out_label = f"c{idx}" if idx < len(cap_files) - 1 else "vfinal"
        filter_parts.append(
            f"[{prev}][{inp_idx}:v]overlay=0:0"
            f":enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
        )
        prev = out_label

    filtergraph = ";".join(filter_parts)

    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[vfinal]",
        "-map", f"{audio_idx}:a:0",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]
    run(cmd, "final_composite")
    return output_path


def compose_avatar_video(celebrity_name: str, output_filename: str = "output_short.mp4") -> dict:
    os.makedirs(TMP, exist_ok=True)
    output_path = os.path.join(TMP, output_filename)

    if not os.path.exists(AVATAR_RAW):
        raise FileNotFoundError(f"Missing: {AVATAR_RAW} -- run generate_did_avatar.py first")
    if not os.path.exists(SRT_FILE):
        raise FileNotFoundError(f"Missing: {SRT_FILE} -- run generate_tts.py first")

    duration        = get_duration(AVATAR_RAW)
    vertical_path   = os.path.join(TMP, "avatar_vertical.mp4")

    make_vertical_avatar(AVATAR_RAW, vertical_path)

    print("Step 2/4 -- Parsing captions...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    print(f"  [OK] {len(srt_entries)} caption lines loaded", flush=True)

    print("Step 3/4 -- Rendering badge overlay...", flush=True)
    badge_png = make_badge_png(celebrity_name)
    print("  [OK] Badge PNG created", flush=True)

    print("Step 4/4 -- Final composite...", flush=True)
    composite_final(vertical_path, AVATAR_RAW, srt_entries, badge_png, output_path, duration)
    print(f"  [OK] Done -> {output_path}", flush=True)

    return {
        "file": output_path,
        "celebrity": celebrity_name,
        "duration_seconds": round(duration, 2),
        "resolution": f"{W}x{H}",
        "captions": len(srt_entries)
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/compose_avatar_video.py \"Celebrity Name\" [output_filename]")
        sys.exit(1)
    name     = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output_short.mp4"
    result   = compose_avatar_video(name, out_file)
    print(json.dumps(result, indent=2))
