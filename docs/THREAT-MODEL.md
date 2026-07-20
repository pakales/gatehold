# Gatehold Threat Model

## Scope

This document covers the Build Week Gatehold release: a local Python daemon and
CLI, local SQLite state, optional GPT-5.6 semantic adviser, a Codex skill, and a
public replay/local dashboard.

Gatehold coordinates cooperative agents running under the local developer's
authority. It is not a sandbox for hostile code and does not replace operating
system permissions, endpoint security, containers, or virtual machines.

## Protected assets

- correctness of workstream and runtime-resource ownership;
- integrity and ordering of admission decisions;
- opaque lease and heartbeat tokens;
- local Gatehold state and receipts;
- `OPENAI_API_KEY`;
- privacy of project names and bounded scope summaries;
- availability of the developer workstation;
- clarity of replay versus live-local evidence.

## Trust boundaries

| Boundary | Untrusted input |
| --- | --- |
| CLI/API request | owner, workstream, scope, path, task class, resource IDs |
| Loopback HTTP | any request from another local process or browser |
| Host probes | volatile or unavailable process/system values |
| Model request/response | scope text and all generated output |
| SQLite state | stale, interrupted, or concurrently accessed lease state |
| Child process | executable and arguments selected by the local operator |
| Public replay | any fixture change that could introduce private or misleading data |

## Security invariants

- Bind only to `127.0.0.1`.
- Validate every external boundary with strict bounded schemas.
- Never expose secrets to the browser, fixtures, receipts, logs, or git.
- Use `store=False` for OpenAI Responses API calls.
- Do not persist source, diffs, conversations, or command arguments.
- Never accept an arbitrary command through HTTP.
- Execute CLI commands with `shell=False`.
- Do not copy the ambient operator environment into governed commands; reject
  credential, Gatehold-control, and known interpreter/startup injection names
  requested through bounded `--pass-env`.
- Never let model output grant clearance or override local policy.
- Use TTL, opaque heartbeat token, release, and expiry for every lease.
- Preserve exclusive ownership of each named runtime resource.
- Never kill unrelated processes.
- Label replay and estimates explicitly.

## Threats and mitigations

### T1: Remote access to the daemon

**Threat:** A bind to `0.0.0.0` or a public interface exposes workstation state.

**Mitigations:** The daemon default and product contract require
`127.0.0.1`. Documentation does not provide a public-bind option. Network
binding changes require an explicit auth and threat-model redesign. `Host` must
be loopback. Tokenless browser reads require an exact origin explicitly
allowlisted with `--dashboard-origin` or `GATEHOLD_DASHBOARD_ORIGINS`; being a
loopback origin alone is not sufficient. Non-loopback origins must use HTTPS.
CORS echoes the exact origin without wildcard or credentials. Origin-less
local clients reading `/v1/*` require the bearer token stored in a mode-`0600`
file.

**Residual risk:** Another process under the same OS user may be able to read
the token file or database. The local account remains the security boundary.

### T2: Command injection

**Threat:** A task description, model output, or API field becomes executable
shell text.

**Mitigations:** HTTP is strictly read-only and has no claim, lease-mutation, or
arbitrary-command operation. Only the CLI starts child processes, using an
argument vector and `shell=False`. The child receives a minimal
runtime-compatible environment, not an ambient environment copy. Explicit
`--pass-env` requests are bounded and reject credential-like names,
Gatehold-control names, and known interpreter/startup injection names before
claim creation. Claim metadata and model output remain data.

**Residual risk:** The local operator can intentionally select a dangerous
executable or a non-protected setting that changes tool behavior. The selected
program can also read same-user files. Gatehold controls admission and limits
accidental environment leakage; it is not a program sandbox.

### T3: Model authority escalation

**Threat:** Prompt injection or malformed output convinces the system to clear
a conflict, skip capacity policy, or allocate a resource.

**Mitigations:** The model schema is hold-only, output is strictly validated,
known identifiers are checked, and deterministic local policy is authoritative.
Failure preserves local policy.

**Residual risk:** The model can add a false-positive hold. This is a safe
availability failure, but it may delay work.

### T4: Sensitive data sent to or returned by the model

**Threat:** Source, diffs, credentials, private prompts, or unrestricted process
data enter the API call or model prose enters logs.

**Mitigations:** Send bounded claim metadata only; redact home paths, emails,
common provider tokens, JWTs, credential assignments, and high-confidence
contextual bearer/API/access secrets before path normalization; use
`store=False`; bound output; avoid raw model prose in receipts; and keep the
key server-only.

**Residual risk:** Pattern filtering is not general DLP. An unknown or
unstructured secret may survive, so operators must not place sensitive content
in a workstream name or scope summary.

### T5: Lease theft or accidental release

**Threat:** Another process guesses an identifier, heartbeats a lease, or
releases work it does not own.

**Mitigations:** Use opaque heartbeat tokens, owner binding, strict state
transitions, and transactional updates. Do not expose tokens in public
receipts.

**Residual risk:** A same-user process with filesystem access may read the
SQLite database or environment. OS account isolation remains the security
boundary.

### T6: Race condition or double admission

**Threat:** Concurrent requests both observe a free workstream or resource.

**Mitigations:** Evaluate conflicts and create leases in SQLite transactions;
add concurrency tests for one-winner behavior and FIFO ordering.

**Residual risk:** Filesystem/database corruption or unsupported network
filesystems can violate SQLite assumptions. Store state on a local filesystem.

### T7: Stale lease blocks work forever

**Threat:** A crashed agent never releases its workstream.

**Mitigations:** Every lease has a TTL, heartbeat token, and explicit
release/expiry path. Expiry is processed before new admission decisions.
Release and expiry first set a terminal cleanup target; the lease and its
allocations remain authoritative until owned runtime cleanup is positively
verified. Ambiguous process identity, an occupied port, or a replaced browser
profile enters a retryable quarantine instead of freeing the lane.

**Residual risk:** Incorrect clocks, suspended hosts, or an ownership mismatch
can delay cleanup and intentionally keep a lane blocked. This fail-closed delay
requires operator investigation rather than guessing which resource to kill.

### T8: Resource exhaustion

**Threat:** Clients flood claims, scope text, or model calls; heavy tasks still
overload the host.

**Mitigations:** Bound schema sizes, restrict API operations, apply deterministic
capacity limits and FIFO ordering, avoid automatic model retries, and never
spawn commands from HTTP.

**Residual risk:** Gatehold cannot control unmanaged processes or guarantee a
stable host after admission. Capacity signals are snapshots.

### T9: Privacy leak through logs, fixtures, or receipts

**Threat:** Home paths, private repo names, commands, hostnames, credentials, or
user data enter committed artifacts.

**Mitigations:** Use synthetic fixtures, stable IDs, bounded reason codes, and
secret/private-pattern sweeps. Ignore local state and environment files in git.

**Residual risk:** Human-authored fixtures can still contain accidental data;
review remains required.

### T10: Replay presented as live evidence

**Threat:** Judges or users infer that synthetic telemetry is real workstation
state or measured savings.

**Mitigations:** Persistently label replay mode, use synthetic timestamps and
identifiers, describe estimates as estimates, and document the local-live
boundary.

**Residual risk:** Screenshots cropped without the mode label can mislead. Keep
the label visible in every demo capture.

### T11: Browser-origin abuse

**Threat:** A malicious website attempts requests to the loopback API.

**Mitigations:** Expose only sanitized read-only health, snapshot, and SSE.
Validate loopback `Host`. Accept tokenless browser access only from exact
configured origins, require HTTPS for non-loopback origins, echo the exact CORS
origin without wildcard/credentials, and require a bearer token for
origin-less `/v1/*` clients. An arbitrary localhost development server is not
implicitly trusted. The dashboard attempts a local connection only from an
HTTP loopback URL carrying the explicit `?local=1` operator flag; the public
replay does not probe `127.0.0.1`. Never put the token in a URL, query, Sites
configuration, or browser storage.

**Residual risk:** Loopback services are discoverable, and a malicious process
under the same OS user may read the token. A future remote-capable dashboard
requires a new authentication and CSRF/CORS design.

### T12: Clearance bypass by an agent

**Threat:** A Codex session edits before claim, ignores `HELD`/`WAITING`, runs a
heavy command directly, or fails to release.

**Mitigations:** The Gatehold skill makes claim-before-edit and governed-run
mandatory, treats unavailable Gatehold as a stop condition, heartbeats long
work, and routes every finish path through the same owned-runtime cleanup.
Normal exit, interruption, lost heartbeat, expiry, and daemon recovery clean
only a provenance-verified private process group, dedicated browser profile,
allocated port, and exact simulator Gatehold itself booted and positively
confirmed. A pre-booted simulator is recorded as external and never touched.
Gatehold persists exact-UDID boot intent before calling `simctl`; unresolved
intent is quarantined and receives no guessed shutdown.

**Residual risk:** Skills are cooperative policy, not an OS enforcement layer.
An unmanaged or intentionally non-compliant process can bypass them.

## Abuse cases Gatehold does not solve

- malicious source code executed by an admitted command;
- compromise of the local operating-system account;
- a user intentionally deleting or modifying the SQLite database;
- unmanaged tools editing the same repository;
- kernel-level CPU, memory, filesystem, or network isolation;
- remote multi-user scheduling;
- proof that tests, builds, or commands actually ran.

## Security test obligations

At minimum, keep automated coverage for:

- loopback-only defaults;
- one-winner concurrent claims;
- FIFO capacity ordering;
- resource exclusivity;
- TTL expiry and token-bound heartbeat/release;
- cleanup-pending and quarantined leases retaining conflict and capacity
  authority;
- PID/PGID/session/create-time mismatch producing zero signals;
- owned descendant cleanup, external port preservation, and replaced-profile
  preservation;
- pre-booted simulator preservation, exact owned-simulator shutdown, ambiguous
  boot-intent quarantine, and fail-closed legacy-state migration;
- strict schema and size rejection;
- model attempt to grant clearance;
- model refusal, timeout, malformed output, and missing-key fallback;
- no secret/raw-command fields in receipts;
- no arbitrary HTTP command execution;
- exact browser-origin allowlisting with arbitrary loopback origins denied;
- replay fixture privacy and mode labeling.

Run the complete gate in [Testing](TESTING.md) before release.
