"""
generate_niche_script.py
Generates a viral 30-second Instagram Reels script for any account niche.
Uses Groq Llama 3.3 70B (free, fast).
Usage: python tools/generate_niche_script.py --account factsflash [--topic "topic here"]
Output: .tmp/script.json with narration, scenes (3 image prompts), caption, hook.
"""

import argparse, json, os, re, sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
try:
    from account_memory import AccountMemory, weighted_choice
except Exception:
    AccountMemory = None
    weighted_choice = None

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP          = os.path.join(PROJECT_ROOT, ".tmp")
CONFIG_DIR   = os.path.join(PROJECT_ROOT, "config", "accounts")
OUT_PATH     = os.path.join(TMP, "script.json")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE    = "https://api.groq.com/openai/v1"
MODEL        = "llama-3.3-70b-versatile"

# Per-account niche configuration
ACCOUNT_CONFIG = {
    "factsflash": {
        "system": (
            "You are a viral facts content creator for Instagram Reels (@FactsFlash). "
            "Write shocking, mind-blowing facts about science, nature, animals, humans, "
            "psychology, or history. Hook viewers instantly with a surprising opening."
        ),
        "narration_style": (
            "Write a viral 30-second Reels voiceover revealing one shocking fact. "
            "Start with a question or statement that stops scrolling. "
            "Explain the fact clearly with 1-2 surprising details. "
            "End with a mind-blowing punchline. 65-80 words. No hashtags."
        ),
        "image_style": "stunning nature or science photography, dramatic lighting, National Geographic style, photorealistic, 4K, ultra detailed",
        "caption_style": "curiosity + follow CTA + facts hashtags",
    },
    "techmindblown": {
        "system": (
            "You are a viral tech content creator for Instagram Reels (@TechMindblown). "
            "Write mind-blowing facts about AI, technology, robots, and the future. "
            "Make every sentence feel like the future is already here."
        ),
        "narration_style": (
            "Write a viral 30-second Reels voiceover about a shocking tech or AI fact. "
            "Start with a hook that makes viewers stop scrolling. "
            "Explain the tech breakthrough in simple, exciting language. "
            "End with a futuristic statement. 65-80 words. No hashtags."
        ),
        "image_style": "futuristic technology, neon cyberpunk aesthetic, AI circuits, holographic displays, dramatic lighting, photorealistic, 4K, ultra detailed",
        "caption_style": "tech amazement + follow CTA + tech/AI hashtags",
    },
    "coresteelfitness": {
        "system": (
            "You are an energetic fitness coach creating viral Instagram Reels (@CoreSteelFitness). "
            "Share powerful fitness tips and body science facts that motivate people to train harder. "
            "Be direct, energetic, and motivating."
        ),
        "narration_style": (
            "Write a viral 30-second Reels voiceover about a fitness tip or body science fact. "
            "Open with a powerful hook about fitness or the human body. "
            "Share the key tip or fact with energy and authority. "
            "Close with a motivational call to action. 65-80 words. No hashtags."
        ),
        "image_style": "fitness athlete in gym, dramatic lighting, muscular physique, motivational, cinematic, photorealistic, 4K, ultra detailed",
        "caption_style": "motivation + follow CTA + fitness hashtags",
    },
    "cricketcuts": {
        "system": (
            "You are a passionate cricket commentator creating viral Instagram Reels (@cre.cketcuts). "
            "Share amazing cricket records, legendary moments, and jaw-dropping player facts. "
            "Use the energy and excitement of live cricket commentary."
        ),
        "narration_style": (
            "Write a viral 30-second Reels voiceover about an amazing cricket fact, record, or legendary moment. "
            "Open with an exciting hook that gets cricket fans hyped. "
            "Share the cricket fact with commentator energy and passion. "
            "End with a statement that will make fans react. 65-80 words. No hashtags."
        ),
        "image_style": "cricket stadium under dramatic lights, cricket ball close-up, crowd cheering, IPL atmosphere, cinematic, photorealistic, 4K, ultra detailed",
        "caption_style": "cricket excitement + follow CTA + cricket hashtags",
    },
}

SCRIPT_PROMPT = """Topic: {topic}

{narration_style}

Return ONLY valid JSON with this exact structure:
{{
  "narration": "The full voiceover text (65-80 words). Hook first sentence. Build. End strong.",
  "hook": "The first 10-12 words only",
  "scenes": [
    {{"id": 1, "image_prompt": "Vivid cinematic image description for scene 1, {image_style}"}},
    {{"id": 2, "image_prompt": "Vivid cinematic image description for scene 2, {image_style}"}},
    {{"id": 3, "image_prompt": "Vivid cinematic image description for scene 3, {image_style}"}}
  ],
  "caption": "One punchy hook sentence. Follow @{page_name} for more! [5-7 relevant hashtags]"
}}

Rules:
- narration: 65-80 words, punchy sentences, no labels, no hashtags
- scenes: 3 vivid visual descriptions that match different parts of the narration
- caption: under 220 chars, include account handle, relevant hashtags
- Return ONLY the JSON object, no markdown, no explanation"""


def _load_account_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Account config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _groq_call(system: str, prompt: str) -> str:
    client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.85,
        max_tokens=700,
    )
    return resp.choices[0].message.content.strip()


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    # Remove markdown code fences if present
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Find JSON object in response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from response:\n{raw[:300]}")


def _build_hints_block(hints: dict) -> str:
    if not hints:
        return ""
    parts = []
    if hints.get("best_hooks"):
        parts.append("Past WINNING hook styles on this channel:\n  - "
                     + "\n  - ".join(h[:80] for h in hints["best_hooks"][:3]))
    if hints.get("best_topics"):
        parts.append("Proven strong topics — prefer these:\n  - "
                     + "\n  - ".join(hints["best_topics"][:5]))
    if hints.get("avoid_topics"):
        parts.append("AVOID these topics (performed poorly):\n  - "
                     + "\n  - ".join(hints["avoid_topics"][:5]))
    if hints.get("avoid_phrases"):
        parts.append("Avoid phrases similar to:\n  - "
                     + "\n  - ".join(hints["avoid_phrases"][:3]))
    if hints.get("trending_hooks"):
        parts.append("Trending hooks in this niche right now:\n  - "
                     + "\n  - ".join(hints["trending_hooks"][:3]))
    return "\n\n".join(parts)


def generate_niche_script(account: str, topic: str = None) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set in .env")

    cfg = _load_account_config(account)
    ac  = ACCOUNT_CONFIG.get(account)

    # Load memory hints + topic weights
    memory_hints = {}
    topic_weights = {}
    if AccountMemory is not None:
        try:
            mem = AccountMemory(account)
            memory_hints  = mem.get_prompt_hints()
            topic_weights = mem.get_topic_weights()
        except Exception as e:
            print(f"  [WARN] memory load failed: {e}", flush=True)
    if not ac:
        # Generic fallback for unknown accounts
        ac = {
            "system": f"You are a viral content creator for Instagram Reels. Niche: {cfg.get('niche', 'general')}.",
            "narration_style": "Write a viral 30-second Reels voiceover. 65-80 words. Hook first. No hashtags.",
            "image_style": "cinematic photography, dramatic lighting, photorealistic, 4K",
            "caption_style": "engaging CTA + hashtags",
        }

    page_name = cfg.get("ig_page_name", f"@{account}").lstrip("@")
    niche     = cfg.get("niche", "general knowledge")

    if not topic:
        import random
        topic_pool = {
            "factsflash":      ["human brain", "deep ocean", "animal kingdom", "ancient history", "space facts", "psychology tricks", "bizarre world records"],
            "techmindblown":   ["artificial intelligence", "quantum computing", "robotics", "future of the internet", "neural networks", "space technology", "cybersecurity"],
            "coresteelfitness":["muscle building science", "fat burning facts", "sleep and fitness", "protein myths", "workout recovery", "metabolism hacks", "body transformation"],
            "cricketcuts":     ["IPL records", "Sachin Tendulkar", "MS Dhoni legend", "cricket world cup moments", "fastest centuries", "greatest catches", "T20 records"],
        }
        pool  = topic_pool.get(account, ["amazing facts"])
        avoid = set(t.lower() for t in memory_hints.get("avoid_topics", []))
        pool  = [t for t in pool if t.lower() not in avoid] or pool

        # 80% use proven winners, 20% experiment
        if topic_weights and weighted_choice and random.random() < 0.8:
            topic = weighted_choice(topic_weights)
        else:
            topic = random.choice(pool)

    print(f"  Niche : {niche}", flush=True)
    print(f"  Topic : {topic}", flush=True)
    print(f"  Model : {MODEL} (Groq)", flush=True)

    prompt = SCRIPT_PROMPT.format(
        topic=topic,
        narration_style=ac["narration_style"],
        image_style=ac["image_style"],
        page_name=page_name,
    )

    hints_block = _build_hints_block(memory_hints)
    system_prompt = ac["system"]
    if hints_block:
        system_prompt = system_prompt + "\n\n" + hints_block
        print(f"  [memory] injected {len(memory_hints.get('best_hooks', []))} hooks, "
              f"{len(memory_hints.get('avoid_topics', []))} avoid topics", flush=True)

    data = None
    for attempt in range(1, 4):
        try:
            raw  = _groq_call(system_prompt, prompt)
            data = _extract_json(raw)
            wc   = len(data.get("narration", "").split())
            print(f"  [attempt {attempt}] word count: {wc}", flush=True)
            if wc >= 35:
                break
            print(f"  Too short, retrying...", flush=True)
        except Exception as e:
            print(f"  [attempt {attempt}] Error: {str(e)[:80]}", flush=True)
            if attempt == 3:
                raise

    if not data:
        raise RuntimeError("Failed to generate script after 3 attempts")

    # Ensure scenes have correct format
    if "scenes" not in data or len(data["scenes"]) < 3:
        data["scenes"] = [
            {"id": 1, "image_prompt": f"{niche}, {ac['image_style']}"},
            {"id": 2, "image_prompt": f"{niche} dramatic close-up, {ac['image_style']}"},
            {"id": 3, "image_prompt": f"{niche} wide cinematic shot, {ac['image_style']}"},
        ]

    data["account"] = account
    data["page_name"] = page_name
    data["topic"] = topic

    os.makedirs(TMP, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Script saved: {OUT_PATH}", flush=True)

    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="Account name (e.g. factsflash)")
    parser.add_argument("--topic",   default=None,  help="Optional topic override")
    args = parser.parse_args()

    print(f"Generating script for [{args.account}]...", flush=True)
    result = generate_niche_script(args.account, args.topic)
    print(json.dumps(result, indent=2, ensure_ascii=False))
