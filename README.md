# Gatehold

**Local air-traffic control for coding agents.**

Gatehold stops two cooperative AI coding agents from silently taking the same
workstream and keeps heavy builds, tests, browser sessions, and simulator lanes
from overwhelming one developer workstation.

Before controlled work starts, Gatehold answers two separate questions:

1. **Does this agent own the workstream?**
2. **Can this machine carry the requested work right now?**

A deterministic local policy grants or withholds clearance. GPT-5.6 can spot a
semantic overlap that exact rules missed and raise an additional hold, but it
can never grant clearance or override a deterministic conflict.

> Gatehold is a cooperative workstation governor. It is not a security
> sandbox, a kernel scheduler, a Mac cleaner, or a guarantee against unmanaged
> processes.

## Why it matters

Parallel agents are fast until they collide: two sessions edit the same flow,
reuse one port, claim one simulator, or start expensive builds at once. Git
worktrees isolate files, but they do not answer who owns the product work or
whether the host has capacity.

Gatehold adds a small admission-control layer:

- one active owner per protected workstream;
- exclusive leases for named runtime surfaces;
- FIFO waiting for heavy work under host pressure;
- TTL, heartbeat, release, and expiry for recoverable leases;
- fail-closed cleanup of the process group and runtime surfaces created by a
  governed command;
- local receipts that explain why a task ran or waited;
- optional GPT-5.6 semantic overlap detection with deterministic fail-safe
  behavior.

Gatehold waits. It never kills unrelated user processes to make room or guesses
that a process belongs to it.

## Judge quickstart

The fastest no-secret path is the bounded public replay described in
[Judge Quickstart](docs/JUDGE-QUICKSTART.md). It is intentionally labeled
**REPLAY** and does not claim to show the judge's machine.

To run the real local product from this repository:

### Prerequisites

- macOS 13 or later (primary supported platform);
- Python 3.12;
- [`uv`](https://docs.astral.sh/uv/);
- Node.js 22.13 or later and npm.

The Python daemon, CLI, and generic leases are also designed to run on Linux on
a best-effort basis. The physical Apple Simulator lifecycle uses `xcrun
simctl` and is macOS-only. The submitted simulator contract tests use a fake
adapter. A separate disposable exact-UDID macOS Simulator lifecycle smoke is
recorded in [Testing](docs/TESTING.md); it validates ownership and cleanup, not
an app launch or device UI flow.

### Install

```bash
uv sync --dev
npm ci
uv run gatehold init
```

No OpenAI API key is required for deterministic admission, status, receipts, or
the replay demo.

### Run

Start the loopback-only daemon for token-authenticated CLI/curl reads:

```bash
npm run core:serve
```

In another terminal, inspect live local state:

```bash
npm run core:status
```

Run the bounded CLI demo:

```bash
npm run core:demo
```

Start the dashboard:

```bash
npm run dev
```

Open the exact local URL printed by the development server. **Replay** needs no
daemon. For **Live local**, restart the daemon with that exact origin explicitly
allowed. For example, if the printed URL is
`http://127.0.0.1:3001`:

```bash
uv run gatehold daemon \
  --dashboard-origin http://127.0.0.1:3001
```

Every browser origin, including localhost, is denied unless it was explicitly
passed with `--dashboard-origin` or configured as the same exact value in
`GATEHOLD_DASHBOARD_ORIGINS`. Local loopback origins may use HTTP; any
non-loopback origin must use HTTPS. Public HTTP and wildcard origins are never
allowed.

### Run with an owned clean finish

Use `gatehold run` when Gatehold should govern the command as well as its
admission:

```bash
uv run gatehold run \
  --owner judge-smoke \
  --workstream judge/clean-finish \
  --scope demo/clean-finish \
  --light \
  --ttl 60 \
  --wait-timeout 0 \
  -- /usr/bin/true
```

A governed command runs in a private process group. Gatehold records bounded
provenance for that group and any allocated port or dedicated browser-profile
directory. At normal exit, interruption, lost heartbeat, expiry, or daemon
recovery, the lifecycle is:

```text
ACTIVE -> CLEANUP_PENDING -> RELEASED or EXPIRED
                         \-> QUARANTINED when cleanup is ambiguous
```

Gatehold releases workstream authority and allocations only after cleanup is
positively verified. Ambiguous ownership or partial cleanup stays quarantined
and continues to block conflicting work; unrelated processes are not signaled.
A successful child whose cleanup cannot be confirmed returns exit code `72`.

When `--simulator` allocates a configured exact UDID on macOS, Gatehold first
inspects that device. A simulator that is already booted is recorded as
external and is never touched. Otherwise Gatehold persists `boot_intent`
before booting, marks the simulator owned only after a successful boot and a
positive second `is_booted` check, and shuts down only that exact confirmed
owned UDID during cleanup. An unresolved `boot_intent` is quarantined with its
allocation and workstream authority intact; Gatehold never guesses a shutdown.

### Optional GPT-5.6 advisory

Copy `.env.example` to `.env.local`, then set `OPENAI_API_KEY` in the local file:

```bash
cp .env.example .env.local
```

The Gatehold CLI does not load `.env.local` implicitly. Run the isolated,
bounded semantic smoke through the repository script, which passes the file
explicitly:

```bash
npm run smoke:model
```

The key stays server-side. Never prefix it with `NEXT_PUBLIC_`, commit it, put
it in a fixture, or expose it to the browser. Without a usable key, on refusal,
timeout, invalid output, or model failure, Gatehold keeps the deterministic
local result.

### Verify

```bash
npm run verify
```

The full gate runs Python tests, Ruff, Pyright, TypeScript type checking, ESLint,
web tests, and a production web build. See [Testing](docs/TESTING.md) for
focused checks and manual scenarios.

## Replay is not live state

| Surface | Data | Secret needed | What it proves |
| --- | --- | --- | --- |
| Public judge replay | Bounded synthetic scenario mirrored under `fixtures/demo/` | No | The product flow and decision explanations |
| Local replay | The same bounded synthetic scenario through the local app/CLI | No | A reproducible demo without external services |
| Live local mode | Sanitized loopback snapshot/SSE from SQLite and current host probes | No for deterministic policy | Actual Gatehold state on that workstation |
| GPT-5.6 advisory | Bounded claim metadata sent by the local server | Yes | A model-raised semantic hold; never clearance |

Replay mode cannot inspect a judge's CPU, memory, processes, browser profiles,
ports, or simulators. Live-local browser reads are possible only from the same
workstation and from the exact origin explicitly allowlisted when the daemon
starts. Merely being a localhost origin is not enough. Any replay screen that
looks like workstation telemetry must remain visibly labeled as replay.

## Codex and GPT-5.6 have different jobs

**Codex is the builder and controlled client.** Codex was used to turn the
product constraints into the clean repository, implement and test the daemon,
CLI, dashboard, replay, and documentation, and package a reusable Gatehold
skill. In normal use, the skill requires Codex to claim a workstream before an
edit, run heavy commands through Gatehold, heartbeat long work, and release its
leases only after the owned runtime reaches a verified clean finish.

**GPT-5.6 is a bounded runtime adviser.** It evaluates whether two differently
worded work claims may still overlap. Its output can only add a hold. It has no
authority to admit work, remove a deterministic conflict, bypass FIFO capacity,
execute a command, or mutate a lease.

The key product decisions remained explicit human/engineering choices:
deterministic clearance is authoritative, the daemon is loopback-only,
commands execute only from the local CLI with `shell=False`, model failure
fails back to local policy, and Gatehold never kills unrelated processes.

## Competitive position

Gatehold does not claim to be the first or only parallel-agent controller.
Existing products already provide valuable worktree isolation, agent
workspaces, process throttling, or command queues.

Gatehold's focus is the boundary between those categories: **product-work
ownership plus host-capacity admission plus named runtime lanes plus
fail-closed owned cleanup**, enforced across the full governed task lifecycle.
Its differentiator is the explicit authority split: deterministic rules can
grant clearance; GPT-5.6 may only make the system more conservative; cleanup
frees authority only after provenance-backed verification.

See [Product Contract](docs/PRODUCT-CONTRACT.md) for the precise claims and
non-claims.

## Privacy and safety

- The daemon binds to `127.0.0.1`, not a public interface.
- SQLite state remains local under `~/.gatehold/` by default.
- HTTP exposes only sanitized read-only health, snapshot, and event routes.
  Health is unauthenticated but loopback-only and returns only status/version.
- Origin-less local reads under `/v1/*` require the bearer token stored in
  `~/.gatehold/daemon.token` with mode `0600`.
- Browser access accepts only exact configured origins, including for local
  development; CORS does not use a wildcard or credentials.
- Source code, diffs, full prompts, conversation content, and command arguments
  are not persisted by Gatehold.
- The OpenAI API call uses `store=False`.
- The browser never receives `OPENAI_API_KEY`.
- The HTTP API never accepts an arbitrary command to execute.
- Governed commands run in a private process group. Cleanup signals only a
  group whose persisted PID, process-group/session identity, boot time, process
  create time, and secret-derived provenance still match.
- Dedicated browser-profile removal requires the exact Gatehold marker,
  device/inode identity, and marker digest. Allocated ports are released only
  after a loopback bind check confirms they are free.
- Ambiguous or partial cleanup is quarantined; workstream conflicts and
  allocations remain authoritative instead of being optimistically freed.
- An already booted configured simulator is external and never touched.
  Gatehold shuts down only the exact UDID for which it durably recorded boot
  intent and then positively confirmed its own successful boot. Ambiguous boot
  intent is quarantined with zero guessed shutdown.
- All task descriptions, paths, scopes, process data, and model output are
  treated as untrusted input.
- Demo fixtures contain synthetic data only.

Read [Privacy](docs/PRIVACY.md) and the
[Threat Model](docs/THREAT-MODEL.md) before extending auth, persistence,
network binding, model prompts, or command execution.

## Build Week provenance and pre-existing-work disclosure

Gatehold is entered in the **Developer Tools** category of OpenAI Build Week.
The clean Gatehold repository and its generalized public implementation were
created during the submission period.

Private EVL Labs workstation prototypes also existed during the submission
period before this public repository was assembled. Gatehold reuses these
concepts, not their private source code:

| Reused concept | New Gatehold implementation |
| --- | --- |
| Explicit workstream ownership checks | General lease and admission state machine |
| A local queue for build/test/browser/iOS-heavy work | Host-capacity policy with FIFO waiting and receipts |
| Named ownership for ports, browser profiles, and simulators | Exclusive runtime leases plus exact-UDID simulator ownership provenance |
| Stale-work recovery | TTL, heartbeat token, release, and expiry paths |
| Local workstation health signals | Bounded host probes used by deterministic admission |

No private repository history, private application code, user content,
credentials, or private prompt transcripts were copied into this repository.
Gatehold adds a new public API/CLI contract, clean implementation, strict model
authority boundary, synthetic replay path, public dashboard, tests,
documentation, and Codex skill.

### Dated Build Week evidence

| Date | Competition-period work | Evidence in this repository |
| --- | --- | --- |
| 2026-07-20 EEST | Defined the Gatehold product, authority boundary, local-only security contract, and clean repo structure | `AGENTS.md`, `docs/PRODUCT-CONTRACT.md`, `docs/THREAT-MODEL.md` |
| 2026-07-20 EEST | Implemented the generalized local daemon/CLI, leases, capacity admission, optional GPT-5.6 hold advisory, provenance-backed process/profile/port cleanup, exact-UDID simulator ownership, and tests | `src/gatehold/`, `tests/core/`, `pyproject.toml` |
| 2026-07-20 EEST | Validated a disposable exact-UDID macOS Simulator lifecycle: boot intent, confirmed ownership, shutdown, cleanup finalization, zero remaining allocations, and zero booted simulators | `tests/core/test_lifecycle_cleanup.py`, `docs/TESTING.md` |
| 2026-07-20 EEST | Built the replay/live-local product experience and contest test route | `app/`, `fixtures/demo/`, `tests/web/`, `docs/JUDGE-QUICKSTART.md` |
| 2026-07-20 EEST | Packaged the Codex operating workflow and English submission materials | `skills/gatehold/`, `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION.md` |

Before final submission, the entrant must add dated commit links and the real
Codex `/feedback` session ID to the Devpost entry. Placeholders are tracked in
[Competition Checklist](docs/COMPETITION-CHECKLIST.md); they are not evidence.

## Repository map

- `src/gatehold/` — Python daemon, deterministic admission engine, host probes,
  persistence, optional model adviser, and CLI.
- `tests/core/` — deterministic, concurrency, API, privacy, and model-boundary
  tests.
- `app/` — Sites-compatible dashboard with replay and live-local modes.
- `fixtures/demo/` — bounded, synthetic public replay.
- `skills/gatehold/` — Codex claim/run/release workflow.
- `docs/` — architecture, contracts, testing, privacy, demo, and submission
  package.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Product Contract](docs/PRODUCT-CONTRACT.md)
- [Privacy](docs/PRIVACY.md)
- [Threat Model](docs/THREAT-MODEL.md)
- [Testing](docs/TESTING.md)
- [Brand asset provenance](docs/BRAND-ASSET.md)
- [Judge Quickstart](docs/JUDGE-QUICKSTART.md)
- [2:51 Demo Script](docs/DEMO-SCRIPT.md)
- [Devpost Submission Copy](docs/SUBMISSION.md)
- [Competition Checklist](docs/COMPETITION-CHECKLIST.md)

## License

Gatehold is available under the [MIT License](LICENSE). Copyright © 2026 Evl
Labs.
