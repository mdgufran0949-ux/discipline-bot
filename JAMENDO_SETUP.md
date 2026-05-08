# Jamendo API Setup
One-time setup, ~3 minutes. After this, the audio library builds and refreshes itself.

## Steps

### 1. Create a Jamendo developer account
Go to: https://devportal.jamendo.com/

Click **Sign Up**. Only requires an email address — no payment, no verification.

### 2. Create an app and get your client_id
After logging in:
1. Click **My Apps** in the top nav
2. Click **Create a new App**
3. App name: `disciplinefuel-bot` (or anything you like)
4. App URL: leave blank or use your GitHub repo URL
5. Click **Create**
6. Copy the **Client ID** shown on the app detail page

### 3. Add client_id to GitHub repo secrets
1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `JAMENDO_CLIENT_ID`
4. Value: paste your client_id
5. Click **Add secret**

### 4. Trigger the bootstrap
1. Go to **Actions** tab in your GitHub repo
2. Select **DisciplineFuel Audio Library — Bootstrap**
3. Click **Run workflow** → **Run workflow**
4. Wait ~5 minutes for 60 tracks to download

### 5. Verify
After the workflow completes, you should see a new commit in your repo:
`feat: bootstrap Jamendo audio library [skip ci]`

The `audio_library/` folder will contain 4 subdirectories (one per pillar)
and `audio_library/manifest.json` with metadata for all 60 tracks.

## After setup

- **Switch to library mode**: set `"manual_audio_mode": false` in `config/accounts/disciplinefuel.json`
- **Weekly refresh**: runs automatically every Sunday at 03:00 UTC
- **Library status**: `python tools/audio_library_manager.py --status`

## Rate limits

Jamendo free tier: 35,000 API requests/month.
Bootstrap uses ~10 requests (one per pillar + pagination).
Weekly refresh uses ~8 requests.
We use ~80 requests/month total — well under the limit.
