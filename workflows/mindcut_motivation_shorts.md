# MINDCUT — English Motivation Shorts Pipeline

## Channel Identity
- **Channel name**: MINDCUT
- **Character**: ALEX (brutal, zero-excuse voice — think sharpest Goggins clips)
- **Format**: 25–30 second English Shorts / Reels
- **Audience**: 18–35 global English speakers
- **Monetization**: $3–5 RPM (global English >> Hindi at ₹5–30/1K)
- **Layout**: Full-screen B-roll + circular face cam (bottom-center) + word-by-word gold captions

## Objective
Produce one viral motivation Short per day using the ALEX character — brutal, short-sentence, second-person truth-telling that makes the viewer feel seen or exposed.

---

## Required Inputs
- Topic (from content_plan in `config/accounts/mindcut.json`)
- `avatar_raw.mp4` in `.tmp/` — talking-head lip-sync video (generated once per avatar session)
- Pexels API key in `.env` as `PEXELS_API_KEY`
- Gemini/Kimi K2 API key for script generation
- Kokoro TTS models (auto-downloaded to `.models/` on first run)

---

## Pipeline Steps

### Step 1 — Generate Script
```bash
set PYTHONIOENCODING=utf-8
python tools/generate_motivation_script.py "topic here"
```
- **Output**: JSON on stdout with `narration`, `caption`, `word_count`
- **Target**: 75–90 words, 25–30 sec spoken
- **Primary**: Gemini 2.0 Flash → fallback: Kimi K2 (NVIDIA)
- **Voice style**: Max 10 words/sentence. Second person only. Power words: soft, dead, buried, lying, comfortable, weak, real, quit, clock, mirror, chosen, accountable, terrified.
- If word count < 65, script auto-retries up to 3 times

### Step 2 — Generate TTS (Kokoro, free, local)
```bash
python tools/generate_kokoro_tts.py "narration text here" am_adam
```
- **Output**: `.tmp/voiceover.mp3` + `.tmp/captions.srt`
- **Voice**: `am_adam` (strong male) — ideal for ALEX character
- **Speed**: 1.05x (slightly punchy)
- **Captions**: 2 words per line, proportional timing estimate
- Models auto-download on first use (~85MB total, one time)

### Step 3 — Fetch B-roll
```bash
python tools/fetch_broll_clips.py "gym workout motivation"
```
- **Output**: `.tmp/broll_1.mp4`, `broll_2.mp4`, `broll_3.mp4`
- **Source**: Pexels (free, `PEXELS_API_KEY` in `.env`)
- Query should match the script's emotional tone: `gym dark cinematic`, `empty road morning`, `city hustle dawn`
- If Pexels fails: falls back to 3 hardcoded fallback queries

### Step 4 — Generate Avatar (LatentSync lip-sync)
```bash
python tools/generate_latsync_avatar.py
```
- **Input**: `.tmp/voiceover.mp3` + base face image/video
- **Output**: `.tmp/avatar_raw.mp4` — talking head synced to voice
- **Note**: Requires D_ID_API_KEY, FAL_API_KEY (with balance), or local LatentSync GPU setup.
- The compose step uses avatar_raw.mp4 for BOTH the face cam video AND the audio track.

**Workaround when no lip-sync service is available** (face cam won't lip-sync but video works):
```bash
FFMPEG=".../ffmpeg.exe"
DURATION=19.39   # match your voiceover duration
"$FFMPEG" -y \
  -stream_loop -1 -i ".tmp/avatar_raw.mp4" \
  -i ".tmp/voiceover.mp3" \
  -map 0:v -map 1:a \
  -t $DURATION \
  -c:v libx264 -preset fast -crf 22 \
  -c:a aac -b:a 192k \
  ".tmp/avatar_raw_new.mp4"
cp ".tmp/avatar_raw_new.mp4" ".tmp/avatar_raw.mp4"
```
This loops the existing talking-head video and replaces its audio with the new voiceover. The 270px face cam circle is small enough that imperfect lip sync is not noticeable.

### Step 5 — Compose Final Video
```bash
set PYTHONIOENCODING=utf-8
python tools/compose_motivation_video.py "MINDCUT"
```
- **Input**: `.tmp/avatar_raw.mp4`, `.tmp/broll_*.mp4`, `.tmp/captions.srt`
- **Output**: `.tmp/output_short.mp4` (1080×1920, 30fps)
- **Layout**:
  - Full-screen B-roll (cinematic grade: -0.18 brightness, 1.3 saturation)
  - Circular face cam: 270px at bottom-center with 7px white ring border
  - Word-by-word captions at 40% screen height (768px), 96px bold Arial
  - Power words in gold (#FFC800), rest white, 8px black outline
  - MINDCUT badge (red pill) at top-center
- **Duration**: taken from avatar_raw.mp4

---

## Content Plan (First 10 Videos)

| # | Topic | Status |
|---|-------|--------|
| 1 | Your phone is stealing your future | ✅ Done |
| 2 | You're not broke, you're just comfortable | Pending |
| 3 | Your 9-to-5 is your real comfort zone | Pending |
| 4 | You don't have a time problem | Pending |
| 5 | Your morning routine is lying to you | Pending |
| 6 | The version of you that quit still lives here | Pending |
| 7 | Stop calling it overthinking | Pending |
| 8 | Your circle is keeping you soft | Pending |
| 9 | You've been rehearsing failure | Pending |
| 10 | You don't want it bad enough | Pending |

---

## What Makes Top Motivation Channels Work (Research Findings)

From analyzing top 100 channels in this niche:

**Formatting that retains viewers:**
- First 3 seconds decide everything — open with a direct accusation or provocative statement
- Word-by-word captions (not sentence captions) — forces eyes to stay on screen
- Power words in gold/yellow — creates visual hierarchy and emphasis
- Face cam creates parasocial connection — circular cam is trending over split-screen
- B-roll must match the mood: dark gyms, empty roads, city dawn — not stock smiling people

**Script patterns of top channels (Goggins-style):**
- Hook: "You've been lying to yourself every single morning"
- Pattern interrupt: name the exact behavior (not vague)
- No advice — just exposure. The viewer already knows what to do.
- Closer: one quotable sentence, 8-12 words, screenshot-worthy

**Posting strategy:**
- 1 video/day minimum to feed the algorithm
- Best time: 6-9 AM EST (morning motivation intent)
- Hashtag mix: 3 mega (#motivation 100M+) + 4 mid (#discipline 10M) + 3 niche (#brutalmindset 1M)
- Caption hook + "Follow for daily mindset shifts." — drives follow intent

**Why English over Hindi:**
- Hindi Shorts: ₹5–30 per 1000 views (India-heavy audience, low ad rates)
- English Shorts: $3–5 per 1000 views (US/UK/AU audience, high CPM)
- Same production effort, 10x monetization gap

---

## Troubleshooting

**Gemini rate limit (429)**: Kimi K2 fallback activates automatically. No action needed.

**Kokoro TTS slow first run**: Models download on first run (~85MB). Subsequent runs are fast.

**avatar_raw.mp4 missing**: Run `generate_latsync_avatar.py` first. Or manually place a talking-head video at `.tmp/avatar_raw.mp4` — any 25-30s talking head video works as placeholder.

**B-roll clips missing**: Run `fetch_broll_clips.py "gym workout"`. If Pexels key expired, update `PEXELS_API_KEY` in `.env`.

**Captions not syncing**: Kokoro uses proportional timing estimate (not word-boundary events). For precise sync, consider switching to edge-tts (`generate_tts.py`) which gives real word boundary events.

**Video not full 1080x1920**: Check B-roll clips have landscape orientation. Portrait clips will be cropped differently. The compose step always crops to 1080x1920.
