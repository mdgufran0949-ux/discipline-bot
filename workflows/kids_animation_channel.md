# Kids Animation Channel — Biscuit & Zara

## Objective
Produce 1–5 fully automated kids animation YouTube Shorts per day featuring recurring characters BISCUIT and ZARA. Target audience: ages 3–10. Format: educational, 45–65 seconds, Shorts-first.

---

## Daily Run Command

```bash
# Standard daily run (3 videos)
python tools/run_kids_pipeline.py --count 3

# Single video on manual topic
python tools/run_kids_pipeline.py --topic "how butterflies grow" --series "Tiny Scientists"

# Test run without uploading
python tools/run_kids_pipeline.py --count 1 --dry-run

# Compose only (no YouTube upload)
python tools/run_kids_pipeline.py --count 1 --no-upload
```

---

## Pipeline Steps

| Step | Tool | API | Cost |
|------|------|-----|------|
| 1. Trend fetch | `fetch_kids_trends.py` | Google Trends RSS + yt-dlp | Free |
| 2. Script gen | `generate_kids_script.py` | Groq Llama 3.3 70B | ~Free |
| 3. Safety check | `kids_safety_check.py` | Gemini 2.0 Flash | ~Free |
| 4. TTS voiceover | `generate_kids_tts.py` | edge-tts AnaNeural | Free |
| 5. Scene images (×6) | `generate_kids_visuals.py` | kie.ai Ideogram V3 | ~$0.048 |
| 6. Video compose | `compose_kids_video.py` | ffmpeg local | Free |
| 7. Thumbnail | `generate_kids_thumbnail.py` | kie.ai Ideogram V3 | ~$0.008 |
| 8. Upload | `run_kids_pipeline.py` | YouTube Data API v3 | Free |

**Estimated cost: ~$0.056/video → ~$0.28/day at 5 videos → ~$8.40/month**

---

## Character Bibles

### BISCUIT — The Curious Yellow Bear

**Personality:**
- Endlessly curious, asks questions, gets excited easily
- Sometimes makes mistakes that become the lesson
- Catchphrases: "Oh wow!", "Really?!", "Let's find out!"
- Role: The learner/questioner — drives episodes by asking why/how/what

**Visual (use this EXACT description in every image prompt):**
```
BISCUIT is a chubby cheerful yellow bear cub with big round dark brown eyes,
a small pink nose, rounded ears with light pink inner ear, soft fluffy fur,
wearing a tiny red bowtie. Wide happy smile. 2D cartoon animation style, Pixar quality.
```

**Voice:** Enthusiastic, slightly breathless, warm. Speech rate -10%, pitch +5Hz (edge-tts AnaNeural).

---

### ZARA — The Smart Purple Owl

**Personality:**
- Knowledgeable but never condescending
- Patient, warm, uses simple facts and demonstrations
- Gentle humor, never scary or negative
- Role: The explainer/guide — answers BISCUIT's questions with information + fun facts

**Visual (use this EXACT description in every image prompt):**
```
ZARA is a small wise purple owl with large yellow eyes behind round spectacles,
a tiny orange beak, soft feathered wings with darker purple tips,
wearing a small blue graduation cap. Thoughtful friendly expression.
2D cartoon animation style, Pixar quality.
```

---

## Visual Style Guide

### Color Palette
| Role | Color | Hex |
|------|-------|-----|
| BISCUIT yellow | Warm gold | `#FFD700` / `#FFC107` |
| ZARA purple | Medium purple | `#9C27B0` / `#7B1FA2` |
| Sky accent | Bright blue | `#29B6F6` |
| Nature accent | Fresh green | `#66BB6A` |
| Energy accent | Sunset orange | `#FF7043` |
| Caption 1 | Deep orange | `#FF5722` |
| Caption 2 | Green | `#4CAF50` |
| Caption 3 | Blue | `#2196F3` |
| Caption 4 | Amber | `#FFC107` |
| Caption 5 | Purple | `#9C27B0` |
| Caption 6 | Pink | `#E91E63` |

### Font Rules
- Caption font: **Comic Sans Bold** (`comicbd.ttf`) — rounded, child-friendly
- Fallback: Arial Bold (`arialbd.ttf`)
- Caption size: 96px at 1080p
- Always white pill background + dark outline for readability
- Colors rotate per caption line (6-color cycle)

### Scene Composition Rules
- Characters always appear in the lower 40% of frame
- Background: bright, saturated, simple — never cluttered
- Maximum 3 visual elements per scene
- Every scene must include at least one of BISCUIT or ZARA
- BOTH characters must appear together in scene 1 and scene 6

### Image Generation Style Prefix
Always prepend to every image prompt:
```
2D cartoon animation style, bright vibrant colors, child-friendly,
Pixar/Disney quality, soft rounded shapes, no text in image,
safe for children, cheerful and warm lighting, illustration,
```

---

## Content Series

### Series 1: Animals ABC
One animal per letter of the alphabet. BISCUIT meets the animal, ZARA explains one fact.
- Format: 26 videos (full alphabet) + evergreen mix
- Example topics: "A is for Alligator", "B is for Butterfly", "E is for Elephant"
- Hashtags: `#animalsabc #kidslearning #animalsforchildren #alphabetforkids`

### Series 2: Fun Numbers
Counting, addition, shapes with real-world objects.
- Format: Numbers 1–20 with thematic scenes
- Example topics: "Counting Farm Animals 1 to 10", "Shapes in the Kitchen"
- Hashtags: `#countingforkids #mathforkids #numbersongs #learningnumbers`

### Series 3: Tiny Scientists
Simple science that kids can relate to or try at home.
- Format: ZARA explains, BISCUIT reacts with surprise
- Example topics: "Why do leaves change color?", "How do volcanoes work?", "Why is the sky blue?"
- Hashtags: `#scienceforkids #kidsexperiments #tinyscientist #curiosityforkids`

### Series 4: Story Time
Classic fairy tales and fables reimagined with Biscuit & Zara.
- Format: 2–3 episode arcs, one story per video
- Example topics: "The Tortoise and the Hare", "The Three Little Pigs", "The Ugly Duckling"
- Hashtags: `#storytime #kidsstories #fairytales #bedtimestories`

### Series 5: World Wonders
Geography, cultures, nature phenomena at kid level.
- Format: BISCUIT and ZARA "visit" a location, learn one fact
- Example topics: "What lives in the Amazon rainforest?", "Why does it snow?"
- Hashtags: `#worldforkids #geographyforkids #cultureforkids`

### Standalone (Trending)
Driven by `fetch_kids_trends.py` daily output. Seasonal, viral animal moments, trending kid topics.

---

## SEO Strategy

### Title Formula
```
[Action Verb] [Topic] with Biscuit and Zara! | [Benefit phrase] | [Age group]
```
Example: `Counting Farm Animals with Biscuit and Zara! | Numbers 1-10 | Learning for Kids`

### Description Template
```
Join Biscuit the bear and Zara the owl as they [topic activity]! Perfect for [age group] learning [topic].

In this video, your child will learn:
• [fact 1]
• [fact 2]
• [fact 3]

#kidslearning #[topic hashtag] #biscuitandzara #educationalvideo #preschool #Shorts
```

### Tags Strategy
Mix three tiers:
1. **Broad discovery**: `kids learning`, `educational`, `preschool`, `toddler`
2. **Topic-specific**: `farm animals`, `counting 1 to 10`, `dinosaurs for kids`
3. **Channel**: `biscuit bear`, `zara owl`, `biscuit and zara`

---

## COPPA Compliance

**ALL videos MUST be uploaded with `selfDeclaredMadeForKids: True`.**

This is enforced in `run_kids_pipeline.py`. Consequences of not setting this:
- FTC fines up to $50,000 per violation
- Channel termination

What this flag does automatically:
- Disables personalized ads (lower CPM but legally required)
- Disables comments
- Restricts data collection from minors

### Safety Check Rules (auto-enforced by `kids_safety_check.py`)
- No violence or threat of violence
- No scary content (death, monsters, darkness)
- No adult themes (romance, money, illness, war)
- No brand names (McDonald's, Coca-Cola, etc.)
- No political content
- No body shaming

### Manual Review Triggers
Log these for human inspection before upload:
- Safety check confidence below 0.85
- Videos about food (risk of brand name)
- Videos about money or economics
- Holiday content (may include religious references)

---

## Scaling Strategy

| Phase | Daily Output | Action |
|-------|-------------|--------|
| Week 1–2 | 1 video/day | Test pipeline end-to-end, verify quality |
| Week 3–4 | 2 videos/day | Check watch time, retention in YouTube Studio |
| Month 2 | 3 videos/day | Introduce second content series |
| Month 3+ | 5 videos/day | Scale to full automation |

---

## Performance Monitoring

Check weekly in YouTube Studio:
- **Watch time %** — target >50% average view duration for kids Shorts
- **CTR** — target >8% (kids thumbnails typically get high CTR)
- **Top performing categories** — double down on what works
- **Subscriber conversion** — which topics drive follows

Upgrade triggers:
- If watch time <40% → improve script pacing (shorter sentences)
- If CTR <5% → A/B test thumbnails (BISCUIT-forward vs ZARA-forward)
- If comments disabled hurts growth → this is normal for COPPA content, expected

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| kie.ai task timeout | Increase `POLL_TIMEOUT` in visuals/thumbnail scripts |
| Safety check blocking valid scripts | Review `kids_safety_check.py` prompt, loosen specific flags |
| TTS too fast | Change `RATE` from `-10%` to `-15%` in `generate_kids_tts.py` |
| Character inconsistency across scenes | Check that BISCUIT_DESC and ZARA_DESC are fully embedded in each image_prompt |
| YouTube upload fails (COPPA) | Verify `selfDeclaredMadeForKids: True` in `run_kids_pipeline.py` |
| Captions out of sync | Verify INTRO_DUR offset is applied in `compose_kids_video.py` |
