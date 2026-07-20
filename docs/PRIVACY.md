# Gatehold Privacy

## Privacy posture

Gatehold is local-first. Deterministic admission, queueing, receipts, and lease
state run on the developer's workstation and do not require an OpenAI API key.

The optional GPT-5.6 adviser is deliberately narrow: it receives bounded claim
metadata to decide whether an additional semantic-overlap hold is warranted.
It does not receive source files, diffs, full conversation history, or command
arguments from Gatehold.

## Data map

| Data class | Example | Stored locally | Sent to OpenAI | Included in public replay |
| --- | --- | ---: | ---: | ---: |
| Lease identity | request ID, owner ID, heartbeat token | Yes, bounded | No | Synthetic only |
| Work claim | normalized workstream, bounded scope summary | Yes, bounded | Optional bounded subset | Synthetic only |
| Runtime resource | logical port/profile/simulator ID | Yes | Only if required by bounded comparison | Synthetic only |
| Runtime provenance | PID/PGID/session, process-create time, host boot time, ownership digests | Yes, bounded | No | Synthetic only |
| Simulator provenance | exact UDID, external/boot-intent/owned/cleaned state, bounded lifecycle timestamps | Yes, bounded | No | Synthetic only |
| Managed exit result | integer child exit code in a temporary mode-`0600` file | Ephemeral local only | No | No |
| Host telemetry | CPU/memory pressure summary | Bounded current/receipt state | No | Synthetic only |
| Source code and diffs | file contents, patches | No | No | No |
| Conversation content | full prompts or chat logs | No | No | No |
| Command arguments | local command and flags | No persistence | No | No |
| OpenAI API key | `OPENAI_API_KEY` | Environment only | Sent by official SDK for authentication | Never |
| Model result | bounded hold/no-hold schema | Bounded decision metadata | Response originates from OpenAI | Synthetic only |

## Local persistence

Gatehold uses SQLite for operational lease recovery and queue consistency. The
default state root is `~/.gatehold/` (mode `0700`), the database is
`~/.gatehold/gatehold.sqlite3` (mode `0600`), the local read token is
`~/.gatehold/daemon.token` (mode `0600`), and logical browser-profile
directories live under `~/.gatehold/browser-profiles/` (mode `0700`). These
paths are local and ignored by git.

The database contains bounded state required for claims, TTL, heartbeat,
queueing, resource ownership, cleanup recovery, and receipts. A managed run
also records bounded process provenance: PID, process-group and session IDs,
process-create and host-boot times, plus one-way ownership digests. It never
stores the raw ownership nonce. For a configured simulator it stores only the
exact UDID, external/boot-intent/owned/cleaned state, and bounded lifecycle
timestamps needed to prove whether shutdown is authorized. A simulator found
already booted is external and never touched; unresolved boot intent remains
quarantined. The supervisor writes only the integer child exit code under
`~/.gatehold/runtime-results/`; that private result is consumed and removed
during cleanup.

Gatehold does not intentionally persist:

- source code or file contents;
- diffs or patches;
- full prompts or conversations;
- environment-variable values;
- passwords, API keys, cookies, or identity tokens;
- child-process command arguments;
- full process command lines.

Deleting the local Gatehold state directory removes the local operational
history. Do this only while no controlled tasks are active.

## OpenAI API use

When `OPENAI_API_KEY` is configured, the local server may call the OpenAI
Responses API for semantic-overlap advice.

The implementation contract requires:

- `store=False`;
- an explicit GPT-5.6 model identifier;
- bounded input metadata;
- strict structured output;
- timeout and output-size limits;
- no automatic authority escalation;
- deterministic fallback on missing credentials, refusal, timeout, malformed
  output, or service failure.

OpenAI service handling is also governed by the applicable OpenAI API terms and
data controls. Operators should avoid putting sensitive client or personal
information into workstream names and scope summaries even though Gatehold
bounds them.

## API key handling

- Keep `OPENAI_API_KEY` in `.env.local` or another server-only environment.
- Never use a `NEXT_PUBLIC_` prefix.
- Never paste the key into a browser field, screenshot, demo, issue, fixture,
  receipt, log, or commit.
- The local installer never loads `.env.local` into its wrapper, and the
  persistent daemon explicitly drops `OPENAI_API_KEY` from its environment.
- Never include `.env.local` in a support bundle.
- Rotate the key if exposure is suspected.

The public replay and deterministic local path work without the key.

## Browser behavior

Replay mode consumes only synthetic data and cannot read a visitor's
workstation.

Live-local mode connects to the read-only loopback Gatehold service from the
same machine. A browser origin must be explicitly and exactly allowlisted with
`--dashboard-origin` or `GATEHOLD_DASHBOARD_ORIGINS`; a loopback origin is not
trusted merely because it is local. Non-loopback browser origins must use
HTTPS. CORS echoes only the configured exact origin, without wildcards or
credentials. Origin-less local clients reading `/v1/*` must send the bearer
token from the mode-`0600` token file. The token must never be stored in Sites,
a URL, query string, browser local storage, or fixture.

Loopback and origin checks reduce exposure; they are not an OS-user
authentication boundary. Do not change the bind address without an explicit
auth, origin, privacy, and threat-model redesign.

## Logs and receipts

Logs and receipts must prefer stable IDs and reason codes over private content.
They must not contain:

- secrets or environment dumps;
- raw model prompts or unrestricted model prose;
- source text, diffs, or command arguments;
- browser cookies or identity headers;
- full process command lines.

Model fallback must be visible as a status, not hidden as a successful live
analysis. Estimated savings must be labeled as estimates.

## Demo and fixture privacy

Everything under `fixtures/demo/` must be synthetic. Before release, search for
private home paths, usernames, hostnames, repository names, emails, tokens,
phone numbers, and live task content.

The demo video must not show:

- API keys or environment files;
- private source repositories or browser tabs;
- personal notifications or user data;
- terminal history containing credentials;
- identity headers, cookies, or access tokens.

## Reporting a privacy issue

Do not publish sensitive evidence in a public issue. Provide a minimal
reproduction with synthetic data and rotate any potentially exposed credential
before sharing details.
