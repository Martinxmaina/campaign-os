# Per-channel content & rich editing — design

**Date:** 2026-06-28
**Status:** Approved (user "proceed") — building in order below.

## Platform-capability research (answers "what does LinkedIn/Blotato authorize")

Grounded in the provider code:
- **Ghost** (`providers/ghost.py`): publishes **full HTML** (`_to_html`, `?source=html`). → rich long-form **articles with inline images are supported**.
- **Social — LinkedIn / X / Instagram / Facebook**, via **Blotato** (`providers/blotato.py`: `content = {text, mediaUrls}`) **and** native providers: **text + attached media only** (images/video, carousels). **No inline mid-caption images.** LinkedIn's separate long-form "Articles" API is not exposed by Blotato → out of scope.
- **Publisher already sends per-channel copy:** `apps/publisher/engine.py` uses `platform_post.effective_caption` / `effective_first_comment` (lines ~522, 666–669, 988), which fall back to `PlatformPost.platform_specific_caption/_first_comment` → **per-channel variant publish wiring already works.**

So "full editing" splits: **inline-image rich articles = Ghost only**; **social = text + multi-image gallery + per-channel variants**.

## Scope (build order)

### 1. Per-channel caption variants — UI only *(publish side done)*
- Composer: a "Customize per channel" affordance — for each **selected** account, an optional textarea pre-filled with that channel's `platform_specific_caption` (empty = uses the shared caption).
- Save: `_sync_platform_posts` reads `pp_caption_<account_id>` from POST; non-empty → set `platform_specific_caption`; empty/blank → `None` (fall back to shared). Same optional pattern reserved for `pp_first_comment_<id>` later.
- Editing a post clears `gate_id`/`content_hash` per the existing invariant so per-channel text re-gates.
- No model/migration change (fields exist).

### 2. Rich editor for Ghost (inline images + formatting)
- When a Ghost channel is selected, the caption editor offers rich formatting + inline image insert; stored as HTML and passed to Ghost. Social channels keep the plain editor. (Design detail at build: editor lib must be CSP-safe/self-hosted; Ghost provider already takes HTML.)

### 3. Multi-image / gallery + per-channel media
- Expose attaching multiple images (ordered `PostMedia` already supports it) and per-channel media selection (`PlatformPost.platform_specific_media` already exists). Carousel-aware per platform limits.

### 4. Review-and-approve → publish, and #11 UTM
- Extend approval-by-email so the reviewer's approve can publish directly.
- UTM: apply per-platform `utm_source` (+ `utm_medium=social`, `utm_campaign=<post.campaign>`) to http(s) URLs **at dispatch, after the gate** (per-platform + avoids changing the gate content-hash); idempotent; workspace toggle.

## Testing
Each item: unit/integration test for the save/publish behavior + a render-smoke for the composer; preserve existing publish-gate tests.
