"""
compose_niche_video.py
Composes a 1080x1920 Instagram Reel from AI images + B-roll clips.
Visual style: AI images (Ken Burns) alternating with B-roll (cinematic grade).
Captions: pill-style white background with colored text.
Watermark: account page name at bottom.

Usage: python tools/compose_niche_video.py --account factsflash --page "@FactsFlash"
Inputs:  .tmp/voiceover.mp3, .tmp/captions.srt,
         .tmp/scene_1.png ... scene_3.png (AI images),
         .tmp/broll_1.mp4 ... broll_3.mp4 (B-roll clips)
Output:  .tmp/output_reel.mp4 (1080x1920 @ 30fps)
"""

import argparse, glob, json, math, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP          = os.path.join(PROJECT_ROOT, ".tmp")
VOICEOVER    = os.path.join(TMP, "voiceover.mp3")
SRT_FILE     = os.path.join(TMP, "captions.srt")

import shutil as _shutil
FFMPEG  = _shutil.which("ffmpeg")  or "ffmpeg"
FFPROBE = _shutil.which("ffprobe") or "ffprobe"
FONT_BOLD  = r"C:\Windows\Fonts\arialbd.ttf"

W, H   = 1080, 1920
FPS    = 30
FADE   = 0.35   # xfade transition duration (seconds)

# Ken Burns patterns: (zoom_expr, x_expr, y_expr)
KB_PATTERNS = [
    # Zoom in center
    ("'min(zoom+0.0012,1.4)'",
     "'iw/2-(iw/zoom/2)'",
     "'ih/2-(ih/zoom/2)'"),
    # Zoom out from top-right
    ("'if(eq(on,1),1.4,max(zoom-0.0012,1.0))'",
     "'iw-(iw/zoom)'",
     "'0'"),
    # Pan left → right
    ("'1.25'",
     "'(iw-iw/zoom)*on/{frames}'",
     "'ih/2-(ih/zoom/2)'"),
    # Zoom in on bottom (close-up)
    ("'min(zoom+0.0015,1.5)'",
     "'iw/2-(iw/zoom/2)'",
     "'ih-(ih/zoom)'"),
    # Zoom out from center
    ("'if(eq(on,1),1.5,max(zoom-0.0015,1.0))'",
     "'iw/2-(iw/zoom/2)'",
     "'ih/2-(ih/zoom/2)'"),
    # Pan right → left
    ("'1.25'",
     "'(iw-iw/zoom)*(1-on/{frames})'",
     "'ih/2-(ih/zoom/2)'"),
]

XFADE_TRANSITIONS = ["fade", "wipeleft", "wiperight", "fade", "circleopen", "fade"]

# Caption accent colors per account niche
NICHE_COLORS = {
    "factsflash":       [(255, 220, 50)],           # gold — curiosity, knowledge
    "techmindblown":    [(0, 200, 255)],             # electric blue — futuristic, tech
    "coresteelfitness": [(255, 80, 40)],             # red-orange — energy, power
    "cricketcuts":      [(50, 200, 80)],             # green — cricket field
}
DEFAULT_ACCENT_COLORS = [(255, 255, 255)]            # white fallback


# ── FFmpeg helpers ─────────────────────────────────────────────────────────────

def run(cmd, label=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error [{label}]:\n{result.stderr[-1500:]}")
    return result


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


# ── Segment generators ─────────────────────────────────────────────────────────

def make_ken_burns_clip(image_path: str, idx: int, duration: float) -> str:
    """Apply Ken Burns effect to a PNG image, output as MP4 segment."""
    out    = os.path.join(TMP, f"seg_img_{idx}.mp4")
    frames = int(duration * FPS)
    z, x, y = KB_PATTERNS[idx % len(KB_PATTERNS)]

    # Replace {frames} placeholder in pan expressions
    x = x.replace("{frames}", str(max(frames, 1)))
    y = y.replace("{frames}", str(max(frames, 1)))

    grade   = "eq=saturation=1.3:brightness=0.02:contrast=1.05"
    zoompan = f"zoompan=z={z}:x={x}:y={y}:d={frames}:s={W}x{H}:fps={FPS}"
    vf      = f"scale={W*2}:{H*2},{zoompan},{grade},format=yuv420p"

    run([
        FFMPEG, "-y",
        "-loop", "1", "-framerate", str(FPS),
        "-i", image_path,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out
    ], f"ken_burns_{idx}")
    return out


def make_broll_clip(broll_path: str, idx: int, duration: float) -> str:
    """Grade and trim a B-roll clip to the required duration."""
    out   = os.path.join(TMP, f"seg_broll_{idx}.mp4")
    src_d = get_duration(broll_path)
    loops = max(1, int(duration / src_d) + 2)
    grade = "eq=brightness=-0.15:saturation=1.25:gamma_r=1.03:gamma_b=0.97"

    vf = (
        f"loop={loops}:size=32767:start=0,"
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"{grade},"
        f"trim=duration={duration:.3f},"
        f"format=yuv420p"
    )
    run([
        FFMPEG, "-y",
        "-i", broll_path,
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-an", out
    ], f"broll_{idx}")
    return out


# ── Segment concat ─────────────────────────────────────────────────────────────

def concat_segments(clip_paths: list, seg_dur: float) -> str:
    out = os.path.join(TMP, "bg_concat.mp4")
    n   = len(clip_paths)

    if n == 1:
        # Single clip — just copy
        run([FFMPEG, "-y", "-i", clip_paths[0],
             "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", out], "concat_single")
        return out

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    # Normalize each input to same fps + timebase before xfade
    norm_parts = []
    for i in range(n):
        norm_parts.append(f"[{i}:v]fps={FPS},settb=1/{FPS}[n{i}]")

    cumulative = 0.0
    prev       = "n0"
    xfade_parts = []

    for i in range(1, n):
        cumulative += seg_dur
        offset      = max(cumulative - i * FADE, 0.0)
        transition  = XFADE_TRANSITIONS[(i - 1) % len(XFADE_TRANSITIONS)]
        out_label   = f"v{i}" if i < n - 1 else "vout"
        xfade_parts.append(
            f"[{prev}][n{i}]xfade=transition={transition}"
            f":duration={FADE}:offset={offset:.3f}[{out_label}]"
        )
        prev = out_label

    all_parts = norm_parts + xfade_parts

    run([
        FFMPEG, "-y", *inputs,
        "-filter_complex", ";".join(all_parts),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out
    ], "concat_xfade")
    return out


# ── SRT parser ─────────────────────────────────────────────────────────────────

def parse_srt(srt_path: str) -> list:
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    def ts(t):
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

    entries = []
    for block in re.split(r"\n\n+", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            t1, t2 = lines[1].split(" --> ")
            entries.append({
                "start": ts(t1.strip()),
                "end":   ts(t2.strip()),
                "text":  " ".join(lines[2:])
            })
    return entries


# ── Caption PNGs ───────────────────────────────────────────────────────────────

def _draw_rounded_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1+radius, y1, x2-radius, y2], fill=fill)
    draw.rectangle([x1, y1+radius, x2, y2-radius], fill=fill)
    draw.ellipse([x1, y1, x1+2*radius, y1+2*radius], fill=fill)
    draw.ellipse([x2-2*radius, y1, x2, y1+2*radius], fill=fill)
    draw.ellipse([x1, y2-2*radius, x1+2*radius, y2], fill=fill)
    draw.ellipse([x2-2*radius, y2-2*radius, x2, y2], fill=fill)


def render_caption_png(text: str, idx: int, account: str = "") -> str:
    """Render a 2-word caption with pill background and colored accent text."""
    img    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)
    font   = ImageFont.truetype(FONT_BOLD, 88)
    colors = NICHE_COLORS.get(account, DEFAULT_ACCENT_COLORS)
    color  = colors[idx % len(colors)]

    text_upper = text.strip().upper()
    bb  = draw.textbbox((0, 0), text_upper, font=font)
    tw  = bb[2] - bb[0]
    th  = bb[3] - bb[1]
    px  = 40
    py  = 20
    x   = (W - tw) // 2
    y   = int(H * 0.65)   # lower-center of screen

    pill = [x - px, y - py, x + tw + px, y + th + py]

    # Drop shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd     = ImageDraw.Draw(shadow)
    _draw_rounded_rect(sd, [pill[0]+6, pill[1]+6, pill[2]+6, pill[3]+6], 28, (0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    img    = Image.alpha_composite(img, shadow)

    # White pill background
    pill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill_layer)
    _draw_rounded_rect(pd, pill, 28, (255, 255, 255, 240))
    img = Image.alpha_composite(img, pill_layer)

    # Dark outline for text
    draw2 = ImageDraw.Draw(img)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if abs(dx) + abs(dy) >= 4:
                continue
            if dx or dy:
                draw2.text((x+dx, y+dy), text_upper, font=font, fill=(30, 30, 30, 160))

    # Colored text
    draw2.text((x, y), text_upper, font=font, fill=(*color, 255))

    path = os.path.join(TMP, f"niche_cap_{idx:04d}.png")
    img.save(path)
    return path


# ── Watermark PNG ──────────────────────────────────────────────────────────────

def render_watermark_png(page_name: str) -> str:
    """Render account page name as watermark at bottom of frame."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 46)

    bb  = draw.textbbox((0, 0), page_name, font=font)
    tw  = bb[2] - bb[0]
    th  = bb[3] - bb[1]
    x   = (W - tw) // 2
    y   = H - th - 55

    # Semi-transparent dark background bar
    bar_h = th + 24
    bar_y = y - 12
    bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd  = ImageDraw.Draw(bar)
    bd.rectangle([0, bar_y, W, bar_y + bar_h], fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img, bar)

    draw2 = ImageDraw.Draw(img)
    # White text with subtle shadow
    draw2.text((x+2, y+2), page_name, font=font, fill=(0, 0, 0, 120))
    draw2.text((x,   y),   page_name, font=font, fill=(255, 255, 255, 230))

    path = os.path.join(TMP, "niche_watermark.png")
    img.save(path)
    return path


# ── Final composite ────────────────────────────────────────────────────────────

def composite_final(bg_path: str, srt_entries: list, watermark_png: str,
                    voiceover_path: str, duration: float, output_path: str,
                    account: str = "") -> None:
    cap_files = [
        (render_caption_png(e["text"], i, account), e["start"], e["end"])
        for i, e in enumerate(srt_entries)
    ]

    # Build inputs
    inputs = ["-i", bg_path, "-i", voiceover_path, "-i", watermark_png]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]

    # Build filter graph
    # watermark is input [2], captions start at [3]
    wm_idx = 2
    filter_parts = [
        f"[0:v][{wm_idx}:v]overlay=0:0[s0]",
    ]

    prev = "s0"
    for idx, (_, start, end) in enumerate(cap_files):
        inp   = idx + 3
        label = f"c{idx}" if idx < len(cap_files) - 1 else "vfinal"
        filter_parts.append(
            f"[{prev}][{inp}:v]overlay=0:0"
            f":enable='between(t,{start:.3f},{end:.3f})'[{label}]"
        )
        prev = label

    if not cap_files:
        filter_parts.append(f"[s0]null[vfinal]")

    filtergraph = ";".join(filter_parts)

    run([
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[vfinal]",
        "-map", "1:a:0",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path
    ], "final_composite")


# ── Main ───────────────────────────────────────────────────────────────────────

def compose_niche_video(page_name: str, output_filename: str = "output_reel.mp4", account: str = "") -> dict:
    os.makedirs(TMP, exist_ok=True)
    output_path = os.path.join(TMP, output_filename)

    if not os.path.exists(VOICEOVER):
        raise FileNotFoundError(f"Missing voiceover: {VOICEOVER} — run generate_elevenlabs_tts.py first")
    if not os.path.exists(SRT_FILE):
        raise FileNotFoundError(f"Missing captions: {SRT_FILE} — run generate_elevenlabs_tts.py first")

    duration = get_duration(VOICEOVER)
    print(f"Voiceover duration: {duration:.1f}s", flush=True)

    # Gather visuals
    images = sorted(glob.glob(os.path.join(TMP, "scene_*.png")))[:3]
    brolls = sorted(glob.glob(os.path.join(TMP, "broll_*.mp4")))[:3]
    print(f"Found: {len(images)} AI image(s), {len(brolls)} B-roll clip(s)", flush=True)

    if not images and not brolls:
        raise FileNotFoundError("No scene_*.png or broll_*.mp4 files in .tmp/")

    # Build interleaved sequence: img, broll, img, broll, ...
    sequence = []
    max_n = max(len(images), len(brolls))
    for i in range(max_n):
        if i < len(images):
            sequence.append(("image", images[i]))
        if i < len(brolls):
            sequence.append(("broll", brolls[i]))

    # Add extra margin for xfade overlap and ensure we cover full duration
    seg_dur = (duration + FADE * len(sequence)) / len(sequence)
    seg_dur = max(seg_dur, 3.0)
    print(f"Segments: {len(sequence)} x {seg_dur:.1f}s each", flush=True)

    # Generate segment clips
    print("\nStep 1 — Generating visual segments...", flush=True)
    clip_paths = []
    img_idx = 0
    broll_idx = 0
    for i, (seg_type, path) in enumerate(sequence):
        print(f"  [{i+1}/{len(sequence)}] {seg_type}: {os.path.basename(path)}", flush=True)
        if seg_type == "image":
            clip = make_ken_burns_clip(path, img_idx, seg_dur)
            img_idx += 1
        else:
            clip = make_broll_clip(path, broll_idx, seg_dur)
            broll_idx += 1
        clip_paths.append(clip)

    # Concat segments with xfade
    print("\nStep 2 — Concatenating with transitions...", flush=True)
    bg_path = concat_segments(clip_paths, seg_dur)
    print(f"  [OK] Background: {bg_path}", flush=True)

    # Parse captions
    print("\nStep 3 — Parsing captions...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    print(f"  [OK] {len(srt_entries)} caption blocks", flush=True)

    # Render watermark
    print("\nStep 4 — Rendering watermark...", flush=True)
    watermark_png = render_watermark_png(page_name)

    # Final composite
    print("\nStep 5 — Final composite...", flush=True)
    composite_final(bg_path, srt_entries, watermark_png, VOICEOVER, duration, output_path, account)
    print(f"  [OK] Done -> {output_path}", flush=True)

    # Cleanup temp segments
    for p in clip_paths + [bg_path, watermark_png]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    for p in glob.glob(os.path.join(TMP, "niche_cap_*.png")):
        try:
            os.remove(p)
        except Exception:
            pass

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    return {
        "file":         output_path,
        "duration":     round(duration, 2),
        "resolution":   f"{W}x{H}",
        "segments":     len(sequence),
        "captions":     len(srt_entries),
        "size_mb":      round(size_mb, 1),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="factsflash", help="Account name")
    parser.add_argument("--page",    default=None,          help="Page name e.g. @FactsFlash")
    parser.add_argument("--output",  default="output_reel.mp4", help="Output filename")
    args = parser.parse_args()

    page_name = args.page
    if not page_name:
        # Try to load from config
        cfg_path = os.path.join(PROJECT_ROOT, "config", "accounts", f"{args.account}.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                page_name = json.load(f).get("ig_page_name", f"@{args.account}")
        else:
            page_name = f"@{args.account}"

    print(f"Composing niche video for [{page_name}]...", flush=True)
    result = compose_niche_video(page_name, args.output, args.account)
    print(json.dumps(result, indent=2))
