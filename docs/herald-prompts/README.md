# HERALD prompt instructions

These files teach HERALD to **understand and curate** content — to read an
approved TWG meeting, judge what's genuinely worth saying, and shape it for each
channel. HERALD is a curator, not a template-filler. Joseph reviews these files
so the judgment, tone, and formatting are right *before* anything auto-publishes.

## The instruction HERALD runs on

**[`HERALD.md`](HERALD.md) is the master operating instruction** — HERALD's role,
the input it receives, the full procedure (understand → curate → plan → angle →
draft → self-check), the hard rules, and the **JSON output contract** the pipeline
consumes. That's the file to read first.

Everything else is the **knowledge HERALD is fed per run**, not separate
instructions:
- [`curation.md`](curation.md) — the expanded curation/judgment method.
- `pillars/<pillar>.md` — standing understanding of each pillar's agenda (the resonance layer).
- `workspaces/waiis.md` — house voice, audience, boundaries.
- `platforms/<platform>.md` — per-channel format.
- `examples/` — illustrates the quality bar; **not** a fixed pattern (the meeting behind it was just an example).

A meeting is raw material, not a script — HERALD curates each one fresh.

## How a post is composed — three layers (after curating)

HERALD stacks three instruction layers for every draft:

```
House (workspace)  ×  Pillar (subject)  ×  Platform (format)
   workspaces/         pillars/             platforms/
```

- **House** — whose brand and audience is this (`waiis`, `afcen`, `ai10b`). Sets voice, audience, and hard boundaries.
- **Pillar** — what the content is *about* (`agribusiness`, `energy`, `minerals`, `ai`, `digital`). This is the **resonance layer**: every post must read unmistakably as *that pillar's* agenda, in its language. The pillar arrives on the webhook as `twg_pillar`.
- **Platform** — how it's shaped for the channel (`linkedin`, `x`, `instagram`). Length, structure, hashtags, CTA.

A LinkedIn recap of an Agribusiness meeting for WAIIS = `waiis.md` + `agribusiness.md` + `linkedin.md`, composed.

## The non-negotiables (apply to every layer)

1. **Resonate with the pillar.** If you swapped the pillar name out, the post should stop making sense. Use the pillar's real vocabulary, initiatives, and framing — not generic "great meeting" copy.
2. **Public-safe only.** Draft *only* from the chair-approved public summary. Never source raw minutes, internal deliberations, attributed private commitments, or action items.
3. **Status-accurate.** "In preparation," "proposed," "under design" — never imply a deal is signed, funds are secured, or an institution has committed unless the public summary says so.
4. **Name only consented institutions/people.** If the public summary didn't clear a name, don't use it.
5. **No hype.** No "thrilled," "game-changer," "revolutionary," emoji storms, or exclamation runs. Credible and specific beats loud.

## Reviewing

- `pillars/*.md` is where tone/subject accuracy lives — check the lexicon and guardrails match reality.
- `platforms/*.md` is where formatting lives — check length/structure/CTA feel right per channel.
- `examples/*.md` shows real drafts produced under these rules — the fastest way to judge the result.

## Scope

**WAIIS only.** This prompt set drives the TWG → social pipeline for the WAIIS
Summit. AfCEN and AI 10B content follow a **different approach** and are out of
scope for these files.

## Status (v1, for review)

Four WAIIS summit pillars. `digital-innovation.md` covers both the `digital` and
`ai` canonical Post pillars.

| Layer | Files | Notes |
|---|---|---|
| House | `waiis` | only house in scope |
| Pillars | `agribusiness`, `energy`, `minerals`, `digital-innovation` | Agribusiness fully grounded (real TWG summary). **Energy / Minerals / Digital have `⚠️ TO CONFIRM` anchor sections** — pillar-specific Communiqué commitments not yet supplied; framing + guardrails are safe to use meanwhile. |
| Platforms | `linkedin`, `x`, `instagram`, `ghost` | — |
| Examples | `agribusiness-freetown-2026-07` | one per pillar as real summaries arrive |

**Next:** to bring Energy / Minerals / Digital to the Agribusiness standard, drop
me each pillar's Communiqué commitments or a TWG summary and I'll fill the
`TO CONFIRM` sections.
