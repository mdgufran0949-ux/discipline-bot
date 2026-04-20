"""
generate_tts_kokoro_pipeline.py
Converts script text to voiceover using the kokoro PyTorch package (KPipeline).
Designed for EC2 where kokoro (torch-based) is installed in ~/kokoro-env.
Usage: ~/kokoro-env/bin/python tools/generate_tts_kokoro_pipeline.py "script text" [voice]
Output: .tmp/voiceover.wav + .tmp/captions.srt + JSON with paths and duration.

Voice options: af_heart, af_bella, af_sarah, af_sky, am_adam, am_michael, bm_george
Default: am_michael (clear male voice, good for motivational content)
Sample rate: 24000 Hz
"""

import json
import os
import sys

import numpy as np
import soundfile as sf

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP          = os.path.join(PROJECT_ROOT, ".tmp")
WAV_PATH     = os.path.join(TMP, "voiceover.wav")
SRT_PATH     = os.path.join(TMP, "captions.srt")
SAMPLE_RATE  = 24000
DEFAULT_VOICE = "am_michael"
WORDS_PER_LINE = 2


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


def generate_tts(text: str, voice: str = DEFAULT_VOICE) -> dict:
    try:
        from kokoro import KPipeline
    except ImportError:
        raise ImportError("Run: ~/kokoro-env/bin/pip install kokoro soundfile")

    os.makedirs(TMP, exist_ok=True)

    print(f"Generating voice with Kokoro (voice: {voice})...", flush=True)
    pipeline = KPipeline(lang_code="a")
    chunks   = []
    for _, _, audio in pipeline(text, voice=voice, speed=1.05):
        chunks.append(audio)

    audio    = np.concatenate(chunks)
    sf.write(WAV_PATH, audio, SAMPLE_RATE)
    print(f"  [OK] WAV: {WAV_PATH}", flush=True)

    total_ms     = int(len(audio) / SAMPLE_RATE * 1000)
    word_timings = _estimate_word_timings(text, total_ms)
    srt_content  = words_to_srt(word_timings)

    with open(SRT_PATH, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"  [OK] Captions: {SRT_PATH}", flush=True)

    return {
        "file":             WAV_PATH,
        "srt":              SRT_PATH,
        "word_count":       len(word_timings),
        "caption_lines":    len([l for l in srt_content.strip().split("\n\n") if l]),
        "duration_seconds": round(total_ms / 1000, 2),
        "voice":            voice,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: ~/kokoro-env/bin/python tools/generate_tts_kokoro_pipeline.py "text" [voice]')
        sys.exit(1)
    text   = sys.argv[1]
    voice  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    result = generate_tts(text, voice)
    print(json.dumps(result, indent=2))
