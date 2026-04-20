"""
generate_discipline_bgm.py
20-second dark ambient BGM for DisciplineFuel reels.
A minor pentatonic, 75 BPM, sparse sustained notes. No API, no credits.

Output: .tmp/disciplinefuel/bgm.mp3  (cached — only regenerates if missing or >7 days old)
Usage:  python tools/generate_discipline_bgm.py
"""

import math
import os
import shutil
import struct
import subprocess
import wave

TOOLS_DIR  = os.path.dirname(os.path.abspath(__file__))
TMP_BASE   = os.path.abspath(os.path.join(TOOLS_DIR, "..", ".tmp", "disciplinefuel"))

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

SAMPLE_RATE = 44100
BPM         = 75
DURATION_S  = 20

# A minor pentatonic: A C D E G
NOTES = {
    "A1": 55.00,
    "A2": 110.00, "C3": 130.81, "D3": 146.83, "E3": 164.81, "G3": 196.00,
    "A3": 220.00,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "G4": 392.00, "A4": 440.00,
    "C5": 523.25, "E5": 659.25,
    "R":  0.0,
}

# Sparse ambient melody — long sustained notes, dark and reflective
# At 75 BPM: 1 beat = 0.8s, 4 beats = 3.2s
MELODY = [
    ("A4", 4), ("G4", 2), ("E4", 2),
    ("D4", 3), ("R",  1), ("C4", 2), ("A3", 2),
    ("E4", 4), ("G4", 2), ("A4", 2),
    ("D4", 3), ("C4", 1), ("A3", 4),
]  # 32 beats = 25.6s — trimmed to DURATION_S

# Slow bass pedal — root-fifth movement
BASS = [
    "A2", "A2", "A2", "A2",
    "E3", "E3", "A2", "A2",
    "A2", "A2", "E3", "E3",
    "D3", "D3", "A2", "A2",
]  # 16 beats, repeats


def _sine_wave(freq, duration_samples, amplitude, harmonics=None):
    if freq == 0:
        return [0.0] * duration_samples
    if harmonics is None:
        harmonics = [(1, 1.0), (2, 0.15), (3, 0.05)]
    samples = []
    for i in range(duration_samples):
        t = i / SAMPLE_RATE
        v = sum(amp * math.sin(2 * math.pi * freq * h * t) for h, amp in harmonics)
        samples.append(v * amplitude)
    return samples


def _apply_envelope(samples, attack=0.1, decay=0.05, sustain=0.82, release=0.2):
    n = len(samples)
    atk_s = max(1, int(attack  * SAMPLE_RATE))
    dec_s = max(1, int(decay   * SAMPLE_RATE))
    rel_s = max(1, int(release * SAMPLE_RATE))
    sus_s = max(0, n - atk_s - dec_s - rel_s)
    env = []
    for i in range(n):
        if i < atk_s:
            env.append(i / atk_s)
        elif i < atk_s + dec_s:
            env.append(1.0 - (1.0 - sustain) * (i - atk_s) / dec_s)
        elif i < atk_s + dec_s + sus_s:
            env.append(sustain)
        else:
            env.append(sustain * (1.0 - (i - atk_s - dec_s - sus_s) / rel_s))
    return [s * e for s, e in zip(samples, env)]


def _generate_track():
    beat_s   = int(SAMPLE_RATE * 60 / BPM)
    total_s  = SAMPLE_RATE * DURATION_S
    left_ch  = [0.0] * total_s
    right_ch = [0.0] * total_s

    def mix(ch, start, samples, gain=1.0):
        for i, s in enumerate(samples):
            idx = start + i
            if 0 <= idx < total_s:
                ch[idx] += s * gain

    # Sustained sub-drone (A1) — atmospheric pad
    drone = _sine_wave(NOTES["A1"], total_s, 0.07, [(1, 1.0), (2, 0.18)])
    fade_in = int(SAMPLE_RATE * 3.0)
    for i in range(min(fade_in, total_s)):
        drone[i] *= i / fade_in
    mix(left_ch,  0, drone)
    mix(right_ch, 0, drone)

    # Melody — sparse long notes, slight build over first 40% of track
    pos = 0
    for _ in range(4):
        for note, beats in MELODY:
            if pos >= total_s:
                break
            dur = beat_s * beats
            raw = _sine_wave(NOTES[note], dur, 0.22, [(1, 1.0), (2, 0.10), (4, 0.03)])
            env = _apply_envelope(raw, attack=0.10, decay=0.05, sustain=0.78, release=0.18)
            progress = pos / total_s
            build   = 0.55 + 0.45 * min(progress * 2.5, 1.0)  # 0.55 → 1.0 over first 40%
            mix(right_ch, pos, env, 0.90 * build)
            mix(left_ch,  pos, env, 0.70 * build)
            pos += dur

    # Bass pedal — root-fifth movement, one note per beat
    pos = 0
    for _ in range(6):
        for note in BASS:
            if pos >= total_s:
                break
            raw = _sine_wave(NOTES[note], beat_s, 0.20, [(1, 1.0), (2, 0.30), (3, 0.08)])
            env = _apply_envelope(raw, attack=0.05, decay=0.05, sustain=0.80, release=0.12)
            mix(left_ch,  pos, env, 0.85)
            mix(right_ch, pos, env, 0.62)
            pos += beat_s

    # Fade in / fade out
    fade_in_s  = int(SAMPLE_RATE * 1.5)
    fade_out_s = int(SAMPLE_RATE * 2.0)
    for i in range(fade_in_s):
        g = i / fade_in_s
        left_ch[i]  *= g
        right_ch[i] *= g
    for i in range(fade_out_s):
        g = 1.0 - i / fade_out_s
        left_ch[total_s - 1 - i]  *= g
        right_ch[total_s - 1 - i] *= g

    combined = []
    for l, r in zip(left_ch, right_ch):
        combined.append(max(-1.0, min(1.0, l)))
        combined.append(max(-1.0, min(1.0, r)))
    return combined


def _save_wav(samples, path):
    with wave.open(path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        packed = struct.pack(f"<{len(samples)}h", *[int(s * 32767) for s in samples])
        wf.writeframes(packed)


def generate_bgm(output_path=None):
    os.makedirs(TMP_BASE, exist_ok=True)
    out_mp3 = output_path or os.path.join(TMP_BASE, "bgm.mp3")
    out_wav = out_mp3.replace(".mp3", "_tmp.wav")

    print("Generating discipline BGM...", flush=True)
    samples = _generate_track()
    _save_wav(samples, out_wav)
    print(f"  [OK] WAV: {DURATION_S}s stereo 44100Hz", flush=True)

    result = subprocess.run(
        [FFMPEG, "-y", "-i", out_wav, "-codec:a", "libmp3lame", "-b:a", "128k", out_mp3],
        capture_output=True
    )
    os.remove(out_wav)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg WAV→MP3 failed: {result.stderr.decode()[-500:]}")

    print(f"  [OK] BGM saved: {out_mp3}", flush=True)
    return out_mp3


if __name__ == "__main__":
    path = generate_bgm()
    print(f"Done: {path}")
