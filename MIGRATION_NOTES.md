# Migration Notes — DisciplineFuel Pipeline Rebuild
Tracking what changed from the original pipeline and why.

---

## What Was Removed / Changed

### Posting frequency: 9/day → 2/day
**Before:** GitHub Actions fired 3×/day, each running `--count 3` → 9 posts/day total.  
**After:** 2 cron triggers (09:00 IST, 18:00 IST), each running `--count 1`.  
**Why:** Instagram's spam-detection threshold for new accounts. 9 posts/day is flagged as bot
behavior and suppresses algorithmic reach. 2 posts/day with 9h separation is the safe floor
for accounts under 1K followers.

### Posting times: exact round times → randomized windows
**Before:** Crons fired at exactly 06:00, 13:00, 20:00 IST every day.  
**After:** Crons fire at 09:00 and 18:00 IST *base*, then a random bash sleep of 300–1800s
(5–30 min) is applied before `run_discipline_pipeline.py` runs.  
**Why:** Exact same-second firing every day is a detectable bot pattern. Human accounts
post at irregular times.

### BGM: procedural sine-wave (cached 7 days) → audio_selector.py
**Before:** `generate_discipline_bgm.py` synthesized a 20s A-minor ambient track and cached
it for 7 days. Every reel for a whole week used identical audio.  
**After:** `audio_selector.py` manages audio strategy with two modes controlled by
`manual_audio_mode` in `config/accounts/disciplinefuel.json`.  
**Why:** Identical procedural BGM on every reel bypasses Instagram's native trending-audio
discovery engine entirely. In 2026, adding a trending sound to a reel is the single highest-
leverage growth lever — reels with trending audio get surfaced in the audio's discovery tab
and the explore page for users following that sound. Our pipeline was leaving this channel
completely dark.

### Import removed: `generate_discipline_bgm`
`import generate_discipline_bgm as bgm_tool` removed from `run_discipline_pipeline.py`.
The BGM tool itself is kept for use as a library fallback inside `audio_selector.py`.

---

## New Components

### `tools/audio_selector.py`
Two operating modes:

**Option B — Manual audio mode (`manual_audio_mode: true`, default)**  
Pipeline composes a silent MP4. After composition, the video is uploaded to Cloudinary
(permanent, not deleted) and a queue JSON is written to `queue/pending_audio/`. The post
is logged in `uploaded_log.json` with `status: "pending_manual_post"`. The user downloads
the video, opens it in the IG app, adds a trending audio track from IG's built-in selector,
and posts manually.

**Option A — Library rotation (`manual_audio_mode: false`)**  
Pipeline picks an mp3 from `audio_library/`, never reusing the same file within 10 posts.
Copies chosen file to `.tmp/disciplinefuel/bgm.mp3` so `compose_discipline_reel.py` picks
it up from its hardcoded path (no changes needed to compose). Falls back to procedural BGM
if the library is empty.

To toggle: change `"manual_audio_mode"` in `config/accounts/disciplinefuel.json`.

### `tools/mark_posted.py`
CLI to close the loop after manual posting. Mutates local files only — no network calls.

```
python tools/mark_posted.py --queue-id <id> --ig-media-id <real_id> [--permalink <url>]
```

Lifecycle of a queued post:
1. Pipeline runs → `queue/pending_audio/<queue_id>.json` created, Cloudinary URL inside
2. User downloads video, adds trending audio in IG app, posts
3. User runs `mark_posted.py` with the real IG media ID
4. Queue file moves from `queue/pending_audio/` → `queue/posted/`
5. `uploaded_log.json` entry updated: `status: "published"`, real `ig_media_id`, real `permalink`
6. Self-improvement loop can now fetch real engagement metrics on next review run

---

## Index Increment Behavior in `manual_audio_mode`

### Policy: indices increment on queue, not on actual posting

`topic_index` and `series_index` in `config/accounts/disciplinefuel.json` increment **when
a post is queued**, not when it is manually posted in the IG app.

**Consequence:** If you queue a post but never post it, that topic and series slot are
consumed and the rotation moves on to the next. Skipping a queued post means that
topic/series combination is effectively used up.

**Reasoning:**
- The alternative (increment only on `mark_posted.py`) creates a multi-day lag between
  queue time and rotation advancement. If you accumulate 4 queued posts before marking any
  of them, the next 4 pipeline runs would all try to pick the same next topic.
- Incrementing at queue time is deterministic and stateless — the pipeline doesn't need to
  know the current queue backlog size.
- If a queued post is abandoned, you can manually edit `topic_index` / `series_index` in
  `config/accounts/disciplinefuel.json` to roll back. The config is human-readable JSON.

**Audit trail:** Every queue JSON in `queue/pending_audio/` and `queue/posted/` contains
`series_label` and `topic` so you can always see what was consumed.

---

## Metrics Fetcher Skips: `QUEUED_` and `DRY_` Prefixes

`review_and_upgrade.py → fetch_and_score_posts()` skips any post whose `ig_media_id`
starts with `QUEUED_` or `DRY_`. These are placeholder IDs assigned at queue/dry-run
time that have no corresponding media on Instagram's API.

Once `mark_posted.py` updates the entry with a real IG media ID, the next review run
will pick it up and fetch real engagement metrics.

---

## `permalink` vs `preview_url` — Field Semantics

**`permalink`** — always means a real Instagram post URL (`https://www.instagram.com/p/...`).
For queued posts before manual posting, this field is set to the string `"pending_manual_post"`.

**`preview_url`** — Cloudinary URL of the silent MP4 generated at queue time. Only present
for `status: "pending_manual_post"` entries. Used to download the video for manual posting.
Null for all published/dry-run posts.

**`queue_id`** — Direct key for O(1) lookup in `mark_posted.py`. Set at queue time, null
for all non-queued posts. Avoids regex-stripping `QUEUED_` prefix from `ig_media_id`.

---

## What Was NOT Changed

These components are unchanged and should not be touched:

| Component | Reason kept |
|---|---|
| `generate_discipline_quote.py` | 4-provider LLM fallback, banned-substring list, quote types all working |
| `generate_discipline_image.py` | 4-provider image fallback (AIMLAPI → fal → Pollinations → Gemini) working |
| `compose_discipline_reel.py` | Ken Burns zoom + Pillow overlay + FFmpeg filtergraph working |
| `upload_reel.py` | Cloudinary → IG Graph API flow working |
| Design style 25% equal weights | Recently fixed; leave stable |

---

## Pending (next PRs, in order)

1. **Pillar + hook template tagging** — tag every post with one of 4 content pillars and
   one of 5 hook templates. Add diversity check against last 10 posts before selecting.
2. **Caption rebuild** — 5-structure rotation + mid-size hashtag pool (50K–500K range).
3. **Engagement bot** — 5 actions/day week 1, ramp to 15/day by week 4.
