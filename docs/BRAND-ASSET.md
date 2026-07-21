# Gatehold Open Graph Asset

`public/gatehold-og.png` is a 1200×630 original raster asset generated with the
built-in OpenAI image-generation tool, then resized locally for social-card
delivery. It contains no personal author or creator metadata.

## Final prompt

```text
Use case: ads-marketing
Asset type: Open Graph / Devpost hero image for a premium developer tool, wide 1.91:1 composition
Primary request: Create an arresting cinematic product-brand visual for GATEHOLD, a local air-traffic-control system for parallel AI coding agents.
Scene/backdrop: near-black graphite command surface, subtle technical grid, one luminous circular host-core radar in the center, three clean agent trajectories approaching it; one trajectory mint-cleared, one amber-held for capacity, one coral-red semantic collision stopped safely before the core.
Style/medium: ultra-premium futuristic industrial UI illustration, restrained and believable, precision engineering, Apple-level polish, not a screenshot, not generic sci-fi.
Composition/framing: wide horizontal banner; radar/core slightly right of center; generous dark negative space on the left for the title; crisp visual hierarchy readable at thumbnail size.
Lighting/mood: controlled low-key glow, quiet authority, safety and coordination rather than danger.
Color palette: graphite black, brushed chrome, mint green #9FF2C7, amber #E8B85C, coral #FF7A72; no blue-purple cyberpunk palette.
Text (verbatim): "GATEHOLD" and below it "EVERY AGENT NEEDS CLEARANCE."
Typography: uppercase geometric sans, widely tracked, exact spelling, left aligned, bright warm white.
Constraints: only the two exact text lines; trajectories must remain visibly separate; the coral line must stop before the core; no people, no robots, no aircraft, no logos from other brands, no code text, no dashboard windows, no watermark.
Avoid: visual clutter, neon overload, gaming aesthetic, stock 3D render, illegible tiny labels, misspelled text.
```

The generated text and clearance-path semantics were visually inspected after
resizing. The committed file's PNG signature and dimensions are also enforced
by `tests/web/rendered-html.test.mjs`.

## Operational surface boundary

The cinematic Open Graph artwork is promotional media, not the dashboard
layout. The live product surface deliberately avoids a radar backdrop,
ambient grid, HUD decoration, and repeated studio watermarks. Its first
viewport is the working clearance system itself: current verdict, two
authoritative keys, one primary replay control, and the bounded replay/live
source boundary.

Gatehold remains the dominant identity. The header carries one small
`AN EV1 LABS BUILD` publisher link using the canonical EV1 mark, while the
footer keeps one plain Build Week collection link.
