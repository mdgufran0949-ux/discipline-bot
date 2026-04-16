"""
discipline_memory.py
Memory System for DisciplineFuel.
Tracks every post's metadata + performance. Prevents repetition.
Powers the self-improving loop: biases future content toward proven winners.

Usage (standalone): python tools/discipline_memory.py --test
Storage: .tmp/disciplinefuel/memory.json
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime

MEMORY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "memory.json")
)

SCORE_WEIGHTS = {
    "saves":    4,
    "shares":   3,
    "comments": 2,
    "likes":    1,
}

STRONG_THRESHOLD = 70   # score >= this → strong pattern
WEAK_THRESHOLD   = 30   # score <= this → weak pattern
AVOID_AFTER_N    = 3    # mark topic as avoid after N consecutive weak posts

# ── Schema ─────────────────────────────────────────────────────────────────────

_EMPTY_MEMORY = {
    "posts": [],
    "patterns": {
        "strong": [],        # list of {quote_type, design_style, format, score}
        "weak":   [],
        "avoid_topics":         [],
        "avoid_hook_keywords":  []
    },
    "stats": {
        "total_posts":         0,
        "by_quote_type":       {},
        "by_design_style":     {},
        "by_format":           {},
        "by_series":           {},
        "top_performing_series": None
    },
    "prompt_hints": {
        "best_hooks":          [],
        "best_quote_types":    [],
        "avoid_phrases":       []
    },
    "competitor_hints": {
        "top_hooks":            [],
        "power_words":          [],
        "winning_structures":   [],
        "benchmark_engagement": 0,
        "updated_at":           None
    },
    "last_upgraded": None
}


# ── I/O ────────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return json.loads(json.dumps(_EMPTY_MEMORY))
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(mem: dict) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    tmp = MEMORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)
    os.replace(tmp, MEMORY_PATH)


# ── Public read functions ──────────────────────────────────────────────────────

def is_duplicate(topic: str, quote_type: str, window: int = 30) -> bool:
    """True if same topic + quote_type combo appeared in the last `window` posts."""
    mem = _load()
    recent = mem["posts"][-window:]
    for post in recent:
        if post.get("topic", "").lower() == topic.lower() and \
           post.get("quote_type", "") == quote_type:
            return True
    return False


def should_avoid(topic: str = None, hook_keyword: str = None) -> bool:
    """True if topic or hook keyword is flagged as weak/avoid."""
    mem = _load()
    patterns = mem["patterns"]
    if topic and topic.lower() in [t.lower() for t in patterns["avoid_topics"]]:
        return True
    if hook_keyword and hook_keyword.lower() in [k.lower() for k in patterns["avoid_hook_keywords"]]:
        return True
    return False


def get_content_weights() -> dict:
    """
    Returns weighted probabilities for content decisions.
    80% toward proven strong patterns, 20% experimental.
    """
    mem = _load()
    strong = mem["patterns"]["strong"]

    # Default weights — aligned with what actually wins in the niche
    # (statement dominates real top posts; pain_driven / command rarely win)
    weights = {
        "format": {"image": 0.50, "carousel": 0.50},
        "design_style": {"dark": 0.50, "minimal": 0.20, "bold": 0.20, "luxury": 0.10},
        "quote_type": {
            "statement":   0.40,
            "contrast":    0.20,
            "punch":       0.15,
            "identity":    0.10,
            "question":    0.08,
            "command":     0.04,
            "pain_driven": 0.03
        }
    }

    if not strong:
        return weights

    # Count occurrences in strong patterns
    format_counts  = Counter(p.get("format") for p in strong if p.get("format"))
    style_counts   = Counter(p.get("design_style") for p in strong if p.get("design_style"))
    qtype_counts   = Counter(p.get("quote_type") for p in strong if p.get("quote_type"))

    def _boost(base: dict, counts: Counter, boost_factor: float = 2.0) -> dict:
        """Boost items that appear in strong patterns."""
        if not counts:
            return base
        total_strong = sum(counts.values())
        result = {}
        for key, default_w in base.items():
            strong_w = counts.get(key, 0) / total_strong if total_strong > 0 else 0
            # 80% proven, 20% experimental
            result[key] = 0.80 * (strong_w if strong_w > 0 else default_w) + 0.20 * default_w
        # Normalize
        total = sum(result.values())
        return {k: v / total for k, v in result.items()}

    weights["format"]       = _boost(weights["format"], format_counts)
    weights["design_style"] = _boost(weights["design_style"], style_counts)
    weights["quote_type"]   = _boost(weights["quote_type"], qtype_counts)

    return weights


def weighted_choice(weights: dict) -> str:
    """Pick a key from a weight dict probabilistically."""
    keys   = list(weights.keys())
    values = list(weights.values())
    return random.choices(keys, weights=values, k=1)[0]


def get_prompt_hints() -> dict:
    """Returns best hooks + quote types (own + competitor) to inject into LLM prompt."""
    mem = _load()
    own  = mem.get("prompt_hints", {}) or {}
    comp = mem.get("competitor_hints", {}) or {}
    return {
        "best_hooks":           own.get("best_hooks", []),
        "best_quote_types":     own.get("best_quote_types", []),
        "avoid_phrases":        own.get("avoid_phrases", []),
        "trending_hooks":       (comp.get("top_hooks") or [])[:5],
        "trending_power_words": (comp.get("power_words") or [])[:10],
        "trending_structures":  comp.get("winning_structures", []),
        "niche_benchmark":      comp.get("benchmark_engagement", 0),
    }


def update_competitor_hints(hints: dict) -> None:
    """Write competitor intel into memory for use by prompt hints."""
    mem = _load()
    current = mem.get("competitor_hints") or {}
    current.update({
        "top_hooks":            hints.get("top_hooks", current.get("top_hooks", [])),
        "power_words":          hints.get("power_words", current.get("power_words", [])),
        "winning_structures":   hints.get("winning_structures", current.get("winning_structures", [])),
        "benchmark_engagement": hints.get("benchmark_engagement", current.get("benchmark_engagement", 0)),
        "updated_at":           hints.get("updated_at", datetime.now().isoformat()),
    })
    mem["competitor_hints"] = current
    _save(mem)


def get_competitor_hints() -> dict:
    mem = _load()
    return mem.get("competitor_hints", {}) or {}


# ── Public write functions ─────────────────────────────────────────────────────

def log_post(post_data: dict) -> None:
    """
    Log a newly uploaded post to memory.
    Required fields: id, quote_type, design_style, format, series,
                     series_number, topic, hook_keyword, posted_at, ig_media_id
    """
    mem = _load()

    entry = {
        "id":            post_data.get("id", f"post_{int(time.time())}"),
        "quote_type":    post_data.get("quote_type", ""),
        "design_style":  post_data.get("design_style", ""),
        "format":        post_data.get("format", "image"),
        "series":        post_data.get("series", ""),
        "series_number": post_data.get("series_number", 0),
        "topic":         post_data.get("topic", ""),
        "hook_keyword":  post_data.get("hook_keyword", ""),
        "selected_quote": post_data.get("selected_quote", ""),
        "posted_at":     post_data.get("posted_at", datetime.now().isoformat()),
        "ig_media_id":   post_data.get("ig_media_id", ""),
        "performance": {
            "saves": 0, "shares": 0, "comments": 0, "likes": 0,
            "score": None, "fetched_at": None
        }
    }

    mem["posts"].append(entry)

    # Update stats
    stats = mem["stats"]
    stats["total_posts"] = len(mem["posts"])
    for field, stat_key in [("quote_type", "by_quote_type"),
                             ("design_style", "by_design_style"),
                             ("format", "by_format"),
                             ("series", "by_series")]:
        val = entry.get(field, "")
        if val:
            stats[stat_key][val] = stats[stat_key].get(val, 0) + 1

    _save(mem)


def update_performance(ig_media_id: str, metrics: dict) -> None:
    """
    Update performance data for a post after fetching IG metrics.
    Called by review_and_upgrade.py weekly.
    metrics: {saves, shares, comments, likes}
    """
    mem = _load()

    for post in mem["posts"]:
        if post.get("ig_media_id") == ig_media_id:
            perf = post["performance"]
            perf["saves"]     = metrics.get("saves", 0)
            perf["shares"]    = metrics.get("shares", 0)
            perf["comments"]  = metrics.get("comments", 0)
            perf["likes"]     = metrics.get("likes", 0)
            perf["score"]     = _compute_score(perf)
            perf["fetched_at"] = datetime.now().isoformat()
            break

    _save(mem)
    _rebuild_patterns(mem)
    _save(mem)


def _compute_score(perf: dict) -> float:
    return sum(perf.get(k, 0) * w for k, w in SCORE_WEIGHTS.items())


def _rebuild_patterns(mem: dict) -> None:
    """Rebuild strong/weak pattern lists from all scored posts."""
    scored_posts = [p for p in mem["posts"] if p["performance"]["score"] is not None]
    if not scored_posts:
        return

    strong_entries = []
    weak_entries   = []
    topic_scores   = {}

    for post in scored_posts:
        score = post["performance"]["score"]
        entry = {
            "quote_type":   post["quote_type"],
            "design_style": post["design_style"],
            "format":       post["format"],
            "series":       post["series"],
            "topic":        post["topic"],
            "hook_keyword": post["hook_keyword"],
            "score":        score
        }
        if score >= STRONG_THRESHOLD:
            strong_entries.append(entry)
        elif score <= WEAK_THRESHOLD:
            weak_entries.append(entry)

        # Track topic scores for avoid detection
        topic = post["topic"].lower()
        if topic not in topic_scores:
            topic_scores[topic] = []
        topic_scores[topic].append(score)

    mem["patterns"]["strong"] = strong_entries[-50:]   # keep last 50 strong
    mem["patterns"]["weak"]   = weak_entries[-50:]

    # Auto-avoid topics with N consecutive weak scores
    avoid_topics = set(mem["patterns"]["avoid_topics"])
    for topic, scores in topic_scores.items():
        if len(scores) >= AVOID_AFTER_N and all(s <= WEAK_THRESHOLD for s in scores[-AVOID_AFTER_N:]):
            avoid_topics.add(topic)
    mem["patterns"]["avoid_topics"] = list(avoid_topics)

    # Identify best hook keywords from strong posts
    strong_hooks = [p["hook_keyword"] for p in strong_entries if p.get("hook_keyword")]
    hook_counts  = Counter(strong_hooks)
    best_hooks   = [kw for kw, _ in hook_counts.most_common(5)]

    # Best quote types
    strong_qtypes = [p["quote_type"] for p in strong_entries if p.get("quote_type")]
    qtype_counts  = Counter(strong_qtypes)
    best_qtypes   = [qt for qt, _ in qtype_counts.most_common(3)]

    # Weak phrases to avoid
    weak_phrases = [p.get("selected_quote", "")[:30] for p in scored_posts
                    if p["performance"]["score"] is not None
                    and p["performance"]["score"] <= WEAK_THRESHOLD]

    mem["prompt_hints"] = {
        "best_hooks":       best_hooks,
        "best_quote_types": best_qtypes,
        "avoid_phrases":    weak_phrases[:10]
    }

    # Top performing series
    series_scores = {}
    for post in scored_posts:
        s = post.get("series", "")
        if s:
            series_scores.setdefault(s, []).append(post["performance"]["score"])
    if series_scores:
        avg_scores = {s: sum(v) / len(v) for s, v in series_scores.items()}
        mem["stats"]["top_performing_series"] = max(avg_scores, key=avg_scores.get)


# ── Report ─────────────────────────────────────────────────────────────────────

def generate_memory_report() -> dict:
    """Returns actionable insights from memory."""
    mem = _load()
    strong = mem["patterns"]["strong"]
    weak   = mem["patterns"]["weak"]

    scored = [p for p in mem["posts"] if p["performance"]["score"] is not None]
    if not scored:
        return {"status": "no_data", "message": "No scored posts yet. Run after 7 days."}

    # Top 5 best combos
    top5 = sorted(strong, key=lambda x: x["score"], reverse=True)[:5]
    # Worst 5 combos
    worst5 = sorted(weak, key=lambda x: x["score"])[:5]

    # Recommended mix
    weights = get_content_weights()
    hints   = get_prompt_hints()

    return {
        "total_posts_scored": len(scored),
        "top_performing": top5,
        "worst_performing": worst5,
        "avoid_topics": mem["patterns"]["avoid_topics"],
        "avoid_hook_keywords": mem["patterns"]["avoid_hook_keywords"],
        "recommended_weights": weights,
        "prompt_hints": hints,
        "top_series": mem["stats"].get("top_performing_series"),
        "stats": mem["stats"]
    }


# ── CLI / test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run unit tests")
    parser.add_argument("--report", action="store_true", help="Print memory report")
    args = parser.parse_args()

    if args.report:
        print(json.dumps(generate_memory_report(), indent=2))

    elif args.test:
        print("Running memory system tests...")

        # Test log_post
        log_post({
            "id": "test_001",
            "quote_type": "contrast",
            "design_style": "dark",
            "format": "image",
            "series": "discipline_rule",
            "series_number": 1,
            "topic": "procrastination is self-betrayal",
            "hook_keyword": "scared",
            "selected_quote": "You're not lazy. You're scared.",
            "posted_at": datetime.now().isoformat(),
            "ig_media_id": "TEST_MEDIA_001"
        })
        print("[OK] log_post works")

        # Test is_duplicate
        dup = is_duplicate("procrastination is self-betrayal", "contrast")
        assert dup, "Should detect duplicate"
        print("[OK] is_duplicate works")

        # Test get_content_weights
        weights = get_content_weights()
        assert "format" in weights and "design_style" in weights
        print(f"[OK] get_content_weights: format={weights['format']}")

        # Test weighted_choice
        choice = weighted_choice(weights["format"])
        assert choice in ("image", "carousel")
        print(f"[OK] weighted_choice: {choice}")

        # Simulate performance update
        update_performance("TEST_MEDIA_001", {"saves": 120, "shares": 45, "comments": 30, "likes": 200})
        print("[OK] update_performance works")

        report = generate_memory_report()
        print(f"[OK] report generated — {report.get('total_posts_scored', 0)} scored posts")
        print("\nAll tests passed.")

    else:
        print(json.dumps(generate_memory_report(), indent=2))
