# Gatehold Engineering Contract

Gatehold is the local admission-control plane for parallel AI coding agents.
Every controlled task must receive workstream clearance and host-capacity
clearance before it runs.

## Product promise

- One owner per workstream.
- One isolated runtime lane per admitted task.
- Heavy work waits when the machine is under pressure.
- GPT-5.6 may detect overlap and raise a hold, but it can never override a
  deterministic conflict or grant clearance by itself.
- Gatehold waits; it never kills unrelated user processes.

## Non-negotiable invariants

- Bind the local daemon only to `127.0.0.1`.
- Treat all task descriptions, scopes, paths, process data, and model output as
  untrusted input.
- Never expose `OPENAI_API_KEY` to the browser, logs, receipts, fixtures, or
  committed files.
- Use `store=False` for OpenAI Responses API calls.
- Model failure, refusal, timeout, or invalid output must fall back to the
  deterministic local policy.
- Do not persist full prompts, source code, diffs, conversation content, or
  command arguments.
- Execute local commands only from the CLI with `shell=False`. The HTTP API
  must never accept an arbitrary command to execute.
- Tokenless browser reads require an exact configured dashboard origin;
  arbitrary loopback origins are not implicitly trusted.
- A lease must have a TTL, heartbeat token, owner identity, and explicit
  release/expiry path.
- A port, browser profile, or simulator lease can have one owner at a time.
- Finish paths clean only resources with durable Gatehold provenance. Ambiguous
  ownership is quarantined with zero guessed signals or deletions.
- Cleanup-pending and quarantined leases retain workstream, capacity, and
  resource authority until cleanup is positively verified.
- Simulator lifecycle is exact-UDID and provenance-bound: a simulator already
  booted before Gatehold inspects it is external and must never be touched.
- Gatehold persists boot intent before booting, marks ownership only after the
  exact UDID is positively confirmed booted, and shuts down only that exact
  owned simulator. Ambiguous boot intent is quarantined with zero guessed
  shutdown.
- Receipts must label estimated savings as estimates.
- The public demo must clearly distinguish replay data from live local state.
- Gatehold is a cooperative workstation governor, not a security sandbox,
  kernel cgroup, Mac cleaner, or guarantee against unmanaged processes.

## Repository map

- `src/gatehold/` — Python local daemon, admission engine, adapters, and CLI.
- `tests/core/` — deterministic, concurrency, privacy, API, and model-boundary
  tests.
- `app/` — Sites-compatible public dashboard and local dashboard client.
- `tests/web/` — rendered product and browser-facing contract tests.
- `fixtures/demo/` — bounded replay fixtures for the public judge path.
- `skills/gatehold/` — Codex skill that claims and releases Gatehold lanes.
- `docs/` — architecture, privacy, threat model, testing, demo, and submission
  evidence.

## Engineering defaults

- Python 3.12 with `uv`.
- Pydantic models at every external boundary.
- SQLite transactions for durable local leases and FIFO ordering.
- React 19, TypeScript, vinext, and OpenAI Sites for the dashboard.
- Keep the public web experience useful without requiring local host access.
- Prefer a small explicit state machine over framework-heavy orchestration.

## Validation

Before meaningful handoff, run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
npm run typecheck
npm run lint
npm test
```

`npm test` creates a clean production bundle before exercising the rendered
web contracts. Use `npm run verify` for the full local gate.

For UI work, also verify desktop and mobile layouts, keyboard use, visible
focus, reduced motion, and no browser console errors.

## Publication boundary

Do not push, deploy, publish, upload a video, or submit Devpost without the
user's explicit approval at that external-action boundary. Never publish the
private workstation source repositories; only this generalized clean repo may
become public.
