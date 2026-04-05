# Workflow: AI Historical Documentary (Hindi) — "AI से देखो Bharat"

## Objective
Produce a 5–10 minute Hindi YouTube documentary showing historical India through AI-reconstructed visuals. Each video reveals what an ancient city, empire, or era actually looked like — content that gets millions of views in English but is barely touched in Hindi.

## Why This Wins
- English channels doing this: 1–2M views/video (proven format)
- Hindi equivalent: almost zero competition
- Indian audience: deep emotional resonance with own history
- Long videos = high watch time = YouTube algorithm boost
- RPM: ₹80–150 (education/history niche)
- Zero copyright risk: historical content

## Channel Concept
**Name:** "AI से देखो Bharat" or "भारत की कहानी"
**Format:** 10 scenes, 5–10 minutes, Hindi narration, AI historical images, Ken Burns effect
**Upload schedule:** 1 video/day or 1 every 2 days

## Topic Pool (proven performers)
| Priority | Topic |
|----------|-------|
| ⭐⭐⭐ | "1800 की दिल्ली — मुगलों की आखिरी राजधानी" |
| ⭐⭐⭐ | "500 साल पहले का भारत — विजयनगर साम्राज्य का स्वर्णकाल" |
| ⭐⭐⭐ | "हड़प्पा सभ्यता: 5000 साल पहले का शहर" |
| ⭐⭐ | "नालंदा विश्वविद्यालय: दुनिया का पहला कैंपस" |
| ⭐⭐ | "1857 की क्रांति: वो दिन जब भारत ने विद्रोह किया" |
| ⭐⭐ | "मुगल काल की आगरा — ताज से पहले का शहर" |
| ⭐⭐ | "चंद्रगुप्त मौर्य का पाटलिपुत्र" |
| ⭐ | "1947 से पहले की मुंबई (बॉम्बे)" |
| ⭐ | "मराठा साम्राज्य: शिवाजी का किला" |
| ⭐ | "तक्षशिला: 2700 साल पहले का ज्ञान का केंद्र" |

## Required .env Keys
```
GROQ_API_KEY     — free at console.groq.com (500k tokens/day)
FAL_API_KEY      — fal.ai account (FLUX images, ~$0.003/image)
```

No IG tokens needed for YouTube uploads.

## Tool Stack
| Step | Tool | Cost |
|------|------|------|
| Script | `generate_documentary_script.py` (Groq Llama 3.3 70B) | Free |
| TTS | `generate_hindi_tts.py` (edge-tts Hindi) | Free |
| Images | `generate_ai_images.py` (fal.ai FLUX schnell) | ~$0.03/video |
| Compose | `compose_documentary.py` (FFmpeg Ken Burns) | Free |
| Upload | `upload_reel.py` (Instagram) or YouTube manually | Free |

**Total cost per video: ~$0.03 (₹2.5)**

---

## Pipeline

### Step 1: Generate Documentary Script
```bash
python tools/generate_documentary_script.py "1800 की दिल्ली — मुगलों की आखिरी राजधानी"
```
- Uses Groq Llama 3.3 70B (free)
- Outputs `.tmp/documentary_script.json`
- 10 scenes: Hindi narration + English image prompts + Ken Burns direction
- **Edge case:** Script has < 5 scenes → re-run. Groq is fast.
- **Edge case:** Groq rate limit (429) → wait 10 seconds, retry

---

### Step 2: Generate Hindi Voiceover
```bash
# Combine all narration from the script JSON, then:
python tools/generate_hindi_tts.py "complete narration text from all scenes"
```

**How to get the combined narration:**
```bash
python -c "
import json
with open('.tmp/documentary_script.json', encoding='utf-8') as f:
    d = json.load(f)
text = ' '.join(s['narration'] for s in d['scenes'])
print(text)
"
```
Then copy the output and pass it to generate_hindi_tts.py.

- Outputs `.tmp/voiceover.mp3` + `.tmp/captions.srt`
- Default voice: hi-IN-MadhurNeural (male, documentary tone)
- For female voice: `python tools/generate_hindi_tts.py --voice female "text"`
- **Edge case:** Silent output → check text has no special characters only
- **Edge case:** ImportError edge_tts → `pip install edge-tts`

---

### Step 3: Generate AI Scene Images
```bash
python tools/generate_ai_images.py
```
- Reads `.tmp/documentary_script.json` for image prompts
- Generates `.tmp/images/scene_001.jpg` through `scene_010.jpg`
- Uses FLUX schnell by default (~$0.003/image)
- For higher quality: `python tools/generate_ai_images.py --quality dev`
- **Edge case:** fal.ai quota exhausted → check usage at fal.ai dashboard
- **Edge case:** One image fails → script skips it, compose tool warns and skips that scene
- Already-generated images are skipped automatically (re-run safe)

---

### Step 4: Compose Documentary Video
```bash
python tools/compose_documentary.py "AI से देखो Bharat"
```
- Reads script, images, voiceover, captions
- Applies Ken Burns effect per scene (zoom in/out/pan alternating)
- Blurred background fills portrait frame
- Burns Hindi captions at bottom
- Channel badge at top
- Outputs `.tmp/output_documentary.mp4` (1080x1920, H.264)
- **Edge case:** Missing image → that scene is skipped, other scenes proceed
- **Edge case:** Hindi captions appear as boxes → Nirmala.ttc font missing. Install Nirmala UI font or use ARIALUNI.TTF fallback.
- **Edge case:** Compose fails on zoompan → update ffmpeg: `winget upgrade Gyan.FFmpeg`

---

### Step 5: Upload
**YouTube Shorts / Long-form:**
Upload `.tmp/output_documentary.mp4` manually to YouTube with:
- Title: use `youtube_title` from script JSON
- Description: use `youtube_description` from script JSON
- Tags: इतिहास, भारत, मुगल, AI, documentary, historical India

**Instagram Reels (optional):**
```bash
python tools/upload_reel.py ".tmp/output_documentary.mp4" "caption from script JSON"
```

---

## Full Pipeline (Copy-Paste)

```bash
# Step 1: Generate script
python tools/generate_documentary_script.py "1800 की दिल्ली — मुगलों की आखिरी राजधानी"

# Step 2: Get combined narration
python -c "
import json
with open('.tmp/documentary_script.json', encoding='utf-8') as f:
    d = json.load(f)
text = ' '.join(s['narration'] for s in d['scenes'])
print(repr(text))
"

# Step 3: Generate Hindi TTS (paste the text from step 2)
python tools/generate_hindi_tts.py "paste full narration here"

# Step 4: Generate AI images
python tools/generate_ai_images.py

# Step 5: Compose
python tools/compose_documentary.py "AI से देखो Bharat"

# Output: .tmp/output_documentary.mp4
```

---

## Background Music (Optional)
Place any royalty-free ambient/orchestral track at:
```
config/music/background.mp3
```
The compose tool auto-detects it and mixes at 10% volume with fade-in/out.

Recommended: search "Indian classical ambient royalty free" on Pixabay or YouTube Audio Library.

---

## Known Constraints
| Issue | Solution |
|-------|----------|
| fal.ai ~$0.003/image | 10 images = $0.03/video. Keep generating daily. |
| FLUX schnell quality | Use `--quality dev` for important topics |
| Hindi captions font | Nirmala.ttc must exist at C:\Windows\Fonts\ |
| Groq 500k tokens/day | ~300 scripts/day — impossible to hit |
| Video too long for Shorts | Target 10 scenes at 5–8 min = YouTube long-form, not Shorts |
| edge-tts requires internet | Use when connected; no API key needed |

## Quality Tips
- **Best topics** for virality: Mughal era, 1857 revolt, ancient cities, Harappa — deeply emotional
- **Image prompt tip:** Add "warm golden hour lighting, dramatic shadows" for cinematic look
- **Narration tip:** Keep each scene to 3 sentences max — punchy, visual, factual
- **Thumbnail:** Use scene_001.jpg or scene_005.jpg with bold Hindi text overlay
- **Consistency:** Use same channel name badge every video for brand recognition
