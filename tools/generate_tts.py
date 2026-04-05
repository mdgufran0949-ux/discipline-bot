"""
generate_tts.py
Converts script text to voiceover MP3 using edge-tts (Microsoft, free).
Also captures word-boundary timestamps and writes a synced SRT caption file.
Usage: python tools/generate_tts.py "script text here"
Output: .tmp/voiceover.mp3 + .tmp/captions.srt + JSON with paths and duration.
"""

import asyncio
import json
import sys
import os
import subprocess

import edge_tts

VOICE       = "en-US-GuyNeural"
RATE        = "-5%"
OUTPUT_MP3  = os.path.join(os.path.dirname(__file__), "..", ".tmp", "voiceover.mp3")
OUTPUT_SRT  = os.path.join(os.path.dirname(__file__), "..", ".tmp", "captions.srt")
FFPROBE     = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe"
WORDS_PER_LINE = 2

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
    """Generate MP3 and collect sentence boundary events."""
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    sentences = []  # list of {text, start_ms, duration_ms}

    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                sentences.append({
                    "text": chunk["text"],
                    "start_ms": chunk["offset"] // 10000,    # 100-ns → ms
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
        per_word_ms = sent["duration_ms"] // len(sent_words)
        for i, w in enumerate(sent_words):
            words.append({
                "word": w,
                "start_ms": sent["start_ms"] + i * per_word_ms,
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
        group = words[i:i + WORDS_PER_LINE]
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

def generate_tts(text: str) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_MP3)), exist_ok=True)
    mp3_path = os.path.abspath(OUTPUT_MP3)
    srt_path = os.path.abspath(OUTPUT_SRT)

    sentences = asyncio.run(_generate_with_timestamps(text, mp3_path))
    words = sentences_to_word_timings(sentences)
    srt_content = words_to_srt(words)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    duration = get_duration(mp3_path)
    return {
        "file": mp3_path,
        "srt": srt_path,
        "word_count": len(words),
        "caption_lines": len(srt_content.strip().split("\n\n")),
        "duration_seconds": round(duration, 2)
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/generate_tts.py \"script text here\"")
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    result = generate_tts(text)
    print(json.dumps(result, indent=2))
