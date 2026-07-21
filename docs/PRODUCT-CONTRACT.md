# Gatehold Product Contract

## Simple promise

For every task that opts into Gatehold:

- one agent owns a protected workstream at a time;
- one owner holds each exclusive runtime resource at a time;
- heavy work starts only after deterministic host-capacity clearance;
- governed work restores its proven process group and runtime surfaces before
  authority is released;
- stale leases recover through heartbeat, cleanup, release, or expiry;
- every decision states why work was admitted, held, or queued.

Gatehold is a cooperative control plane. Clients outside the workflow can still
edit files or start processes.

## Terms

**Claim**
A bounded request from an owner to work on a named workstream with a task class,
scope summary, and optional runtime resources.

**Clearance**
An affirmative decision produced only by deterministic local policy after every
required gate passes.

**Lease**
A TTL-bound ownership record with an opaque heartbeat token and explicit
release/expiry lifecycle.

**Workstream**
A product or engineering responsibility that must not have overlapping active
owners. It is more meaningful than a branch or directory alone.

**Runtime resource**
A named exclusive surface: an allocated port, dedicated browser-profile
directory, or configured exact simulator UDID.

**Owned runtime**
A `gatehold run` process group and its descendants whose captured identity and
secret-derived provenance still match Gatehold's durable record.

**Cleanup pending**
A terminal release or expiry has been requested, but the lease, workstream
conflict, and allocations remain active until owned cleanup is verified. The
current sanitized snapshot continues to show the lease as `ACTIVE`; cleanup
detail is recorded in bounded runtime events.

**Quarantined**
Cleanup is partial or ownership is ambiguous. Gatehold sends no signal to an
unproven process and retains authority and allocations for later idempotent
reconciliation. An unresolved simulator boot intent likewise receives no
guessed shutdown.

**Held**
Work cannot start because a conflict or conservative semantic-overlap advisory
exists.

**Waiting**
Work cannot start yet because host capacity or FIFO order does not permit it.

**Replay**
A bounded synthetic scenario used to demonstrate the product without claiming
access to live workstation state.

## Non-negotiable invariants

1. Deterministic code is the only clearance authority.
2. GPT-5.6 can add a hold; it cannot grant, restore, or broaden clearance.
3. A deterministic conflict cannot be downgraded by model output.
4. A missing, failed, refused, timed-out, or invalid model response cannot
   weaken local policy.
5. A task without clearance must not edit or start controlled heavy work.
6. Every lease has TTL, owner identity, heartbeat token, and
   cleanup-before-release/expiry paths.
7. An exclusive port, browser-profile directory, or configured simulator lease
   has one owner at a time.
8. Capacity waiting preserves the implemented deterministic queue policy.
9. Gatehold never kills unrelated user processes to create capacity.
10. A governed process group is signaled only when its PID, process-group and
    session identity, process create time, host boot time, and secret-derived
    provenance match the registered runtime.
11. A browser-profile directory is removed only when its exact path, Gatehold
    marker, device/inode identity, and marker digest match.
12. A port allocation is finalized only after owned process cleanup and a
    loopback bind check confirms that the port is free.
13. Ambiguous or partial cleanup keeps the workstream conflict and allocations
    active; it never converts uncertainty into clearance.
14. Gatehold inspects the exact configured simulator UDID before acting. A
    simulator already booted at inspection is external and never touched.
15. Gatehold persists `boot_intent` before boot. It marks that exact UDID owned
    only after the boot succeeds and a positive `is_booted` confirmation.
16. Cleanup may shut down only an exact UDID in the confirmed `owned` state.
    An unresolved `boot_intent` is quarantined with zero guessed shutdown.
17. Physical Apple Simulator lifecycle is macOS-only through `xcrun simctl`.
18. Commands run only from the local CLI as an argument vector with
    `shell=False` and a minimal child environment. Optional bounded
    `--pass-env` requests reject credential, Gatehold-control, and known
    interpreter/startup injection names before admission.
19. The HTTP API never accepts arbitrary commands.
20. The daemon binds to `127.0.0.1` by default.
21. Secrets never enter browser bundles, fixtures, receipts, logs, or git.
22. Replay and live-local state remain visibly distinct.
23. Savings and avoided-collision values are labeled estimates.

## Admission contract

A claim can be admitted only when all applicable conditions are true:

```text
valid_request
AND no_authoritative_workstream_conflict
AND no_exclusive_resource_conflict
AND host_capacity_allows_task_class
AND fifo_position_is_eligible
AND no_valid_model_overlap_hold
= CLEARED
```

Every other result is `HELD`, `WAITING`, or a bounded validation/error result.
There is no force, override, ignore, or `--no-gatehold` operation in the
controlled workflow.

If Gatehold is unavailable, a skill-controlled agent stops and reports the
problem. It does not silently continue editing or run a heavy command.

## Managed cleanup contract

Admission and cleanup are one authority lifecycle for `gatehold run`:

```text
ACTIVE
  -> CLEANUP_PENDING
      -> RELEASED or EXPIRED, only after verified cleanup
      -> QUARANTINED, when cleanup is partial or ownership is ambiguous
```

Normal child exit, interruption, heartbeat loss, explicit release, TTL expiry,
and daemon recovery converge on the same idempotent cleanup path. A recorded
release or expiry is terminal intent, not immediate permission for another
agent. Until cleanup completes:

- the lease remains authoritative;
- protected work still conflicts;
- ports, browser profiles, and configured exact simulator UDIDs remain
  allocated;
- later FIFO work cannot treat those surfaces as available.

Cleanup may terminate the proven private process group, including a descendant
dev server, then remove the exact dedicated browser profile and confirm the
allocated port is bind-free. Gatehold does not scan by process name, kill by
port, delete an arbitrary directory, or infer ownership from an executable
name. Unknown or reused identity receives zero signals.

For an allocated simulator on macOS, cleanup distinguishes three cases by the
persisted exact-UDID record:

- `external`: it was already booted before Gatehold acted and is never touched;
- `owned`: Gatehold persisted boot intent, booted the exact UDID, and positively
  confirmed it; cleanup may shut down that exact simulator and verify it is no
  longer booted;
- `boot_intent`: boot ownership was never positively confirmed, so cleanup
  performs zero guessed shutdown and keeps the lifecycle quarantined.

If a child exits successfully but immediate cleanup cannot be verified,
`gatehold run` returns `72` (`CLEANUP_QUARANTINED`) instead of reporting a clean
success. A non-zero child result remains the child result; cleanup status is
still recorded and reconciled.

The standalone `gatehold release` command also returns `0` only with
`state: released`. While cleanup remains pending or quarantined, it reports
`state: active`, returns `72`, and retains workstream/resource authority.

## Model authority contract

GPT-5.6 is useful where exact identifiers and path matching are insufficient.
For example, “repair subscription renewal” and “fix billing retry flow” may
touch the same product responsibility.

The model output is still untrusted. Gatehold validates it against a strict
bounded schema and known claim identifiers. A model-raised hold must reference
claims supplied for that comparison. Prose cannot mutate the state machine.

The product does not claim that GPT-5.6 finds every semantic collision.

## Receipt contract

A receipt must make the decision auditable without exposing secrets or private
work content. The current receipt contains:

- receipt, request, and optional lease identifiers;
- SHA-256 digests for the receipt input, receipt payload, owner, workstream, and
  scope set;
- generated and optional expiry timestamps;
- the deterministic decision and bounded reason codes;
- bounded semantic verdict and optional model identifier;
- the executable basename, never its arguments;
- an optional collision-savings value labeled `estimate`.

Queue credentials/position and lease heartbeat credentials are delivery fields
outside the durable receipt. Snapshots expose hashed owner, workstream, and
scope values rather than their raw text.

A receipt is not:

- proof that a command ran;
- a security attestation;
- a trusted timestamp;
- a cryptographic identity signature;
- proof of source or evidence origin;
- proof that an unmanaged process respected Gatehold.

## Public replay contract

The public replay:

- uses synthetic identifiers and bounded values;
- contains no private repo paths, task prompts, user data, hostnames, process
  command lines, or secrets;
- is clearly labeled `REPLAY`;
- demonstrates the same decision vocabulary as the live product;
- remains functional without a local daemon or API key.

The replay does not claim to be a real-time simulation of a judge's machine.

## Supported platform contract

macOS 13+ is the primary supported platform for the Build Week package.
Python 3.12, Node.js 22.13+, `uv`, and npm are required for a source checkout.

Linux is best-effort for the daemon, CLI, database, host probes, and generic
resource leases. Physical Apple Simulator boot/shutdown uses `xcrun simctl`
and is macOS-only. Gatehold does not promise Windows support.

## Honest market language

Allowed:

- “Local air-traffic control for coding agents.”
- “One owner per controlled workstream.”
- “Deterministic clearance with a GPT-5.6 hold-only adviser.”
- “Combines work ownership, capacity admission, runtime lanes, and fail-closed
  owned cleanup.”
- “Keeps authority quarantined until owned cleanup is verified.”
- “Shuts down only the exact simulator Gatehold booted and confirmed as owned.”

Disallowed without new evidence:

- “first,” “only,” or “unprecedented”;
- “guarantees no conflicts”;
- “secure sandbox” or “tamper-proof”;
- “optimizes your Mac”;
- “proves the command ran”;
- “automatically fixes collisions”;
- “controls every process”;
- “cleans any leftover process”;
- “shuts down any simulator”;
- “takes ownership of a pre-booted simulator”;
- “guarantees simulator cleanup”;
- “proves app launch or device UI behavior” from a lifecycle smoke.

## Definition of done

A meaningful Gatehold change is complete only when:

- the invariants above still hold;
- `npm run verify` passes in the current source state;
- replay data validates and remains synthetic;
- local failure paths do not bypass clearance;
- governed cleanup cannot signal an unproven process or finalize a partial
  cleanup;
- exact-UDID simulator contract tests cover pre-booted external, confirmed
  owned, and ambiguous boot-intent paths; fake-adapter results are never
  reported as live `simctl` evidence;
- affected documentation is synchronized;
- skipped manual checks and residual risks are reported.
