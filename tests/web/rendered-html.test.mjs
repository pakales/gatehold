import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);

async function render() {
  const workerUrl = new URL("../../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Gatehold clearance deck", async () => {
  await access(new URL("dist/server/index.js", root));
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  const normalized = html.replaceAll("<!-- -->", "");
  assert.match(
    normalized,
    /<title>Local clearance for coding agents — GATEHOLD<\/title>/i,
  );
  assert.match(normalized, /GATEHOLD/);
  assert.match(normalized, /Every agent needs clearance\./);
  assert.match(
    normalized,
    /One machine\. Many agents\. One clearance layer\./,
  );
  assert.match(normalized, /Host Core/);
  assert.match(normalized, /Replay agent lanes/);
  assert.match(normalized, /Replay event rail/);
  assert.match(normalized, /Workstream key/);
  assert.match(normalized, /Capacity key/);
  assert.match(normalized, /Run collision demo/);
  assert.match(
    normalized,
    /REPLAY HOST METRICS · REPLAY SCENARIO/,
  );
  assert.match(
    normalized,
    /REPLAY ONLY · Host metrics, A–D lanes, and events are bounded demo data\./,
  );
  assert.match(normalized, /GPT-5\.6 safe boundary/);
  assert.match(normalized, /gatehold-og\.png/);
  assert.doesNotMatch(
    normalized,
    /Your site is taking shape|Building your site/,
  );
  assert.doesNotMatch(normalized, /react-loading-skeleton/);
});

test("ships a correctly sized Open Graph image", async () => {
  const image = await readFile(new URL("public/gatehold-og.png", root));
  assert.deepEqual(
    image.subarray(0, 8),
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
  );
  assert.equal(image.readUInt32BE(16), 1200);
  assert.equal(image.readUInt32BE(20), 630);
});

test("keeps local mode read-only, loopback-only, and secret-free", async () => {
  const [dashboard, page, layout, css, replayFixture] = await Promise.all([
    readFile(new URL("app/GateholdDashboard.tsx", root), "utf8"),
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
    readFile(new URL("fixtures/demo/gatehold-replay.json", root), "utf8"),
  ]);

  assert.match(dashboard, /http:\/\/127\.0\.0\.1:47820/);
  assert.match(dashboard, /\/healthz/);
  assert.match(dashboard, /\/v1\/snapshot/);
  assert.match(dashboard, /\/v1\/events/);
  assert.match(dashboard, /credentials:\s*"omit"/);
  assert.match(
    dashboard,
    /response\.status === 401 \|\| response\.status === 403/,
  );
  assert.match(
    dashboard,
    /health\.status === 401 \|\| health\.status === 403/,
  );
  assert.equal((dashboard.match(/connectLocal\(\)/g) ?? []).length, 1);
  assert.equal((dashboard.match(/mode: "no-cors"/g) ?? []).length, 1);
  assert.match(
    dashboard,
    /health = await fetch\(`\$\{DAEMON_ORIGIN\}\/healthz`, \{\s*cache: "no-store",\s*headers: \{ Accept: "application\/json" \},\s*credentials: "omit",\s*signal: controller\.signal,\s*\}\);/,
  );
  assert.match(
    dashboard,
    /catch \{\s*try \{\s*await fetch\(`\$\{DAEMON_ORIGIN\}\/healthz`, \{\s*method: "GET",\s*mode: "no-cors",\s*cache: "no-store",\s*credentials: "omit",\s*signal: controller\.signal,\s*\}\);[\s\S]*?setLiveState\("blocked"\);[\s\S]*?\}\s*return;/,
  );
  assert.match(
    dashboard,
    /if \(!health\.ok\) \{\s*setLocalSnapshot\(null\);\s*setLiveState\("offline"\);\s*return;\s*\}/,
  );
  assert.doesNotMatch(dashboard, /\bbody\s*:/);
  assert.match(dashboard, /LOCAL ACCESS BLOCKED · REPLAY SCENARIO/);
  assert.match(
    dashboard,
    /Grant browser local access and allowlist this exact origin\./,
  );
  assert.match(dashboard, /request\.semantic_hold/);
  assert.match(dashboard, /lease\.released/);
  assert.match(dashboard, /addEventListener\(eventKind/);
  assert.match(dashboard, /10_000/);
  assert.doesNotMatch(dashboard, /events\.onerror/);
  assert.doesNotMatch(
    dashboard,
    /OPENAI_API_KEY|NEXT_PUBLIC_|Authorization|localStorage|sessionStorage/i,
  );
  for (const id of [
    "scene-a-cleared",
    "scene-b-semantic-hold",
    "scene-c-capacity-hold",
    "scene-d-release",
  ]) {
    assert.match(dashboard, new RegExp(id));
  }
  assert.match(dashboard, /SEMANTIC HOLD/);
  assert.match(dashboard, /CAPACITY HOLD/);
  assert.match(dashboard, /never grants clearance or overrides/i);
  assert.match(dashboard, /LIVE HOST METRICS · REPLAY SCENARIO/);
  assert.match(
    dashboard,
    /Only host metrics and counts are live; A–D lanes and events remain replay\./,
  );
  assert.match(
    dashboard,
    /LIVE HOST METRICS · A–D lanes and events remain bounded replay data\./,
  );
  assert.match(dashboard, /Replay agent lanes/);
  assert.match(dashboard, /Replay event rail/);
  assert.match(
    dashboard,
    /Gatehold later cleans only an exact runtime it booted and confirmed; prebooted human simulators stay untouched\./,
  );
  assert.match(dashboard, /label: "Replay"/);
  assert.match(dashboard, /label: "Live"/);
  assert.match(dashboard, /label: "Blocked"/);
  assert.match(dashboard, /label: "Offline"/);
  assert.match(css, /\.mode-cluster small\s*\{\s*display:\s*none/);
  assert.match(css, /\.source-boundary-live/);
  assert.match(
    replayFixture,
    /Gatehold owns the exact synthetic sim-02 boot; any prebooted human simulator remains untouched\./,
  );
  assert.match(replayFixture, /mobile\/release · exact owned sim-02/);
  assert.match(page, /GateholdDashboard/);
  assert.match(layout, /GATEHOLD — Local clearance for coding agents/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /:focus-visible/);
  assert.doesNotMatch(css, /url\(["']?https?:\/\//i);
});
