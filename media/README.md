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
