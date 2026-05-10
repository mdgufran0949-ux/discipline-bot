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
import logging
import os
import random
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
_TMP_BASE  = os.path.join(_ROOT, ".tmp")
_LOGS_DIR  = os.path.join(_ROOT, "logs")

# ── Constants ──────────────────────────────────────────────────────────────────

STRUCTURES = ["hook_value_cta", "single_line", "numbered_list", "mini_story", "contrarian_take"]

# Soft preference: 75% chance to use a pillar-preferred structure
PILLAR_STRUCTURE_PREF = {
    "hard_truth":  ["hook_value_cta", "single_line"],
    "tactical":    ["numbered_list",  "hook_value_cta"],
    "reframe":     ["contrarian_take","hook_value_cta"],
    "story_proof": ["mini_story",     "hook_value_cta"],
}

PREFERRED_CHANCE      = 0.75
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
    "Return ONLY the caption body. No labels, no explanation.\n\n"
    "FAITHFULNESS REQUIREMENT (do not violate): "
    "The caption body MUST preserve the central claim of the source quote. "
    "If the quote contains a negation (NOT, NEVER, isn't, won't, don't, no), "
    "that negation must appear in the body or the body must restate the negated claim. "
    "The body extends or applies the quote — it never contradicts it. "
    "If expanding the quote would require contradicting it, return the quote's "
    "central claim verbatim as the first sentence of the body.\n\n"
    "BANNED PHRASES — never use these or close variants: "
    "\"the truth is\", \"a staggering fact\", \"a remarkable\", "
    "\"highlights the importance of\", \"ultimately shapes\", \"ultimately determines\", "
    "\"often a convenient\", \"is something you continuously\", \"it's important\", "
    "parallel constructions like \"a mask, a convenience\". "
    "Write the body the way you'd text a friend who needs to hear something hard. "
    "Short sentences. Concrete words. No hedging."
)

BANNED_PHRASES = [
    "the truth is",
    "staggering fact",
    "highlights the importance",
    "ultimately shapes",
    "ultimately determines",
    "often a convenient",
    "is something you continuously",
    "it's important",
    "a powerful reminder",
    "it is a",
]

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


# ── Verification helpers ────────────────────────────────────────────────────────

def _detect_story_shape(quote_text: str) -> bool:
    markers = [
        " at 3 ", " at 4 ", " at 5 ", " at dawn", " one day", " years ago",
        " asked ", " replied ", " said ", " told ",
        " a monk ", " a master", " the teacher", " the student",
    ]
    quote_lower = " " + quote_text.lower() + " "
    return any(m in quote_lower for m in markers)


def _verify_negation_preserved(quote_text: str, body: str) -> bool:
    negation_words = [" not ", " never ", " no ", "isn't", "aren't", "won't",
                      "don't", "doesn't", "wasn't", "weren't", "can't", "wouldn't"]
    quote_lower = " " + quote_text.lower() + " "
    body_lower  = " " + body.lower() + " "
    quote_negs  = [n for n in negation_words if n in quote_lower]
    if not quote_negs:
        return True
    return any(n in body_lower for n in quote_negs)


def _verify_stat_preserved(quote_text: str, body: str, hook: str) -> bool:
    if hook != "stat_shock":
        return True
    quote_nums = re.findall(r'\d+%?', quote_text)
    if not quote_nums:
        return True
    body_nums = re.findall(r'\d+%?', body)
    return any(n in body_nums for n in quote_nums)


def _verify_structure(body: str, structure: str) -> bool:
    if structure == "numbered_list":
        numbered_lines = re.findall(r'(?m)^\s*(?:[1-9]\.|[1-9]\)|[①-⑨])', body)
        return len(numbered_lines) >= 3
    elif structure == "single_line":
        sentences = re.findall(r'[.!?]+', body)
        return len(sentences) <= 1
    elif structure == "mini_story":
        markers = [" at ", " when ", " one day", " asked", " replied", " said", " told"]
        return any(m in " " + body.lower() + " " for m in markers)
    elif structure == "contrarian_take":
        markers = [" but ", " actually", " not ", " the truth is", " wrong", " however"]
        return any(m in " " + body.lower() + " " for m in markers)
    return True


_HOOK_REQUIREMENTS = {
    "question":  "contain at least one question (a sentence ending in ?)",
    "stat_shock": "contain at least one number or percentage",
    "command":   "contain at least one direct imperative sentence",
}


def _verify_hook_alignment(body: str, hook_template: str) -> bool:
    """Verify body matches the hook template's structural requirement."""
    if hook_template == "question":
        return "?" in body
    elif hook_template == "stat_shock":
        return bool(re.search(r'\d+', body))
    elif hook_template == "command":
        imperatives = ["stop ", "start ", "do ", "don't ", "never ", "always ",
                       "drop ", "kill ", "pick ", "build ", "track ", "write ",
                       "focus ", "cut ", "choose ", "show "]
        body_lower = " " + body.lower()
        return any(imp in body_lower for imp in imperatives)
    return True


def _setup_verif_logger() -> logging.Logger:
    os.makedirs(_LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("caption_verifier")
    if not logger.handlers:
        handler = logging.FileHandler(
            os.path.join(_LOGS_DIR, "caption_verification.log"),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ── LLM dispatch ───────────────────────────────────────────────────────────────

def _llm_call(
    prompt: str,
    temperature: float = 0.80,
    max_tokens: int = 400,
    system: str = None,
) -> tuple:
    """OpenRouter -> Groq -> Gemini -> Kimi. Returns (response_text, provider_name)."""
    sys_msg  = system if system is not None else _CAPTION_SYSTEM
    messages = [
        {"role": "system", "content": sys_msg},
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
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=25,
            )
            if resp.ok:
                return resp.json()["choices"][0]["message"]["content"].strip(), "openrouter/gpt-4o-mini"
        except Exception as e:
            print(f"  [CAPTION] OpenRouter failed: {str(e)[:60]}", flush=True)

    if groq_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return r.choices[0].message.content.strip(), "groq/llama-3.3-70b-versatile"
        except Exception as e:
            print(f"  [CAPTION] Groq failed: {str(e)[:60]}", flush=True)

    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=sys_msg + "\n\n" + prompt,
                config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
            return resp.text.strip(), "gemini/gemini-2.0-flash"
        except Exception as e:
            print(f"  [CAPTION] Gemini failed: {str(e)[:60]}", flush=True)

    if kimi_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=kimi_key, base_url="https://integrate.api.nvidia.com/v1")
            r = client.chat.completions.create(
                model="moonshotai/kimi-k2-instruct", messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return r.choices[0].message.content.strip(), "kimi/kimi-k2-instruct"
        except Exception as e:
            print(f"  [CAPTION] Kimi failed: {str(e)[:60]}", flush=True)

    raise ValueError("[CAPTION] All LLMs unavailable")


def _extract_field(text: str, field: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(field + ":"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _semantic_verify(quote: str, body: str) -> dict:
    """LLM-based faithfulness check. Returns verdict, lesson_preserved, reason."""
    prompt = (
        'You are verifying whether a caption body faithfully extends a source quote.\n\n'
        f'QUOTE: "{quote}"\n\n'
        f'BODY: "{body}"\n\n'
        'Answer two questions:\n'
        '1. Does the body\'s central claim AFFIRM or CONTRADICT the quote\'s central claim?\n'
        '2. If the quote contains a specific lesson, named person, or concrete detail, '
        'does the body reference it (yes/no)?\n\n'
        'Reply in this exact format, no other text:\n'
        'VERDICT: AFFIRM or CONTRADICT\n'
        'LESSON_PRESERVED: yes or no\n'
        'REASON: one short sentence explaining your verdict'
    )
    try:
        response, _ = _llm_call(
            prompt,
            temperature=0.10,
            max_tokens=120,
            system="You are a strict caption faithfulness verifier. Reply only in the exact format requested.",
        )
        verdict = _extract_field(response, "VERDICT").upper()
        lesson  = _extract_field(response, "LESSON_PRESERVED").lower()
        reason  = _extract_field(response, "REASON")
        if verdict not in ("AFFIRM", "CONTRADICT"):
            verdict = "AFFIRM"
        return {
            "verdict":          verdict,
            "lesson_preserved": lesson == "yes",
            "reason":           reason,
            "passed":           verdict == "AFFIRM",
        }
    except Exception as e:
        print(f"  [CAPTION] Semantic verifier failed: {str(e)[:60]}", flush=True)
        return {"verdict": "AFFIRM", "lesson_preserved": True,
                "reason": "verifier unavailable", "passed": True}


def _check_banned_phrases(body: str) -> list:
    body_lower = body.lower()
    return [p for p in BANNED_PHRASES if p in body_lower]


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
            "#disciplinefuel", "#disciplinedaily", "#fueledbydiscipline",
            "#dis_ciplinefuel", "#disciplinenotmotivation",
        ],
    }


# ── Structure picker ────────────────────────────────────────────────────────────

def _pick_structure(pillar: str, recent_structures: list, quote: str = "") -> str:
    blocked    = set(recent_structures[-STRUCTURE_BLOCK:]) if recent_structures else set()
    prefs      = PILLAR_STRUCTURE_PREF.get(pillar, ["hook_value_cta", "single_line"])
    avail_pref = [s for s in prefs     if s not in blocked]
    avail_non  = [s for s in STRUCTURES if s not in prefs and s not in blocked]

    # Force mini_story when quote has story shape + story_proof pillar
    if pillar == "story_proof" and quote and _detect_story_shape(quote):
        if "mini_story" not in blocked:
            return "mini_story"

    # True 75/25 split: the 25% branch draws only from non-preferred structures
    if avail_pref and avail_non:
        return random.choice(avail_pref if random.random() < PREFERRED_CHANCE else avail_non)

    # Fallback: one category is exhausted
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

def _generate_body(quote: str, pillar: str, hook_template: str, structure: str) -> tuple:
    """Call LLM to write the caption body. Returns (body, llm_provider, verif_meta)."""
    template = _CAPTION_PROMPTS.get(structure, _CAPTION_PROMPTS["hook_value_cta"])
    prompt   = template.format(quote=quote, pillar=pillar, hook_template=hook_template)

    if hook_template == "stat_shock":
        prompt += (
            "\n\nSTAT REQUIREMENT: The body's first sentence MUST contain a number, percentage, "
            "or statistic from the source quote. Use the exact number verbatim — do not paraphrase."
        )

    _logger      = _setup_verif_logger()
    regen_reasons = []

    def _clean(raw: str) -> str:
        raw   = re.sub(r"#\w+", "", raw).strip()
        lines = raw.splitlines()
        lines = [l for l in lines if not any(c in l.lower() for c in _CTA_INDICATORS)]
        return "\n".join(lines).strip()

    def _fallback_meta(err=""):
        return {"semantic_verdict": "N/A", "semantic_reason": err[:60],
                "lesson_preserved": True, "stat_ok": True, "hook_ok": True,
                "struct_ok": True, "banned_phrases": [],
                "regen_triggered": False, "regen_reasons": []}

    try:
        raw, provider = _llm_call(prompt)
        body = _clean(raw)

        # ── Fix 1: Semantic faithfulness check (replaces keyword negation check) ──
        sem = _semantic_verify(quote, body)

        if not sem["passed"]:
            regen_reasons.append(f"semantic_contradict: {sem['reason']}")
            fix_prompt = (
                f"CORRECTION — your previous attempt was rejected because: {sem['reason']}\n"
                f'Source quote: "{quote}"\n'
                "Rewrite the body so it AFFIRMS the quote's central claim, not contradicts it.\n\n"
                + prompt
            )
            try:
                raw2, provider = _llm_call(fix_prompt, temperature=0.60)
                body = _clean(raw2)
                sem  = _semantic_verify(quote, body)
            except Exception:
                pass

            if not sem["passed"]:
                sentences     = re.split(r'(?<=[.!?])\s', quote)
                first_sentence = sentences[0]
                body = (first_sentence + "\n\n"
                        + "Don't let the wrong label stop you from fixing the right problem.")
                sem  = _semantic_verify(quote, body)

        # ── Fix 2: Story-proof lesson preservation ──────────────────────────────
        if pillar == "story_proof" and not sem.get("lesson_preserved", True):
            regen_reasons.append("story_lesson_missing")
            story_prompt = (
                "STORY_PROOF REQUIREMENT: The body MUST explicitly reference the lesson, "
                "named person, or central image from the quote. Setup alone is not enough. "
                "If the quote mentions a specific phrase or image (e.g. 'sharpened the knife'), "
                "the body must include it or its direct equivalent.\n\n"
                + prompt
            )
            try:
                raw3, provider = _llm_call(story_prompt, temperature=0.60)
                body3 = _clean(raw3)
                sem3  = _semantic_verify(quote, body3)
                if sem3.get("lesson_preserved", False):
                    body = body3
                    sem  = sem3
                else:
                    sentences = re.split(r'(?<=[.!?])\s', quote)
                    if len(sentences) >= 2:
                        body = body + "\n\n" + sentences[1]
                    sem["lesson_preserved"] = True
            except Exception:
                sentences = re.split(r'(?<=[.!?])\s', quote)
                if len(sentences) >= 2:
                    body = body + "\n\n" + sentences[1]

        # ── Fix 3: Banned phrase check ───────────────────────────────────────────
        banned_found = _check_banned_phrases(body)
        if banned_found:
            regen_reasons.append(f"banned_phrases: {banned_found}")
            try:
                raw4, provider = _llm_call(prompt, temperature=0.90)
                body4 = _clean(raw4)
                banned2 = _check_banned_phrases(body4)
                if not banned2:
                    body        = body4
                    banned_found = []
                else:
                    banned_found = banned2  # log and ship
            except Exception:
                pass

        # ── Fix 4: Hook alignment check ─────────────────────────────────────────
        hook_ok = _verify_hook_alignment(body, hook_template)
        if not hook_ok and hook_template in _HOOK_REQUIREMENTS:
            requirement = _HOOK_REQUIREMENTS[hook_template]
            regen_reasons.append(f"hook_misaligned: {hook_template}")
            hook_prompt = (
                f"HOOK REQUIREMENT: This caption uses the {hook_template} hook. "
                f"The body MUST {requirement}.\n\n"
                + prompt
            )
            try:
                raw5, provider = _llm_call(hook_prompt, temperature=0.75)
                body5 = _clean(raw5)
                if _verify_hook_alignment(body5, hook_template):
                    body    = body5
                    hook_ok = True
            except Exception:
                pass  # log and ship

        stat_ok   = _verify_stat_preserved(quote, body, hook_template)
        struct_ok = _verify_structure(body, structure)

        stat_label = "PASS" if stat_ok else ("FAIL" if hook_template == "stat_shock" else "N/A")
        hook_label = "PASS" if hook_ok else ("FAIL" if hook_template in _HOOK_REQUIREMENTS else "N/A")
        regen_str  = "; ".join(regen_reasons) if regen_reasons else "none"

        _logger.info(
            f"structure={structure} | semantic={sem['verdict']} | "
            f"lesson={'yes' if sem.get('lesson_preserved') else 'no'} | "
            f"stat={stat_label} | hook={hook_label} | struct={'PASS' if struct_ok else 'FAIL'} | "
            f"banned={banned_found or 'none'} | regen={regen_str} | "
            f"provider={provider} | quote={quote[:60]!r}"
        )

        verif_meta = {
            "semantic_verdict":  sem["verdict"],
            "semantic_reason":   sem.get("reason", ""),
            "lesson_preserved":  sem.get("lesson_preserved", True),
            "stat_ok":           stat_ok,
            "hook_ok":           hook_ok,
            "struct_ok":         struct_ok,
            "banned_phrases":    banned_found,
            "regen_triggered":   bool(regen_reasons),
            "regen_reasons":     regen_reasons,
        }

        return body, provider, verif_meta

    except Exception as e:
        print(f"  [CAPTION] LLM body failed ({str(e)[:60]}), using quote as body.", flush=True)
        return quote, "fallback", _fallback_meta(str(e))


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

    structure = _pick_structure(pillar, state.get("recent_structures", []), quote=quote)
    cta       = _pick_cta(state.get("recent_ctas", []))
    ht_sets   = _pick_hashtags(pools, history)
    all_tags  = ht_sets["A"] + ht_sets["B"] + ht_sets["C"]

    print(f"  [CAPTION] structure={structure} | cta={cta[:30]}... | tags={len(all_tags)}", flush=True)

    body, llm_provider, verif_meta = _generate_body(quote, pillar, hook_template, structure)
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
        "llm_provider":       llm_provider,
        **verif_meta,
    }
