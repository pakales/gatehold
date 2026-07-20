#!/usr/bin/env node

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const cardsDir = path.join(root, "media", "cards");
await mkdir(cardsDir, { recursive: true });

const escapeXml = (value) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const cards = [
  {
    filename: "owned-cleanup.svg",
    eyebrow: "OWNERSHIP CONTINUES THROUGH CLEANUP",
    title: "Finish clean. Touch only what you own.",
    subtitle:
      "Exit · interruption · lost heartbeat · daemon recovery",
    accent: "#a8f5ce",
    items: [
      ["PROCESS GROUP", "TERM → bounded wait → KILL"],
      ["DEV SERVER + PORT", "Released with owner provenance"],
      ["BROWSER PROFILE", "Dedicated lane removed safely"],
      ["SIMULATOR", "Exact UDID + boot proof required"]
    ],
    footer: "Proven ownership only · ambiguity quarantines the lane"
  },
  {
    filename: "codex-client.svg",
    eyebrow: "CODEX OPERATES THROUGH THE GATE",
    title: "Claim → run → heartbeat → release",
    subtitle: "$ gatehold run --heavy -- npm test",
    accent: "#a8f5ce",
    items: [
      ["01 · WORKSTREAM", "One active owner"],
      ["02 · CAPACITY", "Host headroom or FIFO wait"],
      ["03 · RUNTIME", "Owned process group and named resources"],
      ["04 · COMPLETION", "Release plus verified cleanup"]
    ],
    footer: "No bypass-on-error path"
  },
  {
    filename: "privacy-boundary.svg",
    eyebrow: "HONEST PUBLIC DEMO · PRIVATE LOCAL CONTROL",
    title: "Useful offline. Private by design.",
    subtitle: "Replay and Live local are visibly separate modes",
    accent: "#f6bd69",
    items: [
      ["PUBLIC REPLAY", "Bounded synthetic data"],
      ["LIVE LOCAL", "Read-only loopback daemon"],
      ["DETERMINISTIC CORE", "Works without an API key"],
      ["GPT-5.6", "Sanitized metadata · store false · hold only"]
    ],
    footer: "No prompts, code, diffs, commands, or secrets in receipts"
  }
];

function renderCard(card) {
  const rows = card.items
    .map(
      ([label, value], index) => `<g transform="translate(0 ${index * 116})">
        <rect width="1448" height="92" rx="18" fill="#0d1311" stroke="#26322d"/>
        <circle cx="38" cy="46" r="7" fill="${card.accent}"/>
        <text x="65" y="39" fill="#718078" font-family="SFMono-Regular, Menlo, monospace" font-size="18" letter-spacing="2">${escapeXml(label)}</text>
        <text x="65" y="67" fill="#edf5f0" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif" font-size="26" font-weight="650">${escapeXml(value)}</text>
      </g>`
    )
    .join("\n      ");

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <defs>
    <radialGradient id="glow" cx="50%" cy="44%" r="62%">
      <stop offset="0%" stop-color="${card.accent}" stop-opacity="0.11"/>
      <stop offset="100%" stop-color="#070b09" stop-opacity="0"/>
    </radialGradient>
    <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
      <path d="M48 0H0V48" fill="none" stroke="#17201c" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="1920" height="1080" fill="#070b09"/>
  <rect width="1920" height="1080" fill="url(#grid)" opacity="0.56"/>
  <rect width="1920" height="1080" fill="url(#glow)"/>
  <g transform="translate(120 78)">
    <g>
      <rect width="26" height="26" rx="8" fill="none" stroke="${card.accent}" stroke-width="3"/>
      <path d="M7 13h12M13 7v12" stroke="${card.accent}" stroke-width="2"/>
      <text x="43" y="21" fill="#edf5f0" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif" font-size="27" font-weight="760" letter-spacing="4">GATEHOLD</text>
      <text x="1278" y="20" fill="#718078" font-family="SFMono-Regular, Menlo, monospace" font-size="17" letter-spacing="2">EVERY AGENT NEEDS CLEARANCE</text>
    </g>
    <line x1="0" y1="55" x2="1680" y2="55" stroke="#26322d"/>
    <text x="0" y="125" fill="${card.accent}" font-family="SFMono-Regular, Menlo, monospace" font-size="17" letter-spacing="3">${escapeXml(card.eyebrow)}</text>
    <text x="0" y="204" fill="#f2f7f4" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif" font-size="58" font-weight="720">${escapeXml(card.title)}</text>
    <text x="0" y="255" fill="#93a299" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif" font-size="25">${escapeXml(card.subtitle)}</text>
    <g transform="translate(0 316)">
      ${rows}
    </g>
    <g transform="translate(0 826)">
      <rect width="1448" height="72" rx="18" fill="${card.accent}" fill-opacity="0.09" stroke="${card.accent}" stroke-opacity="0.38"/>
      <text x="30" y="46" fill="${card.accent}" font-family="SFMono-Regular, Menlo, monospace" font-size="19" letter-spacing="1.5">${escapeXml(card.footer)}</text>
    </g>
  </g>
</svg>`;
}

for (const card of cards) {
  await writeFile(path.join(cardsDir, card.filename), renderCard(card));
}

process.stdout.write(`${cards.length} Gatehold cards rendered\n`);
