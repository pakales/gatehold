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
  assert.equal(
    response.headers.get("content-security-policy"),
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'",
  );
  assert.equal(
    response.headers.get("permissions-policy"),
    "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
  );
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");

  const html = await response.text();
  const normalized = html.replaceAll("<!-- -->", "");
  assert.match(
    normalized,
    /<title>Gatehold — Local clearance for parallel coding agents — GATEHOLD<\/title>/i,
  );
  assert.match(normalized, /GATEHOLD/);
  assert.match(normalized, /Every agent needs clearance\./);
  assert.match(
    normalized,
    /One machine\.[\s\S]*Many agents\.[\s\S]*One clearance layer\./,
  );
  assert.match(normalized, /Clearance decision/);
  assert.match(normalized, /Agent clearance lanes/);
  assert.match(normalized, /Decision trace/);
  assert.match(normalized, /Workstream key/);
  assert.match(normalized, /Capacity key/);
  assert.match(normalized, /Play 4-step demo/);
  assert.match(normalized, /Inspect repo evidence/);
  assert.match(
    normalized,
    /github\.com\/pakales\/gatehold#evidence-at-a-glance/,
  );
  assert.match(
    normalized,
    /Two keys to start\. Verified cleanup to release\./,
  );
  assert.match(normalized, /Deterministic policy grants clearance\./);
  assert.match(normalized, /GPT-5\.6 can only add a hold\./);
  assert.match(
    normalized,
    /REPLAY HOST METRICS · REPLAY SCENARIO/,
  );
  assert.match(
    normalized,
    /REPLAY ONLY · Host metrics, A–D lanes, and events are bounded demo data\./,
  );
  assert.match(normalized, /Local mode/);
  assert.match(normalized, /gatehold-og\.png/);
  assert.match(
    normalized,
    /<a href="https:\/\/ev1labs\.com\/"[^>]*>EV1 Labs<\/a>/,
  );
  assert.match(
    normalized,
    /<a href="https:\/\/ev1labs\.com\/labs\/build-week-2026\/"[^>]*>Build Week 2026 collection<\/a>/,
  );
  assert.match(normalized, /Built by/);
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
  assert.equal((dashboard.match(/mode: "no-cors"/g) ?? []).length, 0);
  assert.match(dashboard, /function isLocalOperatorSurface\(\): boolean/);
  assert.match(dashboard, /currentUrl\.protocol === "http:"/);
  assert.match(dashboard, /currentUrl\.searchParams\.get\("local"\) === "1"/);
  assert.match(
    dashboard,
    /if \(!isLocalOperatorSurface\(\)\) \{\s*setLocalSnapshot\(null\);\s*setLiveState\("blocked"\);\s*return;\s*\}/,
  );
  assert.match(
    dashboard,
    /health = await fetch\(`\$\{DAEMON_ORIGIN\}\/healthz`, \{\s*cache: "no-store",\s*headers: \{ Accept: "application\/json" \},\s*credentials: "omit",\s*signal: controller\.signal,\s*\}\);/,
  );
  assert.match(
    dashboard,
    /catch \{\s*setLocalSnapshot\(null\);\s*setLiveState\("offline"\);\s*return;\s*\}/,
  );
  assert.match(
    dashboard,
    /if \(!health\.ok\) \{\s*setLocalSnapshot\(null\);\s*setLiveState\("offline"\);\s*return;\s*\}/,
  );
  assert.doesNotMatch(dashboard, /\bbody\s*:/);
  assert.match(dashboard, /LOCAL ACCESS BLOCKED · REPLAY SCENARIO/);
  assert.match(
    dashboard,
    /Use the documented loopback operator URL and allowlist its exact origin\./,
  );
  assert.match(dashboard, /request\.semantic_hold/);
  assert.match(dashboard, /lease\.released/);
  assert.match(dashboard, /addEventListener\(eventKind/);
  assert.match(dashboard, /const DEMO_STEP_MS = 10_000;/);
  assert.match(dashboard, /aria-pressed=\{isRunning\}/);
  assert.match(dashboard, /Pause demo/);
  assert.match(dashboard, /Resume demo/);
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
  assert.match(dashboard, /Agent clearance lanes/);
  assert.match(dashboard, /Decision trace/);
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
  assert.match(css, /\.decision-deck\s*\{[\s\S]*?order:\s*1;/);
  assert.match(css, /\.scenario-console\s*\{[\s\S]*?order:\s*2;/);
  assert.match(css, /\.intro\s*\{[\s\S]*?order:\s*3;/);
  assert.doesNotMatch(css, /letter-spacing:\s*-/);
  assert.doesNotMatch(dashboard, /Clearance radar|radar-stage|HOST CORE/);
  const header = dashboard.match(/<header[\s\S]*?<\/header>/)?.[0] ?? "";
  assert.match(header, /button-primary/);
  assert.match(header, /button-quiet/);
  assert.match(header, /Inspect repo evidence/);
  assert.doesNotMatch(header, /connectLocal/);
  assert.match(
    replayFixture,
    /Exact workstream and scope checks see no match\.[\s\S]*GPT-5\.6 detects the semantic overlap and adds a HOLD; it can never grant clearance\./,
  );
  assert.match(
    replayFixture,
    /Gatehold owns the exact synthetic sim-02 boot; any prebooted human simulator remains untouched\./,
  );
  assert.match(replayFixture, /mobile\/release · exact owned sim-02/);
  assert.match(page, /GateholdDashboard/);
  assert.match(layout, /GATEHOLD — Local clearance for coding agents/);
  assert.match(layout, /authors:\s*\[\{ name: "EV1 Labs", url: "https:\/\/ev1labs\.com\/" \}\]/);
  assert.match(layout, /creator: "EV1 Labs"/);
  assert.match(layout, /metadataBase: new URL\("https:\/\/gatehold-buildweek\.e-vigelis\.chatgpt\.site"\)/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /:focus-visible/);
  assert.doesNotMatch(css, /url\(["']?https?:\/\//i);
});
