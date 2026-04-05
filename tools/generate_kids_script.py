"""
generate_kids_script.py
Generates a kids animation script (ages 3-10) featuring BISCUIT and ZARA.
Primary: OpenRouter (best model available). Fallback: Groq → Kimi K2.

Characters:
  BISCUIT — chubby cheerful yellow bear cub, curious learner/questioner
  ZARA    — small wise purple owl with spectacles, knowledgeable explainer

Usage: python tools/generate_kids_script.py "topic here" [--series "Animals ABC"]
Output: JSON with title, narration, 6 scenes, thumbnail concept, SEO metadata.
"""

import json
import sys
import os
import re
import argparse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
KIMI_API_KEY  = os.getenv("KIMI_API_KEY")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
KIMI_BASE_URL = "https://integrate.api.nvidia.com/v1"

GROQ_MODEL       = "llama-3.3-70b-versatile"
KIMI_MODEL       = "moonshotai/kimi-k2-instruct"

# ── Character definitions — injected into image_prompt AFTER parsing ──────────

BISCUIT_DESC = (
    "BISCUIT the chubby cheerful yellow bear cub, big round dark brown eyes, "
    "small pink nose, rounded ears with light pink inner ear, soft fluffy fur, tiny red bowtie, wide happy smile"
)

ZARA_DESC = (
    "ZARA the small wise purple owl, large yellow eyes behind round spectacles, "
    "tiny orange beak, soft purple feathered wings, small blue graduation cap, friendly expression"
)

KIDS_STYLE_PREFIX = (
    "2D cartoon illustration, bright vibrant colors, child-friendly, Pixar/Disney quality, "
    "soft rounded shapes, no text in image, safe for children, cheerful warm lighting, "
)

SYSTEM_PROMPT = """You are a children's educational video scriptwriter for ages 3-10.
You write scripts featuring BISCUIT (a curious yellow bear cub) and ZARA (a smart purple owl).

Rules:
- Simple vocabulary, Grade 2 reading level
- Short sentences, rhythmic and fun
- Scene 1 MUST start with a fun question or surprising fact (3-second hook)
- Scene 6 MUST recap the main lesson and say goodbye
- Always return ONLY valid JSON. No markdown. No explanation outside JSON."""


# Compact prompt — scene_desc only, no embedded character descriptions (saves tokens)
PROMPT_TEMPLATE = """Write a kids animation script about: {topic}
Series: {series}

Return ONLY this JSON (no markdown):
{{
  "topic": "{topic}",
  "series": "{series}",
  "title": "Engaging title with emoji, max 60 chars",
  "narration": "Full voiceover text. Exactly 6 sentences, one per scene. Each sentence must be 10-15 words long. Total: 60-90 words.",
  "scenes": [
    {{"id": 1, "speaker": "BISCUIT", "dialogue": "Short excited question 1-2 sentences", "narration": "Opening narrator hook sentence", "scene_desc": "BISCUIT and ZARA at a bright colorful location, scene 1 action"}},
    {{"id": 2, "speaker": "ZARA", "dialogue": "Teaching explanation 1-2 sentences", "narration": "Narrator explains scene 2", "scene_desc": "BISCUIT and ZARA, scene 2 action"}},
    {{"id": 3, "speaker": "BISCUIT", "dialogue": "Excited reaction or follow-up question", "narration": "Narrator scene 3", "scene_desc": "BISCUIT and ZARA, scene 3 action"}},
    {{"id": 4, "speaker": "ZARA", "dialogue": "Key fun fact, simple words", "narration": "Narrator scene 4", "scene_desc": "BISCUIT and ZARA, scene 4 action"}},
    {{"id": 5, "speaker": "BISCUIT", "dialogue": "Surprised happy reaction", "narration": "Narrator scene 5", "scene_desc": "BISCUIT and ZARA, scene 5 action"}},
    {{"id": 6, "speaker": "BOTH", "dialogue": "Recap lesson + goodbye to kids", "narration": "Wrap up, invite kids back tomorrow", "scene_desc": "BISCUIT and ZARA waving goodbye, confetti, big smiles"}}
  ],
  "thumbnail_concept": "Which character, what expression, what object, what background color",
  "seo_title": "SEO title under 100 chars with 'for kids', 'learning', or 'preschool'",
  "description": "2-3 sentences mentioning Biscuit, Zara, topic, and what kids will learn.",
  "tags": ["kids learning", "educational", "preschool", "cartoon", "tag5", "tag6", "tag7", "tag8"],
  "hashtags": ["#kidslearning", "#educationalvideo", "#preschool", "#biscuitandzara", "#Shorts"],
  "category": "animals or numbers or alphabet or science or stories or colors or nature or songs"
}}"""


def _clean_topic(raw_topic: str) -> str:
    """Clean messy YouTube titles — strip hashtags, pipes, extra whitespace.
    Picks the longest meaningful segment from pipe-separated parts."""
    # Remove hashtags
    no_tags = re.sub(r'#\w+', '', raw_topic)
    # Split on pipe, pick the longest segment (most informative)
    parts = [p.strip() for p in no_tags.split('|') if p.strip()]
    best = max(parts, key=len) if parts else no_tags
    # Remove special chars, collapse whitespace
    cleaned = re.sub(r'[^\w\s\-\']', ' ', best)
    cleaned = ' '.join(cleaned.split()).strip()
    return cleaned if len(cleaned) > 5 else raw_topic.split('|')[0].strip()


def _inject_image_prompts(result: dict) -> dict:
    """Inject full character descriptions + style prefix into each scene's image_prompt."""
    for scene in result.get("scenes", []):
        scene_desc = scene.pop("scene_desc", "BISCUIT and ZARA in a bright colorful scene")
        scene["image_prompt"] = (
            f"{KIDS_STYLE_PREFIX}"
            f"{BISCUIT_DESC}, {ZARA_DESC}. "
            f"{scene_desc}"
        )
    return result


def _call_llm(client: OpenAI, model: str, prompt: str) -> str:
    """Call LLM and return raw text."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.75,
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()


def generate_kids_script(topic: str, series: str = "standalone") -> dict:
    clean = _clean_topic(topic)
    if clean != topic:
        print(f"  [TOPIC] Cleaned: '{clean}'", flush=True)

    prompt = PROMPT_TEMPLATE.format(topic=clean, series=series)

    # Provider order: Groq first (free), Kimi K2 fallback
    providers = []
    if GROQ_API_KEY:
        providers.append(("Groq", OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL), GROQ_MODEL))
    if KIMI_API_KEY:
        providers.append(("Kimi K2", OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL), KIMI_MODEL))

    if not providers:
        raise RuntimeError("No LLM API keys found (GROQ_API_KEY or KIMI_API_KEY)")

    last_error = None
    for provider_name, client, model in providers:
        for attempt in range(1, 3):
            try:
                raw = _call_llm(client, model, prompt)

                # Strip markdown fences if present
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()

                result = json.loads(raw)

                # Validate
                assert len(result.get("scenes", [])) == 6, "Expected 6 scenes"
                word_count = len(result.get("narration", "").split())
                assert word_count >= 40, f"Narration too short: {word_count} words"

                # Inject image prompts (done here, not in prompt, to save tokens)
                result = _inject_image_prompts(result)

                print(f"  [OK] Script via {provider_name} ({word_count} words)", flush=True)
                return result

            except Exception as e:
                last_error = e
                err_str = str(e)
                # Rate limit or quota — skip immediately to next provider
                if "rate_limit" in err_str.lower() or "429" in err_str or "402" in err_str:
                    print(f"  [{provider_name} limit] switching to fallback...", flush=True)
                    break
                if attempt == 1:
                    print(f"  [RETRY] Attempt {attempt} failed ({e}), retrying...", flush=True)

    raise RuntimeError(f"Script generation failed on all providers: {last_error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate kids animation script")
    parser.add_argument("topic",    help='Topic e.g. "counting farm animals"')
    parser.add_argument("--series", default="standalone", help="Series name")
    parser.add_argument("--output", default=None,         help="Save JSON to file path")
    args = parser.parse_args()

    result = generate_kids_script(args.topic, args.series)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[OK] Script saved to {args.output}", flush=True)
    else:
        print(output)
