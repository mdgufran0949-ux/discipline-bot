"""
compose_motivation_video.py
Viral-format motivation Reel composer (1080x1920):
  Full-screen B-roll (script-matched, cinematic)
  Small circular face cam at bottom-center (270px with white border)
  Bold word-by-word captions at screen center (power words in gold)
  Channel badge at top

Usage: python tools/compose_motivation_video.py "ALEX" [output_filename]
Inputs:  .tmp/avatar_raw.mp4, .tmp/broll_*.mp4 (or stock_clip.mp4), .tmp/captions.srt
Output:  .tmp/output_short.mp4 (1080x1920 @ 30fps)
"""

import glob, json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

TMP        = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
AVATAR_RAW = os.path.join(TMP, "avatar_raw.mp4")
STOCK_CLIP = os.path.join(TMP, "stock_clip.mp4")
SRT_FILE   = os.path.join(TMP, "captions.srt")

import shutil as _sh
FFMPEG  = _sh.which("ffmpeg")  or "ffmpeg"
FFPROBE = _sh.which("ffprobe") or "ffprobe"
FONT_BOLD  = r"C:\Windows\Fonts\arialbd.ttf"

W, H = 1080, 1920

# Layout — face cam at bottom-center, captions at center of screen
FACE_SIZE   = 270                        # face circle diameter
RING_BORDER = 7                          # white border width in px
RING_SIZE   = FACE_SIZE + RING_BORDER*2  # = 284
FACE_X      = (W - RING_SIZE) // 2      # = 398 (centered)
FACE_Y      = H - RING_SIZE - 110       # = 1526 (near bottom)
CAP_Y       = int(H * 0.40)             # = 768 (center of screen, within safe zone)

# Background music (optional — place epic instrumental here)
MUSIC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "music", "background.mp3"))

# Power words render in gold; everything else is white
POWER_WORDS = {
    "you", "your", "stop", "now", "never", "dead", "truth", "real", "quit",
    "weak", "soft", "lie", "lied", "lies", "lying", "fear", "fail", "failed",
    "win", "own", "rise", "done", "lazy", "buried", "chosen", "fake", "stuck",
    "wrong", "lost", "broken", "scared", "comfort", "comfortable", "excuses",
    "excuse", "accountable", "clock", "mirror", "enough", "today", "wake",
    "assassin", "terrified", "trap", "overdue"
}


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


def _find_broll_clips() -> list:
    clips = sorted(glob.glob(os.path.join(TMP, "broll_*.mp4")))
    if clips:
        return clips
    if os.path.exists(STOCK_CLIP):
        return [STOCK_CLIP]
    return []


def make_full_bg(clip_paths: list, duration: float, output_path: str) -> None:
    """Full 1080x1920 background: clips concatenated, cinematic grade."""
    grade = "eq=brightness=-0.18:saturation=1.3:gamma_r=1.05:gamma_b=0.93"

    if not clip_paths:
        fc = f"color=c=0x0a0a14:size=1080x1920:duration={duration}:rate=30[bg]"
        cmd = [FFMPEG, "-y", "-filter_complex", fc, "-map", "[bg]",
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", output_path]
        run(cmd, "bg_fallback")
        print("  [WARN] No B-roll found — using dark background", flush=True)
        return

    if len(clip_paths) == 1:
        loops = max(1, int(duration / get_duration(clip_paths[0])) + 2)
        fc = (
            f"[0:v]loop={loops}:size=32767:start=0,"
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,{grade},"
            f"trim=duration={duration}[bg]"
        )
        cmd = [FFMPEG, "-y", "-i", clip_paths[0], "-filter_complex", fc,
               "-map", "[bg]", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-an", output_path]
        run(cmd, "bg_single")
    else:
        clip_dur = duration / len(clip_paths)
        inputs_cmd, filter_parts = [], []
        for i, p in enumerate(clip_paths):
            inputs_cmd += ["-i", p]
            loops = max(1, int(clip_dur / get_duration(p)) + 2)
            filter_parts.append(
                f"[{i}:v]loop={loops}:size=32767:start=0,"
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,{grade},"
                f"trim=duration={clip_dur:.3f}[v{i}]"
            )
        concat_in = "".join(f"[v{i}]" for i in range(len(clip_paths)))
        filter_parts.append(f"{concat_in}concat=n={len(clip_paths)}:v=1:a=0[bg]")
        fc = ";".join(filter_parts)
        cmd = [FFMPEG, "-y", *inputs_cmd, "-filter_complex", fc,
               "-map", "[bg]", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-an", output_path]
        run(cmd, "bg_multi")

    print(f"  [OK] Full-screen background ({len(clip_paths)} clip(s))", flush=True)


def make_ring_png() -> str:
    """White ring PNG (RING_SIZE x RING_SIZE): white outer circle, transparent inside/outside."""
    size   = RING_SIZE
    inner  = RING_BORDER
    img    = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill=(255, 255, 255, 255))  # white filled circle
    draw.ellipse([inner, inner, size - 1 - inner, size - 1 - inner], fill=(0, 0, 0, 0))  # punch out inside
    path = os.path.join(TMP, "face_ring.png")
    img.save(path)
    return path


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
    """Render one caption word: power words in gold, rest in white, thick black outline."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 96)

    word     = text.strip().encode("ascii", "ignore").decode("ascii").strip().upper()
    clean    = text.strip().lower().strip(".,!?\"'")
    is_power = clean in POWER_WORDS
    color    = (255, 200, 0, 255) if is_power else (255, 255, 255, 255)

    bbox = draw.textbbox((0, 0), word, font=font)
    tw   = bbox[2] - bbox[0]
    x    = (W - tw) // 2
    y    = CAP_Y

    outline = 8
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), word, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), word, font=font, fill=color)

    path = os.path.join(TMP, f"cap_{idx:04d}.png")
    img.save(path)
    return path


def make_badge_png(name: str) -> str:
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 42)
    tag  = f"  {name.upper()}  "

    bbox = draw.textbbox((0, 0), tag, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    tx   = (W - tw) // 2
    ty   = 55

    pill = Image.new("RGBA", (tw + 40, th + 20), (200, 20, 20, 230))
    img.paste(pill, (tx - 20, ty - 10), pill)
    for dx in [-2, 0, 2]:
        for dy in [-2, 0, 2]:
            if dx or dy:
                draw.text((tx + dx, ty + dy), tag, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, ty), tag, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(TMP, "badge.png")
    img.save(path)
    return path


def composite_final(bg_path: str, ring_png: str,
                    srt_entries: list, badge_png: str,
                    output_path: str, duration: float) -> None:
    """
    Composite:
      [0] bg (full 1080x1920)
      [1] avatar_raw (video for face cam, audio for voice)
      [2] badge PNG
      [3] ring PNG
      [4..N] caption PNGs
      [N+1] music (optional)
    """
    cap_files = [(render_caption_png(e["text"], i), e["start"], e["end"])
                 for i, e in enumerate(srt_entries)]

    has_music = os.path.exists(MUSIC_PATH)
    if has_music:
        print(f"  [music] {os.path.basename(MUSIC_PATH)}", flush=True)

    # Build input list
    inputs = ["-i", bg_path, "-i", AVATAR_RAW, "-i", badge_png, "-i", ring_png]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]
    if has_music:
        music_idx = len(cap_files) + 4
        inputs += ["-i", MUSIC_PATH]

    # Filter graph
    filter_parts = [
        # Circular face crop (270x270, RGBA, transparent outside circle)
        f"[1:v]scale={FACE_SIZE}:{FACE_SIZE}:force_original_aspect_ratio=increase,"
        f"crop={FACE_SIZE}:{FACE_SIZE},format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='255*lt(pow(X-{FACE_SIZE//2},2)+pow(Y-{FACE_SIZE//2},2),pow({FACE_SIZE//2},2))'[fc]",

        # Pad face circle to ring size (adds transparent margin = border area)
        f"[fc]pad={RING_SIZE}:{RING_SIZE}:{RING_BORDER}:{RING_BORDER}:color=black@0[fp]",

        # Overlay white ring on top of padded face
        f"[fp][3:v]overlay=0:0[face_cam]",

        # Overlay face cam on full background
        f"[0:v][face_cam]overlay={FACE_X}:{FACE_Y}[s0]",
    ]

    # Overlay badge
    last_label = "s1" if cap_files else "vfinal"
    filter_parts.append(f"[s0][2:v]overlay=0:0[{last_label}]")

    # Overlay captions one-by-one
    prev = last_label
    for idx, (_, start, end) in enumerate(cap_files):
        inp_idx   = idx + 4
        out_label = f"c{idx}" if idx < len(cap_files) - 1 else "vfinal"
        filter_parts.append(
            f"[{prev}][{inp_idx}:v]overlay=0:0"
            f":enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
        )
        prev = out_label

    # Audio: voice + optional music
    fade_out_start = max(0.0, duration - 2.0)
    if has_music:
        filter_parts.append(
            f"[1:a]volume=1.0[voice];"
            f"[{music_idx}:a]volume=0.12,"
            f"afade=t=in:st=0:d=1.5,"
            f"afade=t=out:st={fade_out_start:.2f}:d=2[music];"
            f"[voice][music]amix=inputs=2:duration=first[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = "1:a:0"

    filtergraph = ";".join(filter_parts)

    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[vfinal]",
        "-map", audio_map,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ]
    run(cmd, "final_composite")


def compose_motivation_video(character_name: str, output_filename: str = "output_short.mp4") -> dict:
    os.makedirs(TMP, exist_ok=True)
    output_path = os.path.join(TMP, output_filename)
    bg_path     = os.path.join(TMP, "bg_prepared.mp4")

    if not os.path.exists(AVATAR_RAW):
        raise FileNotFoundError(f"Missing: {AVATAR_RAW} — run generate_latsync_avatar.py first")
    if not os.path.exists(SRT_FILE):
        raise FileNotFoundError(f"Missing: {SRT_FILE} — run generate_kokoro_tts.py first")

    duration    = get_duration(AVATAR_RAW)
    broll_clips = _find_broll_clips()
    print(f"Composing {duration:.1f}s reel for [{character_name}] | "
          f"{len(broll_clips)} B-roll clip(s)", flush=True)

    print("Step 1/5 — Full-screen B-roll background...", flush=True)
    make_full_bg(broll_clips, duration, bg_path)

    print("Step 2/5 — Parsing captions...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    print(f"  [OK] {len(srt_entries)} caption blocks", flush=True)

    print("Step 3/5 — Badge...", flush=True)
    badge_png = make_badge_png(character_name)

    print("Step 4/5 — Face ring...", flush=True)
    ring_png = make_ring_png()

    print("Step 5/5 — Final composite...", flush=True)
    composite_final(bg_path, ring_png, srt_entries, badge_png, output_path, duration)
    print(f"  [OK] Done -> {output_path}", flush=True)

    if os.path.exists(bg_path):
        os.remove(bg_path)

    return {
        "file":             output_path,
        "character":        character_name,
        "duration_seconds": round(duration, 2),
        "resolution":       f"{W}x{H}",
        "captions":         len(srt_entries),
        "broll_clips":      len(broll_clips),
        "layout":           f"Full B-roll + face cam ({RING_SIZE}px circle at bottom-center) + center captions"
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/compose_motivation_video.py "ALEX" [output_filename]')
        sys.exit(1)
    name     = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output_short.mp4"
    result   = compose_motivation_video(name, out_file)
    print(json.dumps(result, indent=2))
