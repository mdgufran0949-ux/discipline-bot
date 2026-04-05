# Workflow: Claude Pipeline Orchestration

## Objective
Claude runs the full daily Reels pipeline on behalf of the user — no manual steps required. User says something like "run today's pipeline" or "run factsflash" and Claude handles everything, reports back what was uploaded and any errors.

## Trigger Phrases
- "run today's pipeline"
- "run the pipeline"
- "run [account name] pipeline" (e.g. "run factsflash")
- "run all accounts"
- "upload today's reels"

---

## Step 1: Determine Scope

| User says | Command to run |
|-----------|---------------|
| "run all accounts" / "run today's pipeline" | `python tools/run_all_accounts.py` |
| "run factsflash" | `python tools/run_pipeline.py --account factsflash` |
| "run techmindblown" | `python tools/run_pipeline.py --account techmindblown` |
| "run [account] with [hashtag]" | `python tools/run_pipeline.py --account [account] --hashtag "[hashtag]"` |
| "upload [N] reels to [account]" | `python tools/run_pipeline.py --account [account] --count N` |

Available accounts: `factsflash`, `techmindblown`, `coresteelfitness`, `cricketcuts`

---

## Step 2: Run the Pipeline

Execute the appropriate command. The pipeline will:
1. Validate Instagram token — fails fast if expired
2. Run weekly performance monitor (silent, updates content preferences)
3. Auto-refresh hashtag pool if >7 days old
4. Fetch trending YouTube Shorts for the account's niche
5. For each reel: duplicate check → download → resolution check (720p+) → brand → upload → mark uploaded
6. Print a summary at the end

Expected runtime: 5–20 minutes depending on account and reel count.

---

## Step 3: Read and Report the Output

After the run, report back to the user:
- How many reels were **uploaded** (out of target)
- How many were **skipped** (duplicates, low views, low resolution)
- How many **failed** (errors)
- Average YouTube view count of uploaded reels
- Any errors that need attention

**Example report:**
```
factsflash: 8/10 uploaded | 15 skipped (duplicates/low views) | 2 failed
Avg views of uploaded content: 1,200,000
techmindblown: 10/10 uploaded | 8 skipped | 0 failed
```

---

## Step 4: Handle Errors

| Error | Action |
|-------|--------|
| `Token EXPIRED` | Tell user to refresh token at `developers.facebook.com/tools/explorer` and update `config/accounts/{account}.json` |
| `No viral Shorts found` | Suggest running with a different hashtag: `python tools/run_pipeline.py --account [account] --hashtag "facts"` |
| `yt-dlp` errors | Run `pip install -U yt-dlp` then retry |
| Individual reel download failure | Normal — pipeline skips and continues. Only flag if >50% fail. |
| Cloudinary upload error | Check Cloudinary free tier quota at cloudinary.com dashboard |

---

## Step 5: Check Logs (Optional)

If user wants to see detailed logs:
- Latest run: `.tmp/logs/` — read the most recent `.log` file
- Upload history per account: `.tmp/{account}/uploaded_log.json`

---

## Quick Reference

```bash
# Run all accounts (recommended daily)
python tools/run_all_accounts.py

# Run one account
python tools/run_pipeline.py --account factsflash

# Run with specific hashtag
python tools/run_pipeline.py --account factsflash --hashtag "amazingfacts"

# Run fewer reels (e.g. test run)
python tools/run_pipeline.py --account factsflash --count 3

# Check performance metrics
python tools/monitor_reels.py --account factsflash
```

---

## Accounts Reference

| Account | Niche | Min Views |
|---------|-------|-----------|
| factsflash | Amazing general facts, did you know | 500,000 |
| techmindblown | Tech facts | (see config) |
| coresteelfitness | Fitness | (see config) |
| cricketcuts | Cricket | (see config) |
