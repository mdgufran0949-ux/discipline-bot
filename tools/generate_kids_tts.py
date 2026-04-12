"""
generate_kids_tts.py
Converts kids animation script narration to voiceover MP3 using edge-tts (free).
Uses child-friendly voice (en-US-AnaNeural) with slower rate and higher pitch.
Also generates word-synced SRT caption file.

Usage: python tools/generate_kids_tts.py "narration text here"
Output: .tmp/kids_voiceover.mp3 + .tmp/kids_captions.srt + JSON with paths and duration.
"""

import asyncio
import json
import sys
import os
import subprocess
import argparse

import edge_tts

VOICE          = "en-US-AnaNeural"   # Child-friendly, warm female voice
RATE           = "-5%"               # Slightly slower for comprehension, but still musical
PITCH          = "+15Hz"             # Higher pitch — bright, singing-like kid appeal
WORDS_PER_LINE = 2                   # 2 words per caption line — punch and rhythm

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
OUTPUT_MP3  = os.path.join(TMP, "kids_voiceover.mp3")
OUTPUT_SRT  = os.path.join(TMP, "kids_captions.srt")
FFPROBE     = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe"


def srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp format."""
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def _generate_with_timestamps(text: str, mp3_path: str):
    """Generate MP3 and collect word boundary events."""
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    sentences = []

    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                sentences.append({
                    "text":        chunk["text"],
                    "start_ms":    chunk["offset"] // 10000,
                    "duration_ms": chunk["duration"] // 10000
                })
    return sentences


def sentences_to_word_timings(sentences: list) -> list:
    """Distribute word timings evenly within each sentence."""
    words = []
    for sent in sentences:
        sent_words = sent["text"].split()
        if not sent_words:
            continue
        per_word_ms = sent["duration_ms"] // max(len(sent_words), 1)
        for i, w in enumerate(sent_words):
            words.append({
                "word":        w,
                "start_ms":    sent["start_ms"] + i * per_word_ms,
                "duration_ms": per_word_ms
            })
    return words


def words_to_srt(words: list) -> str:
    """Group words into caption lines and format as SRT."""
    if not words:
        return ""
    lines = []
    i = 0
    idx = 1
    while i < len(words):
        group    = words[i:i + WORDS_PER_LINE]
        start_ms = group[0]["start_ms"]
        end_ms   = group[-1]["start_ms"] + group[-1]["duration_ms"]
        text     = " ".join(w["word"] for w in group)
        lines.append(f"{idx}\n{srt_time(start_ms)} --> {srt_time(end_ms)}\n{text}\n")
        idx += 1
        i += WORDS_PER_LINE
    return "\n".join(lines)


def get_duration(file_path: str) -> float:
    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def generate_kids_tts(text: str, voice: str = VOICE) -> dict:
    os.makedirs(TMP, exist_ok=True)
    mp3_path = os.path.abspath(OUTPUT_MP3)
    srt_path = os.path.abspath(OUTPUT_SRT)

    print(f"Generating kids TTS ({voice})...", flush=True)
    sentences   = asyncio.run(_generate_with_timestamps(text, mp3_path))
    words       = sentences_to_word_timings(sentences)
    srt_content = words_to_srt(words)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    duration      = get_duration(mp3_path)
    caption_lines = len([b for b in srt_content.strip().split("\n\n") if b.strip()])

    print(f"  [OK] {duration:.1f}s voiceover, {len(words)} words, {caption_lines} caption lines", flush=True)

    return {
        "file":             mp3_path,
        "srt":              srt_path,
        "word_count":       len(words),
        "caption_lines":    caption_lines,
        "duration_seconds": round(duration, 2),
        "voice":            voice
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kids TTS voiceover generator")
    parser.add_argument("text", nargs="?", help="Narration text (or pass via stdin)")
    parser.add_argument("--voice", default=VOICE, help=f"Voice name (default: {VOICE})")
    args = parser.parse_args()

    text = args.text or " ".join(sys.argv[1:])
    if not text:
        print("Usage: python tools/generate_kids_tts.py \"narration text\"")
        sys.exit(1)

    result = generate_kids_tts(text, args.voice)
    print(json.dumps(result, indent=2))
