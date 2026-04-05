"""
compose_video.py
Composes a 30-second viral Short:
  - 6 AI images with Ken Burns zoom/pan motion (5 sec each)
  - Crossfade transitions between scenes
  - Synced yellow captions from SRT file
  - TRENDING NOW badge overlay
  - Voiceover audio

Usage: python tools/compose_video.py "Title text" [output_filename]
Inputs:  .tmp/scene_1..6.png, .tmp/voiceover.mp3, .tmp/captions.srt
Output:  .tmp/output_short.mp4 (1080x1920)
"""

import json
import sys
import os
import subprocess
import re
from PIL import Image, ImageDraw, ImageFont

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
VOICEOVER   = os.path.join(TMP, "voiceover.mp3")
SRT_FILE    = os.path.join(TMP, "captions.srt")
FFMPEG_BIN  = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG      = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE     = os.path.join(FFMPEG_BIN, "ffprobe.exe")
FONT_BOLD   = r"C:\Windows\Fonts\arialbd.ttf"
FONT_REG    = r"C:\Windows\Fonts\arial.ttf"
W, H        = 1080, 1920
SCENE_DUR   = 5.0   # seconds per scene
N_SCENES    = 6
FADE_DUR    = 0.5   # crossfade duration in seconds

def run(cmd, label=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error [{label}]:\n{result.stderr[-600:]}")
    return result

def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])

# -- Step 1: Ken Burns clip per scene image ----------------------------------

def make_ken_burns_clip(image_path: str, scene_id: int, duration: float) -> str:
    """Apply Ken Burns zoom/pan effect to a single image -> short .mp4 clip."""
    out = os.path.join(TMP, f"kb_{scene_id}.mp4")
    frames = int(duration * 30)  # 30fps

    # Alternate zoom in / zoom out per scene
    if scene_id % 2 == 1:
        zoom_expr = "'min(zoom+0.0015,1.5)'"
    else:
        zoom_expr = "'if(eq(on,1),1.5,max(zoom-0.0015,1.0))'"
    x_expr = "'iw/2-(iw/zoom/2)'"
    y_expr = "'ih/2-(ih/zoom/2)'"

    zoompan = (
        f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
        f":d={frames}:s={W}x{H}:fps=30"
    )
    # Color grade: boost saturation + slight brightness lift
    color_grade = "eq=saturation=1.35:brightness=0.02:contrast=1.05"

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-framerate", "30",
        "-i", image_path,
        "-t", str(duration),
        "-vf", f"scale=2160:3840,{zoompan},{color_grade},format=yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        out
    ]
    run(cmd, f"ken_burns_scene_{scene_id}")
    return out

# -- Step 2: Concat all clips with xfade transitions -------------------------

def concat_with_xfade(clip_paths: list, fade: float = FADE_DUR) -> str:
    """Concatenate N clips using xfade crossfade filter."""
    out = os.path.join(TMP, "background_full.mp4")

    # Build complex filter for chained xfades
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    n = len(clip_paths)
    filt_parts = []
    offset = SCENE_DUR - fade  # first transition offset

    # Chain xfades: [0][1]xfade->v1, [v1][2]xfade->v2, etc.
    prev = "0:v"
    for i in range(1, n):
        out_label = f"v{i}" if i < n - 1 else "vout"
        filt_parts.append(
            f"[{prev}][{i}:v]xfade=transition=fade:duration={fade}"
            f":offset={offset:.2f}[{out_label}]"
        )
        prev = out_label
        offset += SCENE_DUR - fade

    filtergraph = ";".join(filt_parts)

    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        out
    ]
    run(cmd, "concat_xfade")
    return out

# -- Step 3: Parse SRT & render caption frames --------------------------------

def parse_srt(srt_path: str) -> list:
    """Parse SRT into list of {start_sec, end_sec, text}."""
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
    """Render a single caption as transparent PNG."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 80)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2
    y = int(H * 0.76)

    # Semi-transparent dark pill background
    pad = 20
    pill = Image.new("RGBA", (tw + pad*2, th + pad), (0, 0, 0, 160))
    img.paste(pill, (x - pad, y - pad//2), pill)

    # Outline
    outline = 6
    for dx in range(-outline, outline+1):
        for dy in range(-outline, outline+1):
            if dx or dy:
                draw.text((x+dx, y+dy), text, font=font, fill=(0, 0, 0, 255))
    # Yellow text
    draw.text((x, y), text, font=font, fill=(255, 215, 0, 255))

    path = os.path.join(TMP, f"cap_{idx:04d}.png")
    img.save(path)
    return path

# -- Step 4: Badge overlay PNG ------------------------------------------------

def make_badge_png(title: str) -> str:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # "TRENDING NOW" badge
    font_tag = ImageFont.truetype(FONT_BOLD, 44)
    tag = " TRENDING NOW"
    bbox = draw.textbbox((0, 0), tag, font=font_tag)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (W - tw) // 2
    ty = 90
    pill = Image.new("RGBA", (tw + 48, th + 24), (220, 20, 20, 220))
    img.paste(pill, (tx - 24, ty - 12), pill)
    for dx in [-2, 0, 2]:
        for dy in [-2, 0, 2]:
            if dx or dy:
                draw.text((tx+dx, ty+dy), tag, font=font_tag, fill=(0,0,0,255))
    draw.text((tx, ty), tag, font=font_tag, fill=(255, 255, 255, 255))

    # Title (smaller, below badge)
    font_title = ImageFont.truetype(FONT_BOLD, 52)
    words = title.upper().split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0,0), test, font=font_title)
        if bbox[2]-bbox[0] <= W - 80:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur: lines.append(cur)
    lh = 64
    sy = 180
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0,0), line, font=font_title)
        lx = (W - (bbox[2]-bbox[0])) // 2
        for dx in [-3,0,3]:
            for dy in [-3,0,3]:
                if dx or dy:
                    draw.text((lx+dx, sy+i*lh+dy), line, font=font_title, fill=(0,0,0,200))
        draw.text((lx, sy+i*lh), line, font=font_title, fill=(255,255,255,255))

    path = os.path.join(TMP, "badge.png")
    img.save(path)
    return path

# -- Step 5: Final composite --------------------------------------------------

def composite_final(bg_video: str, audio: str, srt_entries: list,
                    badge_png: str, output_path: str, total_duration: float) -> str:
    """Overlay badge + per-caption PNGs onto background video with voiceover."""

    # Render all caption PNGs
    cap_files = []
    for i, entry in enumerate(srt_entries):
        p = render_caption_png(entry["text"], i)
        cap_files.append((p, entry["start"], entry["end"]))

    # Build ffmpeg filter_complex with badge + all captions
    inputs = ["-i", bg_video, "-i", badge_png]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]

    # filter_complex: overlay badge first, then each caption timed
    filter_parts = []
    filter_parts.append(f"[0:v][1:v]overlay=0:0[b0]")

    prev = "b0"
    for idx, (_, start, end) in enumerate(cap_files):
        inp_idx = idx + 2   # inputs start at index 2
        out_label = f"c{idx}" if idx < len(cap_files)-1 else "vfinal"
        filter_parts.append(
            f"[{prev}][{inp_idx}:v]overlay=0:0"
            f":enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
        )
        prev = out_label

    filtergraph = ";".join(filter_parts)

    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-i", audio,
        "-filter_complex", filtergraph,
        "-map", "[vfinal]",
        "-map", f"{len(cap_files)+2}:a:0",
        "-t", str(total_duration),
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

# -- Main ---------------------------------------------------------------------

def compose_video(title: str, output_filename: str = "output_short.mp4") -> dict:
    os.makedirs(TMP, exist_ok=True)
    output_path = os.path.join(TMP, output_filename)
    audio_dur   = get_duration(VOICEOVER)

    print("Step 1/5 -- Ken Burns effects...", flush=True)
    clip_paths = []
    for i in range(1, N_SCENES + 1):
        img = os.path.join(TMP, f"scene_{i}.png")
        if not os.path.exists(img):
            raise FileNotFoundError(f"Missing: {img} -- run generate_visuals.py first")
        clip = make_ken_burns_clip(img, i, SCENE_DUR)
        clip_paths.append(clip)
        print(f"  [OK] Scene {i} Ken Burns done", flush=True)

    print("Step 2/5 -- Concatenating with crossfades...", flush=True)
    bg_video = concat_with_xfade(clip_paths)
    print("  [OK] Background video assembled", flush=True)

    print("Step 3/5 -- Parsing captions...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    print(f"  [OK] {len(srt_entries)} caption lines loaded", flush=True)

    print("Step 4/5 -- Rendering badge overlay...", flush=True)
    badge_png = make_badge_png(title)
    print("  [OK] Badge PNG created", flush=True)

    print("Step 5/5 -- Final composite...", flush=True)
    composite_final(bg_video, VOICEOVER, srt_entries, badge_png, output_path, audio_dur)
    print(f"  [OK] Done -> {output_path}", flush=True)

    return {
        "file": output_path,
        "duration_seconds": round(audio_dur, 2),
        "resolution": f"{W}x{H}",
        "scenes": N_SCENES,
        "captions": len(srt_entries)
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/compose_video.py \"title\" [output_filename]")
        sys.exit(1)
    title    = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output_short.mp4"
    result   = compose_video(title, out_file)
    print(json.dumps(result, indent=2))
