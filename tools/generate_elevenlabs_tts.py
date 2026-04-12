"""
generate_elevenlabs_tts.py
Converts script text to voiceover using ElevenLabs API.
Generates synchronized SRT captions by estimating word-level timings.
Usage: python tools/generate_elevenlabs_tts.py [--voice_id ID] [--text "..."]
       (reads .tmp/script.json by default if --text not provided)
Output: .tmp/voiceover.mp3 + .tmp/captions.srt + JSON with paths and duration.
Requires: ELEVENLABS_API_KEY in .env
"""

import argparse, json, os, subprocess, sys
import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP          = os.path.join(PROJECT_ROOT, ".tmp")
SCRIPT_JSON  = os.path.join(TMP, "script.json")
MP3_PATH     = os.path.join(TMP, "voiceover.mp3")
SRT_PATH     = os.path.join(TMP, "captions.srt")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_BASE    = "https://api.elevenlabs.io/v1"

# Default voice IDs per account (ElevenLabs pre-made voices, free tier)
ACCOUNT_VOICES = {
    "factsflash":      "pNInz6obpgDQGcFmaJgB",  # Adam - confident, clear
    "techmindblown":   "ErXwobaYiN019PkySvjV",  # Antoni - deep, authoritative
    "coresteelfitness":"VR6AewLTigWG4xSOukaG",  # Arnold - energetic, powerful
    "cricketcuts":     "TxGEqnHWrfWFTfGW9XjX",  # Josh - sports commentator
}
DEFAULT_VOICE = "pNInz6obpgDQGcFmaJgB"  # Adam

WORDS_PER_LINE = 2  # Caption grouping

FFPROBE_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe"


def srt_time(ms: int) -> str:
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000;    ms %= 60_000
    s = ms // 1000;      ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _estimate_word_timings(text: str, total_ms: int) -> list:
    words       = text.split()
    if not words:
        return []
    char_counts = [max(len(w.strip(".,!?;:'\""), ), 1) for w in words]
    total_chars = sum(char_counts)
    timings     = []
    current_ms  = 0
    for word, chars in zip(words, char_counts):
        duration = int(total_ms * chars / total_chars)
        timings.append({"word": word, "start_ms": current_ms, "duration_ms": duration})
        current_ms += duration
    return timings


def _words_to_srt(words: list) -> str:
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


def generate_elevenlabs_tts(text: str, voice_id: str = DEFAULT_VOICE) -> dict:
    if not ELEVENLABS_API_KEY:
        raise ValueError(
            "ELEVENLABS_API_KEY not set in .env\n"
            "Get a free key at: https://elevenlabs.io/sign-up\n"
            "Then add: ELEVENLABS_API_KEY=your_key_here to .env"
        )

    os.makedirs(TMP, exist_ok=True)

    print(f"Generating voiceover with ElevenLabs (voice: {voice_id})...", flush=True)

    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.50,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        }
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)

    if not resp.ok:
        raise RuntimeError(f"ElevenLabs API error {resp.status_code}: {resp.text[:400]}")

    with open(MP3_PATH, "wb") as f:
        f.write(resp.content)
    print(f"  [OK] MP3: {MP3_PATH} ({len(resp.content)//1024}KB)", flush=True)

    # Estimate word timings + generate SRT
    total_ms     = _get_duration_ms(MP3_PATH)
    word_timings = _estimate_word_timings(text, total_ms)
    srt_content  = _words_to_srt(word_timings)

    with open(SRT_PATH, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"  [OK] Captions: {SRT_PATH} ({len(word_timings)} words, "
          f"{len([l for l in srt_content.strip().split(chr(10)+chr(10)) if l])} blocks)", flush=True)

    return {
        "file":             MP3_PATH,
        "srt":              SRT_PATH,
        "word_count":       len(word_timings),
        "duration_seconds": round(total_ms / 1000, 2),
        "voice_id":         voice_id,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice_id", default=None,  help="ElevenLabs voice ID")
    parser.add_argument("--text",     default=None,  help="Text to speak (reads script.json if omitted)")
    parser.add_argument("--account",  default=None,  help="Account name to pick voice automatically")
    args = parser.parse_args()

    # Resolve text
    text = args.text
    if not text:
        if not os.path.exists(SCRIPT_JSON):
            print(f"ERROR: No --text provided and {SCRIPT_JSON} not found.")
            sys.exit(1)
        with open(SCRIPT_JSON, encoding="utf-8") as f:
            script = json.load(f)
        text = script.get("narration", "")
        if not text:
            print("ERROR: script.json has no 'narration' field.")
            sys.exit(1)
        print(f"  Text from script.json ({len(text.split())} words)", flush=True)

    # Resolve voice ID
    voice_id = args.voice_id
    if not voice_id and args.account:
        voice_id = ACCOUNT_VOICES.get(args.account, DEFAULT_VOICE)
        print(f"  Voice for [{args.account}]: {voice_id}", flush=True)
    if not voice_id:
        voice_id = DEFAULT_VOICE

    result = generate_elevenlabs_tts(text, voice_id)
    print(json.dumps(result, indent=2))
