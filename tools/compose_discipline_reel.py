"""
compose_discipline_reel.py
Ken Burns zoom + text overlay + BGM mix -> 15s 1080x1920 MP4 for Instagram Reels.

Quick test:
    python tools/compose_discipline_reel.py <path/to/bg.png>
"""

import hashlib
import os
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

TOOLS_DIR  = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.abspath(os.path.join(TOOLS_DIR, "..", "assets", "fonts"))
TMP_BASE   = os.path.abspath(os.path.join(TOOLS_DIR, "..", ".tmp", "disciplinefuel"))

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

W, H = 1080, 1920
FPS  = 30

_FONT_NAMES = [
    "Montserrat-Bold.ttf", "BebasNeue-Regular.ttf",
    "Oswald-Bold.ttf", "PlayfairDisplay-Bold.ttf",
]
_SYS_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
]


def _load_font(size):
    candidates = [os.path.join(ASSETS_DIR, f) for f in _FONT_NAMES] + _SYS_FONTS
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _wrap_text(text, font, max_width, draw):
    words = text.split()
    lines, current = [], []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _render_overlay(quote, series_label):
    """Return path to 1080x1920 RGBA PNG: bottom gradient + quote + series label."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Bottom 40% gradient: transparent → black@0.30 opacity
    grad_top = int(H * 0.60)
    for y in range(grad_top, H):
        alpha = int((y - grad_top) / (H - grad_top) * 77)
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

    word_count = len(quote.split())
    if word_count <= 10:
        q_size = 96
    elif word_count <= 20:
        q_size = 80
    elif word_count <= 35:
        q_size = 68
    else:
        q_size = 56

    font_q = _load_font(q_size)
    font_s = _load_font(38)

    white  = (255, 255, 255, 255)
    shadow = (0,   0,   0,   180)
    max_w  = 940

    lines  = _wrap_text(quote, font_q, max_w, draw)
    line_h = q_size + 14
    block_h = len(lines) * line_h
    y0 = max(int(H * 0.55), int(H * 0.62) - block_h // 2)

    for i, line in enumerate(lines):
        y = y0 + i * line_h
        bbox = draw.textbbox((0, 0), line, font=font_q)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x + 2, y + 2), line, font=font_q, fill=shadow)
        draw.text((x,     y),     line, font=font_q, fill=white)

    # Series label at top
    bbox = draw.textbbox((0, 0), series_label, font=font_s)
    lx = (W - (bbox[2] - bbox[0])) // 2
    draw.text((lx + 2, 82), series_label, font=font_s, fill=shadow)
    draw.text((lx,     80), series_label, font=font_s, fill=(255, 255, 255, 200))

    out = os.path.join(TMP_BASE, "reel_overlay.png")
    img.save(out)
    return out


def compose_discipline_reel(
    quote: str,
    series_label: str,
    design_style: str,
    bg_image_path: str,
    duration_sec: float = 15.0,
    output_path: str = None
) -> dict:
    os.makedirs(TMP_BASE, exist_ok=True)
    reels_dir = os.path.join(TMP_BASE, "reels")
    os.makedirs(reels_dir, exist_ok=True)

    if output_path is None:
        output_path = os.path.join(reels_dir, f"reel_{int(time.time())}.mp4")

    total_frames = int(duration_sec * FPS)

    # Deterministic vertical drift direction from quote hash (±30px over 15s)
    qhash   = int(hashlib.md5(quote.encode()).hexdigest(), 16)
    pan_px  = 28 * (1 if qhash % 2 == 0 else -1)

    overlay_png = _render_overlay(quote, series_label)

    bgm_path = os.path.join(TMP_BASE, "bgm.mp3")
    has_bgm  = os.path.exists(bgm_path)

    # ── ffmpeg inputs ────────────────────────────────────────────────────────
    if has_bgm:
        audio_inputs = ["-i", bgm_path]
        audio_idx    = 2
    else:
        # Silent fallback: lavfi anullsrc as input 2
        audio_inputs = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration_sec + 1}"]
        audio_idx    = 2

    inputs = [
        "-loop", "1", "-r", str(FPS), "-i", bg_image_path,
        "-loop", "1", "-r", str(FPS), "-i", overlay_png,
        *audio_inputs,
    ]

    # ── filtergraph ──────────────────────────────────────────────────────────
    # Ken Burns: zoom 1.0 → 1.15, slight vertical drift
    kb = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='min(1+on/{total_frames}*0.15,1.15)'"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)+{pan_px}*on/{total_frames}'"
        f":d={total_frames}:s={W}x{H}:fps={FPS}[kb]"
    )
    # Text overlay with 0.5s fade-in
    txt = (
        f"[1:v]format=rgba,"
        f"fade=in:st=0:d=0.5:alpha=1[txt]"
    )
    # Composite
    comp = "[kb][txt]overlay=0:0,format=yuv420p[vid]"

    # Audio: volume + fade in/out
    vol = 0.25 if has_bgm else 1.0
    fade_out_start = max(0.0, duration_sec - 1.5)
    aud = (
        f"[{audio_idx}:a]volume={vol},"
        f"afade=t=in:st=0:d=1.0,"
        f"afade=t=out:st={fade_out_start:.2f}:d=1.5[aout]"
    )

    filtergraph = ";".join([kb, txt, comp, aud])

    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[vid]",
        "-map", "[aout]",
        "-t", str(duration_sec),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    print(f"  [reel] Composing {duration_sec:.0f}s reel...", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-1200:]}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [OK] Reel: {output_path} ({size_mb:.1f} MB)", flush=True)

    return {"file": output_path, "duration": duration_sec, "design_style": design_style}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compose_discipline_reel.py <bg_image_path>")
        sys.exit(1)
    r = compose_discipline_reel(
        quote="Discipline is the bridge between goals and accomplishment.",
        series_label="DISCIPLINE RULE #1",
        design_style="dark",
        bg_image_path=sys.argv[1],
    )
    print(r)
