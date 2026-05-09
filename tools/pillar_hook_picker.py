"""
pillar_hook_picker.py
Picks the next content pillar and hook template for DisciplineFuel.

Rules:
  - Never repeat the same pillar as the most recent post
  - Never repeat any of the last 3 hook templates
  - Prefer the least-used pillar and hook template in the last 10 tagged posts
  - Fall back to weighted random across the full set if all options are blocked
"""

import json
import logging
import os
import random

_TOOLS_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT       = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
_TMP_BASE   = os.path.join(_ROOT, ".tmp")
_LOGS_DIR   = os.path.join(_ROOT, "logs")

PILLARS        = ["hard_truth", "tactical", "reframe", "story_proof"]
HOOK_TEMPLATES = ["question", "contrarian", "stat_shock", "story", "command"]

HISTORY_WINDOW = 10   # look back this many tagged posts for preference scoring
PILLAR_BLOCK   = 1    # block the N most-recent pillars
HOOK_BLOCK     = 3    # block the N most-recent hook templates


def _log_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "uploaded_log.json")


def _load_recent_tagged(account: str, n: int) -> list:
    """Return the last n uploaded posts that have both pillar and hook_template set."""
    path = _log_path(account)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        posts = data.get("uploaded", [])
        tagged = [p for p in posts if p.get("pillar") and p.get("hook_template")]
        return tagged[-n:]
    except Exception:
        return []


def _setup_logger() -> logging.Logger:
    os.makedirs(_LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("pillar_hook_picker")
    if not logger.handlers:
        handler = logging.FileHandler(
            os.path.join(_LOGS_DIR, "pillar_hook_decisions.log"),
            encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _pick_least_used(options: list, blocked: set, counts: dict) -> str:
    """
    From `options`, exclude `blocked`, then return one of the least-used
    (by counts). Breaks ties randomly. If all are blocked, ignores block rules.
    """
    available = [o for o in options if o not in blocked]
    if not available:
        available = list(options)  # block rules overridden — all exhausted

    min_count = min(counts.get(o, 0) for o in available)
    candidates = [o for o in available if counts.get(o, 0) == min_count]
    return random.choice(candidates)


def pick_pillar_and_hook(account: str) -> tuple:
    """
    Return (pillar, hook_template) for the next post.
    Logs selection reasoning to logs/pillar_hook_decisions.log.
    """
    logger  = _setup_logger()
    history = _load_recent_tagged(account, HISTORY_WINDOW)

    recent_pillars = [p["pillar"] for p in history]
    recent_hooks   = [p["hook_template"] for p in history]

    # Block sets
    blocked_pillars = set(recent_pillars[-PILLAR_BLOCK:]) if recent_pillars else set()
    blocked_hooks   = set(recent_hooks[-HOOK_BLOCK:])     if recent_hooks   else set()

    # Usage counts over the history window
    pillar_counts = {p: recent_pillars.count(p) for p in PILLARS}
    hook_counts   = {h: recent_hooks.count(h)   for h in HOOK_TEMPLATES}

    chosen_pillar = _pick_least_used(PILLARS,        blocked_pillars, pillar_counts)
    chosen_hook   = _pick_least_used(HOOK_TEMPLATES, blocked_hooks,   hook_counts)

    reason = (
        f"account={account} | "
        f"pillar={chosen_pillar} blocked={sorted(blocked_pillars)} counts={pillar_counts} | "
        f"hook={chosen_hook} blocked={sorted(blocked_hooks)} counts={hook_counts} | "
        f"history_len={len(history)}"
    )
    logger.info(reason)
    print(f"  [PILLAR/HOOK] {chosen_pillar} + {chosen_hook}", flush=True)
    return chosen_pillar, chosen_hook


# ── Sanity check (run directly to verify block rules) ─────────────────────────

def _run_simulation(n: int = 100) -> None:
    """
    Simulate n picks against a fake growing history.
    Asserts no rule violations: pillar != last pillar, hook not in last 3 hooks.
    """
    import sys
    history = []
    violations = []

    for i in range(n):
        tagged  = [p for p in history if p.get("pillar") and p.get("hook_template")]
        recent  = tagged[-HISTORY_WINDOW:]
        r_pils  = [p["pillar"]        for p in recent]
        r_hooks = [p["hook_template"] for p in recent]

        bl_pil  = set(r_pils[-PILLAR_BLOCK:])
        bl_hook = set(r_hooks[-HOOK_BLOCK:])
        pc      = {p: r_pils.count(p)  for p in PILLARS}
        hc      = {h: r_hooks.count(h) for h in HOOK_TEMPLATES}

        # Check if all available options are actually blocked
        all_pils_blocked  = all(p in bl_pil  for p in PILLARS)
        all_hooks_blocked = all(h in bl_hook for h in HOOK_TEMPLATES)

        pillar = _pick_least_used(PILLARS,        bl_pil,  pc)
        hook   = _pick_least_used(HOOK_TEMPLATES, bl_hook, hc)

        # Validate block rules (only when not all-blocked fallback)
        if not all_pils_blocked and pillar in bl_pil:
            violations.append(f"pick {i+1}: pillar '{pillar}' in blocked {bl_pil}")
        if not all_hooks_blocked and hook in bl_hook:
            violations.append(f"pick {i+1}: hook '{hook}' in blocked {bl_hook}")

        history.append({"pillar": pillar, "hook_template": hook})

    print(f"\nSimulation: {n} picks")
    if violations:
        print(f"VIOLATIONS ({len(violations)}):")
        for v in violations[:10]:
            print(f"  {v}")
        sys.exit(1)
    else:
        print(f"  No rule violations in {n} picks.")
        # Print distribution
        pil_dist  = {p: sum(1 for h in history if h["pillar"] == p) for p in PILLARS}
        hook_dist = {h: sum(1 for e in history if e["hook_template"] == h) for h in HOOK_TEMPLATES}
        print(f"  Pillar distribution:  {pil_dist}")
        print(f"  Hook distribution:    {hook_dist}")
        print()
        # Print last 20 picks
        print("  Last 20 picks:")
        for e in history[-20:]:
            print(f"    {e['pillar']:12} + {e['hook_template']}")


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    _run_simulation(n)
