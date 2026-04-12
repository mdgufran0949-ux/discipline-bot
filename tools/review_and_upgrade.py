"""
review_and_upgrade.py
Review + Self-Upgrading Engine for DisciplineFuel.

Runs daily (automatically triggered from run_discipline_pipeline.py).
Fetches real Instagram metrics → scores every post → identifies winning and
losing patterns → upgrades account config weights → refines LLM prompt hints
→ generates strategy report + human-readable REPORT.md.

Usage:
  python tools/review_and_upgrade.py --account disciplinefuel [--force]
  python tools/review_and_upgrade.py --report   # print latest report to stdout

Output:
  .tmp/disciplinefuel/strategy_report.json   — machine-readable full report
  .tmp/disciplinefuel/latest_report.md        — human-readable markdown (working copy)
  .tmp/disciplinefuel/change_history.jsonl   — append-only change log
  .tmp/disciplinefuel/last_prompt_hints.txt  — last rendered LLM prompt hints
  REPORT.md (repo root)                       — published copy committed by GH Actions
"""

import argparse
import json
import os
import re
import sys
import requests
import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
import discipline_memory as mem_module
import fetch_competitor_intel as competitor_tool

GRAPH_BASE  = "https://graph.facebook.com/v19.0"
CONFIG_DIR  = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE    = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SCORE_WEIGHTS        = {"saves": 4, "shares": 3, "comments": 2, "likes": 1}
REVIEW_INTERVAL_DAYS = 1


# ── Config helpers ─────────────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(account: str, cfg: dict) -> None:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def _log_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "uploaded_log.json")


def _report_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "strategy_report.json")


def _load_log(account: str) -> dict:
    path = _log_path(account)
    if not os.path.exists(path):
        return {"uploaded": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Instagram metrics fetching ─────────────────────────────────────────────────

def _fetch_ig_metrics(ig_media_id: str, ig_access_token: str) -> dict:
    """Fetch saves, shares, comments, likes for a single post."""
    basic_resp = requests.get(
        f"{GRAPH_BASE}/{ig_media_id}",
        params={"fields": "like_count,comments_count", "access_token": ig_access_token},
        timeout=20
    )
    if not basic_resp.ok:
        return {}
    basic = basic_resp.json()
    result = {
        "saves":    0,
        "shares":   0,
        "comments": basic.get("comments_count", 0),
        "likes":    basic.get("like_count", 0),
    }
    try:
        ins_resp = requests.get(
            f"{GRAPH_BASE}/{ig_media_id}/insights",
            params={"metric": "saved,shares", "access_token": ig_access_token},
            timeout=20
        )
        if ins_resp.ok:
            for item in ins_resp.json().get("data", []):
                name = item.get("name", "")
                val  = item.get("values", [{}])[0].get("value", 0) if item.get("values") else item.get("value", 0)
                if name == "saved":
                    result["saves"] = val
                elif name == "shares":
                    result["shares"] = val
    except Exception:
        pass
    return result


def _compute_score(metrics: dict) -> float:
    return sum(metrics.get(k, 0) * w for k, w in SCORE_WEIGHTS.items())


# ── Review loop ────────────────────────────────────────────────────────────────

def _should_run(account: str) -> bool:
    mem_data = mem_module._load()
    last = mem_data.get("last_upgraded")
    if not last:
        return True
    last_dt = datetime.datetime.fromisoformat(last)
    return (datetime.datetime.now() - last_dt).days >= REVIEW_INTERVAL_DAYS


def fetch_and_score_posts(account: str, ig_access_token: str, force: bool = False) -> list:
    log    = _load_log(account)
    posts  = log.get("uploaded", [])
    scored = []

    print(f"Fetching metrics for {len(posts)} posts...", flush=True)
    for post in posts:
        media_id = post.get("ig_media_id", "")
        if not media_id:
            continue
        fetched_at = post.get("metrics_fetched_at", "")
        if not force and fetched_at:
            try:
                last = datetime.datetime.fromisoformat(fetched_at)
                if (datetime.datetime.now() - last).total_seconds() < 86400:
                    scored.append(post)
                    continue
            except Exception:
                pass

        metrics = _fetch_ig_metrics(media_id, ig_access_token)
        if not metrics:
            print(f"  [SKIP] {media_id}: could not fetch metrics", flush=True)
            continue

        score = _compute_score(metrics)
        post.update(metrics)
        post["score"]              = score
        post["metrics_fetched_at"] = datetime.datetime.now().isoformat()
        scored.append(post)

        mem_module.update_performance(media_id, metrics)
        print(f"  [OK] {media_id}: score={score:.0f} (saves={metrics['saves']}, shares={metrics['shares']})", flush=True)

    return scored


# ── Config upgrader ────────────────────────────────────────────────────────────

def upgrade_config(account: str, scored_posts: list) -> dict:
    """
    Rebalance account config weights based on performance data.
    Returns upgrade summary including before/after deltas.
    """
    if not scored_posts:
        return {"status": "no_data"}

    cfg = _load_config(account)

    # Snapshot BEFORE values for delta reporting
    old_format_mix    = dict(cfg.get("content_format_mix", {"image": 0.50, "carousel": 0.50}))
    styles            = cfg.get("design_styles", ["dark", "minimal", "bold", "luxury"])
    old_style_weights = dict(zip(styles, cfg.get("design_style_weights", [0.5, 0.2, 0.2, 0.1])))
    old_hints         = cfg.get("content_preferences", {})
    old_avoid_topics  = list(old_hints.get("avoid_topics", []))
    old_best_hooks    = list(old_hints.get("best_hooks", []))

    # Get updated weights from memory
    weights = mem_module.get_content_weights()

    # Update design_style_weights
    new_style_weights = [round(weights["design_style"].get(s, 0.1), 3) for s in styles]
    total = sum(new_style_weights) or 1
    new_style_weights = [round(w / total, 3) for w in new_style_weights]
    cfg["design_style_weights"] = new_style_weights

    # Update content_format_mix
    cfg["content_format_mix"] = {k: round(v, 3) for k, v in weights["format"].items()}

    # Blend competitor media-type signal into format mix
    intel_path = os.path.join(TMP_BASE, account, "competitor_intel.json")
    if os.path.exists(intel_path):
        try:
            with open(intel_path, "r", encoding="utf-8") as f:
                intel = json.load(f)
            media_mix = intel.get("patterns", {}).get("best_media_types", {})
            if media_mix:
                carousel_pct = media_mix.get("CAROUSEL_ALBUM", 0.0)
                image_pct    = media_mix.get("IMAGE", 0.0) + media_mix.get("VIDEO", 0.0)
                current      = cfg["content_format_mix"]
                blended = {
                    "image":    round((current.get("image", 0.5)    + image_pct)    / 2, 3),
                    "carousel": round((current.get("carousel", 0.5) + carousel_pct) / 2, 3),
                }
                tot = blended["image"] + blended["carousel"] or 1
                cfg["content_format_mix"] = {
                    "image":    round(blended["image"]    / tot, 3),
                    "carousel": round(blended["carousel"] / tot, 3),
                }
        except Exception as e:
            print(f"  [WARN] Competitor media-type blend failed: {e}", flush=True)

    # Update content_preferences
    hints = mem_module.get_prompt_hints()
    new_avoid_topics = mem_module._load()["patterns"]["avoid_topics"]
    new_best_hooks   = hints.get("best_hooks", [])
    cfg["content_preferences"] = {
        "best_quote_types": hints.get("best_quote_types", []),
        "best_hooks":       new_best_hooks,
        "avoid_phrases":    hints.get("avoid_phrases", []),
        "avoid_topics":     new_avoid_topics,
    }

    _save_config(account, cfg)

    new_format_mix    = cfg["content_format_mix"]
    new_style_weights_dict = dict(zip(styles, new_style_weights))

    # Compute deltas
    format_delta = {
        k: round(new_format_mix.get(k, 0) - old_format_mix.get(k, 0), 3)
        for k in set(list(old_format_mix.keys()) + list(new_format_mix.keys()))
    }
    style_delta = {
        s: round(new_style_weights_dict.get(s, 0) - old_style_weights.get(s, 0), 3)
        for s in styles
    }
    hooks_added   = [h for h in new_best_hooks  if h not in old_best_hooks]
    hooks_removed = [h for h in old_best_hooks  if h not in new_best_hooks]
    topics_new    = [t for t in new_avoid_topics if t not in old_avoid_topics]

    print(f"[OK] Config upgraded: styles={new_style_weights}, format={cfg['content_format_mix']}", flush=True)

    return {
        "new_style_weights":       new_style_weights_dict,
        "new_format_mix":          new_format_mix,
        "prompt_hints":            hints,
        "avoid_topics_count":      len(new_avoid_topics),
        "changes_applied": {
            "format_mix_before":        old_format_mix,
            "format_mix_after":         new_format_mix,
            "format_mix_delta":         format_delta,
            "style_weights_before":     old_style_weights,
            "style_weights_after":      new_style_weights_dict,
            "style_weights_delta":      style_delta,
            "hooks_added":              hooks_added,
            "hooks_removed":            hooks_removed,
            "topics_blacklisted_new":   topics_new,
        }
    }


# ── Report helpers ─────────────────────────────────────────────────────────────

def _check_hook_adoption(account: str, trending_hints: dict) -> dict:
    """Check if recent posts actually used trending power-words from competitor intel."""
    log   = _load_log(account)
    posts = log.get("uploaded", [])[-20:]
    power_words = [w.lower() for w in (trending_hints.get("trending_power_words") or [])]
    if not power_words or not posts:
        return {"adopted": 0, "ignored": 0, "total": 0, "rate_pct": 0,
                "examples_adopted": [], "examples_ignored": []}

    adopted_ex  = []
    ignored_ex  = []
    for p in posts:
        quote = (p.get("selected_quote") or p.get("quote") or "").lower()
        if not quote:
            continue
        used = [w for w in power_words if w in quote]
        snippet = quote[:70] + ("..." if len(quote) > 70 else "")
        if used:
            adopted_ex.append(f'"{snippet}" (words: {", ".join(used[:3])})')
        else:
            ignored_ex.append(f'"{snippet}"')

    total   = len(adopted_ex) + len(ignored_ex)
    adopted = len(adopted_ex)
    return {
        "adopted":          adopted,
        "ignored":          len(ignored_ex),
        "total":            total,
        "rate_pct":         round(adopted / total * 100) if total else 0,
        "examples_adopted": adopted_ex[:2],
        "examples_ignored": ignored_ex[:2],
    }


def _system_health(account: str) -> dict:
    """Aggregate system health indicators."""
    now    = datetime.datetime.now()
    health = {}

    # Last competitor fetch
    intel_path = os.path.join(TMP_BASE, account, "competitor_intel.json")
    if os.path.exists(intel_path):
        try:
            with open(intel_path) as f:
                d = json.load(f)
            ts      = d.get("last_updated", "")
            dt      = datetime.datetime.fromisoformat(ts) if ts else None
            age_h   = round((now - dt).total_seconds() / 3600, 1) if dt else None
            health["last_competitor_fetch"] = ts
            health["competitor_fetch_age_h"] = age_h
            health["competitor_fetch_ok"]   = age_h is not None and age_h < 50
            health["competitor_posts_last"] = d.get("total_posts_analyzed", 0)
        except Exception:
            health["last_competitor_fetch"]  = None
            health["competitor_fetch_ok"]    = False
    else:
        health["last_competitor_fetch"] = None
        health["competitor_fetch_ok"]   = False

    # Last IG metrics fetch
    log   = _load_log(account)
    posts = log.get("uploaded", [])
    fetched_times = [p.get("metrics_fetched_at") for p in posts if p.get("metrics_fetched_at")]
    if fetched_times:
        last_metrics = max(fetched_times)
        dt = datetime.datetime.fromisoformat(last_metrics)
        health["last_metrics_fetch"]    = last_metrics
        health["metrics_fetch_age_h"]   = round((now - dt).total_seconds() / 3600, 1)
        health["metrics_fetch_ok"]      = (now - dt).total_seconds() < 172800  # 48h
    else:
        health["last_metrics_fetch"]  = None
        health["metrics_fetch_ok"]    = False

    # Hashtag quota used in last 7 days from change_history.jsonl
    history_path = os.path.join(TMP_BASE, account, "change_history.jsonl")
    quota_used   = 0
    consec_fails = 0
    if os.path.exists(history_path):
        seen_hashtags = set()
        week_ago = now - datetime.timedelta(days=7)
        try:
            with open(history_path) as f:
                lines = f.readlines()
            for line in lines:
                try:
                    entry = json.loads(line)
                    ts    = datetime.datetime.fromisoformat(entry.get("timestamp", "2000-01-01"))
                    if ts < week_ago:
                        continue
                    for h in entry.get("competitor_learnings", {}).get("hashtags_scanned", []):
                        seen_hashtags.add(h)
                    if entry.get("competitor_learnings", {}).get("posts_analyzed", 0) == 0:
                        consec_fails += 1
                    else:
                        consec_fails = 0
                except Exception:
                    pass
        except Exception:
            pass
        quota_used = len(seen_hashtags)

    health["ig_hashtag_quota_used_7d"] = quota_used
    health["ig_hashtag_quota_limit"]   = 30
    health["hashtag_quota_ok"]         = quota_used <= 25
    health["consecutive_failed_fetches"] = consec_fails

    return health


def _render_trend_table(account: str, n: int = 7) -> list:
    """Read last n entries from change_history.jsonl, return list of row dicts."""
    history_path = os.path.join(TMP_BASE, account, "change_history.jsonl")
    if not os.path.exists(history_path):
        return []
    rows = []
    try:
        with open(history_path) as f:
            lines = f.readlines()
        for line in reversed(lines[-n:]):
            try:
                e   = json.loads(line)
                cl  = e.get("competitor_learnings", {})
                ch  = e.get("changes_applied", {})
                fmt = ch.get("format_mix_after", {})
                rows.append({
                    "date":       e.get("timestamp", "")[:10],
                    "our_avg":    e.get("our_avg_engagement", 0),
                    "niche_avg":  cl.get("benchmark_engagement", 0),
                    "carousel_pct": round(fmt.get("carousel", 0) * 100),
                })
            except Exception:
                pass
    except Exception:
        pass
    return list(reversed(rows))


def append_change_history(account: str, entry: dict) -> None:
    """Append one JSON line to change_history.jsonl."""
    path = os.path.join(TMP_BASE, account, "change_history.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry["timestamp"] = datetime.datetime.now().isoformat()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def write_human_report(account: str, report: dict) -> None:
    """Write a human-readable markdown report. Copies to repo root REPORT.md."""
    now_str  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines    = []

    lines.append(f"# DisciplineFuel — Review Report")
    lines.append(f"Generated: {now_str}\n")

    # ── System Health ──────────────────────────────────────────────────────────
    health = report.get("system_health", {})
    def _ok(flag): return "✅" if flag else "⚠️"
    health_issues = [
        k for k, v in {
            "competitor_fetch": health.get("competitor_fetch_ok", True),
            "metrics_fetch":    health.get("metrics_fetch_ok", True),
            "hashtag_quota":    health.get("hashtag_quota_ok", True),
        }.items() if not v
    ]
    if health_issues:
        lines.append(f"> ⚠️ **ATTENTION NEEDED:** {', '.join(health_issues)}\n")

    lines.append("## System Health")
    lines.append(f"- Last competitor fetch: {health.get('last_competitor_fetch', 'never')[:16] if health.get('last_competitor_fetch') else 'never'} {_ok(health.get('competitor_fetch_ok'))}")
    lines.append(f"- Last IG metrics fetch: {health.get('last_metrics_fetch', 'never')[:16] if health.get('last_metrics_fetch') else 'never'} {_ok(health.get('metrics_fetch_ok'))}")
    lines.append(f"- IG hashtag quota used (7d): {health.get('ig_hashtag_quota_used_7d', 0)} / 30 {_ok(health.get('hashtag_quota_ok'))}")
    lines.append(f"- Consecutive failed competitor fetches: {health.get('consecutive_failed_fetches', 0)}\n")

    # ── Trend table ────────────────────────────────────────────────────────────
    trend_rows = report.get("trend_rows", [])
    if trend_rows:
        lines.append("## Trend (Last 7 Runs)")
        lines.append("| Date       | Our Avg | Niche Avg | Carousel% |")
        lines.append("|------------|---------|-----------|-----------|")
        for r in trend_rows:
            lines.append(f"| {r['date']} | {int(r['our_avg']):,} | {int(r['niche_avg']):,} | {r['carousel_pct']}% |")
        lines.append("")

    # ── What Changed Today ─────────────────────────────────────────────────────
    ch = report.get("changes_applied", {})
    lines.append("## What Changed Today")
    fmt_before = ch.get("format_mix_before", {})
    fmt_after  = ch.get("format_mix_after", {})
    if fmt_before and fmt_after:
        img_b  = round(fmt_before.get("image", 0) * 100)
        img_a  = round(fmt_after.get("image", 0) * 100)
        car_b  = round(fmt_before.get("carousel", 0) * 100)
        car_a  = round(fmt_after.get("carousel", 0) * 100)
        if img_b != img_a or car_b != car_a:
            lines.append(f"- Format mix: image {img_b}% → {img_a}%, carousel {car_b}% → {car_a}%")
        else:
            lines.append(f"- Format mix: unchanged (image {img_a}%, carousel {car_a}%)")

    style_delta = ch.get("style_weights_delta", {})
    big_style = {k: v for k, v in style_delta.items() if abs(v) >= 0.01}
    if big_style:
        parts = [f"{k} {'+' if v > 0 else ''}{round(v*100)}%" for k, v in big_style.items()]
        lines.append(f"- Style weights shifted: {', '.join(parts)}")

    for h in ch.get("hooks_added", []):
        lines.append(f"- Added hook to prompt: \"{h[:80]}\"")
    for h in ch.get("hooks_removed", []):
        lines.append(f"- Removed hook from prompt: \"{h[:80]}\"")
    for t in ch.get("topics_blacklisted_new", []):
        lines.append(f"- Blacklisted topic: \"{t}\"")

    if not (big_style or ch.get("hooks_added") or ch.get("topics_blacklisted_new")):
        if fmt_before == fmt_after:
            lines.append("- No significant changes this run (system is stable)")
    lines.append("")

    # ── Competitor Learnings ────────────────────────────────────────────────────
    cl = report.get("competitor_learnings", {})
    lines.append("## What We Learned From Competitors")
    if cl.get("posts_analyzed", 0) == 0:
        lines.append("- No competitor data this run (API unavailable or cached)")
    else:
        lines.append(f"- Scanned hashtags: {', '.join(cl.get('hashtags_scanned', []))}")
        lines.append(f"- Posts analyzed: {cl.get('posts_analyzed', 0)}")
        our_avg   = cl.get("our_avg_engagement", 0)
        niche_avg = cl.get("benchmark_engagement", 0)
        gap_pct   = round((our_avg - niche_avg) / niche_avg * 100) if niche_avg > 0 else None
        gap_str   = f"{gap_pct:+}%" if gap_pct is not None else "N/A"
        lines.append(f"- Niche benchmark: {int(niche_avg):,} avg engagement | Our avg: {int(our_avg):,} | Gap: {gap_str}")
        hooks = cl.get("top_hooks_learned", [])
        if hooks:
            lines.append("- Top hooks trending in niche:")
            for i, h in enumerate(hooks[:5], 1):
                lines.append(f"  {i}. \"{h[:90]}\"")
        pw = cl.get("top_power_words", [])
        if pw:
            lines.append(f"- Hot power words: {', '.join(pw[:8])}")
        if cl.get("dominant_structure"):
            lines.append(f"- Dominant quote structure: **{cl['dominant_structure']}**")
        if cl.get("dominant_media_type"):
            lines.append(f"- Dominant media type: **{cl['dominant_media_type']}**")
        if cl.get("caption_length_sweet_spot"):
            lines.append(f"- Caption length sweet spot: {cl['caption_length_sweet_spot']}")
    lines.append("")

    # ── Hook Adoption ──────────────────────────────────────────────────────────
    ha = report.get("hook_adoption", {})
    lines.append("## Hook Adoption (Did We Use the Learnings?)")
    if ha.get("total", 0) == 0:
        lines.append("- No recent posts to check yet")
    else:
        icon = "✅" if ha.get("rate_pct", 0) >= 50 else "⚠️"
        lines.append(f"- {ha['adopted']} / {ha['total']} recent posts used trending power-words ({ha['rate_pct']}%) {icon}")
        for ex in ha.get("examples_adopted", []):
            lines.append(f"  - ✅ {ex}")
        for ex in ha.get("examples_ignored", []):
            lines.append(f"  - ⚠️ {ex}")
    lines.append("")

    # ── LLM Prompt Snapshot ────────────────────────────────────────────────────
    hints_path = os.path.join(TMP_BASE, account, "last_prompt_hints.txt")
    lines.append("## What the LLM Saw Last Run (Prompt Hints)")
    if os.path.exists(hints_path):
        try:
            with open(hints_path, encoding="utf-8") as f:
                hints_txt = f.read().strip()
            lines.append("```")
            lines.append(hints_txt[:800] + ("..." if len(hints_txt) > 800 else ""))
            lines.append("```")
        except Exception:
            lines.append("_(could not read prompt hints file)_")
    else:
        lines.append("_(not yet generated — will appear after first pipeline run)_")
    lines.append("")

    # ── Recent Generated Quotes ────────────────────────────────────────────────
    log   = _load_log(account)
    posts = log.get("uploaded", [])
    recent_posts = [p for p in reversed(posts) if p.get("selected_quote") or p.get("quote")][:3]
    lines.append("## Recent Generated Quotes (last 3)")
    if recent_posts:
        for i, p in enumerate(recent_posts, 1):
            qt   = p.get("quote_type", "?")
            ds   = p.get("design_style", "?")
            fmt  = p.get("format", "?")
            q    = (p.get("selected_quote") or p.get("quote", ""))[:80]
            lines.append(f"{i}. **{qt}** ({ds}, {fmt}) — \"{q}\"")
    else:
        lines.append("_(no uploaded posts with quotes yet)_")
    lines.append("")

    # ── Our Performance ────────────────────────────────────────────────────────
    lines.append("## Our Performance")
    total = report.get("total_posts", 0)
    if total:
        niche_avg = cl.get("benchmark_engagement", 0) if cl else 0
        our_avg   = report.get("avg_score", 0)
        lines.append(f"| Metric           | Us      | Niche Top  |")
        lines.append(f"|------------------|---------|------------|")
        lines.append(f"| Posts scored     | {total}     | —          |")
        lines.append(f"| Avg score        | {report.get('avg_score', 0):.1f}   | —          |")
        lines.append(f"| High performers  | {report.get('high_performers', 0)}       | —          |")
        if niche_avg:
            gap = round((our_avg - niche_avg) / niche_avg * 100) if niche_avg else None
            gap_str = f"{gap:+}%" if gap is not None else "N/A"
            lines.append(f"| Avg engagement   | {int(our_avg):,}   | {int(niche_avg):,}      | {gap_str} |")
    else:
        lines.append("_(no scored posts yet — metrics accumulate after 48h)_")
    lines.append("")

    # ── Next Actions ───────────────────────────────────────────────────────────
    lines.append("## Next Actions (Auto-applied)")
    hints = report.get("upgrade_applied", {}).get("prompt_hints", {})
    ts_list = hints.get("trending_structures", [])
    if ts_list:
        lines.append(f"- Quote generator biased toward: **{', '.join(ts_list[:2])}** structures")
    fmt_after = ch.get("format_mix_after", {})
    if fmt_after:
        lines.append(f"- Carousel ratio set to {round(fmt_after.get('carousel', 0) * 100)}%")
    thooks = hints.get("trending_hooks", [])
    if thooks:
        lines.append(f"- {len(thooks)} trending hooks injected into next LLM prompts")
    lines.append("")
    lines.append("---")
    lines.append("*Auto-generated by DisciplineFuel self-improvement loop*")

    md = "\n".join(lines)

    # Write working copy
    working_path = os.path.join(TMP_BASE, account, "latest_report.md")
    os.makedirs(os.path.dirname(working_path), exist_ok=True)
    tmp = working_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(tmp, working_path)

    # Publish to repo root
    repo_report = os.path.join(REPO_ROOT, "REPORT.md")
    with open(repo_report, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[OK] Human report written: {working_path}", flush=True)
    print(f"[OK] REPORT.md updated at repo root", flush=True)


# ── Strategy report ────────────────────────────────────────────────────────────

def generate_strategy_report(account: str, scored_posts: list, upgrade_summary: dict,
                              competitor_intel: dict = None) -> dict:
    """Generate machine-readable strategy report + rich human report."""
    now     = datetime.datetime.now()
    mem_rep = mem_module.generate_memory_report()
    hints   = mem_module.get_prompt_hints()

    # Our avg engagement from scored posts
    our_avg_eng = 0
    if scored_posts:
        our_avg_eng = sum(
            (p.get("likes", 0) + p.get("comments", 0)) for p in scored_posts
        ) / len(scored_posts)

    # Competitor learnings section
    cl = {}
    if competitor_intel and competitor_intel.get("patterns"):
        pat = competitor_intel["patterns"]
        media_mix = pat.get("best_media_types", {})
        dominant_media = max(media_mix, key=media_mix.get) + f" ({round(max(media_mix.values())*100)}%)" if media_mix else "unknown"
        cap_len = pat.get("caption_length_winners", {})
        sweet_spot = max(cap_len, key=cap_len.get) if cap_len else "unknown"
        struct = pat.get("top_quote_structures", {})
        dom_struct = max(struct, key=struct.get) if struct else "unknown"
        cl = {
            "hashtags_scanned":          competitor_intel.get("hashtags_scanned", []),
            "posts_analyzed":            competitor_intel.get("total_posts_analyzed", 0),
            "benchmark_engagement":      pat.get("avg_engagement_top_25", 0),
            "our_avg_engagement":        round(our_avg_eng, 1),
            "top_hooks_learned":         pat.get("top_hooks", [])[:5],
            "top_power_words":           pat.get("power_words", [])[:8],
            "dominant_structure":        dom_struct,
            "dominant_media_type":       dominant_media,
            "caption_length_sweet_spot": sweet_spot,
        }

    # Core report body
    report: dict = {
        "account":       account,
        "generated_at":  now.isoformat(),
        "period_days":   REVIEW_INTERVAL_DAYS,
        "total_posts":   len(scored_posts),
        "avg_score":     0,
        "avg_saves":     0,
        "high_performers":   0,
        "medium_performers": 0,
        "low_performers":    0,
        "avoid_topics":  mem_rep.get("avoid_topics", []),
        "upgrade_applied": upgrade_summary,
        "changes_applied": upgrade_summary.get("changes_applied", {}),
        "competitor_learnings": cl,
        "hook_adoption":       {},
        "system_health":       {},
        "trend_rows":          [],
        "self_improvement_loop": {
            "strong_patterns_learned": len(mem_rep.get("top_performing", [])),
            "weak_patterns_flagged":   len(mem_rep.get("worst_performing", [])),
            "topics_blacklisted":      len(mem_rep.get("avoid_topics", [])),
            "prompt_updated":          bool(hints.get("best_hooks") or hints.get("trending_hooks"))
        }
    }

    if scored_posts:
        high   = [p for p in scored_posts if p.get("score", 0) >= mem_module.STRONG_THRESHOLD]
        medium = [p for p in scored_posts if mem_module.WEAK_THRESHOLD < p.get("score", 0) < mem_module.STRONG_THRESHOLD]
        low    = [p for p in scored_posts if p.get("score", 0) <= mem_module.WEAK_THRESHOLD]
        top5   = sorted(scored_posts, key=lambda x: x.get("score", 0), reverse=True)[:5]
        worst5 = sorted(scored_posts, key=lambda x: x.get("score", 0))[:5]
        strong_combos = Counter(
            f"{p.get('quote_type','?')}+{p.get('design_style','?')}+{p.get('format','?')}"
            for p in high
        )
        avg_score = sum(p.get("score", 0) for p in scored_posts) / len(scored_posts)
        avg_saves = sum(p.get("saves", 0) for p in scored_posts) / len(scored_posts)
        report.update({
            "high_performers":   len(high),
            "medium_performers": len(medium),
            "low_performers":    len(low),
            "avg_score":         round(avg_score, 1),
            "avg_saves":         round(avg_saves, 1),
            "top_5_posts":  [{"quote": p.get("selected_quote", p.get("quote", ""))[:60],
                               "series": p.get("content_series", ""),
                               "style": p.get("design_style", ""), "format": p.get("format", ""),
                               "score": round(p.get("score", 0), 1), "saves": p.get("saves", 0),
                               "shares": p.get("shares", 0)} for p in top5],
            "worst_5_posts": [{"quote": p.get("selected_quote", p.get("quote", ""))[:60],
                                "style": p.get("design_style", ""), "score": round(p.get("score", 0), 1)} for p in worst5],
            "best_combinations": dict(strong_combos.most_common(5)),
            "next_week_strategy": {
                "double_down": [c for c, _ in strong_combos.most_common(3)],
                "experiment":  "20% of posts should test new quote types/styles",
                "avoid":       mem_rep.get("avoid_topics", [])[:5]
            }
        })

    # Enrich with hook adoption, health, trend
    report["hook_adoption"] = _check_hook_adoption(account, hints)
    report["system_health"] = _system_health(account)
    report["trend_rows"]    = _render_trend_table(account)
    report["our_avg_engagement"] = round(our_avg_eng, 1)

    # Save JSON report
    report_path = _report_path(account)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    tmp = report_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, report_path)
    print(f"[OK] Strategy report saved: {report_path}", flush=True)

    # Write human-readable markdown
    write_human_report(account, report)

    # Append to change history
    append_change_history(account, {
        "changes_applied":     report.get("changes_applied", {}),
        "competitor_learnings": cl,
        "our_avg_engagement":  round(our_avg_eng, 1),
        "total_posts_scored":  len(scored_posts),
    })

    return report


# ── Main ───────────────────────────────────────────────────────────────────────

def run_review(account: str = "disciplinefuel", force: bool = False) -> dict:
    """Full review + upgrade + report cycle."""
    if not force and not _should_run(account):
        print(f"[SKIP] Review ran less than {REVIEW_INTERVAL_DAYS} days ago.", flush=True)
        return {"status": "skipped", "reason": "too_soon"}

    print(f"\n{'='*55}", flush=True)
    print(f"REVIEW + UPGRADE + REPORT: {account.upper()}", flush=True)
    print(f"{'='*55}\n", flush=True)

    cfg             = _load_config(account)
    ig_access_token = cfg.get("ig_access_token", "")
    ig_user_id      = cfg.get("ig_user_id", "")

    # ── 1. Competitor intel ──
    competitor_intel = None
    print("\n[Review] Fetching competitor intel...", flush=True)
    try:
        competitor_intel = competitor_tool.fetch_competitor_intel(
            ig_user_id=ig_user_id,
            access_token=ig_access_token,
            account=account,
            force=force
        )
        if competitor_intel and competitor_intel.get("patterns"):
            patterns = competitor_intel["patterns"]
            mem_module.update_competitor_hints({
                "top_hooks":            patterns.get("top_hooks", []),
                "power_words":          patterns.get("power_words", []),
                "winning_structures":   list(patterns.get("top_quote_structures", {}).keys()),
                "benchmark_engagement": patterns.get("avg_engagement_top_25", 0),
                "updated_at":           datetime.datetime.now().isoformat(),
            })
            print(f"  [OK] {competitor_intel.get('total_posts_analyzed', 0)} posts, benchmark={patterns.get('avg_engagement_top_25', 0):.0f}", flush=True)
    except Exception as e:
        print(f"  [WARN] Competitor intel fetch failed: {e}", flush=True)

    # ── 2. Own-post metrics ──
    if not ig_access_token:
        print("[WARN] No IG access token — skipping metrics fetch.", flush=True)
        scored_posts = []
    else:
        scored_posts = fetch_and_score_posts(account, ig_access_token, force=force)

    # ── 3. Config upgrade ──
    upgrade_summary = upgrade_config(account, scored_posts)

    # ── 4. Report ──
    report = generate_strategy_report(account, scored_posts, upgrade_summary,
                                       competitor_intel=competitor_intel)

    # ── 5. Mark last upgraded ──
    mem_data = mem_module._load()
    mem_data["last_upgraded"] = datetime.datetime.now().isoformat()
    mem_module._save(mem_data)

    # ── 6. Condensed log summary ──
    cl  = report.get("competitor_learnings", {})
    ch  = report.get("changes_applied", {})
    ha  = report.get("hook_adoption", {})
    fmt = ch.get("format_mix_after", {})
    print(f"\n{'─'*55}", flush=True)
    img_pct = round(fmt.get("image", 0) * 100)
    car_pct = round(fmt.get("carousel", 0) * 100)
    fmt_delta = ch.get("format_mix_delta", {})
    delta_str = ""
    if any(abs(v) >= 0.01 for v in fmt_delta.values()):
        d_car = fmt_delta.get("carousel", 0)
        delta_str = f" ({'+' if d_car >= 0 else ''}{round(d_car*100)}% carousel)"
    new_hooks  = len(ch.get("hooks_added", []))
    new_topics = len(ch.get("topics_blacklisted_new", []))
    print(f"[REPORT] Changes: format image {img_pct}%/carousel {car_pct}%{delta_str}; +{new_hooks} hooks; +{new_topics} avoid_topics", flush=True)

    if cl.get("posts_analyzed", 0) > 0:
        our_avg   = cl.get("our_avg_engagement", 0)
        niche_avg = cl.get("benchmark_engagement", 0)
        gap       = round((our_avg - niche_avg) / niche_avg * 100) if niche_avg else None
        gap_str   = f"{gap:+}%" if gap is not None else "N/A"
        print(f"[REPORT] Competitor: {cl['posts_analyzed']} posts, benchmark {int(niche_avg):,} (our avg {int(our_avg):,}, gap {gap_str})", flush=True)
        if cl.get("top_hooks_learned"):
            print(f"[REPORT] Top hook: \"{cl['top_hooks_learned'][0][:70]}\"", flush=True)
        print(f"[REPORT] Dominant structure: {cl.get('dominant_structure','?')} | Media: {cl.get('dominant_media_type','?')}", flush=True)
    else:
        print(f"[REPORT] Competitor: no data this run", flush=True)

    if ha.get("total", 0) > 0:
        print(f"[REPORT] Hook adoption: {ha['adopted']}/{ha['total']} recent posts used trending words ({ha['rate_pct']}%)", flush=True)

    print(f"[REPORT] Full report → REPORT.md", flush=True)
    print(f"{'─'*55}\n", flush=True)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="disciplinefuel")
    parser.add_argument("--force",   action="store_true", help="Force even if run recently")
    parser.add_argument("--report",  action="store_true", help="Print latest REPORT.md to stdout")
    args = parser.parse_args()

    if args.report:
        repo_report = os.path.join(REPO_ROOT, "REPORT.md")
        if os.path.exists(repo_report):
            with open(repo_report, encoding="utf-8") as f:
                print(f.read())
        else:
            print("No REPORT.md yet. Run without --report flag first.")
    else:
        result = run_review(args.account, force=args.force)
        print(json.dumps(result, indent=2))
