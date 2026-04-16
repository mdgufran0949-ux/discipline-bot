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
import random
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
try:
    from account_memory import AccountMemory
except Exception:
    AccountMemory = None

KIDS_ACCOUNT_SLUG = "biscuit_zara"

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

# ── Hook styles — rotate so every video has a different opening ──────────────

HOOK_STYLES = [
    {
        "name": "question",
        "scene1_instruction": "Scene 1 MUST open with a curious question like 'Have you ever wondered why...?' or 'What do YOU think happens when...?' to get kids thinking",
        "scene1_dialogue": "Have you ever wondered [curious question about topic]? Let's find out together!",
        "scene1_narration": "Have you ever wondered [question about topic]? [rhyming setup for the adventure]",
        "scene1_desc": "BISCUIT looks thoughtful and curious, one paw on chin, wondering expression, colorful question marks floating around",
        "seo_hint": "for kids",
    },
    {
        "name": "challenge",
        "scene1_instruction": "Scene 1 MUST open with an interactive challenge like 'Can YOU help us count?' or 'Let's see if YOU can guess!' to involve kids directly",
        "scene1_dialogue": "Can YOU help us learn about [topic] today? Let's count and explore together!",
        "scene1_narration": "Can you help Biscuit and Zara [challenge related to topic]? [rhyming invitation]",
        "scene1_desc": "BISCUIT pointing at the viewer with big excited eyes, ZARA beside with a big smile, bright energetic scene",
        "seo_hint": "preschool",
    },
    {
        "name": "wow_fact",
        "scene1_instruction": "Scene 1 MUST open with a mind-blowing 'Whoa! Did you know...?' fact that instantly wows kids",
        "scene1_dialogue": "Whoa! Did you know [amazing surprising fact about topic]? So cool!",
        "scene1_narration": "Whoa, did you know [amazing fact about topic]? [rhyming wow reaction]",
        "scene1_desc": "BISCUIT with huge round eyes, mouth open in amazement, sparkles and stars all around, bright pop background",
        "seo_hint": "Did You Know",
    },
    {
        "name": "adventure",
        "scene1_instruction": "Scene 1 MUST open with an adventure invitation like 'Come on an adventure!' or 'Let's explore the magical world of...' to spark imagination",
        "scene1_dialogue": "Come on an adventure with us to learn all about [topic]! Let's GO!",
        "scene1_narration": "Come on an adventure, let's explore [topic] today! [rhyming journey opening]",
        "scene1_desc": "BISCUIT and ZARA in explorer outfits, backpacks on, pointing at a colorful magical landscape related to the topic",
        "seo_hint": "for kids",
    },
    {
        "name": "story",
        "scene1_instruction": "Scene 1 MUST open with a mini story starter like 'One day, Biscuit discovered...' or 'Once upon a time...' to draw kids into a narrative",
        "scene1_dialogue": "One day, Biscuit found something amazing — [thing related to topic]! What could it be?",
        "scene1_narration": "One day Biscuit found [discovery related to topic], oh what a wonderful day! [rhyming story opening]",
        "scene1_desc": "BISCUIT discovering something related to the topic with wide curious eyes, ZARA peeking from behind, storybook-style warm scene",
        "seo_hint": "preschool",
    },
    {
        "name": "countdown",
        "scene1_instruction": "Scene 1 MUST open with an exciting countdown or number hook like '3... 2... 1... Let's GO!' or 'We're about to learn 5 amazing things about...'",
        "scene1_dialogue": "3... 2... 1... Let's learn all about [topic]! Are you ready, friends?",
        "scene1_narration": "Three, two, one, let's have some fun and learn about [topic] today! [rhyming countdown]",
        "scene1_desc": "BISCUIT holding a big number sign, countdown bubbles floating, ZARA cheering with pompoms, bright confetti background",
        "seo_hint": "for kids",
    },
]

SYSTEM_PROMPT_BASE = """You are a children's educational video scriptwriter for ages 3-10.
You write scripts featuring BISCUIT (a curious yellow bear cub) and ZARA (a smart purple owl).

Rules:
- Simple vocabulary, Grade 2 reading level
- Narration MUST be musical and rhythmic — like a song or nursery rhyme. Use rhyming couplets, repetition, and a bouncy cadence kids love.
- Narration MUST be EXACTLY 6 sentences (one per scene). Each sentence: 12-16 words. Total narration: 72-96 words. DO NOT write short sentences.
- {hook_instruction}
- Scene 6 MUST recap the lesson with a rhyming goodbye sing-along and invite kids to watch tomorrow
- Every scene should have ENERGY — use exclamation marks, sound effects ("Wow!", "Ooooh!", "That's AMAZING!"), and call kids by name ("friends", "little ones")
- Always return ONLY valid JSON. No markdown. No explanation outside JSON."""


# Compact prompt — scene_desc only, no embedded character descriptions (saves tokens)
PROMPT_TEMPLATE = """Write a kids animation script about: {topic}
Series: {series}

Return ONLY this JSON (no markdown):
{{
  "topic": "{topic}",
  "series": "{series}",
  "title": "Engaging title with emoji, max 60 chars",
  "narration": "MUSICAL rhyming voiceover. MUST use the {hook_name} hook style for scene 1. EXACTLY 6 sentences (one per scene). Each sentence: 12-16 words with rhyme and rhythm. MINIMUM 72 words total. High energy throughout!",
  "scenes": [
    {{"id": 1, "speaker": "BISCUIT", "dialogue": "{scene1_dialogue}", "narration": "{scene1_narration}", "scene_desc": "{scene1_desc}"}},
    {{"id": 2, "speaker": "ZARA", "dialogue": "Teaching explanation 1-2 sentences with wow factor", "narration": "Narrator explains scene 2 with excitement and rhythm", "scene_desc": "ZARA explaining enthusiastically, BISCUIT listening with big eyes, scene 2 action"}},
    {{"id": 3, "speaker": "BISCUIT", "dialogue": "Wow! / That's amazing! + excited follow-up question", "narration": "Narrator scene 3 with rhyme", "scene_desc": "BISCUIT jumping with excitement, ZARA smiling, scene 3 action"}},
    {{"id": 4, "speaker": "ZARA", "dialogue": "Key fun fact, simple memorable words", "narration": "Narrator scene 4 — the most important learning moment", "scene_desc": "BISCUIT and ZARA, visual demonstration of the key fact"}},
    {{"id": 5, "speaker": "BISCUIT", "dialogue": "Amazed happy reaction — teaches kids the key takeaway", "narration": "Narrator scene 5 — recap the cool fact in rhyme", "scene_desc": "BISCUIT and ZARA celebrating, bright happy scene"}},
    {{"id": 6, "speaker": "BOTH", "dialogue": "Recap lesson + goodbye message to little ones at home", "narration": "Sing-along goodbye, invite kids back tomorrow for more fun!", "scene_desc": "BISCUIT and ZARA waving goodbye, confetti, stars, big smiles, colorful background"}}
  ],
  "thumbnail_concept": "BISCUIT with huge surprised eyes, mouth open in amazement, holding something related to topic, bright pop-art background",
  "seo_title": "SEO title under 100 chars with '{seo_hint}' or 'cartoon' or 'animation'",
  "description": "2-3 sentences mentioning Biscuit, Zara, topic, and what kids will learn.",
  "tags": ["kids learning", "educational", "preschool", "cartoon", "{hook_name}", "tag6", "tag7", "tag8"],
  "hashtags": ["#{hook_name}", "#kidslearning", "#educationalvideo", "#preschool", "#biscuitandzara", "#Shorts"],
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


def _build_kids_hints_block(hints: dict) -> str:
    if not hints:
        return ""
    parts = []
    if hints.get("best_topics"):
        parts.append("Proven strong topics (prefer similar ones):\n  - "
                     + "\n  - ".join(hints["best_topics"][:5]))
    if hints.get("best_hooks"):
        parts.append("Past WINNING opening hooks (match this rhythm):\n  - "
                     + "\n  - ".join(h[:80] for h in hints["best_hooks"][:3]))
    if hints.get("avoid_topics"):
        parts.append("AVOID these topics (performed poorly):\n  - "
                     + "\n  - ".join(hints["avoid_topics"][:5]))
    return "\n\n".join(parts)


def _call_llm(client: OpenAI, model: str, prompt: str, system: str = None) -> str:
    """Call LLM and return raw text."""
    if system is None:
        system = SYSTEM_PROMPT_BASE.format(hook_instruction="Scene 1 MUST open with an engaging, surprising hook that instantly grabs kids' attention")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
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

    # Pick a hook style — deterministic per topic so reruns are consistent
    topic_seed = sum(ord(c) for c in clean)
    hook = HOOK_STYLES[topic_seed % len(HOOK_STYLES)]
    print(f"  [hook] Style: {hook['name']}", flush=True)

    prompt = PROMPT_TEMPLATE.format(
        topic=clean,
        series=series,
        hook_name=hook["name"],
        scene1_dialogue=hook["scene1_dialogue"],
        scene1_narration=hook["scene1_narration"],
        scene1_desc=hook["scene1_desc"],
        seo_hint=hook["seo_hint"],
    )

    # Build system prompt with the selected hook instruction
    SYSTEM_PROMPT = SYSTEM_PROMPT_BASE.format(
        hook_instruction=hook["scene1_instruction"]
    )

    # Inject memory hints into system prompt if available
    system_prompt = SYSTEM_PROMPT
    if AccountMemory is not None:
        try:
            hints = AccountMemory(KIDS_ACCOUNT_SLUG).get_prompt_hints()
            block = _build_kids_hints_block(hints)
            if block:
                system_prompt = SYSTEM_PROMPT + "\n\n" + block
                print(f"  [memory] kids hints injected ({len(hints.get('best_topics', []))} topics)", flush=True)
        except Exception as e:
            print(f"  [WARN] kids memory load failed: {e}", flush=True)

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
                raw = _call_llm(client, model, prompt, system=system_prompt)

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
                assert word_count >= 60, f"Narration too short: {word_count} words (need 60+)"

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
