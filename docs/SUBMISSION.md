# Gatehold — Devpost Submission Copy

This file is the English source of truth for the OpenAI Build Week entry.
Fields explicitly marked pending must be replaced and signed-out verified at
the user-approved external-release boundary.

## Submission fields

**Project name**
Gatehold

**Tagline**
Local air-traffic control for coding agents.

**Category**
Developer Tools

**Public demo URL**
<https://gatehold-buildweek.e-vigelis.chatgpt.site>

**Code repository URL**
<https://github.com/pakales/gatehold>

**Public YouTube demo URL**
<https://youtu.be/nMsqkk9oclQ>

**Codex `/feedback` session ID**
`019f7221-2421-78e3-b12e-f6082da1ed87`

**License**
MIT

## Short description

Gatehold gives parallel coding agents a preflight check and a clean landing on
one developer workstation. Before work starts, it prevents cooperative agents
from silently taking the same product outcome, assigns exclusive runtime
lanes, and queues heavy builds or tests when the host is under pressure. Before
authority is reused, it verifies that the governed task's owned process group
and runtime surfaces are clean. Deterministic local policy is the only
clearance authority. GPT-5.6 can detect a semantic overlap and add a hold, but
it can never grant clearance or override a local conflict.

## Fast judge path

Open <https://gatehold-buildweek.e-vigelis.chatgpt.site> with no account, key,
or local installation. In approximately 90 seconds, the bounded replay shows:

1. one agent receiving a TTL-bound workstream lease;
2. a differently worded overlapping claim being held before it edits;
3. a heavy task waiting for deterministic FIFO host capacity;
4. exclusive port, browser-profile, and exact-simulator ownership; and
5. verified owned cleanup completing before the next task becomes eligible.

The experience is persistently labeled **REPLAY** because a public site cannot
truthfully inspect a judge's workstation. A five-minute source path exercises
the real local daemon and CLI.

## Inspiration

AI coding sessions can now run in parallel, but the developer workstation is
still a shared physical system. Worktrees isolate files; they do not establish
who owns a product flow, who has the only simulator or browser profile, or
whether three agents should start builds at the same time.

The intended user is a solo developer or small team running several coding
agents on one workstation. Today that operator becomes a manual scheduler:
remember which agent owns each outcome, watch CPU and memory pressure, reserve
ports and simulators, and clean up after sessions finish.

The failure is rarely dramatic enough to explain itself. It is two reasonable
agents duplicating work, reusing one port, restarting one server, leaving a
browser profile or descendant dev server behind, or making the laptop
unresponsive. We wanted one clear full-flight rule for cooperative agents:
claim the work, wait for the machine, run in an owned lane, and restore that
lane before it clears.

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

## Potential impact

Parallel coding makes starting work cheap, but it also multiplies pressure on a
shared workstation. The operator pays for collisions as duplicated effort,
confusing server state, failed builds, unavailable simulators, and time spent
identifying which process is safe to stop.

Gatehold addresses that problem at two moments where an explanation alone is
too late: **before work starts** and **before a finished lane is reused**. A
hold or wait is accompanied by a bounded reason and recovery condition. A
clean finish is based on verified ownership, not a process name or optimistic
assumption.

The current product deliberately targets cooperative local clients, where its
authority and privacy boundaries are testable. The reusable Codex skill
demonstrates how an agent runtime can adopt the contract today. The same lease
and adapter boundaries could support other local agent clients without turning
Gatehold into a remote surveillance service or expanding GPT-5.6's authority.

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
  `shell=False`; governed children receive a minimal environment with bounded
  protected-name validation for explicit `--pass-env`; HTTP is sanitized and
  read-only.
- React 19, TypeScript, vinext, and OpenAI Sites for a polished public replay
  and live-local dashboard.
- A reusable Codex skill that makes claim-before-edit, governed heavy work,
  heartbeat, and release part of the agent workflow.
- A release gate that collects 246 Python contract cases and three Node web
  contract tests, then runs Ruff, Pyright, TypeScript, ESLint, privacy/link
  checks, and a production build.

## How Codex and GPT-5.6 contributed

Codex was our primary engineering collaborator and later became a controlled
client of the product it helped build. It translated the product invariants
into a clean competition repository, decomposed the daemon, lease model, API,
CLI, tests, UI, replay, threat model, and submission package, and used the
release gate to expose integration failures that did not appear in isolated
checks. Codex accelerated parallel implementation, adversarial review,
documentation synchronization, and public-release verification while the human
selected the product direction and retained the key product and risk
decisions.

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
- A current inventory of 246 Python contract cases plus three Node web contract
  tests, strict Python/TypeScript checks, privacy documentation, and a
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

| Adjacent category | Existing value | Gatehold's additional contract |
| --- | --- | --- |
| Git worktrees | Isolate files and branches | Coordinate ownership of the product outcome across worktrees |
| Multi-agent workspaces | Separate sessions and delegate tasks | Require one shared deterministic preflight before local work begins |
| Process governors and queues | Limit CPU or concurrent jobs | Combine capacity with workstream and named-runtime admission |
| Cleanup utilities | Find stale processes or files | Act only on durable, verified ownership and quarantine uncertainty |

Gatehold focuses on the intersection: product-work ownership,
machine-capacity admission, named runtime lanes, and fail-closed owned cleanup
across a cooperative agent's lifecycle. Its defining technical choices are
that GPT-5.6 may add a semantic hold while only deterministic local policy can
grant clearance, and that only verified cleanup can free authority. The claim
is the coherence of that lifecycle, not that each individual primitive is new.

## Pre-existing-work disclosure

Private EVL Labs workstation-coordination prototypes predated the Submission
Period start on July 13, 2026 at 09:00 PT. The new clean Gatehold repository
was assembled during the Submission Period and generalizes these concepts:

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

The submitted Codex session is a long-running product thread. It contains an
earlier, clearly separate ProofLatch workstream before the user explicitly
pivoted to Gatehold; the Gatehold implementation, decisions, and validation
then continued in that same thread. The shared session identifier reflects
thread continuity, not shared product source. The dated Gatehold repository
history isolates the competition-period implementation.

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

1. Open <https://gatehold-buildweek.e-vigelis.chatgpt.site>.
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
The dashboard attempts loopback access only from an HTTP loopback operator URL
carrying `?local=1`; the public replay never probes a visitor's workstation.

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

> One machine. Many agents. One clearance layer.
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
> Live demo: https://gatehold-buildweek.e-vigelis.chatgpt.site
> Source code: https://github.com/pakales/gatehold
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

**Primary Codex evidence:** `019f7221-2421-78e3-b12e-f6082da1ed87`

**Dated commit evidence:**
[deterministic clearance and owned cleanup](https://github.com/pakales/gatehold/commit/b10d8d578eac6b48c04c58d7dbb77442d6b27594),
[premium control deck](https://github.com/pakales/gatehold/commit/da8e5a0895789b7b50c54e7f90be3ba8417cee25),
and
[judge evidence and demo package](https://github.com/pakales/gatehold/commit/945175d99dec4d49193e237d841911fd79777406).
The public-link update is
[`ae268a5dfcc7240d59a55ffcad9d91553311ff04`](https://github.com/pakales/gatehold/commit/ae268a5dfcc7240d59a55ffcad9d91553311ff04).

**Last published validated baseline:**
[`b530fa173fa526bda0574c218fa700f6902bb00d`](https://github.com/pakales/gatehold/commit/b530fa173fa526bda0574c218fa700f6902bb00d)
— passed the complete public
[Gatehold CI gate](https://github.com/pakales/gatehold/actions/runs/29735811254).

**Final validated executable source:**
[`ba54c575ca510c2ec04bd372392c163fc10099b7`](https://github.com/pakales/gatehold/commit/ba54c575ca510c2ec04bd372392c163fc10099b7)

**Matching public CI run:**
[Gatehold CI #29749328675](https://github.com/pakales/gatehold/actions/runs/29749328675)
— passed the complete release contract and dependency audit on the exact
executable source revision.
