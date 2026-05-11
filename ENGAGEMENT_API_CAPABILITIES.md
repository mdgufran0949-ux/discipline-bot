# Instagram Graph API — Engagement Capabilities (May 2026)

Research conducted before building engagement bot (PR #3).
Sources: Meta Developer docs, live fetch of endpoint reference pages.

---

## Decision summary (read this first)

**Outbound commenting on OTHER accounts' posts is NOT supported by the
Instagram Graph API.** The spec's primary engagement mechanic is blocked
at the API level. Per the build spec: scope-down confirmed.

**PR #3 build decision (2026-05-11):** Implemented self-reply bot only
(`tools/reply_bot.py`). No outbound stub. Ramp schedule: 5/day week 1,
8/day week 2, 12/day week 3, 15/day week 4+. Hard cap: 50/day.
Default `engagement.enabled = false` — flip to activate.

---

## 1. Can we post comments on OTHER users' posts?

**No.**

The official documentation states, verbatim:

> "get comments, reply to comments, delete comments, hide/unhide comments,
> and disable/enable comments on Instagram media **owned by your app user's
> Instagram professional account**"

There is no endpoint that allows an authenticated app to post a new comment
on a media object belonging to a *different* account. The
`POST /{ig-media-id}/comments` endpoint only functions on media IDs that
belong to the authenticated user's own professional account.

This restriction has been in place since API permissions were tightened in
2018 and has not changed in any API version through v22.0 (current as of
May 2026).

**Workarounds via official API: none.**
Browser automation and scraping would violate the constraint "official
Instagram Graph API only" in the build spec. Not building those.

---

## 2. Can we reply to comments on OUR OWN posts?

**Yes.**

Endpoint: `POST /{ig-comment-id}/replies`
Required permissions: `instagram_basic`, `instagram_manage_comments`,
`pages_show_list`, `page_read_engagement`

Restrictions:
- Can only reply to top-level comments (replies to replies land on the
  top-level comment)
- Cannot reply to hidden comments
- Cannot reply to comments on live video

This is the only outbound commenting action available via the API.

---

## 3. Can we detect and respond to @mentions?

**Yes (read) / Partial (respond).**

The API can detect media where our account has been @mentioned by other
users. We can then reply to the comment containing the mention via the
replies endpoint above.

---

## 4. Required permission scopes

| Action | Scopes required |
|--------|----------------|
| Read own comments | `instagram_basic`, `pages_show_list` |
| Reply to own-post comments | `instagram_basic`, `instagram_manage_comments`, `pages_show_list`, `page_read_engagement` |
| Hide/delete own-post comments | `instagram_manage_comments` |
| Detect @mentions | `instagram_basic`, `pages_show_list` |
| Post comment on other user's media | **Not possible** |

Note: `instagram_business_manage_comments` replaces `instagram_manage_comments`
for apps using Instagram Login (vs Facebook Login). Both remain valid as of
v22.0 but `business_manage_comments` is the forward-looking scope.

---

## 5. Rate limits (as of 2025–2026)

Meta significantly reduced Graph API rate limits in 2025 with no advance
notice. Current limits:

- **Per-app, per-hour:** ~200 API calls (down from 5,000 — a 96% reduction)
- **Business Use Case (BUC) model:** `4800 × number_of_impressions` calls
  per rolling 24h window — for high-traffic apps only
- **429 response:** returned when hourly quota exceeded; quota resets on a
  rolling hourly window
- **All calls count against quota:** failed requests, invalid requests, and
  successful requests consume quota equally

Practical implication for our bot: at 200 calls/hour, fetching recent
comments on our posts (1 call per fetch) and replying (1 call per reply)
leaves ample headroom for a low-volume reply bot. Not a concern at our
scale.

---

## 6. Anti-spam mechanisms (2024–2026)

No new comment-specific anti-spam endpoints or signals have been documented
in the Graph API changelog through v22.0. Meta's anti-spam enforcement for
comments is handled at the platform layer (not exposed via API):

- Repeated identical comments from any source are flagged by Instagram's
  internal spam classifier
- Sudden action spikes trigger shadow restrictions on the account
  (not surfaced as API errors — silent throttle)
- These platform-level restrictions apply equally to API-posted actions
  and manual actions

Mitigation: randomize timing, vary comment text, stay well below daily caps.

---

## What IS buildable under official API constraints

Given the above, the engagement bot can legitimately build:

1. **Comment reply engine** — monitor comments on our posts every N hours,
   generate contextual replies, post via `/{comment-id}/replies`
2. **@mention responder** — detect @mentions, reply via the same endpoint
3. **Comment moderation** — hide spam, delete abuse (housekeeping, not growth)

What is NOT buildable without violating the "official API only" constraint:

- Outbound commenting on competitor/niche accounts' posts
- Any form of like/follow interaction with other accounts
- Reading other accounts' comment threads for targeting
