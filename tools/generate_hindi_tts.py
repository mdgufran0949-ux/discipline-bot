"""
generate_hindi_tts.py
Converts Hindi text to voiceover MP3 using edge-tts (Microsoft, free).
Also writes a synced SRT caption file using sentence boundary events.

Usage: python tools/generate_hindi_tts.py "narration text here"
       python tools/generate_hindi_tts.py --voice female "text"

Output: .tmp/voiceover.mp3 + .tmp/captions.srt
Voices:
  male   → hi-IN-MadhurNeural  (deep, documentary-style)
  female → hi-IN-SwaraNeural   (clear, engaging)
"""

import asyncio
import json
import os
import subprocess
import sys

import edge_tts
from dotenv import load_dotenv

load_dotenv()

VOICES = {
    "male":   "hi-IN-MadhurNeural",
    "female": "hi-IN-SwaraNeural",
}
DEFAULT_VOICE  = "male"
RATE           = "-8%"    # slightly slower = more natural documentary cadence
WORDS_PER_LINE = 2   # 2-word groups: faster pacing, more professional documentary feel

TMP        = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
OUTPUT_MP3 = os.path.join(TMP, "voiceover.mp3")
OUTPUT_SRT = os.path.join(TMP, "captions.srt")

def resolve_output_paths(out_dir: str | None) -> tuple[str, str]:
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, "voiceover.mp3"), os.path.join(out_dir, "captions.srt")
    return OUTPUT_MP3, OUTPUT_SRT

import shutil as _sh2; FFPROBE = _sh2.which("ffprobe") or "ffprobe"


def srt_time(ms: int) -> str:
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def _generate(text: str, voice: str, mp3_path: str) -> list:
    communicate = edge_tts.Communicate(text, voice, rate=RATE)
    events = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                events.append({
                    "text":        chunk["text"],
                    "start_ms":    chunk["offset"] // 10000,
                    "duration_ms": chunk["duration"] // 10000,
                })
    return events


def events_to_word_timings(events: list) -> list:
    words = []
    for evt in events:
        parts = evt["text"].split()
        if not parts:
            continue
        per_word = evt["duration_ms"] // len(parts)
        for i, w in enumerate(parts):
            words.append({
                "word":        w,
                "start_ms":    evt["start_ms"] + i * per_word,
                "duration_ms": per_word,
            })
    return words


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


def get_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def generate_hindi_tts(text: str, voice_key: str = DEFAULT_VOICE,
                        out_dir: str | None = None) -> dict:
    voice    = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    mp3_path, srt_path = resolve_output_paths(out_dir)
    mp3_path = os.path.abspath(mp3_path)
    srt_path = os.path.abspath(srt_path)

    os.makedirs(os.path.dirname(mp3_path), exist_ok=True)
    print(f"  Voice: {voice}", flush=True)

    events = asyncio.run(_generate(text, voice, mp3_path))
    words  = events_to_word_timings(events)
    srt    = words_to_srt(words)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)

    duration = get_duration(mp3_path)
    print(f"  [OK] {duration:.1f}s audio, {len(words)} words, {len(srt.strip().split(chr(10)*2))} caption blocks", flush=True)

    return {
        "file":             mp3_path,
        "srt":              srt_path,
        "voice":            voice,
        "word_count":       len(words),
        "duration_seconds": round(duration, 2),
    }


if __name__ == "__main__":
    args      = sys.argv[1:]
    voice_key = DEFAULT_VOICE
    out_dir   = None

    if "--voice" in args:
        idx = args.index("--voice")
        voice_key = args[idx + 1]
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if "--out-dir" in args:
        idx = args.index("--out-dir")
        out_dir = args[idx + 1]
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if not args:
        print('Usage: python tools/generate_hindi_tts.py "Hindi text here"')
        print('       python tools/generate_hindi_tts.py --voice female "text"')
        print('       python tools/generate_hindi_tts.py --out-dir .tmp/insmind_documentary "text"')
        sys.exit(1)

    text   = " ".join(args)
    result = generate_hindi_tts(text, voice_key, out_dir=out_dir)
    print(json.dumps(result, indent=2))
