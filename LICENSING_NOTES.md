# Audio Licensing Notes

## Jamendo tracks (Option A)

All tracks in `audio_library/` are sourced from Jamendo and distributed under
Creative Commons licenses. The pipeline enforces two tiers:

### Standard mode (`monetization_active: false`)
Accepts any CC license, including:
- **CC BY** — credit required
- **CC BY-SA** — credit + share-alike
- **CC0** — public domain
- **CC BY-NC** — non-commercial use only
- **CC BY-ND** — no derivatives
- **CC BY-NC-SA / CC BY-NC-ND** — non-commercial + additional restrictions

### Monetization mode (`monetization_active: true`)
When set in `config/accounts/disciplinefuel.json`, the library manager
automatically excludes any track whose license URL contains `nc` or `nd`.
Only **CC BY**, **CC BY-SA**, and **CC0** tracks are retained.

To enable: add `"monetization_active": true` to your account config before
running bootstrap or refresh. Tracks already in the library that fail the
filter are replaced during the next weekly refresh.

### CC BY attribution requirement
Jamendo's CC BY and CC BY-SA licenses require attribution. The manifest at
`audio_library/manifest.json` records `artist_name`, `title`, and `license_url`
for every track. If you ever display track credits (e.g., in a story or link
in bio), use those fields.

For Instagram Reels, Jamendo's published guidance is that attribution in the
caption or a pinned comment satisfies the CC BY requirement. We do not
currently add attribution automatically — this is a manual step if you choose
to credit.

## ccMixter fallback

When Jamendo is unreachable (network error or API quota exceeded), the library
manager falls back to ccMixter (ccmixter.org), which hosts CC-licensed
instrumental tracks. The same license-tier rules apply.

## What we do NOT use

- **YouTube Audio Library tracks** — Terms of Service prohibit re-hosting
- **Epidemic Sound / Artlist** — Subscription tracks, cannot be self-hosted
- **Any track without an explicit CC license** — Not included

## Updating these notes

If you switch to a paid music licensing service (e.g., Musicbed, Artlist), this
file should be updated and `audio_library_manager.py` should be modified to
remove the Jamendo/ccMixter fallback logic.
