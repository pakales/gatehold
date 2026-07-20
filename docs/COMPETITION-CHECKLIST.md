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
- [ ] Record the final replacement public YouTube URL.
- [x] Record the real Codex `/feedback` session ID.
- [x] Link the dated competition-period commits.
- [ ] Record the final validated source revision and matching green CI run.
- [ ] Confirm no pending-release marker remains in public or submitted copy.
- [ ] Confirm the exact final public demo opens signed out in a private browser
      window.
- [x] Confirm public repository opens signed out and includes MIT `LICENSE`.
- [ ] Confirm the replacement YouTube video is **Public**, not Unlisted or
      Private.
- [x] Confirm the replacement local render is under 3:00 and audio is clear.
- [ ] Confirm the Devpost form is actually submitted, not only saved as draft.

## Product readiness

- [ ] `npm run verify` passes on the exact final commit and public CI.
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
- [x] Governed children receive a minimal environment; bounded `--pass-env`
  rejects credential and known runtime-injection names before admission.
- [x] Missing/failed/invalid GPT-5.6 cannot weaken local policy.
- [x] Model output cannot grant or restore clearance.
- [x] Estimates are visibly labeled.
- [x] Gatehold does not kill unrelated processes.

## Public replay and local-live honesty

- [x] Every public demo screen shows **REPLAY**.
- [x] Replay fixture contains synthetic data only.
- [x] Public site works without localhost, credentials, or API key.
- [x] Live-local mode never implies it can read a remote visitor's workstation.
- [x] Disconnected live-local state is honest and usable.
- [x] Replay scenes match `docs/DEMO-SCRIPT.md`.
- [x] Screenshots and video preserve the mode label.

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
- [x] Review the replacement local render and contact sheet from start to
      finish.
- [ ] Watch the uploaded replacement YouTube version from start to finish.

## Devpost copy

- [x] Name: Gatehold.
- [x] Tagline: “Local air-traffic control for coding agents.”
- [x] Category: Developer Tools.
- [ ] Paste and proofread `docs/SUBMISSION.md`.
- [ ] Public URL, repo URL, replacement YouTube URL, and session ID match the
      final revision.
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

Replace every pending field immediately before submission:

```text
Candidate state:
Local reviewed release candidate; final commit, push, merge, and public CI are
pending the explicit external-release approval boundary.

Local release gate:
PASS — 246 Python tests + 3 Node web tests, Ruff, Pyright, TypeScript, ESLint,
privacy/link checks, production build, dependency audit, CLI lifecycle smoke,
governed interruption cleanup, and bounded live GPT-5.6 smoke.

Replacement video QA:
PASS — 171.021333s; 1920x1080; H.264/yuv420p/30; AAC/48kHz/stereo;
-15.89 LUFS; -4.45 dBTP; exact 9-shot captions; 0 decode errors.
SHA-256:
b96573b39f32eb01cee855057ff6a5a5aabc75212aa06d0c85f481fb6ecb3c15

Current public baseline demo:
https://gatehold-buildweek.e-vigelis.chatgpt.site
Final candidate deployment: PENDING

Public repository:
https://github.com/pakales/gatehold

Replacement public YouTube video:
PENDING — do not submit the superseded https://youtu.be/QBdzI0hqTQY render

Codex /feedback session:
019f7221-2421-78e3-b12e-f6082da1ed87

Final validated executable source:
PENDING

Final GitHub Actions run:
PENDING

Final anonymous checks:
PENDING — exact Sites candidate, repository revision, replacement YouTube
playback, and Devpost links must all be checked signed out.

Devpost:
PENDING — not submitted.

Skipped:
No local source, build, dependency, installer, daemon, model, UI, media, or
privacy check was skipped. Exact public-release checks remain intentionally
pending until publication.

Residual risk:
Gatehold coordinates opt-in cooperative clients, not unmanaged processes.
vinext still emits an upstream Node punycode deprecation warning while the
build succeeds. GitHub branch protection, vulnerability alerts, final Sites
deployment, replacement YouTube publication, and Devpost submission remain
external release actions. The older public video must not be used in the final
Gatehold submission.
```

## Stop boundaries

Do not push, deploy, publish the repository, upload/set-public the video, or
submit/change the Devpost entry without explicit user approval at that external
action boundary.

After the deadline, do not assume the competition entry can be modified. Keep
the free judge route available through the judging period stated in the
official rules.
