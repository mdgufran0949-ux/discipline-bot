# DisciplineFuel Pipeline Audit
Generated: 2026-05-07

---

## 1. Pipeline Architecture

### Execution Entry Point
GitHub Actions triggers `run_discipline_pipeline.py --account disciplinefuel --count 3` three times daily.
Each run posts 3 reels → 9 posts/day total.

### Step-by-step flow (per post):

```
1. Review gate        → review_and_upgrade.py        (runs if ≥7 days since last review)
2. Fetch trends       → fetch_discipline_trends.py    (cached 24h; yt-dlp + Google RSS)
3. Load memory        → discipline_memory.py          (weights, avoid-lists, prompt hints)
4. Pick topic         → from config content_topics[topic_index] (rotates sequentially)
5. Pick series        → series_rotation[series_index] (discipline_rule / wake_up_call / day_becoming_better)
6. Pick design style  → weighted_choice({dark:0.25, minimal:0.25, bold:0.25, luxury:0.25})
7. Generate quote     → generate_discipline_quote.py  (7 variations via LLM, picks best)
8. Generate image     → generate_discipline_image.py  (AIMLAPI FLUX → fal.ai → Pollinations)
9. Compose reel       → compose_discipline_reel.py    (Ken Burns zoom + Pillow overlay + FFmpeg)
   └ BGM              → generate_discipline_bgm.py    (procedural sine-wave, cached 7 days)
10. Upload reel       → upload_reel.py                (Cloudinary temp host → IG Graph API)
11. Log to memory     → discipline_memory.py          (post data, no metrics yet)
12. Save config       → increments topic_index, series_index, series_counters
13. Sleep 180s        → hardcoded between posts in same run
```

### Review loop (weekly, inside same pipeline run):
```
fetch_and_score_posts()  → pulls saves/shares/comments/likes per post from IG API
upgrade_config()         → rebalances design weights, format mix, avoids weak patterns
generate_strategy_report() → writes strategy_report.json + latest_report.md + REPORT.md
```

---

## 2. External Services

| Service | Purpose | Provider | Cost |
|---------|---------|----------|------|
| OpenRouter (Claude Haiku) | Quote generation (primary LLM) | Anthropic via OR | ~$0.001/call |
| Groq (Llama 3.3 70B) | Quote generation (fallback) | Groq | Free tier |
| Gemini 2.0 Flash | Quote generation (fallback 2) | Google | Free tier |
| Kimi K2 | Quote generation (fallback 3) | Moonshot AI | - |
| AIMLAPI (FLUX dev) | Background image generation (primary) | AI/ML API | ~$0.003/img |
| fal.ai (FLUX schnell) | Background image (fallback) | fal.ai | Paid |
| Pollinations.ai | Background image (free fallback) | Pollinations | Free |
| Gemini Imagen | Background image (free fallback 2) | Google | Free |
| Instagram Graph API v19.0 | Reel upload + metrics fetch | Meta | Free |
| Cloudinary | Temporary video hosting (required for IG API) | Cloudinary | Free tier |
| Canva Connect API | Template-based image design | Canva | Free tier |
| YouTube (via yt-dlp) | Trend scraping | Google | Free (scrape) |
| Google Trends RSS | Hot keyword discovery | Google | Free |

**No TTS service** — pipeline is text-on-video only (no voiceover). BGM is procedurally synthesized locally.

---

## 3. Posting Schedule Logic

### Schedule definition (config):
```
posting_schedule: [06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00]  (IST)
posts_per_day: 9
```

### How it actually executes:
- **GitHub Actions crons:** 3 triggers/day → 06:00, 13:00, 20:00 IST (approximate)
- Each trigger runs `--count 3` → posts 3 reels with `time.sleep(180)` between them
- 3 reels × 3 triggers = 9 posts/day

### Critical scheduling problems:
1. **3 posts fire within ~6 minutes** (3-min sleep between each, no time-of-day awareness)
2. **Exact cron times** (00:30 UTC, 07:30 UTC, 14:30 UTC) — no randomisation
3. **No cooldown check** — if a previous run overlaps or fails mid-way, next run doesn't know
4. **9 posts/day** — far above safe threshold; IG spam detection kicks in at 5+/day for new accounts

---

## 4. Script / Quote Generation

### LLM call chain:
1. `generate_discipline_quote.py` calls OpenRouter → Groq → Gemini → Kimi (in order)
2. Generates **7 quote variations** in one prompt
3. Picks the one with highest "quality score" (length heuristic + pattern-interrupt check)

### System prompt (key elements):
- Voice: "stoic, reflective, wise" — NOT gym-bro energy
- Audience: "16-30 year olds, want to be understood not attacked"
- Models: Marcus Aurelius, not "hustle culture"
- Required: universal truth, no dates, no specifics (anyone could write this)

### Quote types generated (all 7 per call):
`STATEMENT, CONTRAST, PUNCH, IDENTITY, QUESTION, COMMAND, PAIN_DRIVEN`

### Length distribution:
- 10% PUNCH: 5-12 words
- 25% MEDIUM: 20-40 words  
- 65% LONG: 40-80 words

### Quality gates (reject if):
- Contains banned phrases (see list below)
- Contains personal attacks ("you're lazy", "you're weak")
- Contains clichés ("hustle harder", "never give up", "you got this")
- Contains platform pollution ("subscribe", "link in bio")
- Too similar to top hooks in recent memory (cosine check)
- Starts with hashtag or contains hashtags

### Banned substrings (hardcoded):
`grind now, are you serious, work hard every day, success is a choice, keep going, hustle harder, you got this, best version, never give up, welcome to, subscribe, this channel, watch till, link in bio, like and share, you're lazy, you're scared, you're weak, you're soft, you're broke`

### Content topic rotation:
30 hardcoded topics in `config/accounts/disciplinefuel.json`, iterated sequentially via `topic_index`.

### Series rotation:
3 series, iterated sequentially via `series_index`:
- `Discipline Rule #N`
- `Wake Up Call #N`
- `Day N of Becoming Better`

**No pillar system. No hook-template rotation. No diversity check against recent posts.**

---

## 5. Caption Logic

### Selection method:
`_pick_caption()` in `run_discipline_pipeline.py` picks randomly from 7 hardcoded templates (or calls LLM for caption).

### Caption templates (7 hardcoded, identical structure):
```
"Save this. Read it every morning. @DisciplineFuel\n\n#discipline #focus #grind..."
"This is the truth nobody told you. @DisciplineFuel\n\n#discipline #sacrifice..."
"Screenshot this. You need it on your worst days. @DisciplineFuel\n\n#discipline..."
"Tag someone who needs to wake up. @DisciplineFuel\n\n#discipline #success..."
"Read this daily. No excuses. @DisciplineFuel\n\n#discipline #focus..."
"The uncomfortable truth. @DisciplineFuel\n\n#discipline #sacrifice..."
"Bookmark this. Come back when you feel weak. @DisciplineFuel\n\n#discipline..."
```

### Hashtag logic:
- All 7 templates include the **same 10 hashtags** (minor variations)
- Pool: `#discipline #focus #grind #sacrifice #success #selfimprovement #motivation #hardwork #mentalstrength #accountability #growthmindset #winning #levelup #noexcuses #hustle`
- **No rotation, no mid-size tag targeting, no freshness check**

### Problems:
- Same 7 captions cycling → IG detects duplicate caption pattern → suppresses reach
- All hashtags are mega-tags (millions of posts) → impossible to rank in
- No CTA variation
- No series-aware captions

---

## 6. Audio Selection Logic

**There is no audio selection logic.**

The pipeline generates **procedural background music** locally (`generate_discipline_bgm.py`):
- 20-second dark ambient track
- A minor pentatonic, 75 BPM, sine wave synthesis
- Drone pad + sparse melody + bass pedal
- Cached for 7 days (same BGM on all reels for a week)

### Problems:
- Same audio for 7 days straight → duplicate audio detection by IG
- Not using Instagram's native audio → loses Reels audio discovery feature
- Procedural synth sounds robotic/cheap vs. licensed tracks

---

## 7. File Inventory

| File | Description |
|------|-------------|
| `tools/run_discipline_pipeline.py` | Master orchestrator: runs 3 posts per execution, all pipeline steps |
| `tools/discipline_memory.py` | Self-improving memory: tracks post history, scoring, weight rebalancing |
| `tools/generate_discipline_quote.py` | LLM-based quote engine: 7 variations, quality gates, fallback chain |
| `tools/generate_discipline_image.py` | AI image generation: FLUX primary, 3 free fallbacks |
| `tools/compose_discipline_reel.py` | FFmpeg reel composition: Ken Burns zoom, Pillow text overlay, BGM mix |
| `tools/generate_discipline_bgm.py` | Procedural BGM synthesis: A-minor ambient, sine waves, no API |
| `tools/upload_reel.py` | IG reel upload: Cloudinary temp host → Graph API container → publish |
| `tools/review_and_upgrade.py` | Weekly self-improvement: fetch metrics, score posts, rebalance weights |
| `tools/fetch_discipline_trends.py` | Trend scraping: yt-dlp YouTube + Google Trends RSS, 24h cache |
| `tools/generate_canva_post.py` | Canva API autofill: template → design → export (image fallback path) |
| `tools/upload_image_post.py` | IG image/carousel upload via Graph API |
| `config/accounts/disciplinefuel.json` | Account config: credentials, topic pool, weights, schedules, templates |
| `.github/workflows/disciplinefuel.yml` | GitHub Actions: cron triggers, run pipeline, commit state back |
| `workflows/disciplinefuel_instagram.md` | Workflow SOP: full pipeline overview, setup, troubleshooting |
| `run_disciplinefuel.bat` | Windows Task Scheduler entry point (superseded by GitHub Actions) |
| `.tmp/disciplinefuel/memory.json` | Runtime state: post history, patterns, avoid-lists, prompt hints |
| `.tmp/disciplinefuel/uploaded_log.json` | Upload log: every post with IG media ID and metrics when fetched |
| `.tmp/disciplinefuel/competitor_intel.json` | Competitor analysis cache |
| `.tmp/disciplinefuel/trends.json` | Trend cache (24h TTL) |
| `.tmp/disciplinefuel/change_history.jsonl` | Append-only log of all config changes |
| `REPORT.md` | Auto-generated weekly strategy report |

---

## 8. Problems Confirmed by Audit

### Spam-pattern problems
- [x] **9 posts/day** — `posts_per_day: 9`, `--count 3` × 3 triggers
- [x] **3 posts within 6 minutes** — `SLEEP_BETWEEN_POSTS = 180` (3 min) within a run
- [x] **Exact round cron times** — `30 0`, `30 7`, `30 14` UTC, no randomisation
- [x] **No cooldown check** — no gate checking last post timestamp

### Content quality problems
- [x] **No pillar system** — same tone/structure every post
- [x] **No hook-template rotation** — quote types selected by scoring heuristic, no structural variety
- [x] **No diversity check** — no rejection based on similarity to last 10 posts
- [x] **No hook-strength scoring** before publish (quality gate is basic length check)
- [x] **Same BGM for 7 days** — audio cached and reused
- [x] **Not using IG native audio** — loses audio-based discovery entirely

### Caption/hashtag problems
- [x] **7 cycling captions** with near-identical structure (all start with imperative + @DisciplineFuel + same 10 hashtags)
- [x] **All mega-tags** (discipline, focus, grind etc. have millions of posts — impossible to rank)
- [x] **No mid-size tags** (50K-500K range where new accounts can actually appear)
- [x] **No hashtag rotation** — same exact set on every post

### Account-signal problems
- [x] Bio, Linktree, following count — cannot verify from code (manual check needed)
- [x] 330 posts, 8 followers — confirmed from user statement

### Engagement loop problems
- [x] **Zero outbound engagement module** — no `engagement_bot.py` or equivalent exists
- [x] **No comment-reply logic** — pipeline only posts, never reads own comments

### Self-improvement system
- [x] `_load_log` had a bug (returns `None` when file exists) — partially fixed this session
- [x] `_save_log` had a `return json.load(f)` stray line — partially fixed this session
- [x] Metrics never persisted to disk until this session's fix
- [x] System has run ~89 posts with no real engagement data in memory

---

## 9. What Is Working

- Reel composition (Ken Burns + text overlay + FFmpeg) — confirmed 89 posts uploaded
- IG Graph API upload flow — confirmed working (Cloudinary → container → publish)
- LLM quote generation — 4-provider fallback chain is robust
- Image generation — 4-provider fallback chain, procedural BGM as last resort
- GitHub Actions automation — running reliably 3×/day, committing state
- Self-improvement framework — architecture is correct, bugs fixable
- Design style diversity — recently fixed to equal 25% weights

---

## 10. Cost Estimate (current, per day)

| Item | Cost |
|------|------|
| 9 × AIMLAPI FLUX image | ~$0.027 |
| 9 × OpenRouter LLM call | ~$0.009 |
| Cloudinary (free tier, 89 uploads so far) | $0 |
| GitHub Actions (2000 free min/month) | $0 |
| **Total per day** | **~$0.036** |
| **Total per month** | **~$1.08** |

Proposed rebuild at 2 posts/day: **~$0.008/day / $0.24/month**
