"""
kids_safety_check.py
AI-powered safety gate for kids animation scripts (ages 3-10).
Reviews script text for child-appropriateness before spending API credits on visuals.

Uses Gemini 2.0 Flash via REST (GEMINI_API_KEY in .env).
Fails open: if Gemini is unavailable, returns PASS with confidence 0.0.

Usage: python tools/kids_safety_check.py script.json
Output: JSON with result (PASS/FAIL), flags, confidence.
"""

import os
import sys
import json
import requests
import argparse
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-2.0-flash:generateContent"
)

SAFETY_PROMPT = """You are a content safety reviewer for a children's YouTube channel targeting ages 3-10.
Review the following script for a kids animation video.

Flag any of these issues:
- violence or threat of violence (even cartoon-style if explicit)
- scary or frightening content (death, monsters, darkness themes, nightmares)
- adult themes (romance, money stress, illness, war, politics)
- brand names or product mentions (fast food chains, tech brands, etc.)
- political content or controversial social topics
- body shaming or negative body image
- any content inappropriate for children under 10
- negative emotions that are not resolved (sadness, fear without comfort)

Return ONLY valid JSON with no markdown:
{
  "result": "PASS" or "FAIL",
  "flags": ["list of specific issues if FAIL, empty array if PASS"],
  "confidence": 0.0 to 1.0,
  "reviewed_word_count": integer
}"""


def _extract_text(script: dict) -> str:
    """Extract all spoken/narrated text from script for review."""
    parts = []

    narration = script.get("narration", "")
    if narration:
        parts.append(f"NARRATION: {narration}")

    for scene in script.get("scenes", []):
        dialogue = scene.get("dialogue", "")
        narr     = scene.get("narration", "")
        if dialogue:
            parts.append(f"DIALOGUE: {dialogue}")
        if narr:
            parts.append(f"SCENE NARRATION: {narr}")

    return "\n".join(parts)


def kids_safety_check(script: dict) -> dict:
    """
    Run safety check on a kids script.

    Args:
        script: Full script dict from generate_kids_script.py

    Returns:
        {result: "PASS"|"FAIL", flags: [], confidence: float, reviewed_word_count: int}
    """
    text = _extract_text(script)
    word_count = len(text.split())

    if not GEMINI_API_KEY:
        print("  [WARN] GEMINI_API_KEY not set — safety check skipped (fail open)", flush=True)
        return {
            "result": "PASS",
            "flags": [],
            "confidence": 0.0,
            "reviewed_word_count": word_count,
            "error": "gemini_key_missing"
        }

    payload = {
        "contents": [{
            "parts": [
                {"text": SAFETY_PROMPT},
                {"text": f"\n\nSCRIPT TO REVIEW:\n{text}"}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 300
        }
    }

    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Strip markdown fences if present
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        result = json.loads(raw)
        result["reviewed_word_count"] = word_count
        return result

    except Exception as e:
        print(f"  [WARN] Safety check Gemini call failed: {e} — failing open", flush=True)
        return {
            "result": "PASS",
            "flags": [],
            "confidence": 0.0,
            "reviewed_word_count": word_count,
            "error": str(e)
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kids script safety checker")
    parser.add_argument("script", help="Path to script JSON file")
    args = parser.parse_args()

    with open(args.script, "r", encoding="utf-8") as f:
        script = json.load(f)

    result = kids_safety_check(script)
    print(json.dumps(result, indent=2))

    if result["result"] == "FAIL":
        print(f"\n[FAIL] Safety check failed: {result['flags']}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n[PASS] Safety check passed (confidence: {result['confidence']})", flush=True)
