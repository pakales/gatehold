# Gatehold competition media

This directory contains deterministic local competition assets. Nothing in
this directory is uploaded or published automatically.

## Build

```bash
uv run --env-file .env.local node scripts/video/generate-tts.mjs
scripts/video/build-demo.sh
scripts/video/qa-demo.sh
```

To regenerate one approved narration segment without spending credits on the
others, pass its manifest ID:

```bash
uv run --env-file .env.local node scripts/video/generate-tts.mjs --shot S06
```

The narration uses the user-approved OpenAI `marin` voice with
`gpt-4o-mini-tts-2025-12-15`. The final YouTube description must retain the
AI-voice disclosure from `shot-manifest.json`.

The four dashboard stills are exact 1920×1080 captures of the local Gatehold
replay. The supporting cards are rendered deterministically from exact copy;
no generated claims or data are introduced.

The opening uses `media/cards/title-safe.svg`, a deterministic 1920×1080 frame
around the approved brand asset. Its slower bounded push-in keeps the wordmark
and tagline inside the conservative 10% title-safe area throughout S01.

`media/cards/devpost-cover.jpg` is the same approved title-safe frame exported
at Devpost's recommended 3:2 gallery ratio, with no new claims or content.
