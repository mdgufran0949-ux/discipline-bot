"""
compose_product_video.py
Composes a 25-30s product review video with cinematic 360-degree multi-angle showcase.

Video structure:
  Scene 1: HOOK (3s)         - main image + gold price text
  Scene 2: 360 VIEW (7s)     - all angle images rapid-fire at 0.9s each
  Scene 3: Feature 1 (4s)    - angle image + feature bullet
  Scene 4: Feature 2 (4s)    - angle image + feature bullet
  Scene 5: Feature 3 (4s)    - angle image + feature bullet
  Scene 6: CTA (3s)          - main image + rating badge + "Link in Bio"

Usage:
  python tools/compose_product_video.py --product product.json --script script.json
  python tools/compose_product_video.py --product product.json --script script.json --audio .tmp/voiceover.mp3

Inputs:  product.json, script.json, voiceover.mp3 + captions.srt (from generate_hindi_tts.py)
Output:  .tmp/product_video.mp4 (1080x1920)
"""

import json
import sys
import os
import re
import argparse
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont

TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
FFMPEG_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
FONT_REG = r"C:\Windows\Fonts\arial.ttf"

_POPPINS_BOLD_URL = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
_POPPINS_REG_URL  = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"


def ensure_fonts():
    """Download Poppins font files once, cache in .tmp/fonts/. Falls back to Arial."""
    font_dir = os.path.join(TMP, "fonts")
    os.makedirs(font_dir, exist_ok=True)
    bold = os.path.join(font_dir, "Poppins-Bold.ttf")
    reg  = os.path.join(font_dir, "Poppins-Regular.ttf")
    for url, path in [(_POPPINS_BOLD_URL, bold), (_POPPINS_REG_URL, reg)]:
        if not os.path.exists(path):
            try:
                r = requests.get(url, timeout=20)
                r.raise_for_status()
                with open(path, "wb") as f:
                    f.write(r.content)
            except Exception as e:
                print(f"[WARN] Font download failed ({url}): {e} — falling back to Arial",
                      file=sys.stderr)
                return FONT_BOLD, FONT_REG
    return bold, reg

W, H = 1080, 1920
MAIN_FADE = 0.2    # crossfade between main scenes
ANGLE_FADE = 0.3   # crossfade inside 360-degree scene
ANGLE_DUR = 0.6    # seconds per angle image in 360-degree scene

SCENE_DURATIONS = {
    "hook":  3.0,
    "feat1": 4.0,
    "feat2": 4.0,
    "feat3": 4.0,
    "cta":   3.0,
}


def run(cmd: list, label: str = ""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error [{label}]:\n{result.stderr[-800:]}")
    return result


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


# ── Image utilities ───────────────────────────────────────────────────────────

def download_image(url: str, dest: str) -> bool:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            stream=True,
        )
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"[WARN] Download failed {url}: {e}", file=sys.stderr)
        return False


def resize_and_crop(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Scale-to-fill then center-crop to target dimensions."""
    img = img.convert("RGB")
    scale = max(tw / img.width, th / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def add_gradient_overlay(img: Image.Image) -> Image.Image:
    """Dark gradient at top (for product name) and bottom (for price/features)."""
    overlay = Image.new("RGBA", (img.width, img.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    h, w = img.height, img.width

    # Bottom gradient — covers lower 45%
    bot_h = int(h * 0.45)
    for y in range(bot_h):
        alpha = int(210 * (y / bot_h) ** 1.6)
        draw.line([(0, h - bot_h + y), (w, h - bot_h + y)], fill=(0, 0, 0, alpha))

    # Top gradient — covers upper 18%
    top_h = int(h * 0.18)
    for y in range(top_h):
        alpha = int(155 * (1 - y / top_h) ** 1.2)
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def shadow_text(draw, pos, text, font, fill, offset=4):
    x, y = pos
    draw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0))
    draw.text(pos, text, font=font, fill=fill)


def wrap_text(text: str, font, max_w: int, draw) -> list:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def paste_pill(img: Image.Image, x: int, y: int, w: int, h: int,
               color=(0, 0, 0, 175)) -> Image.Image:
    """Paste a semi-transparent dark pill rectangle onto img."""
    pill = Image.new("RGBA", (w, h), color)
    base = img.convert("RGBA")
    base.paste(pill, (x, y), pill)
    return base.convert("RGB")


# ── Scene image builders ──────────────────────────────────────────────────────

def build_hook_image(src: Image.Image, price: int, product_name: str,
                     rating: float = 0.0, review_count: int = 0,
                     original_price: int = 0, source: str = "amazon") -> Image.Image:
    img = resize_and_crop(src.copy(), W, H)
    img = add_gradient_overlay(img)
    draw = ImageDraw.Draw(img)

    # Platform badge — top left (orange for Amazon, blue for Flipkart)
    badge_label = "AMAZON FIND" if source == "amazon" else "FLIPKART FIND"
    badge_color = (255, 100, 0, 230) if source == "amazon" else (40, 116, 240, 230)
    font_badge = ImageFont.truetype(FONT_BOLD, 30)
    bw_b = draw.textbbox((0, 0), badge_label, font=font_badge)[2]
    bh_b = draw.textbbox((0, 0), badge_label, font=font_badge)[3]
    img = paste_pill(img, 28, 28, bw_b + 32, bh_b + 18, badge_color)
    draw = ImageDraw.Draw(img)
    draw.text((44, 37), badge_label, font=font_badge, fill=(255, 255, 255))

    # Product name — top, centered, white
    font_name = ImageFont.truetype(FONT_BOLD, 44)
    name_lines = wrap_text(product_name[:70].upper(), font_name, W - 80, draw)
    y = 48 + bh_b + 22
    for line in name_lines[:2]:
        bw = draw.textbbox((0, 0), line, font=font_name)[2]
        shadow_text(draw, ((W - bw) // 2, y), line, font_name, (255, 255, 255))
        y += 56

    # Star rating badge — prominent, above price
    if rating > 0:
        font_stars = ImageFont.truetype(FONT_BOLD, 52)
        full = int(rating)
        half = (rating - full) >= 0.5
        stars = "\u2605" * full + ("\u00bd" if half else "") + "\u2606" * (5 - full - (1 if half else 0))
        badge = f"{stars}  {rating:.1f}"
        bw = draw.textbbox((0, 0), badge, font=font_stars)[2]
        bh = draw.textbbox((0, 0), badge, font=font_stars)[3]
        bx = (W - bw) // 2
        by = H - 510
        img = paste_pill(img, bx - 24, by - 12, bw + 48, bh + 24, (0, 0, 0, 200))
        draw = ImageDraw.Draw(img)
        shadow_text(draw, (bx, by), badge, font_stars, (255, 215, 0), offset=3)
        if review_count > 0:
            font_rev = ImageFont.truetype(FONT_REG, 30)
            rev = f"({review_count:,} verified ratings)"
            rw = draw.textbbox((0, 0), rev, font=font_rev)[2]
            shadow_text(draw, ((W - rw) // 2, by + bh + 6), rev, font_rev, (200, 200, 200))

    # Crossed-out original price (if significantly higher than sale price)
    if original_price and original_price > price * 1.15:
        font_mrp = ImageFont.truetype(FONT_REG, 52)
        mrp_text = f"MRP \u20b9{int(original_price):,}"
        mrp_w = draw.textbbox((0, 0), mrp_text, font=font_mrp)[2]
        mrp_h = draw.textbbox((0, 0), mrp_text, font=font_mrp)[3]
        mrp_x = (W - mrp_w) // 2
        mrp_y = H - 580
        shadow_text(draw, (mrp_x, mrp_y), mrp_text, font_mrp, (180, 180, 180), offset=2)
        line_y = mrp_y + mrp_h // 2
        draw.line([(mrp_x - 6, line_y), (mrp_x + mrp_w + 6, line_y)], fill=(220, 60, 60), width=4)

    # "ONLY" label
    font_only = ImageFont.truetype(FONT_BOLD, 46)
    only_bw = draw.textbbox((0, 0), "ONLY", font=font_only)[2]
    shadow_text(draw, ((W - only_bw) // 2, H - 370), "ONLY", font_only, (255, 215, 0))

    # Price — large, gold
    font_price = ImageFont.truetype(FONT_BOLD, 118)
    price_text = f"\u20b9{price:,}"
    pw = draw.textbbox((0, 0), price_text, font=font_price)[2]
    ph = draw.textbbox((0, 0), price_text, font=font_price)[3]
    px, py = (W - pw) // 2, H - 315
    img = paste_pill(img, px - 24, py - 14, pw + 48, ph + 28, (0, 0, 0, 185))
    draw = ImageDraw.Draw(img)
    shadow_text(draw, (px, py), price_text, font_price, (255, 215, 0), offset=6)

    return img


def build_360_frame(src: Image.Image, frame_idx: int, total: int) -> Image.Image:
    """Angle image with spinning arc progress indicator and dot indicator."""
    img = resize_and_crop(src.copy(), W, H)

    # Light top gradient only — product is the star here
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    th = int(H * 0.13)
    for y in range(th):
        alpha = int(140 * (1 - y / th))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Spinning arc progress ring — top right
    overlay2 = img.convert("RGBA")
    d2 = ImageDraw.Draw(overlay2)
    cx, cy, r = W - 90, 90, 52
    d2.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 180))
    sweep = int(360 * (frame_idx + 1) / max(total, 1))
    d2.arc([cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6],
           start=-90, end=-90 + sweep, fill=(255, 215, 0), width=5)
    img = overlay2.convert("RGB")
    draw = ImageDraw.Draw(img)
    font_360 = ImageFont.truetype(FONT_BOLD, 26)
    arc_label = "360\u00b0"
    lw = draw.textbbox((0, 0), arc_label, font=font_360)[2]
    lh = draw.textbbox((0, 0), arc_label, font=font_360)[3]
    draw.text((cx - lw // 2, cy - lh // 2), arc_label, font=font_360, fill=(255, 255, 255))

    # Dot indicator — bottom center
    n = min(total, 8)
    spacing = 22
    dot_start = (W - n * spacing) // 2
    dot_y = H - 58
    for i in range(n):
        color = (255, 215, 0) if i == (frame_idx % n) else (180, 180, 180)
        draw.ellipse(
            [dot_start + i * spacing, dot_y,
             dot_start + i * spacing + 12, dot_y + 12],
            fill=color,
        )

    return img


def build_feature_image(src: Image.Image, feature_text: str,
                        feat_num: int, product_name: str) -> Image.Image:
    img = resize_and_crop(src.copy(), W, H)
    img = add_gradient_overlay(img)
    draw = ImageDraw.Draw(img)

    # Product name — top, small, grey
    font_name = ImageFont.truetype(FONT_REG, 36)
    shadow_text(draw, (60, 44), product_name[:55], font_name, (200, 200, 200))

    # Feature number badge
    font_num = ImageFont.truetype(FONT_BOLD, 40)
    num_text = f"#{feat_num}"
    shadow_text(draw, (60, H - 340), num_text, font_num, (255, 215, 0))

    # Feature text — large, white, left-aligned, wrapped
    font_feat = ImageFont.truetype(FONT_BOLD, 60)
    lines = wrap_text(feature_text, font_feat, W - 130, draw)
    y = H - 280
    for line in lines[:3]:
        shadow_text(draw, (60, y), line, font_feat, (255, 255, 255), offset=3)
        y += 72

    return img


def build_cta_image(src: Image.Image, price: int, rating: float,
                    review_count: int, source: str) -> Image.Image:
    img = resize_and_crop(src.copy(), W, H)
    img = add_gradient_overlay(img)
    draw = ImageDraw.Draw(img)

    # Stars
    full = int(rating)
    half = (rating - full) >= 0.5
    stars = "\u2605" * full + ("\u00bd" if half else "") + "\u2606" * (5 - full - (1 if half else 0))
    font_stars = ImageFont.truetype(FONT_BOLD, 52)
    star_w = draw.textbbox((0, 0), f"{stars}  {rating}", font=font_stars)[2]
    shadow_text(
        draw, ((W - star_w) // 2, H - 470),
        f"{stars}  {rating}", font_stars, (255, 215, 0),
    )

    # Review count
    font_rev = ImageFont.truetype(FONT_REG, 36)
    rev_text = f"({review_count:,} reviews)"
    rev_w = draw.textbbox((0, 0), rev_text, font=font_rev)[2]
    shadow_text(draw, ((W - rev_w) // 2, H - 405), rev_text, font_rev, (200, 200, 200))

    # Price
    font_price = ImageFont.truetype(FONT_BOLD, 82)
    price_text = f"Only \u20b9{price:,}!"
    pw = draw.textbbox((0, 0), price_text, font=font_price)[2]
    shadow_text(draw, ((W - pw) // 2, H - 330), price_text, font_price, (255, 215, 0), offset=4)

    # CTA pill button
    font_cta = ImageFont.truetype(FONT_BOLD, 52)
    cta_text = "LINK IN BIO  \u2191"
    cw = draw.textbbox((0, 0), cta_text, font=font_cta)[2]
    ch = draw.textbbox((0, 0), cta_text, font=font_cta)[3]
    cx, cy = (W - cw) // 2, H - 190
    img = paste_pill(img, cx - 22, cy - 14, cw + 44, ch + 28, (22, 160, 70, 230))
    draw = ImageDraw.Draw(img)
    draw.text((cx, cy), cta_text, font=font_cta, fill=(255, 255, 255))

    return img


# ── Ken Burns video clips ─────────────────────────────────────────────────────

def make_ken_burns_clip(img_path: str, clip_id: int, duration: float,
                        movement: str = "auto") -> str:
    out = os.path.join(TMP, f"kb_prod_{clip_id}.mp4")
    frames = int(duration * 30)

    if movement == "auto":
        movement = "in" if clip_id % 2 == 1 else "out"

    if movement == "in":
        z = "'min(zoom+0.0015,1.5)'"
    else:
        z = "'if(eq(on,1),1.5,max(zoom-0.0015,1.0))'"

    zoompan = (
        f"zoompan=z={z}:x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30"
    )
    grade = "eq=saturation=1.4:brightness=0.01:contrast=1.12,vignette=PI/4"

    cmd = [
        FFMPEG, "-y", "-loop", "1", "-framerate", "30",
        "-i", img_path, "-t", str(duration),
        "-vf", f"scale=2160:3840,{zoompan},{grade},format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", out,
    ]
    run(cmd, f"kb_{clip_id}")
    return out


def make_angle_clip(img_path: str, clip_id: int) -> str:
    """Short Ken Burns clip for a single angle in the 360-degree scene."""
    out = os.path.join(TMP, f"angle_{clip_id:02d}.mp4")
    frames = int(ANGLE_DUR * 30)

    moves = [
        ("'min(zoom+0.003,1.12)'", "'iw/2-(iw/zoom/2)'", "'ih/2-(ih/zoom/2)'"),
        ("'if(eq(on,1),1.12,max(zoom-0.003,1.0))'", "'iw/2-(iw/zoom/2)'", "'ih/2-(ih/zoom/2)'"),
        ("'1.1'", f"'(iw/2-(iw/zoom/2)) + (on/{frames})*(iw*0.04)'", "'ih/2-(ih/zoom/2)'"),
        ("'1.1'", f"'(iw/2-(iw/zoom/2)) - (on/{frames})*(iw*0.04)'", "'ih/2-(ih/zoom/2)'"),
    ]
    z, x, y = moves[clip_id % 4]
    zoompan = (
        f"zoompan=z={z}:x={x}:y={y}"
        f":d={frames}:s={W}x{H}:fps=30"
    )
    cmd = [
        FFMPEG, "-y", "-loop", "1", "-framerate", "30",
        "-i", img_path, "-t", str(ANGLE_DUR),
        "-vf", f"scale=2160:3840,{zoompan},eq=saturation=1.4:contrast=1.12,vignette=PI/4,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", out,
    ]
    run(cmd, f"angle_{clip_id}")
    return out


def prepare_usecase_clip(media_path: str, media_type: str, label_text: str,
                         duration: float = 5.0) -> str:
    """Trim/resize a stock video or Ken Burns an image for the use-case scene.
    Overlays a label pill at the bottom-center."""
    from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont

    # Step 1: Build the base video clip
    base = os.path.join(TMP, "usecase_base.mp4")
    if media_type == "video":
        vf = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,fps=30,"
            f"eq=saturation=1.3:contrast=1.1,vignette=PI/4"
        )
        cmd = [
            FFMPEG, "-y", "-i", media_path,
            "-t", str(duration),
            "-vf", f"{vf},format=yuv420p",
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", base,
        ]
        run(cmd, "usecase_video")
    else:
        # Ken Burns on static image
        base = make_ken_burns_clip(media_path, 99, duration, "in")

    # Step 2: Render label text overlay PNG
    label_png = os.path.join(TMP, "usecase_label.png")
    img_l = _Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_l = _ImageDraw.Draw(img_l)
    try:
        font_l = _ImageFont.truetype(FONT_BOLD, 64)
    except Exception:
        font_l = _ImageFont.load_default()
    tw = draw_l.textbbox((0, 0), label_text, font=font_l)[2]
    th = draw_l.textbbox((0, 0), label_text, font=font_l)[3]
    tx = (W - tw) // 2
    ty = H - 200
    pill = _Image.new("RGBA", (tw + 48, th + 28), (0, 0, 0, 200))
    img_l.paste(pill, (tx - 24, ty - 14), pill)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx or dy:
                draw_l.text((tx + dx, ty + dy), label_text, font=font_l, fill=(0, 0, 0, 255))
    draw_l.text((tx, ty), label_text, font=font_l, fill=(255, 215, 0, 255))
    img_l.save(label_png)

    # Step 3: Composite label over video
    out = os.path.join(TMP, "usecase_scene.mp4")
    cmd = [
        FFMPEG, "-y", "-i", base, "-i", label_png,
        "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", out,
    ]
    run(cmd, "usecase_label")
    return out


def concat_xfade(clips: list, fade: float, durations: list) -> str:
    """Concatenate N clips with xfade transitions."""
    out = os.path.join(TMP, "product_bg.mp4")
    if len(clips) == 1:
        return clips[0]

    inputs = []
    for p in clips:
        inputs += ["-i", p]

    n = len(clips)
    _main_transitions = ["wipeleft", "wiperight"]
    parts = []
    offset = durations[0] - fade
    prev = "0:v"
    for i in range(1, n):
        label = f"v{i}" if i < n - 1 else "vout"
        parts.append(
            f"[{prev}][{i}:v]xfade=transition={_main_transitions[(i-1) % 2]}"
            f":duration={fade}:offset={offset:.3f}[{label}]"
        )
        prev = label
        if i < len(durations):
            offset += durations[i] - fade

    cmd = [
        FFMPEG, "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", out,
    ]
    run(cmd, "concat_xfade")
    return out


# ── Caption overlay ───────────────────────────────────────────────────────────

def parse_srt(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    def ts(t):
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    entries = []
    for block in re.split(r"\n\n+", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            t = lines[1].split(" --> ")
            entries.append({"start": ts(t[0].strip()), "end": ts(t[1].strip()),
                            "text": " ".join(lines[2:])})
    return entries


def render_caption_png(text: str, idx: int) -> str:
    """CapCut-style captions: bold white ALL CAPS, thick black stroke, no pill background."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 88)
    text_upper = text.upper()
    lines = wrap_text(text_upper, font, W - 80, draw)

    y = int(H * 0.70)
    for line in lines[:2]:
        bw = draw.textbbox((0, 0), line, font=font)[2]
        bh = draw.textbbox((0, 0), line, font=font)[3]
        x = (W - bw) // 2
        # Thick circular black stroke
        STROKE = 5
        for sx in range(-STROKE, STROKE + 1):
            for sy in range(-STROKE, STROKE + 1):
                if sx * sx + sy * sy <= STROKE * STROKE:
                    draw.text((x + sx, y + sy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += bh + 12

    path = os.path.join(TMP, f"prod_cap_{idx:04d}.png")
    img.save(path)
    return path


def render_hook_text_overlay(hook_text: str) -> str:
    """Large gold hook text PNG for animated bounce-in in first 1.5s of video."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 100)
    lines = wrap_text(hook_text.upper(), font, W - 80, draw)
    y = int(H * 0.35)
    for line in lines[:2]:
        bw = draw.textbbox((0, 0), line, font=font)[2]
        bh = draw.textbbox((0, 0), line, font=font)[3]
        x = (W - bw) // 2
        STROKE = 6
        for sx in range(-STROKE, STROKE + 1):
            for sy in range(-STROKE, STROKE + 1):
                if sx * sx + sy * sy <= STROKE * STROKE:
                    draw.text((x + sx, y + sy), line, font=font, fill=(0, 0, 0, 230))
        draw.text((x, y), line, font=font, fill=(255, 215, 0, 255))
        y += bh + 16
    path = os.path.join(TMP, "hook_text_overlay.png")
    img.save(path)
    return path


def generate_sfx() -> dict:
    """Synthesize simple SFX WAV files using Python wave module. Returns {name: path}."""
    import wave, struct, math, random
    sfx_dir = os.path.join(TMP, "sfx")
    os.makedirs(sfx_dir, exist_ok=True)
    SR = 44100

    def write_wav(path, frames):
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(struct.pack(f"{len(frames)}h", *frames))

    # Whoosh: filtered white noise with exponential decay
    whoosh_path = os.path.join(sfx_dir, "whoosh.wav")
    n = int(0.35 * SR)
    frames = [int((random.random() * 2 - 1) * 28000 * max(0, 1 - i / n) ** 0.4) for i in range(n)]
    write_wav(whoosh_path, frames)

    # Cash: ascending sine chirp 400→1600 Hz
    cash_path = os.path.join(sfx_dir, "cash.wav")
    n = int(0.25 * SR)
    frames = [int(math.sin(2 * math.pi * (400 + 1200 * i / n) * i / SR) * 22000 * (1 - i / n) ** 0.5) for i in range(n)]
    write_wav(cash_path, frames)

    # Tick: short 1000 Hz sine pop
    tick_path = os.path.join(sfx_dir, "tick.wav")
    n = int(0.08 * SR)
    frames = [int(math.sin(2 * math.pi * 1000 * i / SR) * 20000 * max(0, 1 - i / n * 3)) for i in range(n)]
    write_wav(tick_path, frames)

    return {"whoosh": whoosh_path, "cash": cash_path, "tick": tick_path}


def render_scene_flash(label: str, idx: int) -> str:
    """Render a centered scene title card (transparent PNG) shown for 0.15s at scene start."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_BOLD, 72)
    except Exception:
        font = ImageFont.load_default()
    tw = draw.textbbox((0, 0), label, font=font)[2]
    th = draw.textbbox((0, 0), label, font=font)[3]
    x = (W - tw) // 2
    y = (H - th) // 2 - 60
    pill = Image.new("RGBA", (tw + 60, th + 30), (0, 0, 0, 195))
    img.paste(pill, (x - 30, y - 15), pill)
    draw.text((x, y), label, font=font, fill=(255, 215, 0, 255))
    path = os.path.join(TMP, f"flash_{idx:02d}.png")
    img.save(path)
    return path


def build_feature_text_png(feature_text: str, feat_num: int,
                            product_name: str, idx: int) -> str:
    """Render feature text elements as a transparent RGBA PNG for slide-in overlay."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Product name — top, small, grey
    try:
        font_name = ImageFont.truetype(FONT_REG, 36)
        font_num  = ImageFont.truetype(FONT_BOLD, 40)
        font_feat = ImageFont.truetype(FONT_BOLD, 60)
    except Exception:
        font_name = font_num = font_feat = ImageFont.load_default()

    # Product name (top)
    draw.text((60, 44), product_name[:55], font=font_name, fill=(200, 200, 200, 220))

    # Feature number badge
    num_text = f"#{feat_num}"
    draw.text((60, H - 340), num_text, font=font_num, fill=(255, 215, 0, 255))

    # Feature text — large, white, left-aligned, wrapped
    lines = wrap_text(feature_text, font_feat, W - 130, draw)
    y = H - 280
    for line in lines[:3]:
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx or dy:
                    draw.text((60 + dx, y + dy), line, font=font_feat,
                              fill=(0, 0, 0, 200))
        draw.text((60, y), line, font=font_feat, fill=(255, 255, 255, 255))
        y += 72

    path = os.path.join(TMP, f"feat_text_{idx:02d}.png")
    img.save(path)
    return path


def render_cta_button_png() -> tuple:
    """Render just the LINK IN BIO button as a transparent PNG. Returns (path, x, y)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font_cta = ImageFont.truetype(FONT_BOLD, 52)
    except Exception:
        font_cta = ImageFont.load_default()
    cta_text = "LINK IN BIO  \u2191"
    cw = draw.textbbox((0, 0), cta_text, font=font_cta)[2]
    ch = draw.textbbox((0, 0), cta_text, font=font_cta)[3]
    cx, cy = (W - cw) // 2, H - 190
    pill = Image.new("RGBA", (cw + 44, ch + 28), (22, 160, 70, 230))
    img.paste(pill, (cx - 22, cy - 14), pill)
    draw.text((cx, cy), cta_text, font=font_cta, fill=(255, 255, 255, 255))
    path = os.path.join(TMP, "cta_button.png")
    img.save(path)
    # Return the button center for FFmpeg overlay positioning
    btn_x = cx - 22
    btn_y = cy - 14
    return path, btn_x, btn_y


def compute_scene_starts(all_durs: list, fade: float) -> list:
    starts = [0.0]
    for d in all_durs[:-1]:
        starts.append(starts[-1] + d - fade)
    return starts


def composite_final(bg: str, audio: str, srt_entries: list,
                    output: str, duration: float,
                    scene_starts: list = None,
                    feat_text_pngs: list = None,
                    scene_labels: list = None,
                    all_durs: list = None,
                    cta_start: float = None,
                    hook_overlay_path: str = None,
                    sfx_paths: dict = None,
                    bgm_path: str = None) -> str:
    """Composite all overlays onto the background video in a single FFmpeg pass.

    Layers (in order):
      1. Background video
      2. Caption PNGs (SRT-timed)
      3. Feature text slide-in PNGs (F/G)
      4. Scene flash label PNGs (F)
      5. Progress bar drawbox (H)
      6. Pulsing CTA button (I)
    """
    # -- 1. Caption PNGs
    cap_files = []
    for i, e in enumerate(srt_entries):
        p = render_caption_png(e["text"], i)
        cap_files.append((p, e["start"], e["end"]))

    # -- 2. Feature text PNGs (slide-in, one per feature scene)
    feat_overlays = []  # list of (png_path, scene_start_t, scene_dur)
    if feat_text_pngs and scene_starts:
        # feature scenes are at indices 3,4,5 in scene_order (after hook,360,usecase)
        # scene_starts is aligned with all_durs
        n_pre = len(scene_starts) - len(feat_text_pngs) - 1  # scenes before features
        feat_scene_offset = len(scene_starts) - len(feat_text_pngs) - 1
        feat_durs = all_durs[feat_scene_offset:feat_scene_offset + len(feat_text_pngs)] if all_durs else [4.0] * 3
        for i, png in enumerate(feat_text_pngs):
            si = feat_scene_offset + i
            if si < len(scene_starts):
                feat_overlays.append((png, scene_starts[si], feat_durs[i] if i < len(feat_durs) else 4.0))

    # -- 3. Scene flash label PNGs
    flash_overlays = []  # list of (png_path, start_t)
    if scene_labels and scene_starts:
        for i, (lbl, t) in enumerate(zip(scene_labels, scene_starts)):
            png = render_scene_flash(lbl, i)
            flash_overlays.append((png, t))

    # -- 4. CTA button (pulsing)
    cta_btn_path, btn_x, btn_y = render_cta_button_png()
    cta_end = cta_start + (all_durs[-1] if all_durs else 4.0) if cta_start is not None else None

    # -- Build FFmpeg inputs list
    inputs = ["-i", bg]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]
    cap_base_idx = 1  # first caption input index

    feat_base_idx = cap_base_idx + len(cap_files)
    for (p, _, _) in feat_overlays:
        inputs += ["-i", p]

    flash_base_idx = feat_base_idx + len(feat_overlays)
    for (p, _) in flash_overlays:
        inputs += ["-i", p]

    cta_btn_idx = flash_base_idx + len(flash_overlays)
    inputs += ["-i", cta_btn_path]

    # Hook text overlay input (if provided)
    hook_ol_idx = None
    if hook_overlay_path:
        hook_ol_idx = cta_btn_idx + 1
        inputs += ["-i", hook_overlay_path]

    # Voiceover audio input
    audio_idx = (hook_ol_idx + 1) if hook_ol_idx is not None else (cta_btn_idx + 1)
    inputs += ["-i", audio]

    # SFX inputs: cash + one whoosh per scene transition
    sfx_cash_idx = None
    sfx_whoosh_idxs = []   # list of (input_idx, scene_start_time)
    if sfx_paths and scene_starts and len(scene_starts) > 1:
        sfx_cash_idx = audio_idx + 1
        inputs += ["-i", sfx_paths["cash"]]
        for j, t in enumerate(scene_starts[1:]):
            widx = sfx_cash_idx + 1 + j
            inputs += ["-i", sfx_paths["whoosh"]]
            sfx_whoosh_idxs.append((widx, t))

    # BGM input (optional)
    bgm_in_idx = None
    if bgm_path:
        bgm_in_idx = audio_idx + 1 + (0 if not sfx_paths else 1 + len(sfx_whoosh_idxs))
        inputs += ["-i", bgm_path]

    # -- Build filter_complex chain
    parts = []
    prev = "0:v"
    overlay_counter = [0]

    def next_label(is_final=False):
        overlay_counter[0] += 1
        return "vfinal_pre" if not is_final else "vfinal_pre"

    # Captions
    for i, (_, s, e) in enumerate(cap_files):
        idx = cap_base_idx + i
        lbl = f"ov{overlay_counter[0]}"
        overlay_counter[0] += 1
        parts.append(
            f"[{prev}][{idx}:v]overlay=0:0"
            f":enable='between(t,{s:.3f},{e:.3f})'[{lbl}]"
        )
        prev = lbl

    # Feature text slide-ins
    SLIDE_DUR = 0.4
    for i, (_, feat_start, feat_dur) in enumerate(feat_overlays):
        idx = feat_base_idx + i
        lbl = f"ov{overlay_counter[0]}"
        overlay_counter[0] += 1
        x_expr = (
            f"if(lt(t-{feat_start:.3f},{SLIDE_DUR}),"
            f"W*(1-(t-{feat_start:.3f})/{SLIDE_DUR}),0)"
        )
        feat_end = feat_start + feat_dur
        parts.append(
            f"[{prev}][{idx}:v]overlay=x='{x_expr}':y=0"
            f":enable='between(t,{feat_start:.3f},{feat_end:.3f})'[{lbl}]"
        )
        prev = lbl

    # Scene flash labels (0.15s at scene start)
    FLASH_DUR = 0.15
    for i, (_, t) in enumerate(flash_overlays):
        idx = flash_base_idx + i
        lbl = f"ov{overlay_counter[0]}"
        overlay_counter[0] += 1
        parts.append(
            f"[{prev}][{idx}:v]overlay=0:0"
            f":enable='between(t,{t:.3f},{t + FLASH_DUR:.3f})'[{lbl}]"
        )
        prev = lbl

    # CTA pulsing button
    if cta_start is not None and cta_end is not None:
        lbl = f"ov{overlay_counter[0]}"
        overlay_counter[0] += 1
        pulse = (
            f"[{cta_btn_idx}:v]"
            f"scale=w='iw*(1+0.06*sin(2*3.14159*2*(t-{cta_start:.3f})))'"
            f":h='ih*(1+0.06*sin(2*3.14159*2*(t-{cta_start:.3f})))'"
            f":eval=frame,format=yuva420p[cta_scaled]"
        )
        parts.append(pulse)
        # Overlay centered at the button position (account for scale shift)
        parts.append(
            f"[{prev}][cta_scaled]overlay=x={btn_x}:y={btn_y}"
            f":enable='between(t,{cta_start:.3f},{cta_end:.3f})'[{lbl}]"
        )
        prev = lbl

    # Hook text overlay — bounce-in scale animation for first 1.5s
    if hook_ol_idx is not None:
        lbl = f"ov{overlay_counter[0]}"
        overlay_counter[0] += 1
        pulse_expr = "iw*max(1.0,1.35-t*1.4)"
        parts.append(
            f"[{hook_ol_idx}:v]scale=w='{pulse_expr}':h='{pulse_expr}'"
            f":eval=frame,format=yuva420p[hook_anim]"
        )
        parts.append(
            f"[{prev}][hook_anim]overlay=x='(main_w-overlay_w)/2'"
            f":y='(main_h-overlay_h)/3':enable='lt(t,1.5)'[{lbl}]"
        )
        prev = lbl

    # Progress bar — static gold accent line at the very bottom of the frame
    lbl_prog = "vprog"
    parts.append(
        f"[{prev}]drawbox=x=0:y={H - 6}:w=iw:h=6"
        f":color=0xFFD700@0.85:t=fill[{lbl_prog}]"
    )

    # -- Audio chain (SFX mixing)
    final_audio_map = f"{audio_idx}:a:0"  # default: direct map
    if sfx_cash_idx is not None:
        # Cash chirp at 1.2s (price reveal moment)
        parts.append(f"[{sfx_cash_idx}:a]adelay=1200|1200[cash_d]")
        whoosh_labels = []
        for j, (widx, t) in enumerate(sfx_whoosh_idxs):
            ms = int(t * 1000)
            wlbl = f"whoosh{j}_d"
            parts.append(f"[{widx}:a]adelay={ms}|{ms}[{wlbl}]")
            whoosh_labels.append(wlbl)
        all_audio = [f"{audio_idx}:a", "cash_d"] + whoosh_labels
        n_audio = len(all_audio)
        weights = "1 0.45 " + " ".join(["0.35"] * len(whoosh_labels))
        audio_inputs_str = "".join(f"[{a}]" for a in all_audio)
        parts.append(
            f"{audio_inputs_str}amix=inputs={n_audio}"
            f":duration=first:weights='{weights.strip()}'[a_sfx]"
        )
        if bgm_in_idx is not None:
            parts.append(
                f"[{bgm_in_idx}:a]volume=0.08,aloop=loop=-1:size=2000000000[bgm_loop]"
            )
            parts.append("[a_sfx][bgm_loop]amix=inputs=2:duration=first[a_final]")
            final_audio_map = "[a_final]"
        else:
            final_audio_map = "[a_sfx]"
    elif bgm_in_idx is not None:
        parts.append(
            f"[{bgm_in_idx}:a]volume=0.08,aloop=loop=-1:size=2000000000[bgm_loop]"
        )
        parts.append(f"[{audio_idx}:a][bgm_loop]amix=inputs=2:duration=first[a_final]")
        final_audio_map = "[a_final]"

    filtergraph = ";".join(parts) if parts else f"[0:v]copy[{lbl_prog}]"

    # Write filtergraph to a temp file to avoid command-line length limits
    fg_file = os.path.join(TMP, "filtergraph.txt")
    with open(fg_file, "w", encoding="utf-8") as f:
        f.write(filtergraph)

    # Build the -map for audio: direct index or filtergraph label
    audio_map_args = ["-map", final_audio_map] if final_audio_map.startswith("[") else ["-map", f"{audio_idx}:a:0"]

    cmd = [
        FFMPEG, "-y", *inputs,
        "-/filter_complex", fg_file,
        "-map", f"[{lbl_prog}]",
        *audio_map_args,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", output,
    ]
    run(cmd, "final_composite")
    return output


# ── Main ──────────────────────────────────────────────────────────────────────

def compose_product_video(product: dict, script: dict, audio_path: str,
                          output_filename: str = "product_video.mp4",
                          usecase_media: dict = None) -> dict:
    os.makedirs(TMP, exist_ok=True)
    global FONT_BOLD, FONT_REG
    FONT_BOLD, FONT_REG = ensure_fonts()

    img_dir = os.path.join(TMP, "product_imgs", product.get("asin", "unknown") or "unknown")
    os.makedirs(img_dir, exist_ok=True)
    output_path = os.path.join(TMP, output_filename)
    audio_dur = get_duration(audio_path)

    # ── Step 1: Download images ───────────────────────────────────────────────
    print("Step 1/6 -- Downloading product images...", flush=True)
    all_urls = product.get("images", {}).get("all", [])
    if not all_urls:
        main_url = product.get("images", {}).get("main", "")
        all_urls = [main_url] if main_url else []

    local_imgs = []
    for i, url in enumerate(all_urls[:8]):
        dest = os.path.join(img_dir, f"img_{i:02d}.jpg")
        if os.path.exists(dest):
            local_imgs.append(dest)
        elif download_image(url, dest):
            local_imgs.append(dest)
            print(f"  [OK] Image {i+1}/{len(all_urls)}", flush=True)

    if not local_imgs:
        raise FileNotFoundError("No product images downloaded")

    # Pad to at least 4 by repeating
    while len(local_imgs) < 4:
        local_imgs.append(local_imgs[0])

    print(f"  [OK] {len(local_imgs)} images ready", flush=True)

    # ── Step 2: Prepare scene images with overlays ────────────────────────────
    print("Step 2/6 -- Preparing scene images...", flush=True)

    segments = script.get("segments", [])
    price = int(product.get("price", 499))
    rating = float(product.get("rating", 4.0))
    review_count = int(product.get("review_count", 0))
    source = product.get("source", "amazon")
    pname = product.get("title", "Product")[:60]

    def seg_text(sid):
        return next((s["text"] for s in segments if s["id"] == sid), "")

    feat1 = seg_text(3) or "Amazing quality and build"
    feat2 = seg_text(4) or "Compact and portable design"
    feat3 = seg_text(5) or "Incredible value for money"

    def save_scene(img: Image.Image, name: str) -> str:
        p = os.path.join(TMP, f"scene_prod_{name}.jpg")
        img.save(p, "JPEG", quality=95)
        return p

    # Smart image selection: white-bg shots for HOOK/CTA, lifestyle for features
    def is_white_background(path):
        try:
            im = Image.open(path).convert("RGB").resize((120, 120), Image.LANCZOS)
            px = list(im.getdata())
            corners = [im.getpixel((0, 0)), im.getpixel((119, 0)),
                       im.getpixel((0, 119)), im.getpixel((119, 119))]
            white_px = sum(1 for r, g, b in px if r > 220 and g > 220 and b > 220)
            corner_white = sum(1 for r, g, b in corners if r > 240 and g > 240 and b > 240)
            return (white_px / len(px)) > 0.5 and corner_white >= 3
        except Exception:
            return False

    white_imgs = [p for p in local_imgs if is_white_background(p)]
    lifestyle_imgs = [p for p in local_imgs if not is_white_background(p)]
    if not lifestyle_imgs:
        # Fall back: use images from index 4+ (Amazon convention: lifestyle after main shots)
        lifestyle_imgs = local_imgs[4:] if len(local_imgs) > 4 else local_imgs[1:]
    if not lifestyle_imgs:
        lifestyle_imgs = local_imgs

    hook_src = white_imgs[0] if white_imgs else local_imgs[0]
    cta_src  = white_imgs[0] if white_imgs else local_imgs[0]
    feat_srcs = [lifestyle_imgs[i % len(lifestyle_imgs)] for i in range(3)]

    img0 = Image.open(hook_src)
    img1 = Image.open(feat_srcs[0])
    img2 = Image.open(feat_srcs[1])
    img3 = Image.open(feat_srcs[2])
    img_cta = Image.open(cta_src)

    # Feature backgrounds (no text baked in — text is a separate slide-in overlay)
    def build_feature_bg(src: Image.Image) -> Image.Image:
        img = resize_and_crop(src.copy(), W, H)
        return add_gradient_overlay(img)

    original_price = int(product.get("original_price", 0))
    scene_paths = {
        "hook":  save_scene(build_hook_image(img0, price, pname, rating, review_count, original_price, source), "hook"),
        "feat1": save_scene(build_feature_bg(img1), "feat1"),
        "feat2": save_scene(build_feature_bg(img2), "feat2"),
        "feat3": save_scene(build_feature_bg(img3), "feat3"),
        "cta":   save_scene(build_cta_image(img_cta, price, rating, review_count, source), "cta"),
    }

    # Feature text PNGs (transparent, for slide-in animation in composite_final)
    feat_text_pngs = [
        build_feature_text_png(feat1, 1, pname, 0),
        build_feature_text_png(feat2, 2, pname, 1),
        build_feature_text_png(feat3, 3, pname, 2),
    ]

    # 360-degree angle images with badge overlay
    angle_scene_paths = []
    for i, img_path in enumerate(local_imgs[:8]):
        img_a = Image.open(img_path)
        prepared = build_360_frame(img_a, i, len(local_imgs))
        p = os.path.join(TMP, f"scene_360_{i:02d}.jpg")
        prepared.save(p, "JPEG", quality=92)
        angle_scene_paths.append(p)

    print(f"  [OK] {len(scene_paths)} main + {len(angle_scene_paths)} angle scenes", flush=True)

    # ── Step 3: Build video clips ─────────────────────────────────────────────
    print("Step 3/6 -- Building video clips...", flush=True)

    # Angle clips for 360-degree scene
    angle_clips = []
    for i, path in enumerate(angle_scene_paths):
        clip = make_angle_clip(path, i)
        angle_clips.append(clip)
        print(f"  [OK] Angle {i+1}/{len(angle_scene_paths)}", flush=True)

    # Merge angle clips into one 360-degree segment
    if len(angle_clips) > 1:
        merged_360 = os.path.join(TMP, "angle_360_merged.mp4")
        a_inputs = []
        for p in angle_clips:
            a_inputs += ["-i", p]
        n = len(angle_clips)
        parts_360 = []
        offset = ANGLE_DUR - ANGLE_FADE
        prev = "0:v"
        _360_transitions = ["slideleft", "slideright"]
        for i in range(1, n):
            label = f"av{i}" if i < n - 1 else "avout"
            parts_360.append(
                f"[{prev}][{i}:v]xfade=transition={_360_transitions[i % 2]}"
                f":duration={ANGLE_FADE}:offset={offset:.3f}[{label}]"
            )
            prev = label
            offset += ANGLE_DUR - ANGLE_FADE
        run(
            [FFMPEG, "-y", *a_inputs,
             "-filter_complex", ";".join(parts_360),
             "-map", "[avout]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "22",
             "-pix_fmt", "yuv420p", merged_360],
            "merge_360",
        )
    else:
        merged_360 = angle_clips[0]

    dur_360 = get_duration(merged_360)
    print(f"  [OK] 360 showcase: {dur_360:.1f}s", flush=True)

    # Use-case scene (Scene 3) — optional
    usecase_clip_path = None
    usecase_dur = 5.0
    if usecase_media and usecase_media.get("type") and usecase_media.get("file"):
        print("  [OK] Preparing use-case scene...", flush=True)
        label_text = script.get("use_case_scene_text", "Perfect for Everyday Use!")
        try:
            usecase_clip_path = prepare_usecase_clip(
                usecase_media["file"],
                usecase_media["type"],
                label_text,
                duration=usecase_dur,
            )
            print(f"  [OK] Use-case scene ready: {label_text}", flush=True)
        except Exception as e:
            print(f"  [WARN] Use-case scene failed: {e} — skipping", flush=True)
            usecase_clip_path = None

    # Main scene clips
    scene_order = [
        ("hook",  SCENE_DURATIONS["hook"],  "in"),
        (merged_360, None, None),             # pre-built 360 segment
    ]
    if usecase_clip_path:
        scene_order.append((usecase_clip_path, None, None))   # pre-built use-case scene
    scene_order += [
        ("feat1", SCENE_DURATIONS["feat1"], "in"),
        ("feat2", SCENE_DURATIONS["feat2"], "out"),
        ("feat3", SCENE_DURATIONS["feat3"], "in"),
        ("cta",   SCENE_DURATIONS["cta"],  "out"),
    ]

    all_clips = []
    all_durs = []
    kb_idx = 0

    for key, dur, movement in scene_order:
        if dur is None:
            # Pre-built clip
            all_clips.append(key)
            all_durs.append(get_duration(key))
        else:
            img_path = scene_paths[key]
            clip = make_ken_burns_clip(img_path, kb_idx, dur, movement)
            all_clips.append(clip)
            all_durs.append(dur)
            print(f"  [OK] Scene '{key}' ({dur}s)", flush=True)
        kb_idx += 1

    # ── Step 4: Concatenate scenes ────────────────────────────────────────────
    print("Step 4/6 -- Concatenating scenes...", flush=True)
    bg_video = concat_xfade(all_clips, MAIN_FADE, all_durs)
    print("  [OK] Background assembled", flush=True)

    # ── Step 5: Load captions ─────────────────────────────────────────────────
    print("Step 5/6 -- Loading captions...", flush=True)
    srt_path = os.path.join(TMP, "voiceover.srt")
    srt_entries = []
    if os.path.exists(srt_path):
        srt_entries = parse_srt(srt_path)
        print(f"  [OK] {len(srt_entries)} caption blocks", flush=True)
    else:
        # Also try captions.srt (default name from generate_hindi_tts)
        alt_srt = os.path.join(TMP, "captions.srt")
        if os.path.exists(alt_srt):
            srt_entries = parse_srt(alt_srt)
            print(f"  [OK] {len(srt_entries)} caption blocks (from captions.srt)", flush=True)
        else:
            print("  [WARN] No SRT file found — no captions", flush=True)

    # ── Step 6: Final composite ───────────────────────────────────────────────
    print("Step 6/6 -- Final composite...", flush=True)

    # Compute absolute scene start times for animation timings
    s_starts = compute_scene_starts(all_durs, MAIN_FADE)

    # Scene flash labels aligned to scene_order
    flash_labels_base = ["HOOK", "360 VIEW"]
    if usecase_clip_path:
        flash_labels_base.append("USE CASE")
    flash_labels_base += ["FEATURE 1", "FEATURE 2", "FEATURE 3", "BUY NOW"]
    scene_labels = flash_labels_base[:len(s_starts)]

    # CTA is always last
    cta_scene_start = s_starts[-1] if s_starts else None

    # Generate hook text overlay PNG (uses LLM's hook_text_overlay field)
    hook_overlay_png = None
    hook_text = script.get("hook_text_overlay", "")
    if hook_text:
        try:
            hook_overlay_png = render_hook_text_overlay(hook_text)
            print(f"  [OK] Hook text overlay: '{hook_text}'", flush=True)
        except Exception as e:
            print(f"  [WARN] Hook overlay failed: {e}", flush=True)

    # Generate SFX
    sfx = None
    try:
        sfx = generate_sfx()
        print("  [OK] SFX generated (whoosh, cash, tick)", flush=True)
    except Exception as e:
        print(f"  [WARN] SFX generation failed: {e}", flush=True)

    # Optional BGM: drop any royalty-free MP3 into .tmp/bgm.mp3
    bgm_file = os.path.join(TMP, "bgm.mp3")
    if not os.path.exists(bgm_file):
        bgm_file = None
    else:
        print("  [OK] BGM found — will mix at 8% volume", flush=True)

    composite_final(
        bg_video, audio_path, srt_entries, output_path, audio_dur,
        scene_starts=s_starts,
        feat_text_pngs=feat_text_pngs,
        scene_labels=scene_labels,
        all_durs=all_durs,
        cta_start=cta_scene_start,
        hook_overlay_path=hook_overlay_png,
        sfx_paths=sfx,
        bgm_path=bgm_file,
    )
    print(f"  [OK] Done -> {output_path}", flush=True)

    return {
        "file": output_path,
        "duration_seconds": round(audio_dur, 2),
        "resolution": f"{W}x{H}",
        "angle_images": len(angle_scene_paths),
        "captions": len(srt_entries),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, help="Path to product JSON")
    parser.add_argument("--script",  required=True, help="Path to script JSON")
    parser.add_argument(
        "--audio", default=os.path.join(TMP, "voiceover.mp3"),
        help="Path to voiceover MP3",
    )
    parser.add_argument("--output", default="product_video.mp4")
    parser.add_argument("--usecase", default=None, help="Path to usecase_media JSON")
    args = parser.parse_args()

    with open(args.product, "r", encoding="utf-8") as f:
        product = json.load(f)
    if isinstance(product, list):
        product = product[0]

    with open(args.script, "r", encoding="utf-8") as f:
        script = json.load(f)

    usecase_media = None
    if args.usecase and os.path.exists(args.usecase):
        with open(args.usecase, "r", encoding="utf-8") as f:
            usecase_media = json.load(f)

    result = compose_product_video(product, script, args.audio, args.output, usecase_media)
    print(json.dumps(result, indent=2))
