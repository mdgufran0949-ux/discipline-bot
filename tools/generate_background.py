"""
generate_background.py
Generates a cinematic animated background video using ffmpeg (no API needed).
Usage: python tools/generate_background.py [duration_seconds]
Output: .tmp/background.mp4 (1080x1920 portrait)
"""

import json
import sys
import os
import subprocess

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "background.mp4")
import shutil as _sh; FFMPEG = _sh.which("ffmpeg") or "ffmpeg"

def generate_background(duration: float = 12.0, style: str = "dark_gradient") -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
    abs_path = os.path.abspath(OUTPUT_PATH)

    # Animated dark gradient background using ffmpeg lavfi
    # Uses sine wave color cycling for a cinematic pulsing effect
    vf = (
        "gradients=size=1080x1920:rate=30:type=radial:"
        "c0=0x0f0c29:c1=0x302b63:c2=0x24243e:x0=540:y0=960:r0=0:r1=1400,"
        "hue=h='sin(t*0.5)*20':s=1.2"
    )

    # Fallback: simpler solid dark blue if gradients not supported
    fallback_vf = "color=size=1080x1920:rate=30:color=0x0f0c29"

    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"color=size=1080x1920:rate=30:color=0x0f0c29,format=yuv420p",
        "-t", str(duration),
        "-vf", (
            "geq="
            "r='128+80*sin(2*PI*T/4)*sin(PI*X/1080)':"
            "g='20+30*sin(2*PI*T/6)':"
            "b='128+100*cos(2*PI*T/5)*cos(PI*Y/1920)',"
            "format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        abs_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg background error:\n{result.stderr[-500:]}")

    return {"file": abs_path, "duration_seconds": duration, "resolution": "1080x1920"}

if __name__ == "__main__":
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    result = generate_background(duration)
    print(json.dumps(result, indent=2))
