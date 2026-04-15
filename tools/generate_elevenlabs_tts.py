"""
generate_elevenlabs_tts.py
Converts script text to voiceover using ElevenLabs API.
Falls back to edge-tts automatically if ElevenLabs is unavailable or returns 401/403.
Generates synchronized SRT captions by estimating word-level timings.
Usage: python tools/generate_elevenlabs_tts.py [--voice_id ID] [--text "..."]
       (reads .tmp/script.json by default if --text not provided)
Output: .tmp/voiceover.mp3 + .tmp/captions.srt + JSON with paths and duration.
"""

import argparse, asyncio, json, os, subprocess, sys
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

# ElevenLabs voice IDs per account
ACCOUNT_VOICES = {
    "factsflash":      "pNInz6obpgDQGcFmaJgB",  # Adam
    "techmindblown":   "ErXwobaYiN019PkySvjV",  # Antoni
    "coresteelfitness":"VR6AewLTigWG4xSOukaG",  # Arnold
    "cricketcuts":     "TxGEqnHWrfWFTfGW9XjX",  # Josh
}
DEFAULT_VOICE = "pNInz6obpgDQGcFmaJgB"

# edge-tts fallback voices (same account mapping, free, no API key)
EDGETTS_VOICES = {
    "factsflash":      "en-US-GuyNeural",       # confident American male
    "techmindblown":   "en-US-EricNeural",      # deep, authoritative
    "coresteelfitness":"en-US-AndrewNeural",    # energetic
    "cricketcuts":     "en-GB-RyanNeural",      # British sports style
}
DEFAULT_EDGE_VOICE = "en-US-GuyNeural"

WORDS_PER_LINE = 2

import shutil as _sh
FFPROBE_BIN = _sh.which("ffprobe") or "ffprobe"


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


def _write_srt(text: str, mp3_path: str) -> str:
    total_ms     = _get_duration_ms(mp3_path)
    word_timings = _estimate_word_timings(text, total_ms)
    srt_content  = _words_to_srt(word_timings)
    with open(SRT_PATH, "w", encoding="utf-8") as f:
        f.write(srt_content)
    n_blocks = len([l for l in srt_content.strip().split("\n\n") if l])
    print(f"  [OK] Captions: {SRT_PATH} ({len(word_timings)} words, {n_blocks} blocks)", flush=True)
    return SRT_PATH


def _edge_tts_fallback(text: str, account: str = "") -> dict:
    """Generate voiceover using edge-tts (free, no API key needed)."""
    import edge_tts
    voice = EDGETTS_VOICES.get(account, DEFAULT_EDGE_VOICE)
    print(f"  [fallback] Using edge-tts voice: {voice}", flush=True)

    os.makedirs(TMP, exist_ok=True)

    async def _speak():
        comm = edge_tts.Communicate(text, voice)
        await comm.save(MP3_PATH)

    asyncio.run(_speak())
    size_kb = os.path.getsize(MP3_PATH) // 1024
    print(f"  [OK] MP3: {MP3_PATH} ({size_kb}KB) via edge-tts", flush=True)

    srt = _write_srt(text, MP3_PATH)
    total_ms = _get_duration_ms(MP3_PATH)
    return {
        "file":             MP3_PATH,
        "srt":              srt,
        "word_count":       len(text.split()),
        "duration_seconds": round(total_ms / 1000, 2),
        "voice_id":         voice,
        "tts_engine":       "edge-tts",
    }


def generate_elevenlabs_tts(text: str, voice_id: str = DEFAULT_VOICE,
                             account: str = "") -> dict:
    os.makedirs(TMP, exist_ok=True)

    # Try ElevenLabs first
    if ELEVENLABS_API_KEY:
        print(f"Generating voiceover with ElevenLabs (voice: {voice_id})...", flush=True)
        url     = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
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

        if resp.ok:
            with open(MP3_PATH, "wb") as f:
                f.write(resp.content)
            print(f"  [OK] MP3: {MP3_PATH} ({len(resp.content)//1024}KB)", flush=True)
            srt = _write_srt(text, MP3_PATH)
            total_ms = _get_duration_ms(MP3_PATH)
            return {
                "file":             MP3_PATH,
                "srt":              srt,
                "word_count":       len(text.split()),
                "duration_seconds": round(total_ms / 1000, 2),
                "voice_id":         voice_id,
                "tts_engine":       "elevenlabs",
            }

        # 401/403 = key issue → fall through to edge-tts
        print(f"  [WARN] ElevenLabs error {resp.status_code}: {resp.text[:200]}", flush=True)
        print(f"  [INFO] Falling back to edge-tts...", flush=True)
    else:
        print(f"  [INFO] No ELEVENLABS_API_KEY — using edge-tts fallback...", flush=True)

    return _edge_tts_fallback(text, account)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice_id", default=None,  help="ElevenLabs voice ID")
    parser.add_argument("--text",     default=None,  help="Text to speak (reads script.json if omitted)")
    parser.add_argument("--account",  default=None,  help="Account name to pick voice automatically")
    args = parser.parse_args()

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

    voice_id = args.voice_id
    if not voice_id and args.account:
        voice_id = ACCOUNT_VOICES.get(args.account, DEFAULT_VOICE)
        print(f"  Voice for [{args.account}]: {voice_id}", flush=True)
    if not voice_id:
        voice_id = DEFAULT_VOICE

    result = generate_elevenlabs_tts(text, voice_id, account=args.account or "")
    print(json.dumps(result, indent=2))
