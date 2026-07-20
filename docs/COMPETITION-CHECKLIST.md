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
- [ ] `uv run gatehold init` succeeds from a fresh state directory.
- [ ] `uv run gatehold demo` emits its documented synthetic grant/hold baseline
  without a key.
- [ ] Daemon binds to `127.0.0.1`.
- [ ] `GET /healthz` is loopback-Host-only and secret-free; `/v1/snapshot`
      and `/v1/events` additionally require bearer auth or an exact allowlisted
      dashboard origin.
- [ ] `GET /v1/events` is read-only SSE and does not leak private values.
- [ ] Concurrent workstream claims produce one owner.
- [ ] Named runtime resources remain exclusive.
- [ ] Heavy work queues deterministically under capacity pressure.
- [ ] TTL, heartbeat token, release, and expiry paths work.
- [ ] A held/waiting task cannot start its controlled command.
- [ ] HTTP cannot execute arbitrary commands.
- [ ] CLI child execution uses `shell=False`.
- [ ] Missing/failed/invalid GPT-5.6 cannot weaken local policy.
- [ ] Model output cannot grant or restore clearance.
- [ ] Estimates are visibly labeled.
- [ ] Gatehold does not kill unrelated processes.

## Public replay and local-live honesty

- [ ] Every public demo screen shows **REPLAY**.
- [ ] Replay fixture contains synthetic data only.
- [ ] Public site works without localhost, credentials, or API key.
- [ ] Live-local mode never implies it can read a remote visitor's workstation.
- [ ] Disconnected live-local state is honest and usable.
- [ ] Replay scenes match `docs/DEMO-SCRIPT.md`.
- [ ] Screenshots and video preserve the mode label.

## Privacy and security

- [ ] `.env.local`, SQLite state, logs, outputs, and runtime lanes are ignored.
- [ ] No `OPENAI_API_KEY`, token, cookie, identity header, or secret is in git.
- [ ] No secret uses a `NEXT_PUBLIC_` prefix.
- [ ] OpenAI requests use `store=False`.
- [ ] No source, diff, full prompt, conversation, or command argument is
  persisted.
- [ ] Fixtures contain no home paths, usernames, emails, hostnames, private repo
  names, or real task text.
- [ ] Model and API inputs are bounded by strict schemas.
- [ ] Demo capture shows no environment file, notification, private tab, or
  personal data.

## README and repository

- [ ] Value is clear in the first screen.
- [ ] macOS primary support and Linux best-effort scope are explicit.
- [ ] Install, run, demo, and test commands match current `--help`.
- [ ] Public replay and live-local distinction is explicit.
- [ ] Codex builder/client role is explicit.
- [ ] GPT-5.6 hold-only adviser role is explicit.
- [ ] Competitive position avoids “first,” “only,” and guarantee language.
- [ ] Pre-existing-work disclosure names reused concepts and says private code
  was not copied.
- [ ] Build Week evidence is dated and linked.
- [ ] License is present and linked.
- [ ] Internal/private repositories are not linked or published.
- [ ] All Markdown links resolve.
- [ ] Replay JSON validates.

## Video

- [ ] Follow `docs/DEMO-SCRIPT.md`.
- [ ] Final cut is ideally 2:45–2:55.
- [ ] Narration is English and audible.
- [ ] Show a working product, not slides only.
- [ ] Demonstrate collision, capacity waiting, isolated resources, and release.
- [ ] Explain Codex separately from GPT-5.6.
- [ ] Explain that deterministic code alone grants clearance.
- [ ] State that public data is replay.
- [ ] Use only owned/authorized visuals and audio.
- [ ] Export at readable resolution and verify terminal text on mobile.
- [ ] Watch the uploaded YouTube version from start to finish.

## Devpost copy

- [ ] Name: Gatehold.
- [ ] Tagline: “Local air-traffic control for coding agents.”
- [ ] Category: Developer Tools.
- [ ] Paste and proofread `docs/SUBMISSION.md`.
- [ ] Public URL, repo URL, YouTube URL, and session ID match this revision.
- [ ] Testing instructions require no paid account or secret.
- [ ] Pre-existing-work disclosure is included, not only in the repo.
- [ ] Distinction from ProofLatch is included and accurate.
- [ ] No claim says Gatehold is first, only, a sandbox, or a guarantee.
- [ ] Representative/entrant details are correct.

## Multiple-submission separation

- [ ] Gatehold remains a pre-work local admission/lease product.
- [ ] ProofLatch remains a post-check release-evidence decision product.
- [ ] No shared product code.
- [ ] Different inputs, state machines, outputs, demo stories, and judging value
  are explicit.
- [ ] Each video and submission copy stands alone.

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
