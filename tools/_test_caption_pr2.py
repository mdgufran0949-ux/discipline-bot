#!/usr/bin/env python3
"""
PR #2 round-2 caption verification — 8 samples, same quotes as round 1.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from caption_generator import (
    generate_caption,
    _verify_stat_preserved,
    PILLAR_STRUCTURE_PREF,
)

SAMPLES = [
    {
        "pillar": "hard_truth",
        "hook":   "question",
        "quote":  "Most people don't fail — they quit before the work gets interesting.",
    },
    {
        "pillar": "hard_truth",
        "hook":   "contrarian",
        "quote":  "The person who says they're always motivated is the same one who skips the gym.",
    },
    {
        "pillar": "tactical",
        "hook":   "stat_shock",
        "quote":  "92% of people who set goals never achieve them. The 8% who do write them down every single morning.",
    },
    {
        "pillar": "tactical",
        "hook":   "command",
        "quote":  "Track one habit for 30 days before adding another. Stacking too fast collapses everything.",
    },
    {
        "pillar": "reframe",
        "hook":   "contrarian",
        "quote":  "You are NOT lazy. You are overwhelmed and calling it laziness to avoid fixing the real problem.",
    },
    {
        "pillar": "reframe",
        "hook":   "question",
        "quote":  "What if every time you chose comfort over growth, you were voting for the person you'd be in five years?",
    },
    {
        "pillar": "story_proof",
        "hook":   "story",
        "quote":  "A monk at dawn would sit in silence for one hour before speaking a single word. He said silence was how he sharpened the knife.",
    },
    {
        "pillar": "story_proof",
        "hook":   "stat_shock",
        "quote":  "One day a student asked: how long to master discipline? The master said: your whole life. The student smiled — he had already begun.",
    },
]

ACCOUNT      = "disciplinefuel_test"
RUN_ONLY     = {1}   # set to None to run all 8

for i, s in enumerate(SAMPLES, 1):
    if RUN_ONLY and i not in RUN_ONLY:
        continue
    result = generate_caption(s["quote"], s["pillar"], s["hook"], ACCOUNT)

    from caption_generator import _HOOK_REQUIREMENTS
    stat_label   = "PASS" if result["stat_ok"] else ("FAIL" if s["hook"] == "stat_shock" else "N/A")
    hook_label   = "PASS" if result["hook_ok"] else ("FAIL" if s["hook"] in _HOOK_REQUIREMENTS else "N/A")
    lesson_label = "yes" if result["lesson_preserved"] else "no" if s["pillar"] == "story_proof" else "N/A"
    banned_label = result["banned_phrases"] if result["banned_phrases"] else "none"
    regen_label  = ("yes (" + "; ".join(result["regen_reasons"]) + ")"
                    if result["regen_triggered"] else "no")

    print(f"--- CAPTION {i} ---")
    print(f"Pillar: {s['pillar']}")
    print(f"Hook: {s['hook']}")
    print(f"Quote: \"{s['quote']}\"")
    print(f"Structure: {result['structure']}")
    print(f"CTA: \"{result['cta']}\"")
    print(f"Hashtags: {' '.join(result['hashtags'])}")
    print(f"LLM provider used: {result['llm_provider']}")
    print(f"Semantic verifier verdict: {result['semantic_verdict']}")
    print(f"Semantic verifier reason: \"{result['semantic_reason']}\"")
    print(f"Lesson preserved: {lesson_label}")
    print(f"Stat verification: {stat_label}")
    print(f"Hook alignment: {hook_label}")
    print(f"Banned phrases found: {banned_label}")
    print(f"Regeneration triggered: {regen_label}")
    print()
    print("FULL CAPTION:")
    print(result["caption"])
    print("--- END ---")
    print()
