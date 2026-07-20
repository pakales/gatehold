# Gatehold Judge Quickstart

## 90-second path — no install, account, or key

1. Open <https://gatehold-buildweek.e-vigelis.chatgpt.site>.
2. Confirm the persistent mode label says **REPLAY**.
3. Start the bounded scenario.
4. Observe one agent receive workstream clearance and a TTL-bound lease.
5. Observe a second agent receive a clear overlap hold before editing.
6. Observe a heavy task wait for deterministic host-capacity/FIFO clearance.
7. Inspect exclusive ownership for a port and dedicated browser profile. For
   the configured simulator, observe the exact-UDID rule: pre-booted is
   external; only a Gatehold-booted and positively confirmed device is owned.
8. Enter Scene D, **Clean finish**. Observe proven owned cleanup complete before
   the next task becomes eligible.
9. Open the authority explanation: deterministic policy alone grants
   clearance; GPT-5.6 may only add a semantic hold; cleanup alone frees runtime
   authority.

This route uses synthetic committed data. It does not inspect your computer and
needs no OpenAI API key.

## Five-minute local source path

### Supported environment

- macOS 13+ (primary);
- Python 3.12;
- `uv`;
- Node.js 22.13+ and npm.

Linux is best-effort for the Python core and generic resource leases. Physical
Apple Simulator boot/shutdown uses `xcrun simctl` and is macOS-only.

### Install and run the deterministic demo

From the repository root:

```bash
uv sync --dev
npm ci
uv run gatehold init
uv run gatehold demo
```

Expected: the CLI emits a synthetic replay disclosure, one granted receipt, one
deterministic overlap-hold receipt, and a sanitized snapshot. No API key is
required. Use the dashboard Replay for the full A–D semantic/capacity/release
story, including Scene D's verified clean finish.

For ongoing macOS use, `./scripts/install-local.sh` also installs the local
wrapper, starts the loopback LaunchAgent, and links the bundled Codex skill. It
does not load `.env.local`; the persistent daemon explicitly drops
`OPENAI_API_KEY`. The five-minute judge path above stays repository-local and
does not require that installation.

### Exercise the managed clean-finish path

```bash
state_dir="$(mktemp -d /tmp/gatehold-judge.XXXXXX)"
uv run gatehold --state-dir "$state_dir" run \
  --owner judge-smoke \
  --workstream judge/clean-finish \
  --scope demo/clean-finish \
  --light \
  --ttl 60 \
  --wait-timeout 0 \
  -- /usr/bin/true
uv run gatehold --state-dir "$state_dir" status
```

Expected: the command exits `0`, the owned runtime cleanup completes, and no
active lease or allocation remains. Gatehold uses a private process group and
releases workstream/resources only after cleanup is verified. If a successful
child's immediate cleanup is partial or ambiguous, the governed run returns
`72` instead of reporting clean success; any unresolved conflict stays
quarantined until reconciliation completes it.

This example intentionally leaves the temporary state directory available for
inspection. It contains no API key; remove it after review using the
operator's normal file workflow.

### Inspect the simulator ownership contract

```bash
uv run pytest tests/core/test_lifecycle_cleanup.py -q
```

The simulator tests use a deterministic fake adapter. Confirm they cover:

- an already booted exact UDID is recorded external and never shut down;
- `boot_intent` is persisted before boot, and ownership requires a successful
  boot plus a positive second `is_booted` check;
- cleanup shuts down only the exact confirmed owned UDID;
- ambiguous boot intent stays quarantined, retains its allocation, and issues
  no guessed shutdown.

These tests validate the ownership state machine; they are not evidence of a
live `simctl` run.

**Recorded live evidence — 2026-07-20:** a disposable Apple Simulator with a
redacted exact UDID (`32A0…`) was created only for this smoke. Gatehold recorded
`boot_intent → owned → cleaned`, reported simulator shutdown and finalized
runtime resources, left zero allocations, and confirmed the device state was
`Shutdown`. The disposable simulator and Gatehold state directory were then
deleted; the final booted-simulator count was zero. This validates the lifecycle
only; it was not an app launch or device UI test.

### Run the live local control plane

Terminal A:

```bash
uv run gatehold daemon
```

Terminal B:

```bash
uv run gatehold status
curl --fail --silent http://127.0.0.1:47820/healthz
GATEHOLD_TOKEN="$(<"${GATEHOLD_STATE_DIR:-$HOME/.gatehold}/daemon.token")"
curl --fail --silent \
  --header "Authorization: Bearer ${GATEHOLD_TOKEN}" \
  http://127.0.0.1:47820/v1/snapshot
unset GATEHOLD_TOKEN
```

The loopback-only health response is unauthenticated and contains only
status/version. The read-only local API also provides server-sent events at
`GET /v1/events`; snapshot and SSE require the bearer above or an exact browser
origin explicitly allowed at daemon startup.

Start the dashboard:

```bash
npm run dev
```

Copy the exact origin printed by the development server. Stop the earlier
daemon and restart it with that origin explicitly allowed. For example:

```bash
dashboard_origin="http://127.0.0.1:3001"
uv run gatehold daemon --dashboard-origin "$dashboard_origin"
```

Replace the example with the exact printed origin; a different localhost host
or port is a different origin. Select **Live local** only after this restart.
No browser origin, including loopback, is trusted implicitly. Local loopback
origins may use HTTP; non-loopback origins must use HTTPS. Public HTTP,
wildcards, and credentialed CORS are not allowed. If the browser cannot reach
the daemon, the UI should show a truthful disconnected state; switch back to
Replay to continue testing. Chrome 142 and later may first ask for
[Local Network Access permission](https://developer.chrome.com/blog/local-network-access)
when the public site checks `127.0.0.1`; grant it only for this intentional
Live-local path.

### Run the complete verification gate

```bash
npm run verify
```

This runs Python tests, Ruff, Pyright, TypeScript type checking, ESLint, web
tests, and the production web build.

## Optional GPT-5.6 check

The core product does not need a key. To exercise semantic overlap, place an
authorized `OPENAI_API_KEY` in the server-only `.env.local` file and run the
isolated bounded smoke:

```bash
npm run smoke:model
```

Confirm:

- differently worded overlapping claims can gain an additional model hold;
- deterministic conflicts remain held regardless of model output;
- no model response can grant clearance;
- removing the key preserves deterministic behavior.

Do not enter a key in the web UI or expose the environment file.

## What to evaluate

| Question | Evidence |
| --- | --- |
| Can two controlled agents own the same protected work? | Collision scene and concurrency tests |
| Can the model overrule policy? | Hold-only schema, failure tests, authority panel |
| Does heavy work start under host pressure? | Capacity/FIFO scene and tests |
| Are runtime surfaces isolated? | Exclusive resource leases |
| Does a finished agent restore its lane? | Scene D and managed-runtime cleanup tests |
| Can crashed work recover safely? | TTL, heartbeat, fail-closed cleanup, quarantine, and daemon reconciliation |
| Can cleanup touch a human process? | No; process signals require matching persisted provenance |
| Can it shut down a pre-existing simulator? | No; exact-UDID fake-adapter tests keep pre-booted devices external |
| When may it shut down a simulator? | Only after durable boot intent, successful boot, and positive ownership confirmation |
| Is the public demo honest? | Persistent REPLAY label and synthetic fixture |
| Can it run without paid API access? | Deterministic demo and full local tests |
| Is it a security sandbox? | No; the product contract says cooperative governor |

## Expected limitations

- Gatehold coordinates clients that opt in; unmanaged tools can bypass it.
- It does not execute commands from HTTP or control every workstation process.
- It never kills by process name or port. Ambiguous ownership is quarantined,
  so a conflict may remain held until reconciliation or operator diagnosis.
- Physical simulator lifecycle is macOS-only. Automated cases use a fake
  adapter; a separate disposable live `simctl` lifecycle smoke is recorded
  above, without claiming an app or device UI test.
- An unresolved simulator `boot_intent` remains quarantined and can require
  operator diagnosis; Gatehold will not guess a shutdown.
- Capacity signals are snapshots, not future guarantees.
- Model semantic classification can create a conservative false-positive hold.
- Loopback binding is not authentication against another process running as the
  same local user.
- Displayed avoided-work and savings values are estimates.

## Troubleshooting

**`gatehold` is not found**
Use `uv run gatehold ...` from the repository root after `uv sync --dev`.

**The daemon is unreachable**
Confirm `uv run gatehold daemon` is running and that
`http://127.0.0.1:47820/healthz` responds. Do not change the service to a public
bind address. For browser Live local, also confirm the daemon was started with
the dashboard's exact `--dashboard-origin`.

**Live local is disconnected**
The public hosted site cannot inspect a remote local machine. Run the dashboard
locally on the same workstation, or use Replay. If Chrome shows a Local Network
Access prompt, grant it only when you intentionally started the loopback daemon;
an origin-denied response still requires restarting the daemon with that exact
`--dashboard-origin`.

**GPT-5.6 status says disabled/fallback**
That is expected without a usable server-side key or when the provider is
unavailable. Deterministic policy still operates.

**A claim remains held after another agent ended**
Inspect `gatehold status`. An unresolved prior lease remains visibly `ACTIVE`
while its lifecycle is conceptually `CLEANUP_PENDING` or `QUARANTINED`;
release/expiry is not finalized until owned cleanup is verified. Allow daemon
reconciliation to retry. Do not delete state, kill by name/port, or bypass
clearance.

**`gatehold run` returns `72` after the child succeeded**
The immediate owned cleanup could not be positively confirmed, so Gatehold did
not report clean success. Any still-unresolved state remains quarantined with
its conflicts/allocations authoritative; reconciliation may subsequently
complete it. Inspect sanitized status and the bounded runtime-cleanup audit
described in [Testing](TESTING.md); unrelated processes were not signaled.

For deeper verification, see [Testing](TESTING.md),
[Architecture](ARCHITECTURE.md), and [Threat Model](THREAT-MODEL.md).
