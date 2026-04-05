"""
generate_motivation_script.py
Generates a viral motivational Instagram Reels script using Google Gemini API.
Primary: Gemini 2.0 Flash (GEMINI_API_KEY)
Fallback: Kimi K2 via NVIDIA API (KIMI_API_KEY)
Usage: python tools/generate_motivation_script.py "topic here"
Output: JSON with narration (75-90 words) + caption
"""

import json, os, re, sys
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KIMI_API_KEY   = os.getenv("KIMI_API_KEY")
GEMINI_MODELS  = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash-latest"]
KIMI_MODEL     = "moonshotai/kimi-k2-instruct"
KIMI_BASE_URL  = "https://integrate.api.nvidia.com/v1"

CHARACTER_SYSTEM = """You are ALEX — a brutal, zero-excuse motivational voice for Instagram Reels.
You speak like the sharpest David Goggins clips: short, visceral, surgical.
Every sentence lands like a slap of truth.

STRICT RULES:
- Never say: grind, hustle, journey, believe in yourself, mindset shift, wake up call
- Max 10 words per sentence. Fragments are powerful. Use them.
- Second person ONLY: you / your / you're
- Power vocabulary: soft, dead, buried, lying, comfortable, weak, real, quit, clock, mirror, chosen, accountable, terrified, grave, snooze, rot
- Every sentence must make the viewer feel seen or exposed"""

NARRATION_PROMPT = """Topic: {topic}

Write a punchy 25-30 second Instagram Reels voiceover. EXACTLY 75-90 words. Count every word.

STRUCTURE (no labels in output):
1. HOOK (10-15 words) — ONE of these patterns, adapted to topic:
   • "You've been lying to yourself every single morning."
   • "Nobody tells you the real reason you're failing."
   • "You're not stuck. You keep choosing comfort over everything."
   • "Most people quit right before everything changes."
   • "This is the thing killing your potential right now."

2. REALITY CHECK (3-4 punchy sentences, 25-30 words)
   — Name the exact behavior. Be specific. Be uncomfortable.

3. THE TRUTH (3-4 sentences, 25-30 words)
   — Raw insight. No advice. The thing they already know but avoid.
   — Add "..." after lines meant to land hard.

4. CLOSER (1 sentence, 8-12 words)
   — Screenshot-worthy. Quotable. Hits like a fact.

OUTPUT RULES:
- Write ONLY the spoken words. No labels, no intro, no hashtags, no emojis.
- No sentence over 10 words.
- Make it feel like the viewer is being caught in a lie."""

CAPTION_PROMPT = """Write an Instagram caption for this script:
"{narration}"

Format: 1 punchy hook sentence that creates curiosity + "Follow for daily mindset shifts." + 5-7 hashtags
Under 220 characters. Return only the caption text."""


def _gemini_call(prompt: str, temperature: float = 0.9) -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    last_err = None
    for model in GEMINI_MODELS:
        try:
            print(f"  Trying {model}...", flush=True)
            response = client.models.generate_content(
                model=model,
                contents=CHARACTER_SYSTEM + "\n\n" + prompt,
                config={"temperature": temperature, "max_output_tokens": 600}
            )
            return response.text.strip()
        except Exception as e:
            last_err = e
            print(f"  [{model}] failed: {str(e)[:80]}", flush=True)
    raise last_err


def _kimi_call(prompt: str, temperature: float = 0.88) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    response = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": CHARACTER_SYSTEM},
            {"role": "user",   "content": prompt}
        ],
        temperature=temperature,
        max_tokens=600,
    )
    return response.choices[0].message.content.strip()


def _call(prompt: str, temperature: float = 0.9) -> str:
    if GEMINI_API_KEY:
        try:
            return _gemini_call(prompt, temperature)
        except Exception as e:
            print(f"  [Gemini failed] falling back to Kimi K2: {str(e)[:60]}", flush=True)
    if KIMI_API_KEY:
        return _kimi_call(prompt, temperature)
    raise ValueError("No API key available. Set GEMINI_API_KEY or KIMI_API_KEY in .env")


def generate_motivation_script(topic: str, min_words: int = 65, max_retries: int = 3) -> dict:
    api = "Gemini" if GEMINI_API_KEY else "Kimi K2"
    print(f"  Using: {api}", flush=True)

    narration = ""
    for attempt in range(1, max_retries + 1):
        raw = _call(NARRATION_PROMPT.format(topic=topic))
        raw = raw.replace('"', '').replace('"', '').replace('"', '').strip()
        # Remove any label lines the model might add
        lines = [l for l in raw.splitlines() if not re.match(r'^(HOOK|REALITY|TRUTH|CLOSER|STRUCTURE):', l.strip(), re.I)]
        raw = " ".join(" ".join(lines).split())
        word_count = len(raw.split())
        print(f"  [attempt {attempt}] word count: {word_count}", flush=True)
        if word_count >= min_words:
            narration = raw
            break
        print(f"  Too short, retrying...", flush=True)

    if not narration:
        narration = raw

    caption = _call(CAPTION_PROMPT.format(narration=narration), temperature=0.7)
    caption = caption.replace('"', '').replace('"', '').strip()

    return {
        "narration":  narration,
        "caption":    caption,
        "topic":      topic,
        "word_count": len(narration.split()),
        "model":      GEMINI_MODELS[0] if GEMINI_API_KEY else KIMI_MODEL
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/generate_motivation_script.py "topic here"')
        sys.exit(1)
    topic  = " ".join(sys.argv[1:])
    result = generate_motivation_script(topic)
    print(json.dumps(result, indent=2))
