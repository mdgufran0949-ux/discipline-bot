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
OPENROUTER_MODEL  = "openai/gpt-4o-mini"
GROQ_MODEL        = "llama-3.3-70b-versatile"
KIMI_MODEL        = "moonshotai/kimi-k2-instruct"

OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
KIMI_BASE_URL     = "https://integrate.api.nvidia.com/v1"
GROQ_BASE_URL     = "https://api.groq.com/openai/v1"

BEST_POSTING_TIMES = ["06:00", "08:00", "12:00", "17:00", "20:00", "22:00"]

# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the content brain behind DisciplineFuel — a reflective, wise, save-worthy Instagram page about discipline, growth, and becoming better.
Your audience: 16-30 year olds who want to build discipline, focus, consistency, and a better life. They don't want to be attacked — they want to feel understood, nudged, and inspired.

VOICE — this is non-negotiable:
- Wise, reflective, observational. Like a mentor who has lived it, not a drill sergeant yelling at them.
- Universal truth over personal attack. The reader should nod, not flinch.
- Calm confidence. No anger, no shaming, no "you're scared / lazy / weak / broke / soft" framing.
- Think: stoicism, quiet strength, long-view thinking. Think Marcus Aurelius, not a gym bro at 5am.
- The reader should finish the quote and want to save it — because it told them something timeless about themselves, not because it attacked them.

WHAT ACTUALLY WINS IN THIS NICHE (from real data — top posts have 10k–20k+ likes):
- "The body achieves what the mind believes."
- "Success isn't about the applause you get when you're winning. It's about the silence you endure when you're building."
- "The older I get, the more I realize happiness isn't loud or complicated."
- "Built, not born."
- "Nobody talks about this phase — but everyone goes through it."
- "Enjoy the process."
- "Growth is quiet. So is discipline. So is everything worth having."
These are warm, universal, reflective. Match this emotional register.

STRUCTURE:
- Primary: STATEMENT — a clean, timeless declaration about discipline, growth, consistency, quiet progress, or identity. No question mark, no accusation, no "you" finger-pointing.
- Secondary: CONTRAST — gentle juxtaposition ("Motivation is a mood. Discipline is a decision.").
- Occasional: PUNCH — iconic short phrase ("Built, not born.").
- Rare: IDENTITY upgrade ("A disciplined person doesn't negotiate with Tuesday.").
- Very rare: QUESTION, COMMAND, PAIN_DRIVEN — use sparingly, and never cruel.

TONE RULES:
- You may use "you" — but gently, as a mirror, not a weapon.
- Prefer universal "we / everyone / the work" over sharp "you're X."
- Short OR long is fine — what matters is depth, not word count.
- No corporate language. No hashtags. No CTAs inside the quote itself.

NEVER WRITE THESE (banned):
- Any insult: "You're lazy / scared / soft / broke / weak / a coward / pathetic."
- Drill-sergeant tone: "Stop crying. Grind. No excuses."
- Clichés: "Hustle harder." "Grind now, rest later." "You got this." "Success is a choice." "Be the best version of yourself." "Never give up."
- Hashtags or symbols inside the quote (#, |, @).
- YouTube/TikTok-speak: "welcome to", "subscribe", "this channel", "link in bio", "watch till the end", "like and share".
- Dates or years ("2024", "2025").
- Quotes that exist only to shame the reader.

COMPETITIVE EDGE:
You will be given real hooks from the top-performing discipline posts on Instagram right now. Use them as inspiration for energy, rhythm, and structure — but NEVER copy them verbatim. Your job is to write something that feels as timeless as those hooks — same wisdom, fresh words."""

# ── Quote generation prompt ────────────────────────────────────────────────────

QUOTE_PROMPT = """Topic: {topic}
Series: {series_label}
Design style: {design_style}
Hot keywords to weave in (use 1-2 gently, never force them): {hot_keywords}
Performance hints: {prompt_hints}
Length target: {length_instruction}

Generate 7 quote variations for this topic. Follow the LENGTH TARGET above strictly. Be reflective, wise, observational. No insults. No attacks. No hashtags. Universal truth, not personal shaming.

Variation types (in order):
1. STATEMENT — a clean, timeless declaration. No question, no accusation. Universal wisdom about discipline, growth, consistency, or the quiet work. (This is the primary type — make it your best one.)
2. CONTRAST — gentle juxtaposition (not X, but Y). Calm, reflective.
3. PUNCH — ultra-short iconic phrase, 5-12 words. Timeless, memorable. Like "Built, not born."
4. IDENTITY — gentle self-image upgrade ("A disciplined person doesn't negotiate with Tuesday.").
5. QUESTION — ONE rhetorical, used sparingly, never cruel.
6. COMMAND — gentle imperative, used rarely, no shouting.
7. PAIN_DRIVEN — names a soft cost, never cruelly, used rarely.

Then select the single best quote (most likely to get saved). Bias heavily toward STATEMENT unless another type is clearly stronger for this topic.

Return ONLY this JSON (no markdown, no explanation):
{{
  "quote_options": [
    {{"type": "statement", "text": "..."}},
    {{"type": "contrast", "text": "..."}},
    {{"type": "punch", "text": "..."}},
    {{"type": "identity", "text": "..."}},
    {{"type": "question", "text": "..."}},
    {{"type": "command", "text": "..."}},
    {{"type": "pain_driven", "text": "..."}}
  ],
  "selected_quote": "...",
  "selected_type": "statement|contrast|punch|identity|question|command|pain_driven",
  "hook_keyword": "single word that anchors the quote (e.g. quiet, growth, built, discipline)",
  "format": "image or carousel",
  "design_style": "{design_style}",
  "image_prompt": "detailed prompt for a cinematic, moody, aesthetic image generation. No text in image. Prefer warm, reflective, atmospheric scenes.",
  "predicted_performance": "high|medium|low",
  "reasoning": "one sentence on why this quote will resonate"
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


# ── Quality + plagiarism gates ────────────────────────────────────────────────

_BANNED_SUBSTRINGS = [
    "grind now", "are you serious", "work hard every day",
    "success is a choice", "keep going", "hustle harder",
    "you got this", "best version", "never give up",
    "welcome to", "subscribe", "this channel", "watch till",
    "link in bio", "like and share", "like & share",
    "you're lazy", "you are lazy", "you're scared", "you are scared",
    "you're weak", "you are weak", "you're soft", "you are soft",
    "you're broke", "you are broke",
]


def _is_quality_quote(quote: str) -> tuple[bool, str]:
    """Validate a generated quote. Returns (ok, reason_if_not_ok)."""
    if not quote:
        return False, "empty"
    q = quote.strip()
    if len(q) < 10:
        return False, "too short"
    if "#" in q:
        return False, "contains hashtag"
    if "|" in q:
        return False, "contains pipe"
    # YouTube/TikTok pollution + shaming language
    q_lower = q.lower()
    for bad in _BANNED_SUBSTRINGS:
        if bad in q_lower:
            return False, f"banned phrase: {bad}"
    # Reject quotes where a date/year leaked in
    if re.search(r"\b20(2[0-9]|3[0-9])\b", q):
        return False, "contains year"
    return True, ""


def _too_similar(quote: str, top_hooks: list, threshold: float = 0.6) -> bool:
    """Jaccard-overlap plagiarism guard against competitor top hooks."""
    q_words = set(re.findall(r"\w+", quote.lower()))
    q_words = {w for w in q_words if len(w) >= 3}
    if len(q_words) < 4:
        return False
    for hook in top_hooks or []:
        h_words = set(re.findall(r"\w+", (hook or "").lower()))
        h_words = {w for w in h_words if len(w) >= 3}
        if not h_words:
            continue
        union = q_words | h_words
        if not union:
            continue
        overlap = len(q_words & h_words) / len(union)
        if overlap >= threshold:
            return True
    return False


def _pick_fallback_quote(quote_options: list) -> tuple[str, str]:
    """Walk the quote_options list and return the first quote that passes the quality gate."""
    for opt in quote_options or []:
        text = (opt.get("text") or "").strip()
        ok, _ = _is_quality_quote(text)
        if ok:
            return text, opt.get("type", "statement")
    return "", ""


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
    hot_kw_str    = ", ".join(hot_keywords[:5]) if hot_keywords else "discipline, growth, focus, quiet, consistent"
    hints_str     = ""
    if prompt_hints:
        if prompt_hints.get("best_hooks"):
            hints_str += f"Our best performing hooks: {', '.join(prompt_hints['best_hooks'][:3])}. "
        if prompt_hints.get("best_quote_types"):
            hints_str += f"Our best performing types: {', '.join(prompt_hints['best_quote_types'][:2])}. "
        trending_hooks = prompt_hints.get("trending_hooks") or []
        if trending_hooks:
            hints_str += "\nHOOKS TRENDING IN THE NICHE RIGHT NOW (from top viral discipline posts — match this ENERGY but write something ORIGINAL, do NOT copy):"
            for h in trending_hooks[:5]:
                hints_str += f'\n  - "{h[:100]}"'
        trending_power = prompt_hints.get("trending_power_words") or []
        if trending_power:
            hints_str += f"\nHIGH-ENGAGEMENT WORDS from top niche posts (weave 2-3 in naturally): {', '.join(trending_power[:10])}"
        trending_struct = prompt_hints.get("trending_structures") or []
        if trending_struct:
            hints_str += f"\nDOMINANT STRUCTURES in top niche posts this week: {', '.join(trending_struct[:3])} (prefer these)"
    if not hints_str:
        hints_str = "No performance data yet. Experiment freely."

    # Snapshot hints for REPORT.md visibility
    try:
        _hints_snapshot_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "last_prompt_hints.txt")
        )
        os.makedirs(os.path.dirname(_hints_snapshot_path), exist_ok=True)
        _tmp_hints = _hints_snapshot_path + ".tmp"
        with open(_tmp_hints, "w", encoding="utf-8") as _f:
            _f.write(hints_str)
        os.replace(_tmp_hints, _hints_snapshot_path)
    except Exception:
        pass

    # Step 1: Pick length distribution — 10% PUNCH, 25% MEDIUM, 65% LONG (matches what wins in the niche)
    length_roll = random.random()
    if length_roll < 0.10:
        length_instruction = "Write a PUNCH quote: 5-12 words ONLY. Iconic, timeless, memorable. Like 'Built, not born.' PUNCH type MUST be under 12 words."
    elif length_roll < 0.35:
        length_instruction = "Write a MEDIUM quote: 20-40 words. 2-3 sentences of calm reflection. Universal, not accusatory."
    else:
        length_instruction = "Write a LONG quote: 40-80 words. 3-5 sentences. Wisdom arc: observe → reflect → affirm. Calm, warm, universal. Most variations should be this length."

    # Step 2: Generate quote options
    print(f"Generating quotes for: {topic}", flush=True)
    quote_prompt = QUOTE_PROMPT.format(
        topic=topic,
        series_label=series_label,
        design_style=design_style,
        hot_keywords=hot_kw_str,
        prompt_hints=hints_str,
        length_instruction=length_instruction
    )

    raw_quote = _call(quote_prompt)
    try:
        quote_data = _extract_json(raw_quote)
    except Exception as e:
        print(f"  [WARN] JSON parse failed: {e}. Retrying...", flush=True)
        raw_quote  = _call(quote_prompt, temperature=0.7)
        quote_data = _extract_json(raw_quote)

    selected_quote = quote_data.get("selected_quote", "")
    selected_type  = quote_data.get("selected_type", "statement")

    # Quality gate — reject polluted / shaming / cliché quotes
    ok, reason = _is_quality_quote(selected_quote)
    trending_hooks_list = (prompt_hints or {}).get("trending_hooks") or []
    plagiarized = _too_similar(selected_quote, trending_hooks_list) if ok else False

    if not ok or plagiarized:
        why = reason if not ok else "too similar to a competitor hook"
        print(f"  [WARN] Quote rejected ({why}). Trying next variation...", flush=True)
        fallback_text, fallback_type = _pick_fallback_quote(quote_data.get("quote_options", []))
        # Walk past plagiarized fallbacks too
        while fallback_text and _too_similar(fallback_text, trending_hooks_list):
            quote_data["quote_options"] = [
                o for o in quote_data.get("quote_options", [])
                if (o.get("text") or "").strip() != fallback_text
            ]
            fallback_text, fallback_type = _pick_fallback_quote(quote_data.get("quote_options", []))

        if fallback_text:
            selected_quote = fallback_text
            selected_type  = fallback_type
        else:
            # Retry the LLM once with a stricter instruction
            print("  [WARN] No fallback passed gate. Retrying LLM...", flush=True)
            retry_prompt = quote_prompt + (
                "\n\nIMPORTANT: Previous attempt was rejected. Write calm, universal, reflective wisdom. "
                "No insults. No hashtags. No YouTube/TikTok speak. No shaming."
            )
            try:
                raw_quote2  = _call(retry_prompt, temperature=0.85)
                quote_data2 = _extract_json(raw_quote2)
                retry_quote = quote_data2.get("selected_quote", "")
                ok2, _ = _is_quality_quote(retry_quote)
                if ok2 and not _too_similar(retry_quote, trending_hooks_list):
                    quote_data     = quote_data2
                    selected_quote = retry_quote
                    selected_type  = quote_data.get("selected_type", selected_type)
                else:
                    fb2, ft2 = _pick_fallback_quote(quote_data2.get("quote_options", []))
                    if fb2:
                        quote_data     = quote_data2
                        selected_quote = fb2
                        selected_type  = ft2
            except Exception as _re:
                print(f"  [WARN] Retry failed: {str(_re)[:80]}", flush=True)

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
