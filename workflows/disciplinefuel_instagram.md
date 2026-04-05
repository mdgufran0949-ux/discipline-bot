# DisciplineFuel Instagram Growth Pipeline

## Objective
Autonomously grow the DisciplineFuel Instagram page by posting 9 original quote-based posts/day (images + carousels). The system generates content, learns from performance, and improves itself weekly without manual intervention.

**Target audience:** 16–30 year olds struggling with procrastination, laziness, distraction  
**Content style:** Dark aesthetic, brutal truth, short punchy quotes  
**Goal:** Saves > Shares > Comments > Likes (saves = viral signal)

---

## System Architecture (8 Engines)

```
fetch_discipline_trends    → Trend Awareness (24h cache)
generate_discipline_quote  → Quote Engine + Viral Framework + Hook System + Save Rules
discipline_memory          → Memory System (duplicate check + content weights)
generate_discipline_image  → Image Gen (fal.ai → Pollinations → Gemini)
generate_canva_post        → Design Engine (Canva API → Pillow fallback)
upload_image_post          → Instagram Graph API (image + carousel)
review_and_upgrade         → Weekly Review + Self-Improvement Loop
run_discipline_pipeline    → Master Orchestrator
```

---

## Required Inputs

| Input | Where | Status |
|---|---|---|
| `IG_USER_ID` | `.env` / `config/accounts/disciplinefuel.json` | Add after account creation |
| `IG_ACCESS_TOKEN` | `config/accounts/disciplinefuel.json` | Add after account creation |
| `CANVA_CLIENT_ID` | `.env` | Done |
| `CANVA_CLIENT_SECRET` | `.env` | Done |
| `CANVA_TEMPLATE_ID` | `config/accounts/disciplinefuel.json → canva.template_id` | Add after creating Canva template |
| `GEMINI_API_KEY` | `.env` | Done |
| `FAL_API_KEY` | `.env` | Done |
| `CLOUDINARY_*` | `.env` | Done |

---

## Setup Steps (One-Time)

### 1. Create the Instagram Business Account
- Create an Instagram account (@DisciplineFuel or similar)
- Convert to Creator/Business account
- Link to a Facebook Page
- Go to developers.facebook.com → Get `IG_USER_ID` and a long-lived `IG_ACCESS_TOKEN`
- Add both to `config/accounts/disciplinefuel.json`

### 2. Set Up Canva Templates
- Log in to Canva, create a new **Instagram Post (1080×1080)** template
- Design 1 dark-aesthetic quote template with 3 text fields named exactly:
  - `quote_text` — main quote
  - `series_label` — "DISCIPLINE RULE #7"
  - `page_name` — "@DisciplineFuel"
- Save as a Brand Template
- Get the Template ID from the URL (e.g., `DAFxxxxx`)
- Add to `config/accounts/disciplinefuel.json → canva.template_id`

### 3. Canva OAuth (First Run Only)
```bash
python tools/canva_auth.py
```
Browser opens → log in to Canva → callback captured → token saved to `.tmp/disciplinefuel/canva_token.json`  
Subsequent runs auto-refresh silently.

### 4. Test Run (Dry Run)
```bash
python tools/run_discipline_pipeline.py --count 1 --dry-run
```
Verify: quote generated, image created, Canva post composed, no upload.

---

## Daily Execution

### Schedule via Windows Task Scheduler
```bat
run_disciplinefuel.bat  → runs at 06:00, 13:00, 20:00 daily
```
Each run: 3 posts × 3 runs = **9 posts/day**

### Manual Run
```bash
python tools/run_discipline_pipeline.py --count 3
```

---

## Pipeline Flow (Per Post)

```
1. Weekly review check (silently skipped if < 7 days)
2. Fetch trends (cached 24h) → get hot_keywords + best_topic
3. Load memory weights (80% proven patterns, 20% experimental)
4. Pick topic (trending → config queue, skip blacklisted)
5. Pick series type (rotates: Discipline Rule → Wake Up Call → Day X)
6. generate_discipline_quote(topic, series, design_style)
   → 5 quote variations (command, question, contrast, pain-driven, identity)
   → selected_quote + hook_keyword + image_prompt + caption + hashtags
7. generate_discipline_image(image_prompt, size, style)
   → fal.ai FLUX schnell → Pollinations fallback → Gemini fallback
8. generate_canva_post(quote, series_label, bg_image)
   → Canva Autofill API → Pillow fallback
9. upload_image_post or upload_carousel_post
   → Cloudinary → Instagram Graph API → cleanup Cloudinary
10. discipline_memory.log_post(metadata)
11. Increment series_counter + topic_index → atomic config save
12. Sleep 180s → next post
```

---

## Content Framework

### Viral Framework (enforced in every quote)
- Structure: **Pain → Reality → Discipline wins**
- Discipline > Motivation always
- Relatable struggle: name the exact behavior (scrolling, delaying, comfort)
- Scarcity: time is running out, others are moving

### Hook System (Line 1 must do one of):
- Stop scroll (fear): "Nobody is coming to save you."
- Expose guilt: "You already know. You just won't act."
- Trigger ambition: "Your future self is watching right now."
- Create curiosity: "This is why you're still stuck."

### Save Optimization (every post):
- Caption always includes: "Save this." / "Read this daily." / "Screenshot this."
- Quote must be re-readable, not one-time-use
- Content should feel like something worth bookmarking

### Series Rotation
| Series | Format | Frequency |
|---|---|---|
| Discipline Rule #X | Image | Every 3rd post |
| Wake Up Call #X | Carousel | Every 3rd post |
| Day X of Becoming Better | Image | Every 3rd post |

---

## Self-Improving Loop (Weekly)

`review_and_upgrade.py` runs automatically every 7 days:

1. **Fetch** — pulls IG metrics (saves, shares, comments, likes) for all posts
2. **Score** — `saves×4 + shares×3 + comments×2 + likes×1`
3. **Classify** — score ≥ 70 → strong | score ≤ 30 → weak
4. **Blacklist** — 3 consecutive weak posts on same topic → added to `avoid_topics`
5. **Upgrade config** — rebalances `design_style_weights` + `content_format_mix` toward winners
6. **Update prompts** — injects best-performing hooks into LLM hint system
7. **Report** — writes `.tmp/disciplinefuel/strategy_report.json`

**80/20 Rule:** 80% of posts use proven strong patterns. 20% experiment.

### Read the report
```bash
python tools/review_and_upgrade.py --account disciplinefuel
```

### Force a review now
```bash
python tools/review_and_upgrade.py --account disciplinefuel --force
```

---

## Memory System

Stored in `.tmp/disciplinefuel/memory.json`  
Tracks per post: quote_type, design_style, format, series, topic, hook_keyword, posted_at, IG metrics, score

```bash
# Check memory report
python tools/discipline_memory.py --report

# Run unit tests
python tools/discipline_memory.py --test
```

---

## Performance Scoring

| Metric | Weight | Reason |
|---|---|---|
| Saves | ×4 | Strongest viral signal — content worth keeping |
| Shares | ×3 | Organic reach multiplier |
| Comments | ×2 | Engagement signal |
| Likes | ×1 | Weakest signal |

**Targets (after 30 days):**
- Saves per post: > 50
- Score: > 70 (strong)
- Avoid anything scoring < 30 for 3+ consecutive posts

---

## Troubleshooting

### Instagram token expired (error 190)
1. Go to developers.facebook.com/tools/explorer
2. Generate new long-lived token
3. Update `config/accounts/disciplinefuel.json → ig_access_token`

### Canva autofill fails
- Check template field names match exactly: `quote_text`, `series_label`, `page_name`
- Verify `canva.template_id` in config is correct
- Falls back to Pillow compositor automatically

### Image generation fails
- fal.ai → check FAL_API_KEY balance at fal.ai/dashboard
- Pollinations free fallback activates automatically
- Gemini Imagen as final fallback

### Rate limits
- Instagram: 25 posts/24h max. Pipeline posts 9/day — safe.
- Between posts: 180s sleep (enforced in orchestrator)
- Canva API: no hard rate limit documented; 1s delay between carousel slides

### Canva token expired
```bash
python tools/canva_auth.py
```
Re-runs browser OAuth flow.

---

## File Structure

```
tools/
  canva_auth.py              ← Canva OAuth (first-run browser flow, auto-refresh)
  fetch_discipline_trends.py ← Trend awareness (YouTube + Google Trends, 24h cache)
  discipline_memory.py       ← Memory system + self-improving weights
  generate_discipline_quote.py ← Quote engine (5 variations + viral framework)
  generate_discipline_image.py ← Image generation (fal.ai → Pollinations → Gemini)
  generate_canva_post.py     ← Design engine (Canva Autofill → Pillow fallback)
  upload_image_post.py       ← Instagram image + carousel upload
  review_and_upgrade.py      ← Weekly review + config rebalancing + report
  run_discipline_pipeline.py ← Master orchestrator

config/accounts/
  disciplinefuel.json        ← Account config, series counters, weights, topics

.tmp/disciplinefuel/
  trends.json                ← Cached trending topics (24h)
  memory.json                ← Post history + performance + patterns
  strategy_report.json       ← Weekly self-improvement report
  uploaded_log.json          ← Full upload history with metrics
  canva_token.json           ← Canva OAuth token (auto-managed)
  images/                    ← Generated background images
  canva/                     ← Canva-exported post images

run_disciplinefuel.bat       ← Scheduler entry (run 3x/day)
```

---

## Estimated Costs (Daily)

| Service | Usage | Cost |
|---|---|---|
| fal.ai FLUX | ~5 images/day @ $0.003 | ~$0.015/day |
| Gemini 2.0 Flash | ~18 LLM calls/day | Free |
| OpenRouter (free model) | Fallback only | Free |
| Pollinations.ai | Fallback only | Free |
| Cloudinary | ~5 images @ ~2MB | Free tier (25GB/month) |
| **Total** | | **~$0.45/month** |
