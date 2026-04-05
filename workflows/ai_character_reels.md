# Workflow: AI Character Instagram Reels Pipeline

## Objective
Post daily Motivation/Mindset Reels to Instagram using a consistent AI character. The same character face appears in every video — building a recognizable virtual influencer persona. Fully automated at $0/month.

## Niche
Motivation / Mindset — daily motivational content, mindset tips, success psychology.

## Tool Stack
| Step | Tool | Cost |
|------|------|------|
| Trending | `fetch_motivation_trends.py` (YouTube + Google Trends) | Free |
| Script | `generate_motivation_script.py` (Groq Llama 3.3 70B) | Free |
| Voice | `generate_kokoro_tts.py` (Kokoro TTS, CPU) | Free |
| Avatar | `generate_latsync_avatar.py` (LatentSync local OR fal.ai) | Free |
| Compose | `compose_avatar_video.py` (FFmpeg) | Free |
| Upload | `upload_reel.py` (Instagram Graph API) | Free |

---

## One-Time Setup (do this before first run)

### 1. Create the character face image
- Generate a photorealistic human face using any free tool:
  - **Leonardo.ai** (free tier) — recommended, highest quality
  - **Adobe Firefly** (free) — good alternative
  - **Stable Diffusion** locally — unlimited, requires setup
- Requirements: front-facing, neutral expression, good lighting, min 512x512px
- Save permanently to: `config/character/face.jpg`
- **Use this SAME image for every single run — never change it**

### 2. Install LatentSync (Option A — local GPU)
```bash
git clone https://github.com/bytedance/LatentSync
cd LatentSync
pip install -r requirements.txt
# Download model checkpoints per LatentSync/README.md
```
- Requires: NVIDIA GPU with 8GB+ VRAM
- If no GPU → use Option B below

### 2b. Set up fal.ai (Option B — no GPU needed)
```bash
pip install fal-client
```
- Register at fal.ai → get free API credits
- Add to `.env`: `FAL_API_KEY=your_key_here`

### 3. Get Groq API key (free)
- Register at console.groq.com
- Add to `.env`: `GROQ_API_KEY=your_key_here`

### 4. Install Kokoro TTS
```bash
pip install kokoro soundfile numpy
```

### 5. Create Instagram Business account for the character
- Create a new Instagram account for your AI character
- Convert to Business/Creator (Professional Account)
- Link to a Facebook Page
- Generate Instagram Graph API access token
- Add to `.env` or to a new account config file

### 6. Create account config
Copy an existing account config and modify:
```bash
cp config/accounts/factsflash.json config/accounts/[character_name].json
```
Update niche, ig_user_id, ig_access_token, ig_page_name, hashtag_pool.

---

## Daily Pipeline

### Step 1: Fetch Trending Topic
```bash
python tools/fetch_motivation_trends.py
```
- Scans YouTube motivation hashtags for today's most relevant topics
- Falls back to evergreen topics if YouTube is slow
- Pick the `best_topic` from the output for the next step
- **Edge case:** yt-dlp timeout → use any evergreen topic manually

---

### Step 2: Generate Script
```bash
python tools/generate_motivation_script.py "why most people never achieve their goals"
```
- Uses Groq Llama 3.3 70B (free, 500k tokens/day)
- Outputs JSON with `narration` (60-80 words) and `caption`
- **Edge case:** Script > 80 words → re-run. Groq is fast, re-run is cheap.
- **Edge case:** Groq rate limit (429) → wait 10 seconds, retry

---

### Step 3: Generate Voiceover
```bash
python tools/generate_kokoro_tts.py "narration text here"
```
- Saves `.tmp/voiceover.mp3` + `.tmp/captions.srt`
- Default voice: `am_adam` (strong male). Change to `af_heart` for female character.
- **Edge case:** `ImportError` → `pip install kokoro soundfile numpy`
- **Edge case:** Silent output → check text has no special characters

---

### Step 4: Generate Avatar Video
```bash
python tools/generate_latsync_avatar.py
```
- Reads `config/character/face.jpg` + `.tmp/voiceover.mp3`
- Outputs `.tmp/avatar_raw.mp4`
- LatentSync (local) takes ~30-120s on GPU
- fal.ai (cloud) takes ~30-60s
- **Edge case:** LatentSync checkpoint missing → follow README.md model download steps
- **Edge case:** fal.ai quota → upgrade plan or switch to local Option A
- **Edge case:** Output video is corrupted → check face.jpg is JPEG, front-facing, min 512x512

---

### Step 5: Compose Final Reel
```bash
python tools/compose_avatar_video.py "CHARACTER NAME"
```
- Outputs `.tmp/output_short.mp4` (1080x1920, H.264, 30fps)
- Replace `CHARACTER NAME` with your character's display name
- **Edge case:** Captions don't appear → check `.tmp/captions.srt` exists and has content

---

### Step 6: Upload to Instagram
```bash
python tools/upload_reel.py ".tmp/output_short.mp4" "caption text here #motivation #mindset"
```
- Use the `caption` field from Step 2 output
- **Edge case:** Token expired (error 190) → refresh token (see Token Refresh below)
- **Edge case:** Video error → re-encode: `ffmpeg -i avatar_raw.mp4 -c:v libx264 -c:a aac fixed.mp4`

---

## Full Daily Run (copy-paste)

```bash
# Step 1 — get today's topic
python tools/fetch_motivation_trends.py

# Step 2 — generate script (use best_topic from step 1)
python tools/generate_motivation_script.py "why most people never achieve their goals"

# Step 3 — generate voiceover (use narration from step 2)
python tools/generate_kokoro_tts.py "Stop waiting for motivation. Discipline is what separates winners from everyone else. You don't need to feel ready. You need to act. The most successful people didn't have better opportunities. They had better habits. Start with one hour of focused work every morning. No phone. No excuses. Your future is built in the hours others waste. What are you doing with yours?"

# Step 4 — generate avatar
python tools/generate_latsync_avatar.py

# Step 5 — compose final reel
python tools/compose_avatar_video.py "ALEX"

# Step 6 — upload
python tools/upload_reel.py ".tmp/output_short.mp4" "Stop waiting for motivation. Discipline wins. Follow @YourCharacter for daily mindset shifts. #motivation #discipline #mindset #success #selfimprovement"
```

---

## Hashtag Rotation (Motivation Niche)

Rotate daily to maximize reach:

| Day | Primary Hashtags |
|-----|-----------------|
| Monday | `#motivation #mondaymotivation #discipline #success` |
| Tuesday | `#mindset #growthmindset #selfimprovement #goals` |
| Wednesday | `#hustle #grind #hardwork #consistency #focus` |
| Thursday | `#habits #morningroutine #productivity #winning` |
| Friday | `#confidence #fearless #levelup #ambition` |
| Saturday | `#success #wealth #mindfulness #mentalstrength` |
| Sunday | `#sundaymotivation #newweek #goaldigger #inspire` |

Always include: `#motivation #mindset #selfimprovement` as baseline.

---

## Token Refresh (every 60 days)

1. Go to `developers.facebook.com/tools/explorer`
2. Select your App → Generate User Token
3. Permissions: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`
4. Click "Generate Long-Lived Token"
5. Update `IG_ACCESS_TOKEN` in `.env` or account config

---

## Known Constraints

| Issue | Solution |
|-------|----------|
| LatentSync needs GPU | Use fal.ai Option B with FAL_API_KEY |
| fal.ai free credits exhausted | Switch to local LatentSync or upgrade plan |
| Groq rate limit (500k tokens/day) | ~600 scripts/day — unlikely to hit this |
| Kokoro TTS no GPU needed | Runs on CPU, takes ~5-15 seconds |
| face.jpg must stay the same | Never replace it — it's your character's identity |
| Instagram posting limit | 1-2 Reels/day for new accounts to avoid spam flags |
| Cloudinary free tier 25GB/month | Auto-deleted after upload — no issue for daily use |
