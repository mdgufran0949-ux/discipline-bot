"""
caption_generator.py
Caption + hashtag generator for DisciplineFuel.

Replaces hardcoded 7-template rotation with:
  5 caption structures  (pillar-informed, never repeat consecutively)
  10-CTA rotation       (no repeat within last 5 posts)
  3-pool hashtag system (4+3+2 = 9 tags/post, 7-day cooldown on pools A+B)
  LLM-written body      (matched to structure + pillar)

Public:
    generate_caption(quote, pillar, hook_template, account, cfg) -> dict

Hashtag activation:
    Tools looks for tools/hashtag_pools.json (activated).
    Falls back to tools/hashtag_pools.PROPOSED.json with a warning.
    Rename PROPOSED -> json after approving the tag list.
"""

import json
import os
import random
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
_TMP_BASE  = os.path.join(_ROOT, ".tmp")

# ── Constants ──────────────────────────────────────────────────────────────────

STRUCTURES = ["hook_value_cta", "single_line", "numbered_list", "mini_story", "contrarian_take"]

# Soft preference: 60% chance to use a pillar-preferred structure
PILLAR_STRUCTURE_PREF = {
    "hard_truth":  ["hook_value_cta", "single_line"],
    "tactical":    ["numbered_list",  "hook_value_cta"],
    "reframe":     ["contrarian_take","hook_value_cta"],
    "story_proof": ["mini_story",     "hook_value_cta"],
}

PREFERRED_CHANCE      = 0.60
STRUCTURE_BLOCK       = 1    # never repeat the N most-recent structures
CTA_BLOCK             = 5    # never reuse a CTA within last N posts
HASHTAG_A_COUNT       = 4    # from Pool A per post
HASHTAG_B_COUNT       = 3    # from Pool B per post
HASHTAG_C_COUNT       = 2    # from Pool C per post
HASHTAG_COOLDOWN_DAYS = 7    # Pool A and B cooldown window

CTA_POOL = [
    "Follow @dis.ciplinefuel for daily fuel.",
    "Save this. Read it tomorrow morning.",
    "Tag someone who needs to hear this.",
    "Comment 'YES' if this hit.",
    "Share this with someone who's stuck.",
    "Bookmark this for your next weak moment.",
    "Follow for unfiltered discipline.",
    "Send this to the version of you that's still asleep.",
    "Comment your biggest excuse below.",
    "Save it. Re-read it. Live it.",
]

# ── LLM prompts ────────────────────────────────────────────────────────────────

_CAPTION_SYSTEM = (
    "You write punchy, raw Instagram caption bodies for DisciplineFuel — a discipline/mindset page. "
    "Voice: wise, direct, relatable. No corporate speak. No clichés. No hashtags. No CTAs. "
    "Audience: 16-30 year olds building discipline and focus. "
    "Return ONLY the caption body. No labels, no explanation."
)

_CAPTION_PROMPTS = {
    "hook_value_cta": (
        'Quote: "{quote}"\n'
        'Pillar: {pillar} | Hook used: {hook_template}\n\n'
        'Write a 2-4 line caption body. NO CTA. NO hashtags.\n'
        'Line 1: Punchy hook — same energy as the quote but completely different words\n'
        'Blank line\n'
        'Lines 2-3: 1-2 sentences of raw insight. No fluff, no corporate speak.\n\n'
        'Return only the body text.'
    ),
    "single_line": (
        'Quote: "{quote}"\n'
        'Pillar: {pillar}\n\n'
        'Write ONE sentence (60-120 chars) that punches harder than the quote. '
        'No CTA. No hashtags. No line breaks.\n\n'
        'Return only the sentence.'
    ),
    "numbered_list": (
        'Quote: "{quote}"\n'
        'Pillar: {pillar}\n\n'
        'Write a numbered list caption body. NO CTA. NO hashtags.\n'
        'Format:\n'
        '[One tight intro sentence]:\n'
        '1. [item — under 55 chars]\n'
        '2. [item]\n'
        '3. [item]\n'
        '(optional 4th item)\n\n'
        'Return only the formatted body, nothing else.'
    ),
    "mini_story": (
        'Quote: "{quote}"\n'
        'Pillar: {pillar}\n\n'
        'Write a mini-story caption body. NO CTA. NO hashtags.\n'
        'Lines 1-2: Vivid setup or scene (max 2 sentences — drop the reader in)\n'
        'Blank line\n'
        'Line 3: One-line lesson or punchline\n\n'
        'Return only the formatted body.'
    ),
    "contrarian_take": (
        'Quote: "{quote}"\n'
        'Pillar: {pillar}\n\n'
        'Write a contrarian caption body. NO CTA. NO hashtags.\n'
        'Line 1: Bold claim that flips common wisdom — direct, no hedging\n'
        'Blank line\n'
        'Lines 2-3: Brief, sharp justification (1-2 sentences)\n\n'
        'Return only the formatted body.'
    ),
}

# Phrases that would indicate the LLM snuck a CTA into the body
_CTA_INDICATORS = (
    "follow @", "save this", "tag someone", "comment 'yes'",
    "share this", "bookmark this", "send this", "comment your",
    "follow for", "like and", "check out",
)


# ── LLM dispatch ───────────────────────────────────────────────────────────────

def _llm_call(prompt: str, temperature: float = 0.80) -> str:
    """OpenRouter -> Groq -> Gemini -> Kimi (mirrors quote generator order)."""
    messages = [
        {"role": "system", "content": _CAPTION_SYSTEM},
        {"role": "user",   "content": prompt},
    ]

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    groq_key       = os.getenv("GROQ_API_KEY")
    gemini_key     = os.getenv("GEMINI_API_KEY")
    kimi_key       = os.getenv("KIMI_API_KEY")

    if openrouter_key:
        try:
            import requests
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/mdgufran0949-ux/discipline-bot"},
                json={"model": "openai/gpt-4o-mini", "messages": messages,
                      "temperature": temperature, "max_tokens": 400},
                timeout=25,
            )
            if resp.ok:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  [CAPTION] OpenRouter failed: {str(e)[:60]}", flush=True)

    if groq_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages,
                temperature=temperature, max_tokens=400,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [CAPTION] Groq failed: {str(e)[:60]}", flush=True)

    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=_CAPTION_SYSTEM + "\n\n" + prompt,
                config={"temperature": temperature, "max_output_tokens": 400},
            )
            return resp.text.strip()
        except Exception as e:
            print(f"  [CAPTION] Gemini failed: {str(e)[:60]}", flush=True)

    if kimi_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=kimi_key, base_url="https://integrate.api.nvidia.com/v1")
            r = client.chat.completions.create(
                model="moonshotai/kimi-k2-instruct", messages=messages,
                temperature=temperature, max_tokens=400,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [CAPTION] Kimi failed: {str(e)[:60]}", flush=True)

    raise ValueError("[CAPTION] All LLMs unavailable")


# ── State I/O ──────────────────────────────────────────────────────────────────

def _state_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "caption_state.json")


def _load_state(account: str) -> dict:
    path = _state_path(account)
    if not os.path.exists(path):
        return {"recent_structures": [], "recent_ctas": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"recent_structures": [], "recent_ctas": []}


def _save_state(account: str, state: dict) -> None:
    path = _state_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["updated_at"] = datetime.now().isoformat()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def _hashtag_history_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "hashtag_history.json")


def _load_hashtag_history(account: str) -> dict:
    path = _hashtag_history_path(account)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_hashtag_history(account: str, history: dict) -> None:
    path = _hashtag_history_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp, path)


# ── Hashtag pool loading ────────────────────────────────────────────────────────

def _load_pools() -> dict:
    """Load activated pools or fall back to PROPOSED with a warning."""
    activated = os.path.join(_TOOLS_DIR, "hashtag_pools.json")
    proposed  = os.path.join(_TOOLS_DIR, "hashtag_pools.PROPOSED.json")

    if os.path.exists(activated):
        with open(activated, "r", encoding="utf-8") as f:
            return json.load(f)

    if os.path.exists(proposed):
        print(
            "  [HASHTAG] WARNING: using PROPOSED hashtag pools (not yet approved). "
            "Rename hashtag_pools.PROPOSED.json -> hashtag_pools.json to activate.",
            flush=True,
        )
        with open(proposed, "r", encoding="utf-8") as f:
            return json.load(f)

    # Emergency fallback when no pools file exists at all
    print("  [HASHTAG] WARNING: hashtag_pools.json not found. Using emergency fallback tags.", flush=True)
    return {
        "pool_A": [
            "#disciplineovermotivation", "#stoicmindset", "#selfimprovementdaily",
            "#disciplineiskey", "#dailydiscipline", "#selfmastery", "#mindsetshift",
            "#consistencyiskey", "#mentalgrowth", "#growthmindsetdaily",
        ],
        "pool_B": [
            "#disciplineequalsfreedom", "#stoicwisdomdaily", "#harshtruths",
            "#buildmentaltoughness", "#stoicismquotes", "#resilientmindset",
            "#consistentaction", "#hardworkpays", "#hardtruthsquotes", "#uncommonmentality",
        ],
        "pool_C": [
            "#disciplinefuel", "#disciplinedaily", "#fueldiscipline",
            "#disciplineismylife", "#disciplinenotmotivation",
        ],
    }


# ── Structure picker ────────────────────────────────────────────────────────────

def _pick_structure(pillar: str, recent_structures: list) -> str:
    blocked    = set(recent_structures[-STRUCTURE_BLOCK:]) if recent_structures else set()
    prefs      = PILLAR_STRUCTURE_PREF.get(pillar, ["hook_value_cta", "single_line"])
    avail_pref = [s for s in prefs     if s not in blocked]
    avail_non  = [s for s in STRUCTURES if s not in prefs and s not in blocked]

    # True 60/40 split: the 40% branch draws only from non-preferred structures
    # so preferred rate cannot exceed PREFERRED_CHANCE through random overlap.
    if avail_pref and avail_non:
        return random.choice(avail_pref if random.random() < PREFERRED_CHANCE else avail_non)

    # Fallback: one category is exhausted (e.g. all non-prefs blocked by chance)
    available = avail_pref + avail_non
    if not available:
        available = STRUCTURES
    return random.choice(available)


# ── CTA picker ─────────────────────────────────────────────────────────────────

def _pick_cta(recent_ctas: list) -> str:
    blocked   = set(recent_ctas[-CTA_BLOCK:]) if recent_ctas else set()
    available = [c for c in CTA_POOL if c not in blocked]
    if not available:
        available = CTA_POOL
    return random.choice(available)


# ── Hashtag picker ─────────────────────────────────────────────────────────────

def _is_on_cooldown(tag: str, history: dict) -> bool:
    entry = history.get(tag)
    if not entry:
        return False
    try:
        last = datetime.fromisoformat(entry["last_used"])
        return (datetime.now() - last).days < HASHTAG_COOLDOWN_DAYS
    except Exception:
        return False


def _pick_from_pool(pool: list, history: dict, count: int, apply_cooldown: bool = True) -> list:
    """Pick `count` unique tags from pool with optional cooldown filter.
    If pool runs dry, bring back oldest-used tags to fill the count."""
    if apply_cooldown:
        available = [t for t in pool if not _is_on_cooldown(t, history)]
    else:
        available = list(pool)

    if len(available) < count:
        # Bring back cooled-out tags sorted oldest-used first
        cooled = [t for t in pool if t not in available]
        cooled.sort(key=lambda t: history.get(t, {}).get("last_used", "2000-01-01"))
        available = available + cooled

    n = min(count, len(available))
    return random.sample(available[:max(n, len(available))], n)


def _pick_hashtags(pools: dict, history: dict) -> dict:
    def _normalise(tags):
        return [t if t.startswith("#") else f"#{t}" for t in tags]

    pool_a = _normalise(pools.get("pool_A", []))
    pool_b = _normalise(pools.get("pool_B", []))
    pool_c = _normalise(pools.get("pool_C", []))

    return {
        "A": _pick_from_pool(pool_a, history, HASHTAG_A_COUNT, apply_cooldown=True),
        "B": _pick_from_pool(pool_b, history, HASHTAG_B_COUNT, apply_cooldown=True),
        "C": _pick_from_pool(pool_c, history, HASHTAG_C_COUNT, apply_cooldown=False),
    }


def _update_hashtag_history(history: dict, tags: list) -> dict:
    now     = datetime.now().isoformat()
    cutoff  = (datetime.now() - timedelta(days=30)).isoformat()
    for tag in tags:
        entry = history.get(tag, {"last_used": now, "use_count_30d": 0})
        if entry.get("last_used", "2000-01-01") < cutoff:
            entry["use_count_30d"] = 0
        entry["last_used"]     = now
        entry["use_count_30d"] = entry.get("use_count_30d", 0) + 1
        history[tag] = entry
    return history


# ── Caption body ───────────────────────────────────────────────────────────────

def _generate_body(quote: str, pillar: str, hook_template: str, structure: str) -> str:
    """Call LLM to write the caption body. Falls back to quote text on failure."""
    template = _CAPTION_PROMPTS.get(structure, _CAPTION_PROMPTS["hook_value_cta"])
    prompt   = template.format(quote=quote, pillar=pillar, hook_template=hook_template)

    try:
        body = _llm_call(prompt)
        # Strip any stray hashtags the LLM might have added
        body = re.sub(r"#\w+", "", body).strip()
        # Remove lines that smell like a CTA
        lines = body.splitlines()
        lines = [l for l in lines if not any(c in l.lower() for c in _CTA_INDICATORS)]
        return "\n".join(lines).strip() or quote
    except Exception as e:
        print(f"  [CAPTION] LLM body failed ({str(e)[:60]}), using quote as body.", flush=True)
        return quote


# ── Public interface ────────────────────────────────────────────────────────────

def generate_caption(
    quote: str,
    pillar: str,
    hook_template: str,
    account: str,
    cfg: dict = None,
) -> dict:
    """
    Generate a full Instagram caption: body + CTA + hashtags.

    Returns:
        caption            str  — assembled full caption
        structure          str  — which of the 5 structures was used
        cta                str  — the CTA appended
        hashtags           list — all 9 tags (with # prefix)
        hashtag_pools_used dict — {"A": [...], "B": [...], "C": [...]}
    """
    state   = _load_state(account)
    history = _load_hashtag_history(account)
    pools   = _load_pools()

    structure = _pick_structure(pillar, state.get("recent_structures", []))
    cta       = _pick_cta(state.get("recent_ctas", []))
    ht_sets   = _pick_hashtags(pools, history)
    all_tags  = ht_sets["A"] + ht_sets["B"] + ht_sets["C"]

    print(f"  [CAPTION] structure={structure} | cta={cta[:30]}... | tags={len(all_tags)}", flush=True)

    body    = _generate_body(quote, pillar, hook_template, structure)
    caption = f"{body}\n\n{cta}\n\n{' '.join(all_tags)}"

    # Persist state (keep last 20 of each for history window)
    _save_state(account, {
        "recent_structures": (state.get("recent_structures", []) + [structure])[-20:],
        "recent_ctas":       (state.get("recent_ctas",       []) + [cta])[-20:],
    })
    # Only A+B have cooldowns; C (branded) always available
    history = _update_hashtag_history(history, ht_sets["A"] + ht_sets["B"])
    _save_hashtag_history(account, history)

    return {
        "caption":            caption,
        "structure":          structure,
        "cta":                cta,
        "hashtags":           all_tags,
        "hashtag_pools_used": ht_sets,
    }
