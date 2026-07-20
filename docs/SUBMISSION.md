# Gatehold — Devpost Submission Copy

This file is the English source of truth for the OpenAI Build Week entry. Replace
every `PENDING_*` marker with verified final evidence before submission.

## Submission fields

**Project name**
Gatehold

**Tagline**
Local air-traffic control for coding agents.

**Category**
Developer Tools

**Public demo URL**
`PENDING_PUBLIC_DEMO_URL`

**Code repository URL**
`PENDING_PUBLIC_REPOSITORY_URL`

**Public YouTube demo URL**
`PENDING_PUBLIC_YOUTUBE_URL`

**Codex `/feedback` session ID**
`PENDING_CODEX_SESSION_ID`

**License**
MIT

## Short description

Gatehold is a local admission-control plane for parallel AI coding agents. It
prevents cooperative agents from silently taking the same product work,
assigns isolated runtime lanes, and queues heavy builds or tests when
the workstation is under pressure. It also verifies that a governed task's
owned process group and runtime surfaces are clean before releasing authority.
Deterministic local policy is the only clearance authority. GPT-5.6 can detect
a semantic overlap and add a hold, but it can never grant clearance or override
a local conflict.

## Inspiration

AI coding sessions can now run in parallel, but the developer workstation is
still a shared physical system. Worktrees isolate files; they do not establish
who owns a product flow, who has the only simulator or browser profile, or
whether three agents should start builds at the same time.

The failure is rarely dramatic. It is two reasonable agents duplicating work,
reusing one port, restarting one server, leaving a browser profile or dev
server behind, or making the laptop unusable. We wanted a clear full-flight
rule for cooperative agents: claim the work, wait for the machine, run in an
owned lane, and restore that lane before it clears.

## What it does

Gatehold evaluates two gates before controlled work begins:

1. **Workstream clearance** — only one active owner can hold overlapping
   protected work and exclusive resources.
2. **Host-capacity clearance** — heavy tasks wait in deterministic order when
   bounded local CPU or memory-pressure policy says the machine cannot carry
   more work.

Admitted work receives a TTL-bound lease with heartbeat and
cleanup-before-release/expiry paths. Exclusive resources can allocate a port,
dedicated browser-profile directory, or configured exact simulator UDID. A
governed command runs in a private process group. Gatehold verifies that
group's persisted provenance, removes only an exactly marked
profile, and confirms the port is free before finalizing the lease.

The lifecycle is fail-closed:
`ACTIVE → CLEANUP_PENDING → RELEASED/EXPIRED`. Partial or ambiguous cleanup
becomes `QUARANTINED`; conflicts and allocations remain held for reconciliation
and unproven processes receive no signal. For simulators, a pre-booted exact
UDID is external and never touched. Gatehold records boot intent before boot,
confirms ownership only after a positive boot check, and shuts down only that
exact owned simulator. Ambiguous boot intent stays quarantined with zero guessed
shutdown. Receipts explain whether work was admitted, held, or queued; bounded
runtime events record the cleanup result and reason.

The public judge experience is a clearly labeled synthetic replay. The local
mode reads the loopback daemon and current Gatehold state on the same machine.
Gatehold never pretends a public website can inspect a visitor's workstation.

## How we built it

- Python 3.12, FastAPI, Pydantic, SQLite, psutil, and `uv` for the local control
  plane.
- A transactional deterministic admission engine for conflicts, resource
  exclusivity, TTL, heartbeat, expiry, FIFO capacity waiting, and two-phase
  cleanup finalization.
- A private process-group supervisor with an activation handshake and durable
  PID, process-group/session, create-time, boot-time, and secret-derived
  provenance. Cleanup uses bounded `TERM` then `KILL` only after identity
  verification.
- Exact-marker browser-profile cleanup and bind-free port verification. Partial
  cleanup stays quarantined and is retried idempotently by daemon recovery.
- A macOS `xcrun simctl` adapter with an exact-UDID state machine:
  `external`, durable `boot_intent`, positively confirmed `owned`, then
  `cleaned`. Fake-adapter contract tests cover pre-booted, owned, and ambiguous
  paths. A separate disposable exact-UDID macOS Simulator smoke verified the
  live lifecycle without claiming an app or device UI test.
- An optional OpenAI Responses API integration using GPT-5.6 with strict
  hold-only output, `store=False`, bounded input, and deterministic fallback.
- A local CLI for claim, status, heartbeat, release, governed run, and demo.
  Commands and all state mutations execute only from the CLI/local service with
  `shell=False`; HTTP is sanitized and read-only.
- React 19, TypeScript, vinext, and OpenAI Sites for a polished public replay
  and live-local dashboard.
- A reusable Codex skill that makes claim-before-edit, governed heavy work,
  heartbeat, and release part of the agent workflow.

## How Codex and GPT-5.6 contributed

Codex was our primary engineering collaborator. It translated the product
invariants into a clean repository, decomposed the daemon, lease model, API,
CLI, tests, UI, replay, threat model, and submission package, then validated
the implementation as an integrated release candidate. Codex accelerated
parallel inspection and implementation while the human retained the key
product and risk decisions.

Those decisions include:

- deterministic code is the only clearance authority;
- the daemon is loopback-only;
- model failure never weakens local policy;
- command execution stays out of HTTP;
- Gatehold waits instead of killing unrelated processes and never guesses
  runtime ownership;
- release/expiry frees authority only after owned cleanup is verified;
- pre-booted simulators remain external, and only an exact simulator Gatehold
  booted and positively confirmed may be shut down;
- public replay and live workstation state stay visibly distinct.

GPT-5.6 has a separate runtime role. It reviews bounded descriptions for
semantic overlap that exact identifiers may miss. Its structured output can
only add a hold. It cannot admit work, clear a deterministic collision, allocate
a resource, reorder capacity, execute a command, or mutate a lease.

## Challenges

The hardest problem was not adding an AI classifier; it was limiting its
authority. A persuasive model explanation must never become a hidden permission
system. We designed the state machine so clearance exists entirely outside the
model schema and tested failure, refusal, timeout, malformed output, and
prompt-injection-shaped input.

The second challenge was honest observability. A public site cannot read a
judge's local processes or machine pressure, so Gatehold provides a bounded
synthetic replay and labels it continuously. Live-local state is a separate
loopback path.

The third challenge was crash recovery without collateral damage. A vanished
agent may leave descendants running, but a reused PID or human process must
never be mistaken for owned work. Gatehold retains the active conflict while it
verifies process-group provenance and converges normal exit, interruption,
heartbeat loss, expiry, and daemon recovery on one idempotent cleanup path.
Uncertainty becomes quarantine, not optimistic release.

The fourth challenge was simulator ownership. Observing a booted device after a
failure does not prove who booted it. Gatehold therefore records intent before
boot, requires a second positive check before ownership, treats a pre-booted
UDID as external, and quarantines unresolved intent rather than guessing a
shutdown.

## Accomplishments

- A non-trivial local daemon and CLI that work without an OpenAI key.
- Deterministic one-owner and one-resource invariants under concurrent claims.
- Machine-aware FIFO waiting without killing unrelated processes.
- Provenance-backed cleanup of a governed process group, descendant dev server,
  exact dedicated browser profile, and allocated port.
- Exact-UDID simulator ownership that protects pre-booted human simulators and
  shuts down only a positively confirmed Gatehold-owned boot.
- A disposable macOS Simulator smoke that reached
  `boot_intent → owned → cleaned`, confirmed shutdown and resource finalization,
  and left zero allocations or booted simulators.
- Fail-closed quarantine that retains conflicts and allocations until cleanup
  is positively verified.
- A GPT-5.6 integration that can only make admission more conservative.
- A public no-secret replay plus a separate live-local control desk.
- A Codex skill that operationalizes the safety contract for real coding work.
- Strict Python/TypeScript checks, contract tests, privacy documentation, and a
  reproducible judge route.

## What we learned

Parallel-agent safety is mostly an authority-design problem. File isolation,
semantic understanding, and CPU telemetry each solve a different layer.
Combining them works only when the system is explicit about which component can
say “go.” We also learned that waiting is a product outcome, not an error: a
useful control plane must explain the hold and show the recovery condition.
Likewise, “finished” cannot mean only that the direct child exited; it means
that owned descendants and runtime surfaces were verified clean without
touching anything Gatehold cannot prove it owns. Simulator state made that rule
especially concrete: boot intent is evidence, but only a confirmed boot becomes
ownership.

## Competitive differentiation

Gatehold does not claim to be the first or only tool for parallel agents.
Worktree managers, multi-agent workspaces, OS process governors, and command
queues already solve valuable parts of the problem.

Gatehold focuses on their intersection: product-work ownership,
machine-capacity admission, named runtime lanes, and fail-closed owned cleanup
across a cooperative agent's lifecycle. Its defining technical choices are
that GPT-5.6 may add a semantic hold while only deterministic local policy can
grant clearance, and that only verified cleanup can free authority.

## Pre-existing-work disclosure

Before this public repository was assembled, private EVL Labs workstation
prototypes existed, including during the Build Week submission period. The new
clean Gatehold repository generalizes these concepts:

- explicit workstream collision checks;
- queued build/test/browser/iOS-heavy work;
- named ownership for ports, browser profiles, and simulators;
- local host-health signals;
- stale-work recovery and operator receipts;
- fail-closed cleanup of proven owned runtime surfaces.

No private source code, private repository history, user data, credentials, or
private prompt transcripts were copied into Gatehold. The competition-period
public work adds the generalized state machine, schemas, daemon/API/CLI,
hold-only GPT-5.6 boundary, synthetic replay, public UI, tests, documentation,
and Codex skill.

Dated evidence is recorded in the repository README and must be paired with
final dated commit links and the submitted `/feedback` session ID.

## Distinction from our other submission

Gatehold is substantially different from ProofLatch:

| | Gatehold | ProofLatch |
| --- | --- | --- |
| Problem | Prevent parallel local agent/workstation collisions before work starts | Evaluate a bounded release-evidence packet after checks |
| Primary input | Work claims, resource requests, local capacity | Release checks and evidence |
| State machine | Claim → hold/wait/admit → heartbeat → cleanup pending/quarantine → release/expiry | Evidence → deterministic BLOCKED/READY → receipt |
| Runtime surface | Local daemon, CLI, Codex skill, workstation dashboard | Release decision desk and evidence receipt |
| GPT-5.6 role | May add semantic overlap hold | Explains a deterministic release assessment |
| Output | Lease and admission receipt | Release decision and repair brief |

The projects use separate codebases, product contracts, test suites, user
flows, and submission narratives. They share no product source code.

## Testing instructions

### Fast path — no install

1. Open `PENDING_PUBLIC_DEMO_URL`.
2. Confirm the mode is labeled **REPLAY**.
3. Step through admitted ownership, workstream collision, host-capacity waiting,
   exclusive runtime lanes, exact-UDID simulator ownership, and Scene D's
   verified clean finish.
4. Open the architecture/authority explanation in the product.

No account, API key, payment, or workstation access is required.

### Local source path

Requirements: macOS 13+, Python 3.12, `uv`, Node.js 22.13+, and npm.

```bash
uv sync --dev
npm ci
uv run gatehold init
uv run gatehold demo
npm run verify
```

To inspect live local state:

```bash
uv run gatehold daemon
```

Then in another terminal:

```bash
uv run gatehold status
```

The read-only loopback API exposes an unauthenticated `/healthz` route restricted
to loopback `Host` and returning only status/version. `/v1/snapshot` and
`/v1/events` require either an exact browser origin explicitly allowed at daemon
startup or the bearer token stored in the local mode-`0600` token file. The
token never enters the URL, browser storage, fixture, or public site.

The deterministic product and demo require no OpenAI key. An optional
server-only key enables the GPT-5.6 semantic adviser. Linux is best-effort for
the core daemon/CLI and generic resource leases. Physical Apple Simulator
boot/shutdown uses `xcrun simctl` and is macOS-only. The exact-UDID simulator
contract is covered by fake-adapter tests and a disposable live macOS Simulator
lifecycle smoke. The latter is not an app launch or device UI test.

## What's next

- signed local client identity for stronger same-user process separation;
- richer adapters for existing agent runtimes without expanding model
  authority;
- policy profiles for different workstation sizes;
- privacy-preserving aggregate operational metrics;
- opt-in remote coordination only after a new authentication and threat model.

## YouTube publishing copy

**Title**
Gatehold — Every Agent Needs Clearance | OpenAI Build Week

**Description**

> One machine. Many agents. Zero collisions.
>
> Gatehold is local clearance control for parallel AI coding agents. Before a
> controlled task edits or starts heavy work, deterministic policy checks
> workstream ownership and workstation capacity. GPT-5.6 may add a conservative
> semantic hold, but it can never grant clearance.
>
> In this 2:51 demo: clean admission, semantic collision detection,
> deterministic FIFO capacity waiting, provenance-backed cleanup, and safe
> exact-UDID simulator ownership. A pre-booted simulator stays external;
> Gatehold shuts down only the exact simulator it booted and confirmed.
>
> Live demo: PENDING_PUBLIC_DEMO_URL
> Source code: PENDING_PUBLIC_REPOSITORY_URL
>
> Built for OpenAI Build Week in the Developer Tools category using Codex and a
> bounded GPT-5.6 runtime adviser.
>
> Voice disclosure: English narration is AI-generated with OpenAI
> gpt-4o-mini-tts-2025-12-15, Marin voice.
>
> The hosted dashboard shown is a labeled synthetic replay. Live-local state is
> available only from the loopback daemon with an explicitly allowed browser
> origin.
>
> #OpenAI #BuildWeek #DeveloperTools #AIAgents

## Build Week evidence

**Submission period work date:** 2026-07-20 EEST
**Primary Codex evidence:** `PENDING_CODEX_SESSION_ID`
**Dated commit evidence:** `PENDING_DATED_COMMIT_URLS`
**Final validation revision:** `PENDING_FINAL_COMMIT_SHA`

These markers must not remain in the submitted Devpost entry.
