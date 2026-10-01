# Campaign OS — Handover Pack

Prepared 2026-10-01 from a full read of this repository (`Martinxmaina/campaign-os`, branch state at commit `883dabc`, last code change 2026-07-03).

This pack hands the Campaign OS platform over to AfCEN. It is written for whoever takes over operating it, whether technical or not. Read the documents in order.

| # | Document | What it covers |
|---|---|---|
| 1 | [01-system-overview.md](01-system-overview.md) | What the system does, every system it connects to, what works today and what does not |
| 2 | [02-runbook.md](02-runbook.md) | How to deploy, restart, run one-off commands, and fix each known failure |
| 3 | [03-monitoring-and-alerting.md](03-monitoring-and-alerting.md) | What monitoring exists, what does not, and who receives alerts today |
| 4 | [04-known-gaps.md](04-known-gaps.md) | Bugs, unfinished features, and risks, stated plainly |
| 5 | [05-accounts-and-access.md](05-accounts-and-access.md) | Register of every account, system, repo, domain, tool, dataset and third-party service, with owner, control status and billing |
| 6 | [06-credential-transfer.md](06-credential-transfer.md) | Every secret that must be handed over, how to hand it over safely, and how to rotate it |

## How to read the "status" markings

- **Verified in code**: read directly from the source in this repository.
- **From repo docs**: stated in an older document in `docs/`, not re-checked against live systems.
- **TO CONFIRM**: cannot be known from the repository (for example, who pays a bill, or which login owns a dashboard). These must be filled in by the outgoing owner, Martin Maina, during the handover meeting. Each one is listed again in the checklist at the end of [05-accounts-and-access.md](05-accounts-and-access.md).

## What this pack is not

- It contains **no passwords, API keys, tokens or secrets**. Those are transferred separately, following [06-credential-transfer.md](06-credential-transfer.md). If you find a secret value written into any file in this repository, treat it as leaked and rotate it.
- It does not cover the **agent-service** code in detail. That is a separate codebase (FastAPI) that is **not in this repository**. This pack describes how Campaign OS depends on it, and flags that its source location must be confirmed and transferred.

## Test suite status at time of writing

The suite was run on 2026-10-01 against PostgreSQL 16:

```
2 failed, 1838 passed in 129s
```

Both failures are test problems, not production problems:

1. `tests/providers/test_blotato_provider.py::test_registry_exposes_blotato_twitter`. The test still expects the X limit to be 280 characters. Commit `e5f43f9` deliberately raised it to 25,000 for X Premium long-form posts. The test was not updated.
2. `tests/test_gate_media_parity.py::test_gated_post_with_media_publishes_text_only_hash`. The test needs a fixture image at `test_media/media_library/2026/06/shared.png`. `test_media/` is in `.gitignore`, so the file only exists on the original developer's laptop. On a fresh checkout the media download fails and the post stays `scheduled`.

The README's figure of "1,380+ tests" is out of date.
