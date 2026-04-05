"""
compose_documentary.py
Composes AI Historical Documentary video (1080x1920) from scene images + voiceover.

Layout:
  - Each scene: landscape AI image with Ken Burns effect (slow zoom/pan)
  - Blurred background fills top/bottom bars (portrait frame)
  - Hindi captions burned at bottom
  - Channel badge at top

Usage: python tools/compose_documentary.py "AI से देखो Bharat"
Inputs:
  .tmp/documentary_script.json  — scene data and word counts
  .tmp/images/scene_001.jpg ...  — AI-generated scene images
  .tmp/voiceover.mp3             — Hindi narration audio
  .tmp/captions.srt              — synced Hindi captions
Output: .tmp/output_documentary.mp4 (1080x1920, H.264, AAC)
"""

import glob
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw, ImageFont

TMP          = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
IMAGES_DIR   = os.path.join(TMP, "images")
SCRIPT_FILE  = os.path.join(TMP, "documentary_script.json")
AUDIO_FILE   = os.path.join(TMP, "voiceover.mp3")
SRT_FILE     = os.path.join(TMP, "captions.srt")
CLIPS_DIR    = os.path.join(TMP, "scene_clips")

FFMPEG_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG     = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE    = os.path.join(FFMPEG_BIN, "ffprobe.exe")

# Hindi font with Devanagari support
FONT_HINDI = r"C:\Windows\Fonts\Nirmala.ttc"
FONT_BOLD  = r"C:\Windows\Fonts\arialbd.ttf"

W, H      = 1080, 1920   # output portrait resolution
FPS       = 30
IMG_W     = 1280         # landscape image width (from FLUX landscape_16_9)
IMG_H     = 720          # landscape image height
FG_H      = int(IMG_H * (W / IMG_W))  # foreground height after scaling: 607px
FG_Y      = (H - FG_H) // 2          # vertical center offset: ~656px

# Background music (optional)
MUSIC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "music", "background.mp3"))


def run(cmd: list, label: str = "") -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg error [{label}]:\n{r.stderr[-2000:]}")


def get_audio_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def calc_scene_durations(scenes: list, total_duration: float) -> list:
    """Proportional duration per scene based on narration word count."""
    total_words = sum(s.get("word_count", len(s["narration"].split())) for s in scenes)
    durations   = []
    accumulated = 0.0
    for i, s in enumerate(scenes):
        wc = s.get("word_count", len(s["narration"].split()))
        if i == len(scenes) - 1:
            dur = total_duration - accumulated   # last scene gets remainder
        else:
            dur = round((wc / total_words) * total_duration, 3)
        durations.append(max(dur, 2.0))          # minimum 2s per scene
        accumulated += dur
    return durations


def make_scene_clip(image_path: str, duration: float, output_path: str,
                    pan: str = "zoom_in") -> None:
    """Render a single scene: Ken Burns on foreground + blurred background."""
    frames  = max(int(duration * FPS), FPS)
    incr    = 0.15 / frames

    # Ken Burns zoom expressions per pan type
    if pan == "zoom_out":
        z_expr = f"if(eq(on,1),1.15,max(1.0,zoom-{incr:.7f}))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif pan == "pan_left":
        z_expr = "1.1"
        max_x  = int(IMG_W - IMG_W / 1.1)       # ≈116px travel
        px_inc = max_x / frames
        x_expr = f"if(eq(on,1),0,min({max_x},x+{px_inc:.4f}))"
        y_expr = "ih/2-(ih/zoom/2)"
    elif pan == "pan_right":
        z_expr = "1.1"
        max_x  = int(IMG_W - IMG_W / 1.1)
        px_inc = max_x / frames
        x_expr = f"if(eq(on,1),{max_x},max(0,x-{px_inc:.4f}))"
        y_expr = "ih/2-(ih/zoom/2)"
    else:  # zoom_in (default)
        z_expr = f"if(eq(on,1),1.0,min(1.15,zoom+{incr:.7f}))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    # Foreground: Ken Burns animation → 1080 x FG_H
    fg_filter = (
        f"[0:v]scale={IMG_W}:{IMG_H},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d=99999:s={W}x{FG_H}:fps={FPS}[fg]"
    )

    # Background: scale to fill 1080x1920, heavy blur + darken
    bg_filter = (
        f"[0:v]scale=-1:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"boxblur=35:1,"
        f"colorchannelmixer=rr=0.55:gg=0.55:bb=0.55[bg]"
    )

    # Composite: overlay fg centered on bg
    overlay = f"[bg][fg]overlay=x=0:y={FG_Y}[out]"

    fc  = ";".join([fg_filter, bg_filter, overlay])
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-filter_complex", fc,
        "-map", "[out]",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        output_path
    ]
    run(cmd, f"scene_{os.path.basename(output_path)}")


def concat_clips(clip_paths: list, output_path: str) -> None:
    """Concatenate scene clips with brief crossfade transitions."""
    if len(clip_paths) == 1:
        import shutil
        shutil.copy(clip_paths[0], output_path)
        return

    # Write concat list file
    list_file = os.path.join(TMP, "concat_list.txt")
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an", output_path
    ]
    run(cmd, "concat")


def make_badge_png(channel_name: str) -> str:
    """Channel badge PNG overlay (red pill at top)."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_BOLD, 44)
    except Exception:
        font = ImageFont.load_default()

    tag  = f"  {channel_name.upper()}  "
    bbox = draw.textbbox((0, 0), tag, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    tx   = (W - tw) // 2
    ty   = 58

    pill = Image.new("RGBA", (tw + 44, th + 22), (200, 20, 20, 235))
    img.paste(pill, (tx - 22, ty - 11), pill)
    for dx in [-2, 0, 2]:
        for dy in [-2, 0, 2]:
            if dx or dy:
                draw.text((tx + dx, ty + dy), tag, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, ty), tag, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(TMP, "doc_badge.png")
    img.save(path)
    return path


def parse_srt(srt_path: str) -> list:
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    def ts_to_sec(ts):
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    entries = []
    for block in re.split(r"\n\n+", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            times = lines[1].split(" --> ")
            entries.append({
                "start": ts_to_sec(times[0].strip()),
                "end":   ts_to_sec(times[1].strip()),
                "text":  " ".join(lines[2:]),
            })
    return entries


def render_caption_png(text: str, idx: int) -> str:
    """Render a single Hindi caption line as transparent PNG."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_HINDI, 62, index=0)
    except Exception:
        try:
            font = ImageFont.truetype(FONT_BOLD, 62)
        except Exception:
            font = ImageFont.load_default()

    cap_y = int(H * 0.88)   # 88% from top = near bottom

    # Dark pill background for readability
    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    tx   = (W - tw) // 2
    pill_pad = 18
    pill = Image.new("RGBA", (tw + pill_pad * 2, th + pill_pad), (0, 0, 0, 160))
    img.paste(pill, (tx - pill_pad, cap_y - pill_pad // 2), pill)

    # Text outline
    outline = 5
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx or dy:
                draw.text((tx + dx, cap_y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, cap_y), text, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(TMP, f"doc_cap_{idx:04d}.png")
    img.save(path)
    return path


def compose_final(video_raw: str, audio_path: str, srt_entries: list,
                  badge_png: str, output_path: str, duration: float) -> None:
    """Merge video + audio + badge + captions into final output."""
    cap_files = [
        (render_caption_png(e["text"], i), e["start"], e["end"])
        for i, e in enumerate(srt_entries)
    ]

    has_music = os.path.exists(MUSIC_PATH)
    if has_music:
        print(f"  [music] {os.path.basename(MUSIC_PATH)}", flush=True)

    # Input list: 0=video, 1=badge, 2..N=captions, N+1=voice, [N+2=music]
    inputs = ["-i", video_raw, "-i", badge_png]
    for (p, _, _) in cap_files:
        inputs += ["-i", p]
    voice_idx = 2 + len(cap_files)
    inputs += ["-i", audio_path]
    if has_music:
        inputs += ["-i", MUSIC_PATH]
        music_idx = voice_idx + 1

    filter_parts = []

    # Overlay badge on video
    filter_parts.append("[0:v][1:v]overlay=0:0[s0]")
    prev = "s0"

    # Overlay each caption at its timestamp
    for idx, (_, start, end) in enumerate(cap_files):
        inp   = idx + 2
        label = f"c{idx}" if idx < len(cap_files) - 1 else "vfinal"
        filter_parts.append(
            f"[{prev}][{inp}:v]overlay=0:0"
            f":enable='between(t,{start:.3f},{end:.3f})'[{label}]"
        )
        prev = label

    if not cap_files:
        filter_parts.append(f"[s0]copy[vfinal]")

    # Audio mix
    fade_start = max(0.0, duration - 2.5)
    if has_music:
        filter_parts.append(
            f"[{voice_idx}:a]volume=1.0[voice];"
            f"[{music_idx}:a]volume=0.10,"
            f"afade=t=in:st=0:d=2,"
            f"afade=t=out:st={fade_start:.2f}:d=2.5[music];"
            f"[voice][music]amix=inputs=2:duration=first[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{voice_idx}:a:0"

    fc  = ";".join(filter_parts)
    cmd = [
        FFMPEG, "-y",
        *inputs,
        "-filter_complex", fc,
        "-map", "[vfinal]",
        "-map", audio_map,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ]
    run(cmd, "final_compose")


def compose_documentary(channel_name: str,
                        output_filename: str = "output_documentary.mp4") -> dict:
    output_path = os.path.join(TMP, output_filename)

    # Validate inputs
    for path, label in [
        (SCRIPT_FILE, "documentary_script.json"),
        (AUDIO_FILE,  "voiceover.mp3"),
        (SRT_FILE,    "captions.srt"),
    ]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing: {path} — run the pipeline steps first")

    with open(SCRIPT_FILE, "r", encoding="utf-8") as f:
        script = json.load(f)

    scenes         = script["scenes"]
    total_duration = get_audio_duration(AUDIO_FILE)
    durations      = calc_scene_durations(scenes, total_duration)

    print(f"Composing documentary: {script.get('title', 'Untitled')}", flush=True)
    print(f"  {len(scenes)} scenes | {total_duration:.1f}s audio | {channel_name}", flush=True)

    # Step 1: Generate scene clips
    os.makedirs(CLIPS_DIR, exist_ok=True)
    clip_paths = []

    for i, (scene, dur) in enumerate(zip(scenes, durations)):
        n          = scene["scene_num"]
        img_path   = os.path.join(IMAGES_DIR, f"scene_{n:03d}.jpg")
        clip_path  = os.path.join(CLIPS_DIR, f"clip_{n:03d}.mp4")
        pan        = scene.get("pan", "zoom_in")

        if not os.path.exists(img_path):
            print(f"  [WARN] Missing image scene_{n:03d}.jpg — skipping scene", flush=True)
            continue

        if not os.path.exists(clip_path):
            print(f"  Scene {n}/{len(scenes)} ({dur:.1f}s, {pan})...", flush=True)
            make_scene_clip(img_path, dur, clip_path, pan)
        else:
            print(f"  [skip] clip_{n:03d}.mp4 exists", flush=True)

        clip_paths.append(clip_path)

    if not clip_paths:
        raise RuntimeError("No scene clips generated — check that images exist in .tmp/images/")

    # Step 2: Concat all clips
    print(f"Step 2 — Concatenating {len(clip_paths)} clips...", flush=True)
    video_raw = os.path.join(TMP, "doc_raw.mp4")
    concat_clips(clip_paths, video_raw)

    # Step 3: Parse captions
    print(f"Step 3 — Parsing {SRT_FILE}...", flush=True)
    srt_entries = parse_srt(SRT_FILE)
    print(f"  [OK] {len(srt_entries)} caption blocks", flush=True)

    # Step 4: Badge
    print(f"Step 4 — Badge...", flush=True)
    badge_png = make_badge_png(channel_name)

    # Step 5: Final composite (audio + captions + badge)
    print(f"Step 5 — Final composite...", flush=True)
    compose_final(video_raw, AUDIO_FILE, srt_entries, badge_png, output_path, total_duration)

    # Cleanup intermediates
    for f in [video_raw, badge_png]:
        if os.path.exists(f):
            os.remove(f)
    for p in glob.glob(os.path.join(TMP, "doc_cap_*.png")):
        os.remove(p)
    if os.path.exists(os.path.join(TMP, "concat_list.txt")):
        os.remove(os.path.join(TMP, "concat_list.txt"))

    print(f"  [OK] Done → {output_path}", flush=True)

    return {
        "file":             output_path,
        "channel":          channel_name,
        "title":            script.get("title", ""),
        "duration_seconds": round(total_duration, 2),
        "scenes":           len(clip_paths),
        "resolution":       f"{W}x{H}",
        "captions":         len(srt_entries),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/compose_documentary.py "AI से देखो Bharat" [output.mp4]')
        sys.exit(1)
    name    = sys.argv[1]
    out     = sys.argv[2] if len(sys.argv) > 2 else "output_documentary.mp4"
    result  = compose_documentary(name, out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
