# Workflow: Content Strategy Feedback Loop

## Objective
Read weekly performance data for each account, interpret the strategy report, and update content direction for the coming week. This is how the system learns — every upload cycle feeds into better decisions next cycle.

---

## When to Run
- **Automatically**: `monitor_reels.py` runs silently every 7 days from inside `run_pipeline.py`
- **Manually** (to force a fresh report):
  ```bash
  python tools/monitor_reels.py --account factsflash
  python tools/monitor_reels.py --account techmindblown
  python tools/monitor_reels.py --account coresteelfitness
  python tools/monitor_reels.py --account cricketcuts
  ```

---

## Step 1: Read the Strategy Report

Each account has a report at `.tmp/<account>/strategy_report.json`

Key fields to check:

| Field | What it tells you |
|---|---|
| `best_hashtags` | Which hashtags are sourcing the highest-view content |
| `worst_hashtags` | Hashtags with low source views — reduce or drop |
| `top_performers` | Your 3 best-uploaded reels (caption + yt_views + score) |
| `content_insights.good_keywords` | Topics/words that appear in top-performing content |
| `content_insights.avoid_keywords` | Topics/words that appear in low-performing content |
| `recommendations` | Plain-language action items generated automatically |

---

## Step 2: Interpret the Scoring

**How content is scored (in order of priority):**

1. **Instagram engagement** (when available): `likes + (comments × 3) + (ig_views ÷ 1000)`
2. **YouTube source views** (fallback when IG metrics are 0): `yt_views ÷ 10,000`

> If all scores look identical or suspiciously low, it means IG metrics are not returning (requires `instagram_manage_insights` permission on the token). The system will fall back to yt_views automatically — this still gives useful ranking data.

---

## Step 3: Act on Recommendations

### Hashtag strategy
```
Best hashtag is showing 10x higher source views than others?
→ Prioritise it: move it to position 1 in hashtag_pool in config/accounts/<account>.json
→ The pipeline auto-selects the best-performing hashtag first
```

### Content filtering
```
Good keywords identified (e.g. "animals", "science", "record")?
→ These are already written into content_preferences.good_keywords
→ Pipeline uses them automatically to prefer matching reels

Avoid keywords identified (e.g. "prank", "comedy")?
→ Already written to content_preferences.avoid_keywords
→ Pipeline filters these out automatically before download
```

### Min view threshold
```
Avg source views much higher than current min_reel_views?
→ Consider raising min_reel_views in account config to only source top-tier content
→ Example: if avg yt_views = 5M, set min_reel_views to 1,000,000
```

---

## Step 4: Update Account Config (if needed)

If recommendations suggest config changes:

```bash
# Open account config
code config/accounts/factsflash.json

# Fields to adjust:
# - min_reel_views: raise if avg source views >> current threshold
# - hashtag_pool: reorder to put best-performing tags first
# - niche_require: add good keywords that are niche-specific
# - niche_exclude: add avoid keywords that are clearly off-niche
```

---

## Step 5: Report Back

After reviewing, report this summary to the user:

```
[Account] Weekly Strategy Update — [Date]

Best hashtag: #[tag] ([avg_views] avg source views)
Top content theme: [good_keywords]
Avoid: [avoid_keywords]

Action taken: [what was updated in config, or "no changes needed"]
Next run: [date + 7 days]
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| All scores = 0 | IG metrics not returned | Normal — system uses yt_views fallback. No action needed. |
| No good/avoid keywords | Captions not stored in log | Only affects uploads after the fix was deployed (caption now stored). Give it one week. |
| Strategy report not found | monitor_reels hasn't run yet | Run manually: `python tools/monitor_reels.py --account <name>` |
| Good keywords look wrong | Not enough data (< 10 uploads) | Wait until you have 10+ uploads per account for reliable patterns |

---

## Account Quick Reference

| Account | Niche | Min Views | Best Hashtag (current) |
|---|---|---|---|
| factsflash | Amazing facts, science, history | 500,000 | #amazingfacts (4.1M avg) |
| techmindblown | Tech, AI, innovation | 300,000 | Check strategy_report.json |
| coresteelfitness | Fitness, workout, gym | 500,000 | Check strategy_report.json |
| cricketcuts | Cricket, IPL highlights | 500,000 | Check strategy_report.json |
