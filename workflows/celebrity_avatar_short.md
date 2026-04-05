# Workflow: Celebrity AI Talking Avatar YouTube Short

## Objective
Generate a 10-15 second vertical YouTube Short (1080x1920) featuring a celebrity AI talking avatar, lip-synced to a scripted voiceover. Replicates the MrBeast-style AI avatar format with a different celebrity and challenge/dare content.

## Required Inputs
- Celebrity name (must exist in `tools/fetch_celebrity_image.py` curated list)
- Content topic (e.g., "Elon Musk challenge dare")
- fal.ai API key (free credits at fal.ai)

## Prerequisites
```
pip install requests python-dotenv Pillow openai edge-tts fal-client
```
- FFmpeg must be on PATH (installed via WinGet)
- `FAL_API_KEY` set in `.env`

## Pipeline

### Step 1 — Generate Script
```bash
python tools/generate_script.py "Elon Musk extreme challenge dare"
```
- Produces 75-85 word narration (note: for avatar use, 25-30 words is better — edit prompt if needed)
- Save the `narration` field for Step 2
- **Edge case:** If script is too long (>30 sec audio), trim it manually to 3-4 punchy sentences

### Step 2 — Generate TTS Voiceover
```bash
python tools/generate_tts.py "I dare you to live on $4 a day for 30 days. If you do it, I will pay off your student loans. Comment I am in to join."
```
- Output: `.tmp/voiceover.mp3` + `.tmp/captions.srt`
- Voice: `en-US-GuyNeural` (authoritative, clear)
- **Edge case:** If captions.srt is empty, check that edge-tts returned word boundary events

### Step 3 — Fetch Celebrity Image
```bash
python tools/fetch_celebrity_image.py "Elon Musk"
```
- Output: `.tmp/celebrity.jpg`
- Available celebrities: Elon Musk, Jeff Bezos, Mark Zuckerberg, Bill Gates, Cristiano Ronaldo, Virat Kohli
- **Edge case:** If image download fails, manually save a front-facing JPEG (min 512x512) to `.tmp/celebrity.jpg`
- **Important:** Image must be front-facing, well-lit, neutral expression for best D-ID results

### Step 4 — Generate Talking Avatar (MuseTalk via fal.ai)
```bash
python tools/generate_did_avatar.py
```
- Output: `.tmp/avatar_raw.mp4`
- Sends celebrity image + audio to fal.ai MuseTalk, completes in ~30-60 seconds
- No credit limit — pay per use (~$0.085/video) using `FAL_API_KEY` in `.env`
- **Edge case:** If fal.ai returns no video URL, check FAL_API_KEY and fal.ai account balance
- **Edge case:** If timeout, re-run — fal.ai occasionally has queue delays

### Step 5 — Compose Final Short
```bash
python tools/compose_avatar_video.py "ELON MUSK"
```
- Output: `.tmp/output_short.mp4` (1080x1920, H.264, AAC audio)
- Avatar is scaled to fill vertical frame with blurred background
- Captions overlay at 76% height (yellow bold, black outline, dark pill bg)
- Celebrity name badge at top (red pill)
- **Edge case:** If captions don't appear, verify `.tmp/captions.srt` exists and has content
- **Edge case:** If avatar looks cropped, D-ID may have returned a square video — the compose script handles this automatically

## Output
- Final file: `.tmp/output_short.mp4`
- Duration: ~10-15 seconds
- Resolution: 1080x1920 @ 30fps
- Ready to upload to YouTube Shorts / TikTok / Instagram Reels

## Adding New Celebrities
To add a new celebrity to the curated list, edit `tools/fetch_celebrity_image.py`:
```python
CELEBRITY_IMAGES = {
    ...
    "new celebrity name": "https://wikipedia_or_public_domain_image_url.jpg",
}
```
Requirements for the image URL:
- Public domain or CC license (Wikipedia Commons recommended)
- Front-facing, neutral expression
- Resolution ≥ 512x512
- JPEG or PNG format

## Known Constraints
| Issue | Solution |
|-------|----------|
| fal.ai ~$0.085/video | New accounts get free credits. Check fal.ai dashboard for balance. |
| MuseTalk renders only face area | Compose script adds blurred background to fill 1080x1920 |
| Audio > 30 seconds | Trim script to 25-30 words for ideal Short length |
| Celebrity not in curated list | Add public-domain image URL to fetch_celebrity_image.py |
| Poor lip-sync quality | Use a cleaner front-facing image with neutral expression |
