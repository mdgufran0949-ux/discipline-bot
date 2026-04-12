"""
account_memory.py
Generalized memory system for any account (factsflash, cricketcuts, coresteel,
techmindblown, biscuit_zara, disciplinefuel).

Port of discipline_memory.py — same scoring, thresholding, and pattern logic,
but keyed by account_slug so state lives at .tmp/<account>/memory.json.

Usage:
    from account_memory import AccountMemory
    mem = AccountMemory("factsflash")
    mem.add_post({...})
    hints = mem.get_prompt_hints()
"""

import json
import os
import random
import time
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP_BASE     = os.path.join(PROJECT_ROOT, ".tmp")

# Scoring weights — Instagram engagement
IG_WEIGHTS = {"saves": 4, "shares": 3, "comments": 2, "likes": 1}

# Combined score formula (IG + YouTube)
#   score = ig_engagement + yt_views/1000 + yt_watchtime_min/10 + yt_ctr*50
STRONG_THRESHOLD = 70
WEAK_THRESHOLD   = 30
AVOID_AFTER_N    = 3

_EMPTY_MEMORY = {
    "account": "",
    "posts": [],
    "patterns": {
        "strong": [],
        "weak":   [],
        "avoid_topics":         [],
        "avoid_hook_keywords":  []
    },
    "stats": {
        "total_posts":           0,
        "by_quote_type":         {},
        "by_hook_type":          {},
        "by_topic":              {},
        "by_format":             {},
        "by_series":             {},
        "top_performing_series": None,
        "top_performing_topic":  None,
    },
    "prompt_hints": {
        "best_hooks":       [],
        "best_topics":      [],
        "best_quote_types": [],
        "avoid_phrases":    [],
    },
    "competitor_hints": {
        "top_hooks":            [],
        "power_words":          [],
        "winning_structures":   [],
        "benchmark_engagement": 0,
        "updated_at":           None,
    },
    "last_upgraded": None,
    "last_reviewed": None,
}


def compute_score(metrics: dict) -> float:
    """Combined score across IG + YouTube metrics."""
    ig = sum(metrics.get(k, 0) * w for k, w in IG_WEIGHTS.items())
    yt = (
        metrics.get("yt_views", 0) / 1000.0
        + metrics.get("yt_watchtime_min", 0) / 10.0
        + metrics.get("yt_ctr", 0) * 50.0
    )
    return round(ig + yt, 2)


class AccountMemory:
    def __init__(self, account_slug: str):
        self.account = account_slug
        self.path = os.path.join(TMP_BASE, account_slug, "memory.json")

    # ── I/O ────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            mem = json.loads(json.dumps(_EMPTY_MEMORY))
            mem["account"] = self.account
            return mem
        with open(self.path, "r", encoding="utf-8") as f:
            mem = json.load(f)
        # Fill missing top-level keys (schema migration)
        for k, v in _EMPTY_MEMORY.items():
            if k not in mem:
                mem[k] = json.loads(json.dumps(v))
        mem["account"] = self.account
        return mem

    def _save(self, mem: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        os.replace(tmp, self.path)

    # ── Reads ──────────────────────────────────────────────────────────────

    def is_duplicate(self, topic: str, window: int = 30) -> bool:
        """True if same topic appeared in the last `window` posts."""
        if not topic:
            return False
        mem = self._load()
        recent = mem["posts"][-window:]
        t = topic.lower().strip()
        return any(p.get("topic", "").lower().strip() == t for p in recent)

    def should_avoid(self, topic: str = None, hook_keyword: str = None) -> bool:
        mem = self._load()
        patterns = mem["patterns"]
        if topic and topic.lower() in [t.lower() for t in patterns["avoid_topics"]]:
            return True
        if hook_keyword and hook_keyword.lower() in [k.lower() for k in patterns["avoid_hook_keywords"]]:
            return True
        return False

    def get_content_weights(self) -> dict:
        """
        Returns weighted probabilities for content decisions.
        80% toward proven strong patterns, 20% experimental baseline.
        """
        mem = self._load()
        strong = mem["patterns"]["strong"]

        base = {
            "format":     {"image": 0.50, "video": 0.50},
            "hook_type":  {"question": 0.35, "fact": 0.35, "story": 0.15, "imperative": 0.15},
        }

        if not strong:
            return base

        format_counts = Counter(p.get("format")    for p in strong if p.get("format"))
        hook_counts   = Counter(p.get("hook_type") for p in strong if p.get("hook_type"))

        def _boost(defaults: dict, counts: Counter) -> dict:
            if not counts:
                return defaults
            total = sum(counts.values())
            out = {}
            for k, default_w in defaults.items():
                strong_w = counts.get(k, 0) / total if total else 0
                out[k] = 0.80 * (strong_w if strong_w > 0 else default_w) + 0.20 * default_w
            s = sum(out.values()) or 1
            return {k: v / s for k, v in out.items()}

        return {
            "format":    _boost(base["format"],    format_counts),
            "hook_type": _boost(base["hook_type"], hook_counts),
        }

    def get_topic_weights(self) -> dict:
        """Return {topic: weight} for weighted topic sampling. 80/20 mix."""
        mem = self._load()
        strong = mem["patterns"]["strong"]
        if not strong:
            return {}
        counts = Counter(p.get("topic", "") for p in strong if p.get("topic"))
        avoid  = set(t.lower() for t in mem["patterns"]["avoid_topics"])
        total  = sum(counts.values()) or 1
        return {
            topic: round(c / total, 3)
            for topic, c in counts.items()
            if topic.lower() not in avoid
        }

    def get_prompt_hints(self) -> dict:
        mem = self._load()
        own  = mem.get("prompt_hints", {}) or {}
        comp = mem.get("competitor_hints", {}) or {}
        return {
            "best_hooks":           own.get("best_hooks", []),
            "best_topics":          own.get("best_topics", []),
            "best_quote_types":     own.get("best_quote_types", []),
            "avoid_phrases":        own.get("avoid_phrases", []),
            "avoid_topics":         mem["patterns"].get("avoid_topics", []),
            "trending_hooks":       (comp.get("top_hooks") or [])[:5],
            "trending_power_words": (comp.get("power_words") or [])[:10],
            "trending_structures":  comp.get("winning_structures", []),
            "niche_benchmark":      comp.get("benchmark_engagement", 0),
        }

    def get_memory_report(self) -> dict:
        mem = self._load()
        scored = [p for p in mem["posts"] if p.get("performance", {}).get("score") is not None]
        if not scored:
            return {"status": "no_data", "account": self.account}

        strong = mem["patterns"]["strong"]
        weak   = mem["patterns"]["weak"]
        return {
            "account":            self.account,
            "total_posts_scored": len(scored),
            "top_performing":     sorted(strong, key=lambda x: x["score"], reverse=True)[:5],
            "worst_performing":   sorted(weak,   key=lambda x: x["score"])[:5],
            "avoid_topics":       mem["patterns"]["avoid_topics"],
            "prompt_hints":       self.get_prompt_hints(),
            "content_weights":    self.get_content_weights(),
            "top_series":         mem["stats"].get("top_performing_series"),
            "top_topic":          mem["stats"].get("top_performing_topic"),
            "stats":              mem["stats"],
        }

    # ── Writes ─────────────────────────────────────────────────────────────

    def add_post(self, post_meta: dict) -> None:
        """
        Log a new post. Accepts any of these fields (all optional except id):
            id, ig_media_id, yt_video_id, topic, hook, hook_type, hook_keyword,
            quote_type, design_style, format, series, series_number,
            selected_quote, caption, hashtags, scene_prompts, posted_at
        """
        mem = self._load()

        entry = {
            "id":             post_meta.get("id", f"post_{int(time.time())}"),
            "ig_media_id":    post_meta.get("ig_media_id", ""),
            "yt_video_id":    post_meta.get("yt_video_id", ""),
            "topic":          post_meta.get("topic", ""),
            "hook":           post_meta.get("hook", ""),
            "hook_type":      post_meta.get("hook_type", ""),
            "hook_keyword":   post_meta.get("hook_keyword", ""),
            "quote_type":     post_meta.get("quote_type", ""),
            "design_style":   post_meta.get("design_style", ""),
            "format":         post_meta.get("format", "video"),
            "series":         post_meta.get("series", ""),
            "series_number":  post_meta.get("series_number", 0),
            "selected_quote": post_meta.get("selected_quote", ""),
            "caption":        post_meta.get("caption", ""),
            "hashtags":       post_meta.get("hashtags", []),
            "scene_prompts":  post_meta.get("scene_prompts", []),
            "posted_at":      post_meta.get("posted_at", datetime.now().isoformat()),
            "performance": {
                "saves": 0, "shares": 0, "comments": 0, "likes": 0,
                "yt_views": 0, "yt_watchtime_min": 0, "yt_ctr": 0,
                "score": None, "fetched_at": None,
            },
        }

        mem["posts"].append(entry)

        stats = mem["stats"]
        stats["total_posts"] = len(mem["posts"])
        for field, stat_key in [("quote_type",   "by_quote_type"),
                                ("hook_type",    "by_hook_type"),
                                ("topic",        "by_topic"),
                                ("format",       "by_format"),
                                ("series",       "by_series")]:
            val = entry.get(field, "")
            if val:
                stats[stat_key][val] = stats[stat_key].get(val, 0) + 1

        self._save(mem)

    def update_performance(self, post_id: str, metrics: dict) -> None:
        """
        Update performance for a post. `post_id` matches on ig_media_id,
        yt_video_id, or id (first match wins).
        metrics: any of {saves, shares, comments, likes, yt_views,
                         yt_watchtime_min, yt_ctr}
        """
        mem = self._load()
        for post in mem["posts"]:
            if post_id in (post.get("ig_media_id"), post.get("yt_video_id"), post.get("id")):
                perf = post["performance"]
                for k in ("saves", "shares", "comments", "likes",
                          "yt_views", "yt_watchtime_min", "yt_ctr"):
                    if k in metrics:
                        perf[k] = metrics[k]
                perf["score"]      = compute_score(perf)
                perf["fetched_at"] = datetime.now().isoformat()
                break
        self._rebuild_patterns(mem)
        self._save(mem)

    def update_scores(self, perf_data: dict) -> None:
        """
        Bulk-update scores from a performance.json payload.
        perf_data: {post_id: {metrics dict}, ...}
        """
        mem = self._load()
        for post in mem["posts"]:
            for key in (post.get("ig_media_id"), post.get("yt_video_id"), post.get("id")):
                if key and key in perf_data:
                    perf = post["performance"]
                    metrics = perf_data[key]
                    for k in ("saves", "shares", "comments", "likes",
                              "yt_views", "yt_watchtime_min", "yt_ctr"):
                        if k in metrics:
                            perf[k] = metrics[k]
                    perf["score"]      = compute_score(perf)
                    perf["fetched_at"] = datetime.now().isoformat()
                    break
        self._rebuild_patterns(mem)
        mem["last_reviewed"] = datetime.now().isoformat()
        self._save(mem)

    def update_competitor_hints(self, hints: dict) -> None:
        mem = self._load()
        current = mem.get("competitor_hints") or {}
        current.update({
            "top_hooks":            hints.get("top_hooks", current.get("top_hooks", [])),
            "power_words":          hints.get("power_words", current.get("power_words", [])),
            "winning_structures":   hints.get("winning_structures", current.get("winning_structures", [])),
            "benchmark_engagement": hints.get("benchmark_engagement", current.get("benchmark_engagement", 0)),
            "updated_at":           hints.get("updated_at", datetime.now().isoformat()),
        })
        mem["competitor_hints"] = current
        self._save(mem)

    def mark_upgraded(self) -> None:
        mem = self._load()
        mem["last_upgraded"] = datetime.now().isoformat()
        self._save(mem)

    # ── Pattern extraction ─────────────────────────────────────────────────

    def _rebuild_patterns(self, mem: dict) -> None:
        scored = [p for p in mem["posts"] if p["performance"]["score"] is not None]
        if not scored:
            return

        strong_entries = []
        weak_entries   = []
        topic_scores   = {}

        for post in scored:
            score = post["performance"]["score"]
            entry = {
                "quote_type":   post.get("quote_type", ""),
                "hook_type":    post.get("hook_type", ""),
                "hook":         post.get("hook", ""),
                "hook_keyword": post.get("hook_keyword", ""),
                "topic":        post.get("topic", ""),
                "format":       post.get("format", ""),
                "series":       post.get("series", ""),
                "score":        score,
            }
            if score >= STRONG_THRESHOLD:
                strong_entries.append(entry)
            elif score <= WEAK_THRESHOLD:
                weak_entries.append(entry)

            topic = post.get("topic", "").lower()
            if topic:
                topic_scores.setdefault(topic, []).append(score)

        mem["patterns"]["strong"] = strong_entries[-50:]
        mem["patterns"]["weak"]   = weak_entries[-50:]

        # Auto-avoid topics with N consecutive weak posts
        avoid = set(mem["patterns"]["avoid_topics"])
        for topic, scores in topic_scores.items():
            if len(scores) >= AVOID_AFTER_N and all(s <= WEAK_THRESHOLD for s in scores[-AVOID_AFTER_N:]):
                avoid.add(topic)
        mem["patterns"]["avoid_topics"] = list(avoid)

        # Best hooks
        best_hooks = [h for h, _ in Counter(
            p["hook"] for p in strong_entries if p.get("hook")
        ).most_common(5)]

        # Best topics
        best_topics = [t for t, _ in Counter(
            p["topic"] for p in strong_entries if p.get("topic")
        ).most_common(5)]

        # Best quote types
        best_qtypes = [q for q, _ in Counter(
            p["quote_type"] for p in strong_entries if p.get("quote_type")
        ).most_common(3)]

        # Weak phrases to avoid
        weak_phrases = [p.get("selected_quote", "")[:30] for p in scored
                        if p["performance"]["score"] <= WEAK_THRESHOLD
                        and p.get("selected_quote")]

        mem["prompt_hints"] = {
            "best_hooks":       best_hooks,
            "best_topics":      best_topics,
            "best_quote_types": best_qtypes,
            "avoid_phrases":    weak_phrases[:10],
        }

        # Top performing series + topic
        series_scores = {}
        topic_avg     = {}
        for post in scored:
            s = post.get("series", "")
            t = post.get("topic", "")
            if s:
                series_scores.setdefault(s, []).append(post["performance"]["score"])
            if t:
                topic_avg.setdefault(t, []).append(post["performance"]["score"])
        if series_scores:
            avg = {s: sum(v) / len(v) for s, v in series_scores.items()}
            mem["stats"]["top_performing_series"] = max(avg, key=avg.get)
        if topic_avg:
            avg = {t: sum(v) / len(v) for t, v in topic_avg.items()}
            mem["stats"]["top_performing_topic"] = max(avg, key=avg.get)


def weighted_choice(weights: dict) -> str:
    """Pick a key from a {key: weight} dict probabilistically."""
    if not weights:
        return ""
    keys   = list(weights.keys())
    values = list(weights.values())
    return random.choices(keys, weights=values, k=1)[0]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    mem = AccountMemory(args.account)
    if args.report:
        print(json.dumps(mem.get_memory_report(), indent=2))
    else:
        print(json.dumps(mem.get_prompt_hints(), indent=2))
