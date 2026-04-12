"""
generate_kids_bg_music.py
Generates a cheerful kids background music track using Python (no API, no credits).
Uses sine wave synthesis with pentatonic scale melody + simple percussion.

Output: .tmp/kids_bg_music.mp3 (60s loopable, stereo, 44100 Hz)
Usage:  python tools/generate_kids_bg_music.py
"""

import os
import math
import wave
import struct
import subprocess
import sys

TMP        = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
OUTPUT_WAV = os.path.join(TMP, "kids_bg_music.wav")
OUTPUT_MP3 = os.path.join(TMP, "kids_bg_music.mp3")

FFMPEG_BIN = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
FFMPEG     = os.path.join(FFMPEG_BIN, "ffmpeg.exe")

SAMPLE_RATE = 44100
BPM         = 108          # Upbeat tempo for kids
DURATION_S  = 64           # Slightly over 1 min so it loops cleanly

# Pentatonic major scale — C D E G A (happy, simple, no dissonance)
NOTES = {
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "G3": 196.00, "A3": 220.00,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "G4": 392.00, "A4": 440.00,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A5": 880.00,
    "R":  0.0,    # rest
}

# Melody (note, beats) — 4/4 time, 4 bars that loop
MELODY = [
    ("C5", 1), ("E5", 1), ("G5", 1), ("A5", 1),
    ("G5", 2), ("E5", 1), ("C5", 1),
    ("D5", 1), ("E5", 1), ("G5", 1), ("E5", 1),
    ("C5", 2), ("R",  2),

    ("A4", 1), ("C5", 1), ("E5", 1), ("G5", 1),
    ("E5", 2), ("C5", 1), ("A4", 1),
    ("G4", 1), ("A4", 1), ("C5", 1), ("A4", 1),
    ("G4", 2), ("R",  2),

    ("C5", 1), ("G4", 1), ("E4", 1), ("G4", 1),
    ("A4", 2), ("G4", 2),
    ("E4", 1), ("G4", 1), ("A4", 1), ("C5", 1),
    ("G4", 2), ("E4", 2),

    ("D5", 1), ("C5", 1), ("A4", 1), ("G4", 1),
    ("E5", 2), ("C5", 2),
    ("D5", 1), ("E5", 1), ("G5", 1), ("A5", 1),
    ("G5", 4),
]

# Bass line (root notes, 1 per beat)
BASS = [
    "C3", "C3", "C3", "C3",
    "G3", "G3", "C3", "C3",
    "D3", "D3", "C3", "C3",
    "C3", "C3", "C3", "C3",

    "A3", "A3", "A3", "A3",
    "E3", "E3", "A3", "A3",
    "G3", "G3", "E3", "E3",
    "G3", "G3", "G3", "G3",

    "C3", "C3", "G3", "G3",
    "A3", "A3", "G3", "G3",
    "E3", "E3", "G3", "G3",
    "G3", "G3", "E3", "E3",

    "D3", "D3", "A3", "A3",
    "C4", "C4", "C4", "C4",
    "D3", "D3", "G3", "G3",
    "G3", "G3", "G3", "G3",
]


def sine_wave(freq: float, duration_samples: int, amplitude: float,
              harmonics: list = None) -> list:
    """Generate a sine wave with optional harmonics for richer sound."""
    if freq == 0:
        return [0.0] * duration_samples
    if harmonics is None:
        harmonics = [(1, 1.0), (2, 0.3), (3, 0.1)]
    samples = []
    for i in range(duration_samples):
        t = i / SAMPLE_RATE
        v = sum(amp * math.sin(2 * math.pi * freq * h * t)
                for h, amp in harmonics)
        samples.append(v * amplitude)
    return samples


def apply_envelope(samples: list, attack: float = 0.02,
                   decay: float = 0.05, sustain: float = 0.85,
                   release: float = 0.08) -> list:
    """ADSR envelope for natural note decay."""
    n = len(samples)
    atk_s  = int(attack  * SAMPLE_RATE)
    dec_s  = int(decay   * SAMPLE_RATE)
    rel_s  = int(release * SAMPLE_RATE)
    sus_s  = n - atk_s - dec_s - rel_s

    env = []
    for i in range(n):
        if i < atk_s:
            env.append(i / max(atk_s, 1))
        elif i < atk_s + dec_s:
            env.append(1.0 - (1.0 - sustain) * (i - atk_s) / max(dec_s, 1))
        elif i < atk_s + dec_s + sus_s:
            env.append(sustain)
        else:
            env.append(sustain * (1 - (i - atk_s - dec_s - sus_s) / max(rel_s, 1)))

    return [s * e for s, e in zip(samples, env)]


def percussion_hit(duration_samples: int, amplitude: float = 0.25) -> list:
    """Simple hi-hat click using filtered noise."""
    import random
    rng   = random.Random(42)
    decay = int(0.03 * SAMPLE_RATE)
    samps = []
    for i in range(min(decay, duration_samples)):
        noise = rng.uniform(-1, 1)
        env   = math.exp(-8 * i / decay)
        samps.append(noise * amplitude * env)
    samps += [0.0] * (duration_samples - len(samps))
    return samps


def kick_drum(duration_samples: int, amplitude: float = 0.4) -> list:
    """Simple kick drum using swept sine."""
    samps = []
    for i in range(duration_samples):
        t   = i / SAMPLE_RATE
        env = math.exp(-15 * t)
        freq = 100 * math.exp(-30 * t) + 40
        samps.append(amplitude * env * math.sin(2 * math.pi * freq * t))
    return samps


def generate_track() -> list:
    """Assemble full stereo track."""
    beat_s   = int(SAMPLE_RATE * 60 / BPM)   # samples per beat
    total_s  = SAMPLE_RATE * DURATION_S
    left_ch  = [0.0] * total_s
    right_ch = [0.0] * total_s

    def mix(channel, start, samples, pan=0.0):
        # pan: -1 = left, 0 = center, +1 = right
        gain = 1.0 - abs(pan) * 0.4
        for i, s in enumerate(samples):
            idx = start + i
            if 0 <= idx < total_s:
                channel[idx] += s * gain

    # ── Melody (right of center) ──
    pos = 0
    melody_pos = 0
    for rep in range(DURATION_S // (16 * 60 // BPM * 4) + 2):
        for (note, beats) in MELODY:
            if pos >= total_s:
                break
            freq      = NOTES[note]
            dur       = beat_s * beats
            raw       = sine_wave(freq, dur, 0.32, [(1, 1.0), (2, 0.25), (4, 0.08)])
            enveloped = apply_envelope(raw, 0.02, 0.08, 0.7, 0.1)
            mix(right_ch, pos, enveloped, pan=0.25)
            mix(left_ch,  pos, enveloped, pan=-0.1)
            pos += dur

    # ── Bass line (left of center) ──
    pos = 0
    bass_beat = 0
    for rep in range(DURATION_S // (16 * 60 // BPM) + 2):
        for note in BASS:
            if pos >= total_s:
                break
            freq      = NOTES[note]
            raw       = sine_wave(freq, beat_s, 0.28, [(1, 1.0), (2, 0.4), (3, 0.15)])
            enveloped = apply_envelope(raw, 0.01, 0.05, 0.8, 0.15)
            mix(left_ch,  pos, enveloped, pan=-0.3)
            mix(right_ch, pos, enveloped, pan=0.1)
            pos += beat_s

    # ── Percussion (center) ──
    pos = 0
    while pos < total_s:
        # Kick on beats 1 and 3
        for beat_offset in [0, 2 * beat_s]:
            kick_pos = pos + beat_offset
            k = kick_drum(beat_s // 2, 0.3)
            mix(left_ch,  kick_pos, k)
            mix(right_ch, kick_pos, k)
        # Hi-hat every beat
        for b in range(4):
            hat_pos = pos + b * beat_s
            h = percussion_hit(beat_s // 4, 0.12)
            mix(left_ch,  hat_pos, h)
            mix(right_ch, hat_pos, h)
        # Off-beat hi-hat
        for b in range(4):
            hat_pos = pos + b * beat_s + beat_s // 2
            h = percussion_hit(beat_s // 6, 0.07)
            mix(left_ch,  hat_pos, h)
            mix(right_ch, hat_pos, h)
        pos += 4 * beat_s

    # ── Fade in / fade out ──
    fade_s = int(SAMPLE_RATE * 2.0)
    for i in range(fade_s):
        g = i / fade_s
        left_ch[i]              *= g
        right_ch[i]             *= g
        left_ch[total_s-1-i]    *= g
        right_ch[total_s-1-i]   *= g

    # Interleave stereo
    combined = []
    for l, r in zip(left_ch, right_ch):
        combined.append(max(-1.0, min(1.0, l)))
        combined.append(max(-1.0, min(1.0, r)))

    return combined


def save_wav(samples: list, path: str) -> None:
    with wave.open(path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        packed = struct.pack(f"<{len(samples)}h",
                             *[int(s * 32767) for s in samples])
        wf.writeframes(packed)


def generate_kids_bg_music() -> str:
    os.makedirs(TMP, exist_ok=True)
    print("Generating background music...", flush=True)

    samples = generate_track()
    save_wav(samples, OUTPUT_WAV)
    print(f"  [OK] WAV generated ({DURATION_S}s, stereo, 44100Hz)", flush=True)

    # Convert to MP3
    subprocess.run([
        FFMPEG, "-y", "-i", OUTPUT_WAV,
        "-codec:a", "libmp3lame", "-b:a", "128k",
        OUTPUT_MP3
    ], capture_output=True)
    os.remove(OUTPUT_WAV)
    print(f"  [OK] Background music saved: {OUTPUT_MP3}", flush=True)
    return OUTPUT_MP3


if __name__ == "__main__":
    path = generate_kids_bg_music()
    print(f"Done: {path}")
