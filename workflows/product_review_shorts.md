# Workflow: Product Review Shorts (Amazon + Flipkart)

## Objective
Automatically discover trending tech gadgets under Rs.999 on Amazon India and Flipkart, generate English AI review scripts, compose a cinematic product showcase video (with 360-degree multi-angle view), and cross-post to Instagram Reels + YouTube Shorts.

## Account Config
`config/accounts/techdeals.json`
- Fill in `ig_user_id` and `ig_access_token` for Instagram
- Fill in `yt_channel_id` for YouTube
- Replace affiliate placeholder tags after signup

## Required Environment Variables (`.env`)
```
RAPIDAPI_KEY=          # For Amazon product search (rapidapi.com — free tier, 100 req/month)
GROQ_API_KEY=          # Already set — used for script generation
IG_USER_ID=            # Instagram Business account ID
IG_ACCESS_TOKEN=       # Instagram long-lived access token
CLOUDINARY_CLOUD_NAME= # Already set — used for Reel upload
CLOUDINARY_API_KEY=    # Already set
CLOUDINARY_API_SECRET= # Already set
```

---

## Standard Run

```bash
# Test with 1 product, no uploads (always start here)
python tools/run_product_pipeline.py --source amazon --count 1 --dry-run

# Live run: 2 products from both platforms
python tools/run_product_pipeline.py --source both --count 2

# Amazon only, 3 products
python tools/run_product_pipeline.py --source amazon --count 3

# Skip YouTube if not yet authorized
python tools/run_product_pipeline.py --source both --count 2 --skip-youtube
```

---

## Pipeline Steps (run_product_pipeline.py orchestrates all of these)

### Step 1: Fetch Products
```bash
python tools/fetch_product_deals.py --source amazon --count 5 --max-price 999 --output .tmp/products.json
```
- Amazon: Uses RapidAPI "Real-Time Amazon Data" (set `RAPIDAPI_KEY`)
- Flipkart: Scrapes search results with BeautifulSoup
- Returns: title, price, rating, review_count, ALL product images (angles 1-8), product_url
- Filters: 4.0+ stars, 50+ reviews, price <= Rs.999, minimum 1 image

### Step 2: Generate Script
```bash
python tools/generate_product_script.py --product .tmp/products.json --output .tmp/product_script.json
```
- Model: Groq Llama 3.3 70B
- Output: English script (~100 words), 6 segments with timings, title, hashtags, caption
- Script structure: Hook (0-3s) → 360° narration (3-11s) → 3 features → CTA (23-26s)

### Step 3: TTS
```bash
python tools/generate_kokoro_tts.py "script text here" af_sarah
```
- Voice: af_sarah (Kokoro, local, free)
- Output: `.tmp/voiceover.mp3` + `.tmp/captions.srt`

### Step 4: Compose Video
```bash
python tools/compose_product_video.py --product .tmp/current_product.json --script .tmp/product_script.json --audio .tmp/voiceover.mp3
```
- Downloads all product images (up to 8 angles)
- Scene 1: HOOK — main image + gold price overlay
- Scene 2: 360° VIEW — rapid fire through all angles (0.9s per image), `360° VIEW` badge + dot indicator
- Scene 3-5: Feature shots — angle image + white bullet text
- Scene 6: CTA — star rating + price + "LINK IN BIO" green button
- Output: `.tmp/product_video.mp4` (1080x1920)

### Step 5: Upload Instagram
```bash
python tools/upload_reel.py .tmp/product_video.mp4 "caption text"
```
- Requires `IG_USER_ID` and `IG_ACCESS_TOKEN` in `.env`

### Step 6: Upload YouTube Shorts
```bash
python tools/upload_youtube_short.py --video .tmp/product_video.mp4 --script .tmp/product_script.json
```
- First run: opens browser for Google OAuth (saves token to `.tmp/youtube_token.pkl`)
- Subsequent runs: auto-refresh
- Requires YouTube Data API v3 enabled on the Google Cloud project in `credentials.json`

---

## First-Time Setup

### RapidAPI (Amazon product data)
1. Sign up at rapidapi.com (free)
2. Search "Real-Time Amazon Data" → Subscribe to free tier (100 req/month)
3. Copy API key → add to `.env` as `RAPIDAPI_KEY=`

### Instagram
1. Convert Instagram account to Business/Creator
2. Connect to a Facebook Page
3. Generate long-lived access token via Facebook Developer Console
4. Add `IG_USER_ID` and `IG_ACCESS_TOKEN` to `.env`

### YouTube
1. Go to Google Cloud Console → Enable YouTube Data API v3
2. Create OAuth 2.0 credentials (Desktop app type)
3. Download as `credentials.json` (project root)
4. Run `python tools/upload_youtube_short.py --video test.mp4 --script test.json` once to authorize
5. Token saved to `.tmp/youtube_token.pkl` — auto-refreshes from then on

### Amazon Associates (affiliate links)
1. Sign up at affiliate-program.amazon.in
2. Get your Tracking ID (e.g. `yourname-21`)
3. Update `config/accounts/techdeals.json` → `monetization.amazon_affiliate`
4. Update caption templates to include affiliate link

---

## Duplicate Prevention
Uploaded product IDs (ASIN / Flipkart product ID) are logged to `.tmp/product_upload_log.json`.
The pipeline skips any product that was already uploaded.

---

## Known Constraints
- **RapidAPI free tier**: 100 requests/month. Each pipeline run with `--source amazon --count 3` uses ~6 requests (3 search + 3 detail calls). Budget ~16 runs/month.
- **Flipkart scraping**: May break if Flipkart changes their HTML/CSS class names. Update selectors in `fetch_product_deals.py` if it stops working.
- **YouTube OAuth**: Token expires after ~1 hour of inactivity but auto-refreshes. If token file is deleted, re-run the upload tool once to re-authorize.
- **Image white backgrounds**: Amazon product images have white backgrounds. The gradient overlay in `compose_product_video.py` handles this — text is readable but the product stays visible.
- **Kokoro TTS**: Uses local `af_sarah` voice (English). Runs fully offline, no API cost. If audio quality is off, try `af_bella` or `am_adam` as alternative voices.

---

## Improving Over Time
- If a particular product category performs well, hardcode it in `AMAZON_QUERIES` inside `fetch_product_deals.py`
- If a hook formula goes viral, add it to the Groq prompt template in `generate_product_script.py`
- Track which products drove affiliate clicks and feed that data back into the fetch filters
