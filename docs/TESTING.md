# Gatehold Testing

## Release gate

From the repository root:

```bash
uv sync --dev
npm ci
npm run verify
```

`npm run verify` is the canonical full check:

```text
uv run pytest
uv run ruff check .
uv run pyright
npm run typecheck
npm run lint
npm test
```

`npm test` is self-contained: it creates a clean production bundle before
running the rendered web contracts. This keeps the same command reproducible in
a fresh clone with no pre-existing `dist/`.

Do not state that the gate passed unless it was run against the exact source
state being handed off.

CI also runs this network-backed advisory gate after the deterministic release
checks:

```bash
npm run audit:deps
```

This audits the complete npm graph, including build tooling, and the locked
Python environment. The local `gatehold` package itself is expected to be
skipped because it is not published on PyPI.

## Focused commands

| Concern | Command |
| --- | --- |
| Python behavior and contracts | `uv run pytest` |
| Python lint/security rules | `uv run ruff check .` |
| Strict Python types | `uv run pyright` |
| TypeScript types | `npm run typecheck` |
| Web lint | `npm run lint` |
| Web contract tests | `npm test` |
| Production web build | `npm run build` |
| CLI discovery | `uv run gatehold --help` |
| Deterministic demo | `uv run gatehold demo` |
| Local status | `uv run gatehold status` |
| Managed-run CLI and exit handling | `uv run pytest tests/core/test_cli.py` |
| Lease/storage finalization | `uv run pytest tests/core/test_store_and_admission.py tests/core/test_resources.py` |
| Owned cleanup and simulator provenance | `uv run pytest tests/core/test_lifecycle_cleanup.py` |

The deterministic test suite must pass with `OPENAI_API_KEY` unset.

## Automated contract matrix

### Admission and concurrency

- one of two concurrent claims for the same protected workstream wins;
- a conflicting claim returns a hold with a bounded reason;
- disjoint workstreams can be admitted when host policy allows;
- exclusive resources have one owner;
- heavy work respects capacity limits and deterministic queue order;
- Gatehold does not kill or suspend unrelated processes.

### Lease lifecycle

- an admitted lease has TTL and an opaque heartbeat token;
- a valid heartbeat extends active ownership;
- a wrong token cannot heartbeat or release another lease;
- release or expiry records terminal intent without immediately freeing
  authority;
- `ACTIVE` moves through `CLEANUP_PENDING` before `RELEASED` or `EXPIRED`;
- workstream conflicts and allocations remain held until cleanup is verified;
- partial or ambiguous cleanup becomes `QUARANTINED` for idempotent
  reconciliation;
- a successful child with unverified cleanup returns `72`;
- interrupted governed runs use the same owned cleanup path.

### Owned runtime boundary

- governed commands use a private process group and activation handshake;
- process cleanup requires matching PID, process-group/session identity,
  process create time, host boot time, and secret-derived provenance;
- an unknown, reused, or unproven identity receives no signal;
- background descendants in the proven group are cleaned with bounded
  `TERM`-then-`KILL`;
- a dedicated browser profile is removed only when path, marker,
  device/inode, and marker digest match;
- an allocated port is finalized only after it is bind-free;
- a pre-booted exact simulator UDID is recorded external and never touched;
- simulator `boot_intent` is persisted before boot, and ownership requires a
  successful boot plus a positive second `is_booted` confirmation;
- cleanup shuts down only the exact confirmed owned UDID;
- ambiguous simulator boot intent is quarantined, retains its allocation, and
  receives zero guessed shutdown.

### Model boundary

- model output cannot grant clearance;
- model output cannot clear deterministic conflict or capacity waiting;
- a valid semantic-overlap result can add a hold;
- unknown claim IDs and invalid structured output are rejected;
- missing key, refusal, timeout, malformed output, and provider failure preserve
  deterministic policy;
- OpenAI requests set `store=False`;
- bounded model input redacts home paths, emails, common provider tokens, JWTs,
  credential assignments, and high-confidence contextual secrets while
  preserving ordinary documentation examples;
- secrets and raw private content do not appear in receipts or logs.

### API and command boundary

- the service defaults to `127.0.0.1`;
- `GET /healthz`, `GET /v1/snapshot`, and `GET /v1/events` are read-only;
- `/healthz` is unauthenticated but loopback-Host-only and returns only
  status/version;
- snapshot/SSE require either an exact explicitly allowed browser origin or a
  valid bearer token;
- mutation inputs use strict bounded schemas;
- wrong content type, oversized input, and extra fields are rejected;
- the HTTP API has no arbitrary-command endpoint;
- the CLI executes argument vectors with `shell=False`;
- governed children receive a minimal runtime environment rather than the
  ambient operator environment;
- bounded `--pass-env` forwards present non-protected settings while rejecting
  credentials, Gatehold controls, and known interpreter/startup injection
  names before a claim exists.

### Replay and web

- replay JSON parses and has a supported schema version;
- every replay record is synthetic and mode-labeled;
- no fixture contains secrets or private workstation paths;
- the product renders without a local daemon;
- replay and live-local controls remain distinguishable;
- keyboard focus is visible;
- reduced-motion preference is respected;
- desktop and mobile layouts have no overlap or horizontal clipping.

## Manual local verification

### 1. Initialize and start the daemon

Terminal A:

```bash
uv run gatehold init
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

Expected:

- the daemon binds only to loopback;
- health returns a bounded success response;
- snapshot returns Gatehold state without secrets, raw commands, or private
  process details;
- an invalid `Host`, unlisted browser `Origin`, missing origin-less `/v1/*`
  bearer, and wildcard CORS assumption are rejected. Origin-less `/healthz`
  remains bearer-free and returns only status/version.

### 2. Run the bounded demo

```bash
uv run gatehold demo
```

Confirm the CLI demo emits:

1. a synthetic replay disclosure;
2. one granted receipt with bounded resource allocation;
3. one deterministic overlap-hold receipt;
4. a sanitized snapshot with no queue or heartbeat tokens.

No live API key is needed for this baseline. The full A–D collision, semantic
hold, host-capacity, and FIFO-release story is the dashboard Replay tested in
step 4.

### 3. Inspect command contracts

```bash
uv run gatehold claim --help
uv run gatehold heartbeat --help
uv run gatehold release --help
uv run gatehold run --help
```

Use the help text from the current build; do not copy options from an older
receipt or documentation draft.

Confirm:

- no force or bypass flag exists;
- a held/waiting result does not start a command;
- a long-running controlled task heartbeats;
- normal completion and interruption request owned cleanup;
- release/expiry finalizes only after cleanup is verified;
- partial cleanup reports quarantine rather than optimistic success.

### 4. Verify the dashboard

```bash
npm run dev
```

Copy the exact origin printed by the development server. Stop the Step 1 daemon
and restart it with that origin explicitly allowlisted. For example:

```bash
dashboard_origin="http://127.0.0.1:3001"
uv run gatehold daemon --dashboard-origin "$dashboard_origin"
```

Replace the example value when the printed host or port differs. Confirm that a
different localhost origin is rejected; loopback is not implicitly trusted.

Check both modes:

- **Replay:** works with the daemon stopped and remains visibly labeled.
- **A–D replay:** clean admit, semantic hold, capacity hold, and Scene D's
  clean-finish/queue advance match `fixtures/demo/gatehold-replay.json`.
- **Live local:** only reports the loopback daemon on this machine; a
  disconnected state is honest and actionable.

Test at approximately 1440×900, 390×844, and keyboard-only navigation. Check the
browser console for errors.

### 5. Verify a real managed clean finish

Use a fresh state directory and a command with no external side effects:

```bash
state_dir="$(mktemp -d /tmp/gatehold-true-smoke.XXXXXX)"
uv run gatehold --state-dir "$state_dir" run \
  --owner smoke-owner \
  --workstream smoke/true \
  --scope smoke/true \
  --light \
  --ttl 15 \
  --no-semantic \
  --wait-timeout 0 \
  -- /usr/bin/true
uv run gatehold --state-dir "$state_dir" status --recent 20
sqlite3 "$state_dir/gatehold.sqlite3" \
  "SELECT kind, json_extract(detail_json, '$.result'), json_extract(detail_json, '$.resources_finalized') FROM events WHERE kind IN ('runtime.registered', 'runtime.cleanup') ORDER BY sequence;"
```

Confirm:

- the child exits `0`;
- the bounded SQLite audit shows `runtime.registered` before
  `runtime.cleanup | cleaned`;
- the final snapshot has no active lease or allocation for the smoke claim;
- the private runtime-result file is removed;
- no heartbeat or queue token is printed.

Then verify a descendant that outlives its direct parent:

```bash
descendant_pid_file="$state_dir/descendant.pid"
uv run gatehold --state-dir "$state_dir" run \
  --owner smoke-owner \
  --workstream smoke/descendant \
  --scope smoke/descendant \
  --light \
  --ttl 15 \
  --no-semantic \
  --wait-timeout 0 \
  -- python3 -c \
  'import pathlib, subprocess, sys; child = subprocess.Popen(["/bin/sleep", "120"]); pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="ascii")' \
  "$descendant_pid_file"
descendant_pid="$(<"$descendant_pid_file")"
if ps -p "$descendant_pid" -o pid= >/dev/null; then
  echo "FAIL: owned descendant survived cleanup"
  exit 1
fi
uv run gatehold --state-dir "$state_dir" status --recent 20
sqlite3 "$state_dir/gatehold.sqlite3" \
  "SELECT kind, json_extract(detail_json, '$.result'), json_extract(detail_json, '$.resources_finalized') FROM events WHERE kind IN ('runtime.registered', 'runtime.cleanup') ORDER BY sequence;"
```

Confirm the owned descendant is gone, cleanup is complete, and the lease,
workstream conflict, and allocations are finalized. Do not replace this with
`pkill`, `killall`, kill-by-port, or name-based cleanup.

If the direct child exits `0` but immediate cleanup cannot be confirmed, the
expected command result is `72`. Any still-unresolved state remains
quarantined; an idempotent reconciliation retry may later complete it. A
non-zero child result remains the child result; cleanup evidence must still be
inspected.

The temporary state directory is intentionally retained for release evidence.
Remove it after review using the operator's normal file workflow.

### 6. Verify exact-UDID simulator ownership

```bash
uv run pytest tests/core/test_lifecycle_cleanup.py -q
```

The simulator cases use a deterministic fake adapter. Confirm:

1. a pre-booted exact UDID becomes `external`; boot and shutdown are never
   called;
2. an initially stopped exact UDID gets durable `boot_intent`, is booted, is
   positively re-checked, becomes `owned`, and only then is shut down during
   cleanup;
3. a failed or unconfirmed boot remains `boot_intent`, produces no shutdown,
   keeps the simulator allocation, and blocks a competing lease;
4. a legacy ambiguous ownership record migrates fail-closed to `boot_intent`.

These tests validate the state machine and call contract. They are not a
live `simctl` smoke.

#### Recorded disposable macOS Simulator smoke

**Run date:** 2026-07-20
**Result:** PASS

A disposable Apple Simulator with a redacted exact UDID (`32A0…`) was created
solely for the lifecycle test. The observed evidence was:

- Gatehold persisted `boot_intent`, positively confirmed `owned`, then marked
  the exact simulator `cleaned`;
- the cleanup event reported `simulator_shutdown=true`;
- `resources_finalized=1` and `allocations_remaining=0`;
- the exact simulator state was `Shutdown` after cleanup;
- the disposable simulator and temporary Gatehold state directory were
  deleted;
- the final booted-simulator count was `0`.

This was an exact-UDID ownership and cleanup smoke. It did not install, launch,
or verify an app and is not a device UI test. The full temporary UDID is omitted
from public documentation intentionally.

### 7. Optional live GPT-5.6 boundary

Only after intentionally providing a server-side `OPENAI_API_KEY`, start the
relevant command with `uv run --env-file .env.local ...`; the CLI does not load
the file implicitly.

Run the isolated bounded smoke:

```bash
npm run smoke:model
```

It prints only the model verdict, bounded reason/confidence, receipt hash, and
estimated-savings label. It releases any granted lease, deletes its temporary
state directory, and never prints the API key or lease credentials.

1. submit two differently worded but semantically overlapping claims;
2. confirm the model can add a hold;
3. submit a deterministic conflict and confirm the model cannot clear it;
4. make the model unavailable and confirm the local result persists;
5. inspect logs/receipts for accidental prompt, key, code, diff, or command
   leakage.

Do not capture the environment file or API key in screenshots or video.

## Fixture validation

```bash
python3 -m json.tool fixtures/demo/gatehold-replay.json >/dev/null
```

Review the fixture for:

- `mode: "replay"`;
- bounded array sizes and strings;
- synthetic owner, workstream, host, and resource identifiers;
- no home directories, emails, tokens, or real repository names;
- scenes that match [Demo Script](DEMO-SCRIPT.md).

## Judge route

The public judge route must work without rebuilding and without credentials. It
is a replay, not live telemetry. The optional source-run route is documented in
[Judge Quickstart](JUDGE-QUICKSTART.md).

Before submission, verify the public site signed out, in a private browser
window, from a second network if practical.

## Release evidence record

Record the exact source revision and results:

```text
Revision:
Run date/time:
npm run verify:
Public replay:
Local live mode:
macOS manual check:
Managed `/usr/bin/true` cleanup:
Managed descendant cleanup:
Cleanup quarantine/exit 72:
Simulator fake-adapter ownership contract:
Disposable exact-UDID macOS Simulator smoke:
Linux best-effort check:
Optional GPT-5.6 check:
Skipped checks:
Residual risk:
```

Do not replace a skipped check with an assumption.
