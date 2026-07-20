# Gatehold Competition Checklist

## Current official gate

Verified against the
[OpenAI Build Week official rules](https://openai.devpost.com/rules) on
2026-07-20.

- **Category:** Developer Tools.
- **Submission deadline:** 2026-07-21 17:00 PDT / 2026-07-22 03:00 EEST.
- **Video:** clear demo with audible explanation of Codex and GPT-5.6, under
  three minutes, publicly visible on YouTube.
- **Repository:** URL available for judging/testing with relevant license.
- **README:** install, supported platforms, judge test route, Codex
  collaboration, human decisions, and GPT-5.6 contribution.
- **Codex evidence:** `/feedback` session ID for the thread where most core
  functionality was built.
- **Testing:** working site/demo/test build free and unrestricted through the
  judging period.
- **Language:** English submission materials.
- **Existing work:** clearly separate prior work from competition-period work
  with dated Codex/commit evidence.
- **Multiple submissions:** each entry must be unique and substantially
  different.

The official rules and Devpost site override this checklist.

## P0 blockers — must be real, public, and signed-out tested

- [x] Record the production demo URL in `docs/SUBMISSION.md`.
- [x] Record the public repository URL.
- [x] Record the public YouTube URL.
- [x] Record the real Codex `/feedback` session ID.
- [x] Link the dated competition-period commits.
- [x] Record the final validated source revision.
- [x] Confirm no submission placeholder remains in public or submitted copy.
- [ ] Confirm public demo opens signed out in a private browser window.
- [ ] Confirm public repository opens signed out and includes MIT `LICENSE`.
- [x] Confirm YouTube visibility is **Public**, not Unlisted or Private.
- [x] Confirm video runtime is under 3:00 and audio is clear.
- [ ] Confirm the Devpost form is actually submitted, not only saved as draft.

## Product readiness

- [ ] `npm run verify` passes on the final commit.
- [x] `uv run gatehold init` succeeds from a fresh state directory.
- [x] `uv run gatehold demo` emits its documented synthetic grant/hold baseline
  without a key.
- [x] Daemon binds to `127.0.0.1`.
- [x] `GET /healthz` is loopback-Host-only and secret-free; `/v1/snapshot`
      and `/v1/events` additionally require bearer auth or an exact allowlisted
      dashboard origin.
- [x] `GET /v1/events` is read-only SSE and does not leak private values.
- [x] Concurrent workstream claims produce one owner.
- [x] Named runtime resources remain exclusive.
- [x] Heavy work queues deterministically under capacity pressure.
- [x] TTL, heartbeat token, release, and expiry paths work.
- [x] A held/waiting task cannot start its controlled command.
- [x] HTTP cannot execute arbitrary commands.
- [x] CLI child execution uses `shell=False`.
- [x] Missing/failed/invalid GPT-5.6 cannot weaken local policy.
- [x] Model output cannot grant or restore clearance.
- [x] Estimates are visibly labeled.
- [x] Gatehold does not kill unrelated processes.

## Public replay and local-live honesty

- [ ] Every public demo screen shows **REPLAY**.
- [ ] Replay fixture contains synthetic data only.
- [ ] Public site works without localhost, credentials, or API key.
- [ ] Live-local mode never implies it can read a remote visitor's workstation.
- [ ] Disconnected live-local state is honest and usable.
- [ ] Replay scenes match `docs/DEMO-SCRIPT.md`.
- [ ] Screenshots and video preserve the mode label.

## Privacy and security

- [x] `.env.local`, SQLite state, logs, outputs, and runtime lanes are ignored.
- [x] No `OPENAI_API_KEY`, token, cookie, identity header, or secret is in git.
- [x] No secret uses a `NEXT_PUBLIC_` prefix.
- [x] OpenAI requests use `store=False`.
- [x] No source, diff, full prompt, conversation, or command argument is
  persisted.
- [x] Fixtures contain no home paths, usernames, emails, hostnames, private repo
  names, or real task text.
- [x] Model and API inputs are bounded by strict schemas.
- [x] Demo capture shows no environment file, notification, private tab, or
  personal data.

## README and repository

- [x] Value is clear in the first screen.
- [x] macOS primary support and Linux best-effort scope are explicit.
- [x] Install, run, demo, and test commands match current `--help`.
- [x] Public replay and live-local distinction is explicit.
- [x] Codex builder/client role is explicit.
- [x] GPT-5.6 hold-only adviser role is explicit.
- [x] Competitive position avoids “first,” “only,” and guarantee language.
- [x] Pre-existing-work disclosure names reused concepts and says private code
  was not copied.
- [x] Build Week evidence is dated and linked.
- [x] License is present and linked.
- [x] Internal/private repositories are not linked or published.
- [x] All Markdown links resolve.
- [x] Replay JSON validates.

## Video

- [x] Follow `docs/DEMO-SCRIPT.md`.
- [x] Final cut is ideally 2:45–2:55.
- [x] Narration is English and audible.
- [x] Show a working product, not slides only.
- [x] Demonstrate collision, capacity waiting, isolated resources, and release.
- [x] Explain Codex separately from GPT-5.6.
- [x] Explain that deterministic code alone grants clearance.
- [x] State that public data is replay.
- [x] Use only owned/authorized visuals and audio.
- [x] Export at readable resolution and verify terminal text on mobile.
- [x] Watch the uploaded YouTube version from start to finish.

## Devpost copy

- [x] Name: Gatehold.
- [x] Tagline: “Local air-traffic control for coding agents.”
- [x] Category: Developer Tools.
- [ ] Paste and proofread `docs/SUBMISSION.md`.
- [x] Public URL, repo URL, YouTube URL, and session ID match this revision.
- [x] Testing instructions require no paid account or secret.
- [x] Pre-existing-work disclosure is included, not only in the repo.
- [x] Distinction from ProofLatch is included and accurate.
- [x] No claim says Gatehold is first, only, a sandbox, or a guarantee.
- [ ] Representative/entrant details are correct.

## Multiple-submission separation

- [x] Gatehold remains a pre-work local admission/lease product.
- [x] ProofLatch remains a post-check release-evidence decision product.
- [x] No shared product code.
- [x] Different inputs, state machines, outputs, demo stories, and judging value
  are explicit.
- [x] Each video and submission copy stands alone.

## Final evidence block

Complete this immediately before submission:

```text
Final commit SHA:
npm run verify result and timestamp:
Public demo URL:
Public repo URL:
Public YouTube URL and runtime:
Codex /feedback session ID:
Private-window demo check:
Private-window repo check:
Private-window YouTube check:
Devpost submitted timestamp:
Skipped checks:
Residual risk:
```

## Stop boundaries

Do not push, deploy, publish the repository, upload/set-public the video, or
submit/change the Devpost entry without explicit user approval at that external
action boundary.

After the deadline, do not assume the competition entry can be modified. Keep
the free judge route available through the judging period stated in the
official rules.
