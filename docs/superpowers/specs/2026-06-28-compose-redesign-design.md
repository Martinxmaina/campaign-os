# Compose Redesign — Roomy Editor + True-to-Platform Previews

**Date:** 2026-06-28
**Status:** Approved (visual mockup signed off via Artifact `compose-redesign-v1`)
**Surface:** `templates/composer/compose.html`, `templates/composer/partials/preview_panel.html`, `apps/composer/views.py` (preview context)

## Problem

1. **Blotato + Ghost channels render as a bland generic card.** The live-preview panel branches on raw `platform` keys (`twitter`, `instagram`, `linkedin_company`, …). The actually-connected accounts are `blotato_twitter`, `blotato_linkedin`, `blotato_instagram`, `blotato_facebook`, `blotato_threads`, `blotato_bluesky` — none match, and there is **no `ghost` branch**. So every Blotato channel and Nexus Brief fall through to the generic fallback. → "I can't see how an X post renders" / "render like it should on Ghost."
2. **No X (Twitter) preview card exists at all** — not even for native `twitter`.
3. **Editing area is cramped** — the user wants more writing room.
4. **Account logos** should lead the channel chips to guide selection.
5. **Ghost needs article fields** (title, feature image, rich body) + placeholders, distinct from a social caption.

## Non-goals

- No change to the publish gate, gate hashing, or dispatch. This is editor + preview only.
- No change to how content is stored (caption / `platform_specific_caption` / Ghost `body_format=html` extra are unchanged).
- No new platform integrations.

## Design

### A. Preview platform normalization (the core fix)
Add a single canonical `preview_kind` to each preview dict built in `apps/composer/views.py` (the `previews` list used by `preview_panel.html`). Map:

| account.platform | preview_kind |
|---|---|
| `twitter`, `blotato_twitter` | `x` |
| `instagram`, `instagram_login`, `blotato_instagram` | `instagram` |
| `facebook`, `blotato_facebook` | `facebook` |
| `linkedin_personal`, `linkedin_company`, `blotato_linkedin` | `linkedin` |
| `threads`, `blotato_threads` | `threads` |
| `bluesky`, `blotato_bluesky` | `bluesky` |
| `ghost` | `ghost` |
| `youtube` | `youtube` · `tiktok`→`tiktok` · `pinterest`→`pinterest` |
| anything else | `generic` |

`preview_panel.html` branches on `p.preview_kind` instead of raw `p.account.platform`. Existing cards are preserved (renamed branch keys); add **two new cards**: `x` and `ghost`.

### B. New X card
Layout matching X: avatar (logo/initial), display name + verified tick + `@handle` + "· now", post text (preserving line breaks, links tinted), a 1–4 image grid in X's grid proportions, and the action row (reply / retweet / like / views) with muted counts. Char badge shows `char_count/280` (red when over). Reuses the existing `is_over_limit` footer.

### C. New Ghost card
Renders as a Ghost article: publication masthead (workspace/account name), feature image (from the post's first image or a feature-image field), serif headline (post title), byline (author + date + read-time estimate), and the body rendered as HTML when `body_format == html` (sanitized for display) else paragraphs from the caption. This is the read-as-published view.

### D. Roomy split layout
On desktop (`md+`): a 2-column grid, editor `~1.55fr` / preview `~1fr`, the preview pane **docked** (not a slide-over) with a collapse toggle that hands the full width back to the editor (Alpine state `previewOpen`). On mobile: preview stays the existing slide-over (`showPreviewPanel`). Editor gains vertical room (larger caption textarea).

### E. Per-channel editing tabs
The per-channel override UI already exists (`override_caption_<id>` → `platform_specific_caption`, plus the rich Ghost editor for the Ghost channel). Re-present the selected channels as a tab strip above the caption: "All" + one tab per selected account (logo dot + platform). Selecting a tab scopes the editor to that channel's variant. "All" edits the base caption. This is a re-skin of the existing override inputs — no new persistence.

### F. Ghost editing mode
When the active channel tab is Ghost: the editor shows **Title**, **Feature image** (upload, stored as the post's feature/first image), and the existing **rich Body** editor (contenteditable + toolbar) with placeholders. When the active tab is a social channel: the normal caption box + counter.

### G. Account logos
Chips and preview avatars use `account.logo_display_url` when set, else a brand-initial chip (current behavior). Add the small platform badge on the chip logo (already present) — verify it shows for `blotato_*` via the platform-icon partial's alias map.

## Files

- `apps/composer/views.py` — add `preview_kind` to each preview dict (one helper `_preview_kind(platform)`); ensure the preview context is built for both `compose` (initial) and `composer:preview` (htmx refresh).
- `templates/composer/partials/preview_panel.html` — branch on `preview_kind`; add `x` and `ghost` cards.
- `templates/composer/compose.html` — roomy docked/collapsible split; per-channel tab strip; Ghost editing mode toggle; verify logo chips.
- `partials/_platform_icon.html` — ensure `blotato_*` and `ghost` resolve to a sensible glyph.

## Testing

- Unit: `_preview_kind` maps every `blotato_*` + `ghost` + native key correctly; unknown → `generic`.
- Render: `composer:preview` with a `blotato_twitter` account renders the X card (asserts `@handle`, `/280`); with `ghost` renders the Ghost article (asserts masthead + serif title); over-limit X caption shows the red badge.
- Existing compose render tests stay green (`test_compose_renders`, `test_compose_quickfixes`).

## Rollout

Build in a worktree off `main`, test, `git merge --ff-only`, `railway up --service web`, verify on prod. Template/view-only — no migration.
