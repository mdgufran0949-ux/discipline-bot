# Workflow: YouTube Shorts Re-upload to Instagram Pipeline

## Objective
Find 10 trending YouTube Shorts in the **Facts / Did You Know** niche, brand each one with your page name (replacing the original watermark), and upload all 10 to your Instagram page daily.

## Niche Strategy
- **Primary hashtags to rotate:** `didyouknow`, `facts`, `amazingfacts`, `mindblowing`, `interestingfacts`
- **Why Facts niche:** Highest save rate on Instagram → algorithm pushes to more people. Globally shareable, not language-limited.
- **Daily volume:** 10 Reels per day. Do not exceed — accounts posting 20+ Reels/day trigger spam signals.

## How Fetching Works
Content is fetched from **YouTube Shorts** (not Instagram) using **yt-dlp** — no API key required. The tool scans YouTube hashtag pages, filters for Shorts under 90 seconds, and sorts by view count.

## Required .env Keys
```
IG_USER_ID              — your Instagram Business account numeric ID
IG_ACCESS_TOKEN         — long-lived Graph API token (expires every 60 days — see Token Refresh below)
IG_PAGE_NAME            — your page handle e.g. @FactsVault
CLOUDINARY_CLOUD_NAME   — cloudinary.com free account
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
```

## Required Inputs Per Run
- `hashtag` — which hashtag to scrape (rotate daily from the list below)
- `caption` — crafted by the agent (see Caption Guidelines below)

## Output
- 10 Reels published to your Instagram page
- `.tmp/uploaded_log.json` updated with all 10 entries
- `.tmp/reels/` contains both raw and branded `.mp4` files (safe to delete after run)

---

## Steps

### Step 1: Fetch 10 Trending Shorts
```bash
python tools/fetch_reels.py "didyouknow" 10
```
- Scans the YouTube hashtag page for `#didyouknow`
- Returns JSON with up to 10 Shorts sorted by view count (highest first)
- Each result includes: `id`, `video_url`, `post_url`, `caption`, `view_count`, `owner_username`
- Save the full JSON output — iterate over the `reels` array in subsequent steps
- **Edge case:** 0 results → try a broader hashtag (`facts` instead of `didyouknow`)
- **Edge case:** yt-dlp timeout → re-run once; if it fails again, run `pip install -U yt-dlp`

---

### Step 2: For Each Reel — Check for Duplicates
```bash
python tools/check_duplicate.py "{reel_id}"
```
- If `already_uploaded == true` → skip this Reel, move to next
- If `already_uploaded == false` → proceed to Step 3
- Repeat until you have up to 10 non-duplicate Reels to process

---

### Step 3: Download the Short
```bash
python tools/download_reel.py "{video_url}" "{reel_id}" "{post_url}"
```
- Pass `video_url` and `post_url` from Step 1 output (they are the same YouTube URL)
- Downloads to `.tmp/reels/{reel_id}.mp4` using yt-dlp at best available quality
- **Edge case:** File < 100KB → download failed. Skip this Reel and move to next.
- **Edge case:** yt-dlp error → update yt-dlp: `pip install -U yt-dlp`, then retry.

---

### Step 4: Brand the Reel
```bash
python tools/brand_reel.py ".tmp/reels/{reel_id}.mp4" "@YourPageName" "{owner_username}" "" "" "{post_url}"
```
- Use `owner_username` from Step 1 output
- Use `post_url` from Step 1 output (enables YouTube subtitle-based CTA trimming)
- What branding does:
  - OCR scans frames for the original creator's `@handle` watermark → delogs it
  - Replaces it with your page name at the same position
  - Always adds your page name at bottom center
  - Detects creator's "follow me" CTA via subtitles → trims video at that point
  - Adds your own "Follow @YourPage" overlay for last 2.5 seconds
- Output: `.tmp/reels/{reel_id}_branded.mp4`
- **Edge case:** FFmpeg error → re-encode first, then brand:
  ```bash
  ffmpeg -i .tmp/reels/{reel_id}.mp4 -c:v libx264 -c:a aac .tmp/reels/{reel_id}_fixed.mp4
  python tools/brand_reel.py ".tmp/reels/{reel_id}_fixed.mp4" "@YourPageName" "{owner_username}" "" "" "{post_url}"
  ```
- **Edge case:** No audio stream error → the source video has no audio track. Skip this Reel.

---

### Step 5: Craft a Caption
Do NOT copy the original creator's caption verbatim. Write a short, engaging caption:

**Format:**
```
[Hook sentence about the fact] 🤯

Follow @YourPageName for daily mind-blowing facts!

#didyouknow #facts #amazingfacts #mindblowing #interestingfacts #knowledge #learneveryday #factsoflife
```

**Rules:**
- Keep it under 2200 characters (Instagram limit)
- Use 5–8 hashtags: mix broad (`#facts` — 500M+ posts) and niche (`#interestingfacts` — 30M posts)
- Always include a follow CTA: "Follow @YourPageName for daily facts!"
- Add credit to the original creator: "Credit: @{owner_username}"

---

### Step 6: Upload to Instagram
```bash
python tools/upload_reel.py ".tmp/reels/{reel_id}_branded.mp4" "Your caption here #facts"
```
- Uploads branded video to Cloudinary → publishes via Instagram Graph API → deletes from Cloudinary
- Polls container status up to 300 seconds
- On success: prints the live Instagram permalink
- **Edge case:** `status_code == ERROR` → re-encode the video (see Step 4 edge case)
- **Edge case:** Token expired (error 190) → refresh token (see Token Refresh section below)

---

### Step 7: Mark as Uploaded
```bash
python tools/check_duplicate.py "{reel_id}" --mark-uploaded --hashtag "didyouknow"
```
- Logs to `.tmp/uploaded_log.json` immediately after successful upload
- **Critical:** Do not skip this step. If skipped, the same Reel will be re-uploaded next session.
- **Edge case:** If this step fails after a successful upload, run it manually before proceeding.

---

### Step 8: Repeat for Next Reel
Return to Step 2 for the next Reel in the Step 1 results array.

---

## Full Daily Run Example (condensed)

```bash
# Fetch 10 trending YouTube Shorts
python tools/fetch_reels.py "didyouknow" 10

# For each reel from the results (use id, video_url, post_url, owner_username):
python tools/check_duplicate.py "{reel_id}"
# (if not duplicate:)
python tools/download_reel.py "{video_url}" "{reel_id}" "{post_url}"
python tools/brand_reel.py ".tmp/reels/{reel_id}.mp4" "@FactsFlash" "{owner_username}" "" "" "{post_url}"
python tools/upload_reel.py ".tmp/reels/{reel_id}_branded.mp4" "Did you know? 🤯 Credit: @{owner_username} | Follow @FactsFlash! #facts #didyouknow #amazingfacts #mindblowing #knowledge"
python tools/check_duplicate.py "{reel_id}" --mark-uploaded --hashtag "didyouknow"

# Repeat for all 10 Reels
```

---

## Hashtag Rotation Schedule

Rotate hashtags daily to get fresh content and avoid scraping the same Shorts repeatedly:

| Day | Hashtag |
|-----|---------|
| Monday | `didyouknow` |
| Tuesday | `facts` |
| Wednesday | `amazingfacts` |
| Thursday | `mindblowing` |
| Friday | `interestingfacts` |
| Saturday | `knowledge` |
| Sunday | `factsoflife` |

---

## Token Refresh (every 60 days)

Instagram `IG_ACCESS_TOKEN` expires every 60 days. Set a calendar reminder.

**To refresh:**
1. Go to `developers.facebook.com/tools/explorer`
2. Select your App → Generate User Token
3. Grant permissions: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`
4. Click "Generate Long-Lived Token" (exchanges for 60-day token)
5. Copy the new token → update `IG_ACCESS_TOKEN` in `.env`

---

## First-Time Setup Checklist

- [ ] Install yt-dlp: `pip install yt-dlp`
- [ ] Switch Instagram account to Business/Creator (Professional Account)
- [ ] Create Facebook Page and link to Instagram
- [ ] Create Facebook Developer App at developers.facebook.com
- [ ] Generate long-lived access token → get `IG_USER_ID` and `IG_ACCESS_TOKEN`
- [ ] Sign up at cloudinary.com → get `CLOUDINARY_*` keys
- [ ] Run `pip install cloudinary` in your Python environment
- [ ] Fill in all keys in `.env`
- [ ] Post 3–5 Reels manually on the new account before running automation (avoids spam flags)

---

## Known Constraints & Edge Cases

| Issue | Solution |
|-------|----------|
| yt-dlp YouTube blocks | Update yt-dlp: `pip install -U yt-dlp` |
| IG_ACCESS_TOKEN expires 60 days | Refresh manually, set calendar reminder |
| Graph API container ERROR | Re-encode: `ffmpeg -i input.mp4 -c:v libx264 -c:a aac output.mp4` |
| Cloudinary free tier 25GB/month | Assets auto-deleted after publish |
| 0 Shorts found for hashtag | Try broader hashtag; YouTube may be slow |
| Account posting limit (~10–20/day) | Capped at 10/day — do not increase |
| Brand step fails (no audio stream) | Skip that Reel — source has no audio track |

---

## ToS & Copyright Notice

1. **Instagram ToS:** Re-uploading others' content without permission violates Instagram's Terms of Service (Section 3.1). Instagram may remove content, issue warnings, or disable the account.
2. **Copyright:** Original creators own copyright. DMCA takedowns are possible. Always add `"Credit: @original_username"` to captions — this is standard practice in the repost niche.
3. **Recommendation:** Target Shorts from accounts under 50K followers (less active monitoring). Always add credit in captions.
