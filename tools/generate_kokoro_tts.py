"""
generate_kokoro_tts.py
Converts script text to voiceover using Kokoro-ONNX TTS (free, runs on CPU, Windows-compatible).
Generates synchronized SRT captions by estimating word-level timings.
Usage: python tools/generate_kokoro_tts.py "script text here" [voice]
Output: .tmp/voiceover.mp3 + .tmp/captions.srt + JSON with paths and duration.

Install: pip install kokoro-onnx soundfile numpy
Voice options: am_adam, am_michael, af_heart, af_bella, af_sarah, bm_george
Default: am_adam (strong male voice — ideal for motivation content)
"""

import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP          = os.path.join(PROJECT_ROOT, ".tmp")
MODELS_DIR   = os.path.join(PROJECT_ROOT, ".models")
WAV_PATH     = os.path.join(TMP, "voiceover.wav")
MP3_PATH     = os.path.join(TMP, "voiceover.mp3")
SRT_PATH     = os.path.join(TMP, "captions.srt")

MODEL_PATH  = os.path.join(MODELS_DIR, "kokoro-v1.0.int8.onnx")
VOICES_PATH = os.path.join(MODELS_DIR, "voices-v1.0.bin")

MODEL_URL  = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

WORDS_PER_LINE = 2
DEFAULT_VOICE  = "am_adam"

FFMPEG_BIN  = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
FFPROBE_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe"


def _download_file(url: str, dest: str) -> None:
    """Download a file with progress indicator."""
    print(f"  Downloading {os.path.basename(dest)}...", flush=True)
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", flush=True)
    print(f"\n  [OK] Saved: {dest}", flush=True)


def _ensure_models() -> None:
    """Download Kokoro ONNX model files if not already present."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    if not os.path.exists(MODEL_PATH):
        print("Kokoro model not found — downloading (~83MB)...", flush=True)
        _download_file(MODEL_URL, MODEL_PATH)
    if not os.path.exists(VOICES_PATH):
        print("Kokoro voices not found — downloading (~2MB)...", flush=True)
        _download_file(VOICES_URL, VOICES_PATH)


def srt_time(ms: int) -> str:
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000;    ms %= 60_000
    s = ms // 1000;      ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _estimate_word_timings(text: str, total_ms: int) -> list:
    words       = text.split()
    if not words:
        return []
    char_counts = [max(len(w.strip(".,!?;:")), 1) for w in words]
    total_chars = sum(char_counts)
    timings     = []
    current_ms  = 0
    for word, chars in zip(words, char_counts):
        duration = int(total_ms * chars / total_chars)
        timings.append({"word": word, "start_ms": current_ms, "duration_ms": duration})
        current_ms += duration
    return timings


def words_to_srt(words: list) -> str:
    if not words:
        return ""
    lines = []
    i, idx = 0, 1
    while i < len(words):
        group    = words[i:i + WORDS_PER_LINE]
        start_ms = group[0]["start_ms"]
        end_ms   = group[-1]["start_ms"] + group[-1]["duration_ms"]
        text     = " ".join(w["word"] for w in group)
        lines.append(f"{idx}\n{srt_time(start_ms)} --> {srt_time(end_ms)}\n{text}\n")
        idx += 1
        i   += WORDS_PER_LINE
    return "\n".join(lines)


def _get_duration_ms(file_path: str) -> int:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
        capture_output=True, text=True, check=True
    )
    return int(float(json.loads(result.stdout)["format"]["duration"]) * 1000)


def _wav_to_mp3(wav_path: str, mp3_path: str) -> None:
    subprocess.run(
        [FFMPEG_BIN, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path],
        capture_output=True, check=True
    )


def generate_kokoro_tts(text: str, voice: str = DEFAULT_VOICE) -> dict:
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        raise ImportError("Run: pip install kokoro-onnx soundfile numpy")

    os.makedirs(TMP, exist_ok=True)
    _ensure_models()

    print(f"Generating voice with Kokoro TTS (voice: {voice})...", flush=True)
    kokoro  = Kokoro(MODEL_PATH, VOICES_PATH)
    samples, sample_rate = kokoro.create(text, voice=voice, speed=1.05, lang="en-us")

    sf.write(WAV_PATH, samples, sample_rate)
    print(f"  [OK] WAV: {WAV_PATH}", flush=True)

    _wav_to_mp3(WAV_PATH, MP3_PATH)
    os.remove(WAV_PATH)
    print(f"  [OK] MP3: {MP3_PATH}", flush=True)

    total_ms     = _get_duration_ms(MP3_PATH)
    word_timings = _estimate_word_timings(text, total_ms)
    srt_content  = words_to_srt(word_timings)

    with open(SRT_PATH, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"  [OK] Captions: {SRT_PATH}", flush=True)

    return {
        "file":             MP3_PATH,
        "srt":              SRT_PATH,
        "word_count":       len(word_timings),
        "caption_lines":    len([l for l in srt_content.strip().split("\n\n") if l]),
        "duration_seconds": round(total_ms / 1000, 2),
        "voice":            voice
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/generate_kokoro_tts.py \"script text\" [voice]")
        sys.exit(1)
    text   = sys.argv[1]
    voice  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    result = generate_kokoro_tts(text, voice)
    print(json.dumps(result, indent=2))
