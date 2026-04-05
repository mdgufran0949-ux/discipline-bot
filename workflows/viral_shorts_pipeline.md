# Workflow: Viral Shorts Pipeline

## Objective
Produce a 30-second AI-generated YouTube Short based on a currently trending news topic.

## Required Inputs
- `GROQ_API_KEY` in `.env` — free at console.groq.com (used for script generation)
- ffmpeg installed on system PATH

## Output
- `.tmp/output_short.mp4` — 1080x1920 vertical video, ~30 seconds, with voiceover + captions + AI visuals

---

## Steps

### Step 1: Fetch Trending Topics
```bash
python tools/fetch_trends.py
```
- Uses pytrends (free, no key needed)
- Returns top 10 Google Trends (US)
- Pick the most newsworthy / shocking topic from the list
- Edge case: If pytrends returns a 429 (rate limited), wait 60 seconds and retry. Max 3 retries.

### Step 2: Generate Viral Script
```bash
python tools/generate_script.py "TOPIC HERE" > .tmp/script.json
```
- Calls Groq Llama 3.3 70B (free, 1,000 req/day at console.groq.com)
- Outputs a JSON file with:
  - `narration`: 75–85 word punchy voiceover script
  - `scenes`: 6 image prompts for AI visual generation
- Criteria for a good script:
  - Hook in first sentence (shocking stat, question, or reveal)
  - One mind-blowing fact or twist in the middle
  - Ends with a strong statement
- If narration is over 85 words, re-run with same topic
- Edge case: Groq 429 rate limit → wait 10 seconds and retry

### Step 3: Generate Voiceover
```bash
python tools/generate_tts.py "NARRATION TEXT FROM SCRIPT JSON"
```
- Uses edge-tts (Microsoft, free, no API key)
- Voice: en-US-GuyNeural at +10% speed
- Saves to `.tmp/voiceover.mp3` + `.tmp/captions.srt`
- Returns duration in seconds (target: 25–35 seconds)

### Step 4: Generate AI Scene Images
```bash
python tools/generate_visuals.py
```
- Reads scene prompts from `.tmp/script.json`
- Calls Pollinations.ai FLUX (free, no API key needed — pollinations.ai)
- Outputs `.tmp/scene_1.png` through `.tmp/scene_6.png`
- Each image is cinematic, portrait-oriented, 1024x1024
- Waits 5s between images (free tier rate limit) — 6 images takes ~30 seconds total
- If one scene fails → fallback solid color is used automatically, pipeline continues
- Edge case: Slow response from Pollinations → shared GPU queue, retry automatically

### Step 5: Compose Final Video
```bash
python tools/compose_video.py "TITLE TEXT"
```
- Reads 6 AI scene images + voiceover + captions SRT
- Applies Ken Burns zoom/pan effect per scene (5 sec each)
- Adds crossfade transitions between scenes
- Overlays synced yellow captions
- Adds TRENDING NOW badge at top
- Saves to `.tmp/output_short.mp4` (1080x1920, H.264)
- Edge case: Missing scene image → that scene uses fallback, compose proceeds
- Edge case: Captions don't appear → check `.tmp/captions.srt` exists and has content

---

## Full Pipeline (Single Run)

```bash
# 1. Get trends
python tools/fetch_trends.py

# 2. Pick best topic, generate script (saves to .tmp/script.json)
python tools/generate_script.py "chosen topic" > .tmp/script.json

# 3. Generate voiceover (copy exact narration text from script.json)
python tools/generate_tts.py "exact narration text here"

# 4. Generate AI scene images
python tools/generate_visuals.py

# 5. Compose final video
python tools/compose_video.py "Short title for overlay"
```

Output: `.tmp/output_short.mp4`

---

## Known Constraints
- pytrends rate limit: ~10 requests/minute. If blocked, wait 60s.
- Groq free tier: 1,000 req/day, 100K tokens/day on llama-3.3-70b-versatile. Enough for ~1,000 scripts/day.
- Pollinations.ai: 1 req/5s with free account (register at pollinations.ai). 1 req/15s anonymous.
- edge-tts: free but requires internet connection.
- ffmpeg: must be on system PATH. Install via: `winget install Gyan.FFmpeg`

## Edge Cases
| Problem | Solution |
|---------|----------|
| pytrends 429 rate limit | Wait 60s, retry up to 3 times |
| Groq 429 rate limit | Wait 10s, retry |
| Script narration too long (>85 words) | Re-run generate_script.py |
| Scene image generation fails | Fallback color used automatically |
| Pollinations slow response | Shared GPU queue — script retries automatically |
| Captions missing | Check .tmp/captions.srt exists |
| ffmpeg not found | Run: winget install Gyan.FFmpeg, restart shell |
