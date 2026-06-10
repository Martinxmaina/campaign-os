# Phase 2 Part A — Exit Gate Report

**Date:** 2026-06-10
**Branch:** feature/phase1-c1-herald
**Reviewer:** Campaign OS automation (Task 14)

---

## 1. Full Test Suite

| Metric | Result |
|--------|--------|
| Total collected | 797 |
| Passed | 797 |
| Failed | 0 |
| Errors | 0 |
| Warnings | 320 (non-fatal; all are deprecation notices from upstream libs) |
| Runtime | 72.16 s |

**Pass rate: 100% (797/797)**

Notable warning: `ninja` `DeprecationWarning` about tuple return style from `apps/api` — upstream issue, not project code.

---

## 2. Rebrand Audit (BrightBean → Campaign OS)

**Grep scope:** `apps/`, `config/`, `templates/` — `*.py` and `*.html` files.
**Exclusions:** `__pycache__`, `migrations/`, `test_agpl`, `0004_set_site`, `LICENSE`, `NOTICE`.

**Result: 2 files, 4 lines — all intentional frozen cryptographic constants.**

| File | Line | String | Status |
|------|------|--------|--------|
| `apps/api_keys/services.py:63` | comment | `brightbean-api-key-hmac` | FROZEN — HKDF comment |
| `apps/api_keys/services.py:71` | `info=b"brightbean-api-key-hmac"` | HKDF info bytes | FROZEN — production key anchor |
| `apps/common/encryption.py:36` | comment | `brightbean-field-encryption` | FROZEN — HKDF comment |
| `apps/common/encryption.py:44` | `info=b"brightbean-field-encryption"` | HKDF info bytes | FROZEN — production key anchor |

**Why frozen:** These are HKDF `info=` parameters baked into every API-key HMAC and every field-encrypted row written to the production database. Changing either string would permanently invalidate all existing API keys or make all encrypted rows unreadable. The code carries an explicit `# IMPORTANT: Do NOT change this info string` comment. Any future rotation requires a data migration that decrypts-and-re-encrypts under the new info string before the old one is removed.

**Rebrand verdict: ZERO unintentional violations. 4 lines are intentional frozen legacy byte-strings.**

---

## 3. Beat Schedule Entries

File: `jobs/schedules.py`

| Beat name | Present |
|-----------|---------|
| `beat-heartbeat` | YES |
| `intake-sheets-sync` | YES |
| `calendar-gap-scan` | YES |

**All 3 required beat entries are present.**

---

## 4. RBAC Tests (`apps/members/tests/test_roles.py`)

16 tests collected, 16 passed.

| Test | Result |
|------|--------|
| `test_pillar_field_only_allowed_for_pillar_lead_role` | PASS |
| `test_role_change_from_pillar_lead_clears_pillar_on_explicit_clear` | PASS |
| `test_update_workspace_assignments_clears_pillar_on_role_change` | PASS |
| `test_admin_workspace_role_has_all_permissions` | PASS |
| `test_campaign_owner_can_approve` | PASS |
| `test_principal_can_approve` | PASS |
| `test_pillar_lead_cannot_publish_directly` | PASS |
| `test_member_cannot_approve` | PASS |
| `test_campaign_os_roles_in_choices` | PASS |
| `test_all_workspace_roles_in_ws_role_level` | PASS |
| `test_all_workspace_roles_in_builtin_role_permissions` | PASS |
| `test_new_roles_have_higher_level_than_viewer` | PASS |
| `test_campaign_owner_level_below_owner` | PASS |
| `test_role_hierarchy_ordering` | PASS |
| `test_campaign_owner_permissions_identical_to_owner_is_intentional` | PASS |
| `test_campaign_owner_is_not_a_privilege_escalation_vs_owner_level` | PASS |

---

## 5. Gate Compliance Matrix

Files: `test_gate_enforcement.py`, `test_models.py`, `test_normalization.py`

88 tests collected, 88 passed.

### Gate Enforcement (4 tests)

| Test | Result |
|------|--------|
| `test_private_hold_blocks_dispatch` | PASS |
| `test_open_conditions_block_dispatch` | PASS |
| `test_needs_verification_proof_blocks` | PASS |
| `test_public_safe_no_conditions_passes` | PASS |

### Content Intake Models (13 tests)

| Test | Result |
|------|--------|
| `test_intake_with_open_conditions_is_not_schedulable` | PASS |
| `test_private_hold_intake_is_not_schedulable` | PASS |
| `test_confidential_intake_is_not_schedulable` | PASS |
| `test_public_safe_no_conditions_is_schedulable` | PASS |
| `test_example_row_marked_skipped` | PASS |
| `test_needs_verification_proof_status_is_not_schedulable` | PASS |
| `test_closed_condition_does_not_block_scheduling` | PASS |
| `test_intake_review_item_created_unresolved` | PASS |
| `test_intake_review_item_resolve_flow` | PASS |
| `test_post_field_is_one_to_one` | PASS |
| `test_has_open_conditions_uses_annotation_when_present` | PASS |
| `test_has_open_conditions_fallback_query_without_annotation` | PASS |
| `test_proof_status_defaults_to_tbd` | PASS |

### Normalization (71 tests)

All 71 normalization tests pass, covering:
- `TestNormalizeSensitivity` (13 tests): public/partner/confidential/private variants + fail-closed on unknown/empty/non-string
- `TestParseChannels` (12 tests): joseph-personal, nexus-brief, linkedin-waiis-page, compound tokens, unknowns preserved
- `TestMapStatus` (29 tests): all canonical statuses, round-trips, review-queue fallback
- `TestExtractUnblockConditions` (17 tests): verify-source, hold-until, partner-permission, figure-confirmation, dedup, description preservation

---

## 6. Deferred to Live Run

The following are not covered by unit tests because they require external services or a full content cycle:

| Item | Why deferred | Owner |
|------|-------------|-------|
| Real Google Sheets sync | Requires live Sheets API credentials + populated spreadsheet | Martin (ops) |
| 4-week content production cycle | No 4-week content slate exists yet; EGM content is in progress | Joseph / WAIIS team |
| Voice profiles per pillar lead | Pillar-lead HERALD persona prompts need real author samples | AfCEN comms team |
| Calendar gap alerts to Slack/email | Notification delivery requires Slack webhook / email SMTP live config | Martin (ops) |
| Production Redis + Celery beat live | Beat schedule tested via `tests/test_beat_schedule.py` but live broker not wired in dev | Martin (ops) |
| Provider OAuth token rotation | Social account OAuth tokens expire; needs refresh-token flow tested in prod | Martin (ops) |

---

## 7. Summary Verdict

| Gate | Result |
|------|--------|
| Full test suite 797/797 | PASS |
| Rebrand violations (non-frozen) | 0 — PASS |
| Beat entries (3/3 present) | PASS |
| RBAC tests (16/16) | PASS |
| Gate compliance matrix (88/88) | PASS |

**All Phase 2 Part A foundation tasks are complete. The platform is ready for live content onboarding.**
