"""
generate_discipline_quote.py
Quote Engine for DisciplineFuel.
Generates 5 quote variations using Viral Framework + Hook System + Save Optimization.

LLM priority: Gemini 2.0 Flash → OpenRouter (free) → Groq → Kimi K2

Usage: python tools/generate_discipline_quote.py "topic here"
Output: Full JSON payload for one post
"""

import json
import os
import re
import sys
import random
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
KIMI_API_KEY      = os.getenv("KIMI_API_KEY")

GEMINI_MODELS     = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash-latest"]
OPENROUTER_MODEL  = "anthropic/claude-3-5-haiku"
GROQ_MODEL        = "llama-3.3-70b-versatile"
KIMI_MODEL        = "moonshotai/kimi-k2-instruct"

OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
KIMI_BASE_URL     = "https://integrate.api.nvidia.com/v1"
GROQ_BASE_URL     = "https://api.groq.com/openai/v1"

BEST_POSTING_TIMES = ["06:00", "08:00", "12:00", "17:00", "20:00", "22:00"]

# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the content brain behind DisciplineFuel — a dark, raw, viral Instagram motivation page.
Your audience: 16-30 year olds who secretly know they're slacking. They struggle with procrastination, laziness, distraction. They want success, money, focus, and respect.

VIRAL FRAMEWORK (mandatory for every quote):
- Structure: Pain → Reality → Solution (discipline always wins over motivation)
- Make it relatable: name the EXACT specific struggle they're hiding — not vague, not generic
- Add scarcity: time is running out, others are moving while they scroll
- Discipline > Motivation. Always.

HOOK SYSTEM (first line of every quote MUST):
- Stop the scroll in under 2 seconds
- Trigger exactly ONE emotion: fear, guilt, ambition, or pride
- Create a curiosity gap OR make them feel caught/exposed
- Use these proven hook patterns:
  "You're not lazy. You're scared."
  "Nobody is coming to save you."
  "Your future self is watching right now."
  "Stop pretending you don't know what to do."
  "Every scroll is a vote against your future."
  "You already know. You just won't act."

SAVE OPTIMIZATION (mandatory):
- Every quote must be worth bookmarking and re-reading
- Caption must include exactly one of: "Save this." / "Read this daily." / "Screenshot this."
- Content must feel re-readable — timeless, not one-time-use

TONE:
- Raw and real. No corporate language. No fluff.
- Short sentences. Fragments are power. Max 10 words per sentence.
- Second person only: you / your / you're
- Sound like a real person who's lived it, not a motivational poster

NEVER WRITE THESE (banned — too generic, will not stop scroll):
- "Grind now, rest later."
- "Are you serious?"
- "Work hard every day."
- "Success is a choice."
- "Keep going, don't stop."
- "Hustle harder."
- "You got this."
- "Be the best version of yourself."
- Any quote under 20 words that doesn't name a SPECIFIC struggle.
These are clichés. They get scrolled past. Every quote must feel original, personal, and uncomfortably specific.

EXAMPLE GREAT QUOTES (match this quality and depth):
- "You said 'I'll start Monday' last Monday. And the Monday before that. The version of you that keeps delaying is winning right now. Stop letting him."
- "Your phone knows more about you than your gym does. That's not a flex. That's the problem."
- "Everyone who has what you want woke up when they didn't feel like it. You're still deciding whether to try."
- "The comfort you're protecting right now is the exact reason you're not where you want to be. Comfort doesn't build anything."
- "You're not overwhelmed. You're avoiding the one thing that would actually move your life forward. You know what it is.\""""

# ── Quote generation prompt ────────────────────────────────────────────────────

QUOTE_PROMPT = """Topic: {topic}
Series: {series_label}
Design style: {design_style}
Hot keywords to weave in (use 1-2): {hot_keywords}
Performance hints: {prompt_hints}

Generate 5 quote variations for this topic. Each must be 2-4 sentences, 30-60 words. Be specific, personal, uncomfortable — name the exact pain. No clichés, no generic phrases.

Variation types (in order):
1. COMMAND — direct order, imperative, no softening
2. QUESTION — rhetorical, exposes the reader, makes them feel caught
3. CONTRAST — juxtaposition (they do X, you do Y / comfort vs discipline)
4. PAIN_DRIVEN — names the exact hurt, the cost, what they're losing
5. IDENTITY — attacks or upgrades self-image ("A disciplined person would never...")

Then select the single best quote (most likely to stop scrolling + get saved).

Return ONLY this JSON (no markdown, no explanation):
{{
  "quote_options": [
    {{"type": "command", "text": "..."}},
    {{"type": "question", "text": "..."}},
    {{"type": "contrast", "text": "..."}},
    {{"type": "pain_driven", "text": "..."}},
    {{"type": "identity", "text": "..."}}
  ],
  "selected_quote": "...",
  "selected_type": "command|question|contrast|pain_driven|identity",
  "hook_keyword": "single word that makes the hook land (e.g. scared, clock, broke)",
  "format": "image or carousel",
  "design_style": "{design_style}",
  "image_prompt": "detailed prompt for dark aesthetic image generation, no text in image, cinematic, moody",
  "predicted_performance": "high|medium|low",
  "reasoning": "one sentence on why this quote will perform"
}}"""

CAPTION_PROMPT = """Write an Instagram caption for this DisciplineFuel post.

Quote: {quote}
Series: {series_label}
Topic: {topic}

Rules:
- Line 1: punchy hook (same energy as the quote, different words)
- Line 2: blank line
- Line 3: 1-2 sentence insight (raw, no fluff)
- Line 4: blank line
- Line 5: ONE of these CTAs: "Save this." / "Read this daily." / "Screenshot this."
- Line 6: blank line
- Line 7: Follow @DisciplineFuel for daily truth.
- Line 8: blank line
- Line 9: hashtags (15 total on one line)

Return only the caption text, no JSON."""

HASHTAG_PROMPT = """Generate exactly 15 Instagram hashtags for a DisciplineFuel post.
Topic: {topic}
Keywords: {hot_keywords}

Split into 3 groups:
- 5 trending (high volume, currently hot in motivation niche)
- 5 niche (specific to discipline/self-improvement community)
- 5 broad (general reach)

Return as a single JSON array of 15 strings, no # symbol, no explanation."""


# ── LLM calls ─────────────────────────────────────────────────────────────────

def _gemini_call(system: str, prompt: str, temperature: float = 0.9) -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    last_err = None
    for model in GEMINI_MODELS:
        try:
            print(f"  [Gemini] trying {model}...", flush=True)
            response = client.models.generate_content(
                model=model,
                contents=system + "\n\n" + prompt,
                config={"temperature": temperature, "max_output_tokens": 1000}
            )
            return response.text.strip()
        except Exception as e:
            last_err = e
            print(f"  [Gemini/{model}] failed: {str(e)[:80]}", flush=True)
    raise last_err


def _openrouter_call(system: str, prompt: str, temperature: float = 0.9) -> str:
    import requests as _req
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/mdgufran0949-ux/discipline-bot",
        "X-Title": "DisciplineFuel"
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": 1000,
    }
    resp = _req.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _groq_call(system: str, prompt: str, temperature: float = 0.9) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=temperature,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


def _kimi_call(system: str, prompt: str, temperature: float = 0.88) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    response = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=temperature,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


def _call(prompt: str, system: str = None, temperature: float = 0.9, fast: bool = False) -> str:
    """
    LLM dispatch: OpenRouter (Claude Haiku, primary) → Groq → Gemini → Kimi.
    fast=True uses Groq first (cheaper/faster for carousel extra slides).
    """
    sys_prompt = system or SYSTEM_PROMPT
    errors = []

    if fast and GROQ_API_KEY:
        try:
            return _groq_call(sys_prompt, prompt, temperature)
        except Exception as e:
            errors.append(f"Groq: {e}")

    # Primary: OpenRouter with Claude Haiku (paid, best quality)
    if OPENROUTER_API_KEY:
        try:
            print(f"  [OpenRouter/Claude Haiku]...", flush=True)
            return _openrouter_call(sys_prompt, prompt, temperature)
        except Exception as e:
            errors.append(f"OpenRouter: {e}")
            print(f"  [OpenRouter failed: {str(e)[:80]}] trying Groq...", flush=True)

    if GROQ_API_KEY:
        try:
            return _groq_call(sys_prompt, prompt, temperature)
        except Exception as e:
            errors.append(f"Groq: {e}")
            print(f"  [Groq failed] trying Gemini...", flush=True)

    if GEMINI_API_KEY:
        try:
            return _gemini_call(sys_prompt, prompt, temperature)
        except Exception as e:
            errors.append(f"Gemini: {e}")
            print(f"  [Gemini failed] trying Kimi...", flush=True)

    if KIMI_API_KEY:
        return _kimi_call(sys_prompt, prompt, temperature)

    raise ValueError(f"All LLMs failed: {'; '.join(errors)}")


def _extract_json(raw: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences."""
    raw = raw.strip()
    # Remove ```json ... ``` fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _series_label(series_type: str, series_number: int) -> str:
    labels = {
        "discipline_rule":      f"Discipline Rule #{series_number}",
        "wake_up_call":         f"Wake Up Call #{series_number}",
        "day_becoming_better":  f"Day {series_number} of Becoming Better"
    }
    return labels.get(series_type, f"#{series_number}")


# ── Main function ──────────────────────────────────────────────────────────────

def generate_discipline_quote(
    topic: str,
    series_type: str = "discipline_rule",
    series_number: int = 1,
    design_style: str = "dark",
    hot_keywords: list = None,
    prompt_hints: dict = None
) -> dict:
    """
    Generate a full DisciplineFuel content payload.
    Returns the JSON spec required by run_discipline_pipeline.py
    """
    series_label  = _series_label(series_type, series_number)
    hot_kw_str    = ", ".join(hot_keywords[:5]) if hot_keywords else "discipline, scared, comfort, clock, broke"
    hints_str     = ""
    if prompt_hints:
        if prompt_hints.get("best_hooks"):
            hints_str += f"Best performing hooks: {', '.join(prompt_hints['best_hooks'][:3])}. "
        if prompt_hints.get("best_quote_types"):
            hints_str += f"Best performing types: {', '.join(prompt_hints['best_quote_types'][:2])}."
    if not hints_str:
        hints_str = "No performance data yet. Experiment freely."

    # Step 1: Generate quote options
    print(f"Generating quotes for: {topic}", flush=True)
    quote_prompt = QUOTE_PROMPT.format(
        topic=topic,
        series_label=series_label,
        design_style=design_style,
        hot_keywords=hot_kw_str,
        prompt_hints=hints_str
    )

    raw_quote = _call(quote_prompt)
    try:
        quote_data = _extract_json(raw_quote)
    except Exception as e:
        print(f"  [WARN] JSON parse failed: {e}. Retrying...", flush=True)
        raw_quote  = _call(quote_prompt, temperature=0.7)
        quote_data = _extract_json(raw_quote)

    selected_quote = quote_data.get("selected_quote", "")
    selected_type  = quote_data.get("selected_type", "contrast")

    # Quality gate — reject generic/short quotes and retry once
    BANNED_PHRASES = ["grind now", "are you serious", "work hard every day",
                      "success is a choice", "keep going", "hustle harder",
                      "you got this", "best version", "never give up"]
    quote_words = len(selected_quote.split())
    is_generic  = any(b in selected_quote.lower() for b in BANNED_PHRASES)
    if quote_words < 20 or is_generic:
        print(f"  [WARN] Quote too short or generic ({quote_words} words). Retrying...", flush=True)
        retry_prompt = quote_prompt + "\n\nIMPORTANT: The previous attempt was too short or too generic. Write longer, more specific, more personal quotes — 30-60 words each. Name the exact pain."
        raw_quote2 = _call(retry_prompt, temperature=0.95)
        try:
            quote_data2 = _extract_json(raw_quote2)
            if len(quote_data2.get("selected_quote", "").split()) >= 20:
                quote_data    = quote_data2
                selected_quote = quote_data.get("selected_quote", selected_quote)
                selected_type  = quote_data.get("selected_type", selected_type)
        except Exception:
            pass  # Keep original if retry fails

    # Step 2: Generate caption
    print("Generating caption...", flush=True)
    caption_raw = _call(
        CAPTION_PROMPT.format(
            quote=selected_quote,
            series_label=series_label,
            topic=topic
        ),
        temperature=0.75
    )

    # Step 3: Generate hashtags
    print("Generating hashtags...", flush=True)
    hashtag_raw = _call(
        HASHTAG_PROMPT.format(topic=topic, hot_keywords=hot_kw_str),
        temperature=0.5
    )
    try:
        hashtags = _extract_json(hashtag_raw) if hashtag_raw.strip().startswith("[") else json.loads(hashtag_raw)
        if not isinstance(hashtags, list):
            hashtags = list(hashtags.values())[:15]
    except Exception:
        hashtags = ["discipline", "focus", "grind", "sacrifice", "success",
                    "selfimprovement", "hardwork", "mentalstrength", "accountability",
                    "growthmindset", "motivation", "winning", "levelup", "noexcuses", "hustle"]

    # Inject save CTA into caption if missing
    cta_phrases = ["Save this.", "Read this daily.", "Screenshot this."]
    if not any(cta.lower() in caption_raw.lower() for cta in cta_phrases):
        caption_raw = caption_raw.rstrip() + "\n\nSave this."

    # Determine best posting time
    best_time = random.choice(BEST_POSTING_TIMES)

    return {
        "quote_options":   [{"type": q["type"], "text": q["text"]}
                            for q in quote_data.get("quote_options", [])],
        "selected_quote":  selected_quote,
        "selected_type":   selected_type,
        "hook_keyword":    quote_data.get("hook_keyword", ""),
        "format":          quote_data.get("format", "image"),
        "design_style":    design_style,
        "caption":         caption_raw.strip(),
        "hashtags":        hashtags[:15],
        "image_prompt":    quote_data.get("image_prompt", f"dark cinematic moody {design_style} aesthetic"),
        "tool_recommendation": {
            "design_tool": "Canva",
            "reason": "Pre-made DisciplineFuel templates with consistent branding and typography"
        },
        "best_time":       best_time,
        "content_series":  series_label,
        "series_type":     series_type,
        "series_number":   series_number,
        "topic":           topic,
        "predicted_performance": quote_data.get("predicted_performance", "medium"),
        "reasoning":       quote_data.get("reasoning", "")
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/generate_discipline_quote.py "topic here"')
        sys.exit(1)
    topic  = " ".join(sys.argv[1:])
    result = generate_discipline_quote(topic)
    print(json.dumps(result, indent=2))
