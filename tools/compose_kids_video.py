"""
compose_kids_video.py — Professional Edition
Broadcast-quality kids animation Shorts for the Biscuit & Zara channel.

Features:
  - Animated channel logo intro (PIL-rendered, ffmpeg-animated)
  - 6 unique Ken Burns patterns with subtle character bounce
  - Glow + shadow captions (Comic Sans Bold 130px, rotating colors, rounded pill)
  - Varied xfade transitions (fade / wipeleft / wiperight / circleopen)
  - Professional animated outro ("See You Tomorrow!")
  - FIXED audio sync: narration starts after intro (adelay)
  - Background music at 12% volume if .tmp/kids_bg_music.mp3 exists
  - Outputs 1080x1920 Shorts + 1920x1080 landscape
"""

import json, sys, os, subprocess, re, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
IMAGES_DIR  = os.path.join(TMP, "kids_images")
VOICEOVER   = os.path.join(TMP, "kids_voiceover.mp3")
SRT_FILE    = os.path.join(TMP, "kids_captions.srt")
BG_MUSIC    = os.path.join(TMP, "kids_bg_music.mp3")   # optional — place your own royalty-free track here

FFMPEG_BIN  = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG      = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE     = os.path.join(FFMPEG_BIN, "ffprobe.exe")

FONT_KIDS   = r"C:\Windows\Fonts\comicbd.ttf"
FONT_BOLD   = r"C:\Windows\Fonts\arialbd.ttf"
FONT_PATH   = FONT_KIDS if os.path.exists(FONT_KIDS) else FONT_BOLD

W, H        = 1080, 1920
SCENE_DUR   = 8.0
N_SCENES    = 6
FADE_DUR    = 0.4
INTRO_DUR   = 2.0
OUTRO_DUR   = 3.0

# Bright, rotating caption colors (6-color cycle)
CAPTION_COLORS = [
    (255,  87,  34),   # deep orange
    ( 76, 175,  80),   # green
    ( 33, 150, 243),   # blue
    (255, 193,   7),   # amber
    (156,  39, 176),   # purple
    (233,  30,  99),   # pink
]

# Varied xfade transitions (index matches scene index)
TRANSITIONS = ["fade", "wipeleft", "wiperight", "fade", "circleopen", "fade", "fade"]

# 6 Ken Burns patterns — varied zoom direction + bounce
KB_PATTERNS = [
    # 1: Zoom in center
    ("'min(zoom+0.0015,1.5)'",
     "'iw/2-(iw/zoom/2)'",
     "'ih/2-(ih/zoom/2)+3*sin(2*PI*on/(30*1.5))'"),
    # 2: Zoom out, start from top-right
    ("'if(eq(on,1),1.5,max(zoom-0.0015,1.0))'",
     "'iw-(iw/zoom)'",
     "'0'"),
    # 3: Pan left (character enters from right)
    ("'min(zoom+0.001,1.35)'",
     "'iw-(iw/zoom)'",
     "'ih/2-(ih/zoom/2)+3*sin(2*PI*on/(30*1.2))'"),
    # 4: Pan right (character enters from left)
    ("'min(zoom+0.001,1.35)'",
     "'0'",
     "'ih/2-(ih/zoom/2)'"),
    # 5: Zoom in on bottom (character close-up)
    ("'min(zoom+0.002,1.8)'",
     "'iw/2-(iw/zoom/2)'",
     "'ih-(ih/zoom)'"),
    # 6: Wide reveal — zoom out, see full scene
    ("'if(eq(on,1),1.8,max(zoom-0.002,1.0))'",
     "'iw/2-(iw/zoom/2)'",
     "'ih/2-(ih/zoom/2)+3*sin(2*PI*on/(30*2))'"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, label=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error [{label}]:\n{result.stderr[-1200:]}")
    return result


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def draw_rounded_rect(draw, xy, radius, fill):
    """Draw a filled rounded rectangle (PIL compat for all versions)."""
    x1, y1, x2, y2 = xy
    draw.rectangle([x1+radius, y1, x2-radius, y2], fill=fill)
    draw.rectangle([x1, y1+radius, x2, y2-radius], fill=fill)
    draw.ellipse([x1, y1, x1+2*radius, y1+2*radius], fill=fill)
    draw.ellipse([x2-2*radius, y1, x2, y1+2*radius], fill=fill)
    draw.ellipse([x1, y2-2*radius, x1+2*radius, y2], fill=fill)
    draw.ellipse([x2-2*radius, y2-2*radius, x2, y2], fill=fill)


def draw_star(draw, cx, cy, size, color):
    """Draw a filled 5-point star."""
    pts = []
    for i in range(10):
        angle = math.pi * i / 5 - math.pi / 2
        r = size if i % 2 == 0 else size * 0.42
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(pts, fill=color)


# ── Intro PNG ─────────────────────────────────────────────────────────────────

def make_intro_png() -> str:
    img  = Image.new("RGBA", (W, H), (255, 215, 0, 255))   # Golden yellow
    draw = ImageDraw.Draw(img)

    # Radial gradient overlay (darker at edges → bright center)
    for y in range(0, H, 4):
        for x in range(0, W, 4):
            cx = (x - W/2) / (W/2)
            cy = (y - H/2) / (H/2)
            d  = min(1.0, math.sqrt(cx**2 + cy**2))
            alpha = int(d * 60)
            draw.rectangle([x, y, x+3, y+3], fill=(200, 150, 0, alpha))

    # Background star decorations
    rng = random.Random(42)
    for _ in range(18):
        sx    = rng.randint(40, W - 40)
        sy    = rng.randint(40, H - 40)
        size  = rng.randint(18, 55)
        alpha = rng.randint(80, 180)
        draw_star(draw, sx, sy, size, (255, 255, 255, alpha))

    # Channel logo circle
    cx, cy, r = W//2, H//2 - 150, 240
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 255, 255, 230))

    # "B&Z" inside circle
    font_logo = ImageFont.truetype(FONT_PATH, 160)
    bz_text   = "B&Z"
    bb = draw.textbbox((0, 0), bz_text, font=font_logo)
    tx = cx - (bb[2]-bb[0])//2
    ty = cy - (bb[3]-bb[1])//2 - 10
    # Shadow
    draw.text((tx+5, ty+5), bz_text, font=font_logo, fill=(0, 0, 0, 80))
    # Gradient text (orange)
    draw.text((tx, ty), bz_text, font=font_logo, fill=(255, 87, 34, 255))

    # Channel name
    font_title = ImageFont.truetype(FONT_PATH, 90)
    title      = "Biscuit & Zara"
    bb2 = draw.textbbox((0, 0), title, font=font_title)
    tx2 = (W - (bb2[2]-bb2[0])) // 2
    ty2 = H//2 + 130
    draw.text((tx2+4, ty2+4), title, font=font_title, fill=(0, 0, 0, 100))
    draw.text((tx2, ty2), title, font=font_title, fill=(255, 255, 255, 255))

    # Tagline
    font_sub = ImageFont.truetype(FONT_PATH, 52)
    tagline  = "Learning is Fun!"
    bb3 = draw.textbbox((0, 0), tagline, font=font_sub)
    tx3 = (W - (bb3[2]-bb3[0])) // 2
    ty3 = ty2 + 110
    draw.text((tx3, ty3), tagline, font=font_sub, fill=(255, 87, 34, 255))

    # Star accents around text
    for (sx, sy, ss) in [(W//2-380, ty2+50, 28), (W//2+380, ty2+50, 28),
                          (W//2-330, ty2+160, 22), (W//2+330, ty2+160, 22)]:
        draw_star(draw, sx, sy, ss, (255, 87, 34, 220))

    path = os.path.join(TMP, "kids_intro_bg.png")
    img.save(path)
    return path


# ── Outro PNG ─────────────────────────────────────────────────────────────────

def make_outro_png() -> str:
    img  = Image.new("RGBA", (W, H), (76, 175, 80, 255))   # Bright green
    draw = ImageDraw.Draw(img)

    # Background stars
    rng = random.Random(99)
    for _ in range(20):
        sx    = rng.randint(40, W-40)
        sy    = rng.randint(40, H-40)
        size  = rng.randint(15, 50)
        alpha = rng.randint(80, 200)
        draw_star(draw, sx, sy, size, (255, 255, 255, alpha))

    # Main text
    font_big = ImageFont.truetype(FONT_PATH, 95)
    font_sub = ImageFont.truetype(FONT_PATH, 62)
    font_sm  = ImageFont.truetype(FONT_PATH, 48)

    lines = [
        ("See You", font_big, (255, 255, 255, 255)),
        ("Tomorrow!", font_big, (255, 215, 0, 255)),
        ("", None, None),
        ("Subscribe for", font_sub, (255, 255, 255, 220)),
        ("more fun! ⭐", font_sub, (255, 255, 255, 220)),
    ]

    y = H//2 - 250
    for (text, font, color) in lines:
        if font is None:
            y += 30
            continue
        bb = draw.textbbox((0, 0), text, font=font)
        tx = (W - (bb[2]-bb[0])) // 2
        draw.text((tx+4, y+4), text, font=font, fill=(0, 0, 0, 80))
        draw.text((tx, y), text, font=font, fill=color)
        y += (bb[3]-bb[1]) + 20

    # "Biscuit & Zara" bottom badge
    badge_text = "Biscuit & Zara"
    bb4 = draw.textbbox((0, 0), badge_text, font=font_sm)
    tx4 = (W - (bb4[2]-bb4[0])) // 2
    draw.text((tx4, H - 200), badge_text, font=font_sm, fill=(255, 255, 255, 200))

    path = os.path.join(TMP, "kids_outro_bg.png")
    img.save(path)
    return path


# ── Animated intro/outro clips ────────────────────────────────────────────────

def make_animated_clip(png_path: str, duration: float, out_name: str,
                        zoom_in: bool = True) -> str:
    """Animate a PNG with zoom + fade effect."""
    out    = os.path.join(TMP, out_name)
    frames = int(duration * 30)
    z_expr = f"'min(zoom+0.008,1.15)'" if zoom_in else "'if(eq(on,1),1.15,max(zoom-0.008,1.0))'"
    fade_in  = f"fade=t=in:st=0:d=0.4"
    fade_out = f"fade=t=out:st={duration-0.4:.2f}:d=0.4"

    vf = (
        f"scale={W*2}:{H*2},"
        f"zoompan=z={z_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps=30,"
        f"{fade_in},{fade_out},format=yuv420p"
    )
    run([
        FFMPEG, "-y",
        "-loop", "1", "-framerate", "30",
        "-i", png_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        out
    ], f"animated_{out_name}")
    return out


# ── Ken Burns per scene ───────────────────────────────────────────────────────

def make_ken_burns_clip(image_path: str, scene_idx: int, duration: float) -> str:
    """Apply unique Ken Burns pattern with character bounce."""
    out    = os.path.join(TMP, f"kids_kb_{scene_idx}.mp4")
    frames = int(duration * 30)
    z, x, y = KB_PATTERNS[(scene_idx - 1) % len(KB_PATTERNS)]

    color_grade = "eq=saturation=1.4:brightness=0.02:contrast=1.05"
    zoompan = f"zoompan=z={z}:x={x}:y={y}:d={frames}:s={W}x{H}:fps=30"

    vf = f"scale={W*2}:{H*2},{zoompan},{color_grade},format=yuv420p"
    run([
        FFMPEG, "-y",
        "-loop", "1", "-framerate", "30",
        "-i", image_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        out
    ], f"ken_burns_{scene_idx}")
    return out


# ── Concat with varied xfade transitions ──────────────────────────────────────

def concat_with_xfade(clip_paths: list, clip_durations: list,
                       fade: float = FADE_DUR) -> str:
    out    = os.path.join(TMP, "kids_background_full.mp4")
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    n          = len(clip_paths)
    cumulative = 0
    prev       = "0:v"
    parts      = []

    for i in range(1, n):
        cumulative += clip_durations[i - 1]
        offset      = max(cumulative - i * fade, 0)
        transition  = TRANSITIONS[min(i-1, len(TRANSITIONS)-1)]
        out_label   = f"v{i}" if i < n - 1 else "vout"
        parts.append(
            f"[{prev}][{i}:v]xfade=transition={transition}:duration={fade}"
            f":offset={offset:.3f}[{out_label}]"
        )
        prev = out_label

    run([
        FFMPEG, "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        out
    ], "concat_xfade")
    return out


# ── SRT parsing ───────────────────────────────────────────────────────────────

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
            entries.append({"start": ts(t1.strip()), "end": ts(t2.strip()),
                             "text": " ".join(lines[2:])})
    return entries


# ── Professional caption PNG ──────────────────────────────────────────────────

def render_caption_png(text: str, idx: int) -> str:
    """
    Render a caption PNG with:
    - Rounded pill background with drop shadow
    - Colored glow underneath text
    - Comic Sans Bold 130px
    - Rotating bright color per caption
    """
    img    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)
    font   = ImageFont.truetype(FONT_PATH, 130)
    color  = CAPTION_COLORS[idx % len(CAPTION_COLORS)]

    bb     = draw.textbbox((0, 0), text, font=font)
    tw     = bb[2] - bb[0]
    th     = bb[3] - bb[1]
    px, py = 36, 22
    x      = (W - tw) // 2
    y      = int(H * 0.73)

    pill_rect = [x - px, y - py, x + tw + px, y + th + py]

    # 1. Drop shadow (offset pill)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd     = ImageDraw.Draw(shadow)
    draw_rounded_rect(sd, [pill_rect[0]+8, pill_rect[1]+8,
                            pill_rect[2]+8, pill_rect[3]+8], 30, (0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
    img    = Image.alpha_composite(img, shadow)

    # 2. Pill background (white, semi-transparent)
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd   = ImageDraw.Draw(pill)
    draw_rounded_rect(pd, pill_rect, 30, (255, 255, 255, 235))
    img  = Image.alpha_composite(img, pill)

    # 3. Colored glow behind text
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    gd.text((x, y), text, font=font, fill=(*color, 200))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=14))
    img  = Image.alpha_composite(img, glow)

    # 4. Dark outline
    draw2 = ImageDraw.Draw(img)
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            if abs(dx) + abs(dy) >= 5:
                continue
            if dx or dy:
                draw2.text((x+dx, y+dy), text, font=font, fill=(20, 20, 20, 180))

    # 5. Bright colored text
    draw2.text((x, y), text, font=font, fill=(*color, 255))

    # 6. Mini star decorations at pill corners
    draw_star(draw2, pill_rect[0] - 12, pill_rect[1] - 12, 14, (*color, 200))
    draw_star(draw2, pill_rect[2] + 12, pill_rect[1] - 12, 14, (*color, 200))

    path = os.path.join(TMP, f"kids_cap_{idx:04d}.png")
    img.save(path)
    return path


# ── Channel badge ─────────────────────────────────────────────────────────────

def make_kids_badge_png() -> str:
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 44)
    name = "★ Biscuit & Zara"
    bb   = draw.textbbox((0, 0), name, font=font)
    tw   = bb[2] - bb[0]
    th   = bb[3] - bb[1]
    pad  = 20
    bw   = tw + pad * 2 + 10
    bh   = th + pad
    bx   = W - bw - 24
    by   = H - bh - 30

    # Gradient fill (gold → orange)
    for i in range(bw):
        r = 255
        g = int(200 * (1 - i/bw) + 80 * (i/bw))
        b = int(0   * (1 - i/bw) + 0  * (i/bw))
        draw.rectangle([(bx+i, by), (bx+i, by+bh)], fill=(r, g, b, 220))

    # Rounded corners (mask)
    mask = Image.new("L", (W, H), 0)
    md   = ImageDraw.Draw(mask)
    draw_rounded_rect(md, [bx, by, bx+bw, by+bh], 18, 255)
    img.putalpha(mask)
    # Redraw text on top of gradient
    img2  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw3 = ImageDraw.Draw(img2)
    tx = bx + pad
    ty = by + pad // 2
    draw3.text((tx+2, ty+2), name, font=font, fill=(0, 0, 0, 160))
    draw3.text((tx, ty), name, font=font, fill=(255, 255, 255, 255))
    combined = Image.alpha_composite(img, img2)

    path = os.path.join(TMP, "kids_badge.png")
    combined.save(path)
    return path


# ── Final composite ───────────────────────────────────────────────────────────

def composite_final(bg_video: str, audio: str, srt_entries: list,
                    badge_png: str, output_path: str, total_duration: float) -> str:
    """
    1. Overlay badge (static) onto background video
    2. Batch captions in groups of 6 (avoids input limit)
    3. Mux audio with adelay=INTRO_DUR (FIXES SYNC)
    4. Mix background music at 12% if available
    """
    # Step A: Badge overlay
    badge_out = os.path.join(TMP, "kids_with_badge.mp4")
    run([
        FFMPEG, "-y",
        "-i", bg_video, "-i", badge_png,
        "-filter_complex", "[0:v][1:v]overlay=0:0[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        badge_out
    ], "badge_overlay")

    # Step B: Caption overlays in batches of 6
    cap_data      = []
    for i, entry in enumerate(srt_entries):
        p = render_caption_png(entry["text"], i)
        cap_data.append((p, entry["start"], entry["end"]))

    current_video = badge_out
    BATCH = 6
    for batch_start in range(0, len(cap_data), BATCH):
        batch     = cap_data[batch_start:batch_start + BATCH]
        batch_out = os.path.join(TMP, f"kids_caps_{batch_start:03d}.mp4")

        inputs     = ["-i", current_video]
        for (p, _, _) in batch:
            inputs += ["-i", p]

        parts = []
        prev  = "0:v"
        for bi, (_, start, end) in enumerate(batch):
            out_lbl = f"c{bi}" if bi < len(batch)-1 else "vout"
            parts.append(
                f"[{prev}][{bi+1}:v]overlay=0:0"
                f":enable='between(t,{start:.3f},{end:.3f})'[{out_lbl}]"
            )
            prev = out_lbl

        run([
            FFMPEG, "-y", *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            batch_out
        ], f"caps_batch_{batch_start}")
        current_video = batch_out

    # Step C: Mux audio (FIXED SYNC — narration delayed by INTRO_DUR)
    delay_ms  = int(INTRO_DUR * 1000)
    has_music = os.path.exists(BG_MUSIC)

    if has_music:
        audio_inputs = ["-i", audio, "-i", BG_MUSIC]
        audio_filter = (
            f"[0:a]adelay={delay_ms}|{delay_ms}[narration];"
            f"[1:a]volume=0.12,aloop=loop=-1:size=2e+09[bg];"
            f"[narration][bg]amix=inputs=2:duration=first[final_a]"
        )
        audio_map = "[final_a]"
    else:
        audio_inputs = ["-i", audio]
        audio_filter = f"[0:a]adelay={delay_ms}|{delay_ms}[final_a]"
        audio_map    = "[final_a]"

    run([
        FFMPEG, "-y",
        "-i", current_video,
        *audio_inputs,
        "-filter_complex", audio_filter,
        "-map", "0:v",
        "-map", audio_map,
        "-t", str(total_duration),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ], "mux_audio")

    return output_path


def make_landscape_version(shorts_path: str, landscape_path: str) -> str:
    run([
        FFMPEG, "-y", "-i", shorts_path,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy", landscape_path
    ], "landscape")
    return landscape_path


# ── Main ──────────────────────────────────────────────────────────────────────

def compose_kids_video(_title: str, output_filename: str = "kids_output.mp4") -> dict:
    os.makedirs(TMP, exist_ok=True)
    output_path    = os.path.join(TMP, output_filename)
    landscape_path = os.path.join(TMP, output_filename.replace(".mp4", "_landscape.mp4"))

    print("Step 1/6 -- Rendering intro & outro...", flush=True)
    intro_png  = make_intro_png()
    outro_png  = make_outro_png()
    intro_clip = make_animated_clip(intro_png, INTRO_DUR, "kids_intro.mp4", zoom_in=True)
    outro_clip = make_animated_clip(outro_png, OUTRO_DUR, "kids_outro.mp4", zoom_in=False)
    print("  [OK] Animated intro & outro", flush=True)

    print("Step 2/6 -- Ken Burns effects on scene images...", flush=True)
    clip_paths     = [intro_clip]
    clip_durations = [INTRO_DUR]
    for i in range(1, N_SCENES + 1):
        img_path = os.path.join(IMAGES_DIR, f"scene_{i:03d}.png")
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"Missing: {img_path}")
        clip = make_ken_burns_clip(img_path, i, SCENE_DUR)
        clip_paths.append(clip)
        clip_durations.append(SCENE_DUR)
        print(f"  [OK] Scene {i} — pattern {((i-1) % len(KB_PATTERNS)) + 1}", flush=True)
    clip_paths.append(outro_clip)
    clip_durations.append(OUTRO_DUR)

    print("Step 3/6 -- Concatenating with varied transitions...", flush=True)
    bg_video = concat_with_xfade(clip_paths, clip_durations, fade=FADE_DUR)
    print("  [OK] Background video assembled", flush=True)

    print("Step 4/6 -- Parsing captions & applying sync offset...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    # Shift caption timestamps to match video (intro plays before narration starts)
    for e in srt_entries:
        e["start"] += INTRO_DUR
        e["end"]   += INTRO_DUR
    print(f"  [OK] {len(srt_entries)} caption lines (synced to video)", flush=True)

    print("Step 5/6 -- Rendering professional captions + badge...", flush=True)
    badge_png = make_kids_badge_png()
    print(f"  [OK] Badge ready — rendering {len(srt_entries)} caption frames...", flush=True)

    print("Step 6/6 -- Final composite (audio sync fixed)...", flush=True)
    total_dur = INTRO_DUR + (N_SCENES * SCENE_DUR) + OUTRO_DUR
    has_music = os.path.exists(BG_MUSIC)
    if has_music:
        print(f"  [MUSIC] Mixing background music at 12% volume", flush=True)
    composite_final(bg_video, VOICEOVER, srt_entries, badge_png, output_path, total_dur)
    print(f"  [OK] Shorts video -> {output_path}", flush=True)

    print("Generating landscape version...", flush=True)
    make_landscape_version(output_path, landscape_path)
    print(f"  [OK] Landscape -> {landscape_path}", flush=True)

    return {
        "file":             output_path,
        "landscape_file":   landscape_path,
        "duration_seconds": round(total_dur, 2),
        "resolution":       f"{W}x{H}",
        "scenes":           N_SCENES,
        "captions":         len(srt_entries),
        "has_intro":        True,
        "has_outro":        True,
        "background_music": has_music
    }


if __name__ == "__main__":
    title    = sys.argv[1] if len(sys.argv) > 1 else "Biscuit and Zara"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "kids_output.mp4"
    result   = compose_kids_video(title, out_file)
    print(json.dumps(result, indent=2))
