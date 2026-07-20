---
name: gatehold
description: Enforce Gatehold clearance for cooperative local coding agents. Use whenever Codex will edit a Gatehold-controlled repository, start heavy build/test/browser/iOS work, or claim a shared port, browser profile, or configured simulator UDID while parallel sessions may be active.
---

# Gatehold

Use the local `gatehold` CLI as the only claim, lease, and governed-command
surface. Claim before the first edit, wait for deterministic clearance, keep
the lease alive, and leave only after its owned cleanup reaches a verified
terminal state.

## Resolve the local CLI

Prefer an installed local wrapper:

```bash
command -v gatehold
gatehold --help
```

When working inside the Gatehold source repository and no wrapper is installed,
use:

```bash
uv run gatehold --help
```

Set one invocation form for the task and use it consistently. Do not use HTTP
to claim, heartbeat, release, or run commands; Gatehold HTTP routes are
read-only.

If neither invocation works, stop controlled work and report that Gatehold is
unavailable. Do not edit or run the heavy command directly.

## Define a bounded claim

Choose:

- a stable, non-secret owner ID for this Codex task;
- one concrete product workstream;
- the smallest complete set of repository scopes;
- `light` for ordinary editing or `heavy` for builds, broad tests, browser
  suites, simulator work, and other expensive jobs;
- only the port, dedicated browser-profile, or configured exact simulator UDID
  actually required;
- an optional semantic summary that contains no source, diff, secret, private
  prompt, or personal data.

Do not rename a workstream, narrow a scope dishonestly, or classify heavy work
as light to avoid a hold.

## Claim before editing

1. Inspect current state:

   ```bash
   gatehold status --recent 10
   ```

2. Set bounded values in the current shell:

   ```bash
   owner="codex-<stable-task-id>"
   workstream="<concrete-product-workstream>"
   scope="<smallest-complete-repository-scope>"
   ```

3. Capture the JSON result so queue/heartbeat tokens do not appear in tool
   output:

   ```bash
   claim_rc=0
   claim_json="$(
     gatehold claim \
       --owner "$owner" \
       --workstream "$workstream" \
       --scope "$scope" \
       --light \
       --ttl 900 \
       --summary "<bounded non-sensitive intent>"
   )" || claim_rc=$?
   ```

   Repeat `--scope` for additional necessary scopes. Add `--port`,
   `--browser-profile`, or `--simulator` only when required.

4. Parse `decision`, `request_id`, and either the queue token or
   `lease.lease_id` and `lease.heartbeat_token` inside the same shell. Keep
   tokens in shell variables only. Print only a sanitized projection containing
   decision, IDs, reason codes, queue position, allocations, and model status.
5. Begin editing only when the authoritative `decision` is `GRANTED` and
   `lease` is present.

Treat every other result as a stop:

- `DETERMINISTIC_HOLD` — another active workstream or scope conflicts;
- `SEMANTIC_HOLD` — GPT-5.6 raised an additional conservative hold;
- `QUEUED` — capacity or FIFO order is not yet eligible;
- validation, token, state, or CLI error — clearance was not obtained.

The claim command exits `0` for `GRANTED`, `75` for `QUEUED`, and `73` for
either hold. These non-zero hold/wait codes are policy results, not permission
to bypass Gatehold.

A model `CLEAR`, explanation, missing key, timeout, or fallback is not itself
clearance. Only the final deterministic `GRANTED` decision authorizes work.

Never paste the heartbeat or queue token into commentary, chat, a file, a
receipt, or a log.

For a queued claim, keep its `request_id` and `queue_token`. Retry the same
request without exposing the token:

```bash
retry_rc=0
retry_json="$(
  GATEHOLD_QUEUE_TOKEN="$queue_token" gatehold claim \
    --owner "$owner" \
    --workstream "$workstream" \
    --scope "$scope" \
    --light \
    --ttl 900 \
    --request-id "$request_id"
)" || retry_rc=$?
```

Parse and sanitize `retry_json` exactly like the first response. Do not create a
fresh request ID to jump the FIFO queue.

## Keep the lease alive

For a long edit:

1. Heartbeat before the lease expires, using only the lease credentials returned
   by the local CLI:

   ```bash
   GATEHOLD_HEARTBEAT_TOKEN="$heartbeat_token" \
     gatehold heartbeat "$lease_id" --owner "$owner" --ttl 900
   ```

2. Capture and sanitize the JSON result before reporting it.
3. Stop editing if heartbeat fails or the lease is no longer active.

Do not assume that an old lease ID or token remains valid.

## Run heavy work through the governor

For a build, broad test, browser suite, simulator job, or other heavy command:

1. Request the honest `heavy` workload and required resources:

   ```bash
   gatehold run \
     --owner "$owner" \
     --workstream "$workstream" \
     --scope "$scope" \
     --heavy \
     --ttl 900 \
     --wait-timeout 900 \
     --poll-interval 2 \
     -- <executable> <arg> ...
   ```

2. Repeat `--scope` as required and add `--port`, `--browser-profile`, or
   `--simulator` only when the command needs it.
3. Pass the executable and arguments only after `--`.
4. Let `gatehold run` wait, heartbeat, execute with `shell=False`, and release
   through its owned cleanup contract.
5. Preserve the child command's result. Exit `75` means the queue wait timed
   out; it does not authorize a direct retry outside Gatehold.

Gatehold injects granted `GATEHOLD_PORT`, `GATEHOLD_BROWSER_PROFILE`, and
`GATEHOLD_SIMULATOR` values into the child environment. Use those allocations;
do not replace them with another task's resources. `GATEHOLD_SIMULATOR` is the
exact configured UDID, not a generic device selector.

The governed command runs under a private process-group supervisor. Exit,
interruption, heartbeat loss, expiry, and daemon recovery enter
`CLEANUP_PENDING`. Gatehold keeps the workstream and runtime allocations active
until it verifies cleanup of the proven process group, exact dedicated browser
profile, allocated port, and any exact simulator it positively owns. Partial or
ambiguous cleanup is `QUARANTINED`; it is not a release. A successful child
whose cleanup cannot be confirmed returns `72`.

On macOS, simulator ownership is fail-closed:

- Gatehold inspects the exact allocated UDID first;
- if it is already booted, Gatehold marks it external and never touches it;
- otherwise Gatehold persists `boot_intent`, boots that UDID, and marks it
  owned only after a positive `is_booted` confirmation;
- cleanup may shut down only that exact confirmed owned UDID;
- unresolved `boot_intent` remains quarantined with zero guessed shutdown.

Do not describe fake-adapter contract tests as a live `simctl` smoke. Physical
Apple Simulator lifecycle uses `xcrun simctl` and is macOS-only; generic leases
remain best-effort on Linux.

Do not run the command directly after a hold, queue-without-admission, timeout,
or Gatehold error.

If an editing lease would conflict with a separate governed run, release the
editing lease first, use `gatehold run`, then obtain a new `GRANTED` editing
lease before making more changes. Never create a second overlapping claim just
to keep both paths active.

## Release and re-scope

Before handing off, switching to overlapping work, or ending the task:

1. Release every active lease owned by this task with its valid credentials:

   ```bash
   GATEHOLD_HEARTBEAT_TOKEN="$heartbeat_token" \
     gatehold release "$lease_id" --owner "$owner"
   ```

2. Capture and sanitize the JSON result before reporting it.
3. Confirm with `gatehold status` that cleanup completed and the lease reached
   `RELEASED` or `EXPIRED`.

A release request may leave the lifecycle conceptually `CLEANUP_PENDING` or
`QUARANTINED`. The current sanitized status keeps that unresolved lease
`ACTIVE`; bounded runtime events carry the cleanup result. While unresolved,
its workstream conflict and allocations are still authoritative. Stop
controlled work, let daemon reconciliation retry, and report only the bounded
state without exposing process details or tokens. Do not treat the release
request itself as proof of a clean finish.

If the task's workstream or scopes materially change, release the current lease
and make a new honest claim before touching the new area.

Use TTL expiry as crash recovery, not as normal cleanup.

## No-bypass rules

Never:

- edit before `GRANTED`;
- treat `QUEUED`, `DETERMINISTIC_HOLD`, or `SEMANTIC_HOLD` as advisory;
- run a held heavy command outside `gatehold run`;
- invent a new owner/workstream/scope to evade an existing lease;
- delete or modify the SQLite database or token file to make work appear clear;
- kill, suspend, or restart another task to manufacture capacity;
- manually kill by process name, executable, or port to bypass a cleanup
  quarantine;
- delete a browser profile, runtime-result file, or allocation record to force
  finalization;
- boot or shut down an external simulator to manufacture ownership or clear an
  ambiguous `boot_intent`;
- change the configured simulator UDID after allocation;
- reuse another task's heartbeat or queue token;
- use GPT-5.6 output as permission;
- retry with `--no-semantic` merely to remove a semantic hold;
- change the loopback bind, origin policy, capacity limits, or TTL merely to
  obtain clearance.

When blocked, report the owner/conflict reason or queue condition without
exposing private scope text or tokens. Wait, choose genuinely disjoint work, or
ask the user to resolve ownership.

## Optional read-only dashboard

Use `gatehold daemon` only when a local dashboard or read-only snapshot/SSE is
needed. Do not put the bearer token in a URL, query, Sites configuration,
browser storage, or fixture. Pass every browser origin explicitly:

```bash
gatehold daemon --dashboard-origin http://127.0.0.1:3001
```

Use the dashboard's exact printed origin; a different localhost host or port is
not trusted. Local loopback origins may use HTTP. Non-loopback origins must
match an exact operator-approved HTTPS `GATEHOLD_DASHBOARD_ORIGINS` entry or
exact `--dashboard-origin` value.
