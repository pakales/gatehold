#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const manifestPath = path.join(root, "media", "shot-manifest.json");
const outputDir = path.join(root, "media", "audio", "raw");
const apiKey = process.env.OPENAI_API_KEY;
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const shotFlagIndex = process.argv.indexOf("--shot");
const requestedShot =
  shotFlagIndex >= 0
    ? process.argv[shotFlagIndex + 1]
    : process.argv.find((argument) => argument.startsWith("--shot="))?.split("=")[1];

if (!apiKey) {
  throw new Error("OPENAI_API_KEY is unavailable in the process environment.");
}
if (shotFlagIndex >= 0 && !requestedShot) {
  throw new Error("--shot requires a shot ID.");
}

const selectedShots = requestedShot
  ? manifest.shots.filter((shot) => shot.id === requestedShot)
  : manifest.shots;
if (requestedShot && selectedShots.length === 0) {
  throw new Error(`Unknown shot ID: ${requestedShot}`);
}

await mkdir(outputDir, { recursive: true });

const instructions = [
  "Speak in natural American English for a premium developer-product demo.",
  "Sound calm, assured, warm, intelligent, and conversational.",
  "Never sound theatrical, salesy, breathy, robotic, or like an announcer.",
  "Use subtle sentence-level intonation, clean technical diction, and restrained emotion.",
  "Pronounce Gatehold as 'Gate Hold', GPT-5.6 as 'G P T five point six', Codex as 'Co-dex', FIFO as 'first in, first out', and TTL as 'time to live'.",
  "Do not add, remove, paraphrase, repeat, or comment on any words.",
  "Do not add interjections, music, or sound effects."
].join(" ");

async function synthesize(shot, attempt = 1) {
  const response = await fetch("https://api.openai.com/v1/audio/speech", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: manifest.voice.model,
      voice: manifest.voice.voice,
      input: shot.narration,
      instructions: `${instructions} Finish comfortably within approximately ${Math.max(3, shot.durationSeconds - 1).toFixed(1)} seconds.`,
      response_format: "wav",
      speed: 1
    })
  });

  if (!response.ok) {
    const safeMessage = `HTTP ${response.status}`;
    if (attempt < 3 && (response.status === 429 || response.status >= 500)) {
      await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
      return synthesize(shot, attempt + 1);
    }
    throw new Error(`TTS failed for ${shot.id}: ${safeMessage}`);
  }

  const audio = Buffer.from(await response.arrayBuffer());
  const output = path.join(outputDir, `${shot.id}.wav`);
  await writeFile(output, audio);
  return {
    id: shot.id,
    model: manifest.voice.model,
    voice: manifest.voice.voice,
    output: path.relative(root, output)
  };
}

const results = [];
for (const shot of selectedShots) {
  process.stdout.write(`Generating ${shot.id}... `);
  results.push(await synthesize(shot));
  process.stdout.write("done\n");
}

const generationPath = path.join(outputDir, "generation.json");
let previousResults = [];
try {
  const previous = JSON.parse(await readFile(generationPath, "utf8"));
  previousResults = Array.isArray(previous.results) ? previous.results : [];
} catch {
  // A missing or invalid prior manifest is replaced with the current run.
}
const merged = new Map(previousResults.map((result) => [result.id, result]));
for (const result of results) {
  merged.set(result.id, result);
}
const orderedResults = manifest.shots
  .map((shot) => merged.get(shot.id))
  .filter(Boolean);

await writeFile(
  generationPath,
  `${JSON.stringify(
    {
      generatedAt: new Date().toISOString(),
      disclosure: manifest.voice.disclosure,
      results: orderedResults
    },
    null,
    2
  )}\n`
);

process.stdout.write(
  `${results.length} narration segment${results.length === 1 ? "" : "s"} generated\n`
);
