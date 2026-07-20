#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

if (!process.env.OPENAI_API_KEY) {
  console.error(
    "OPENAI_API_KEY is unavailable. Run with: uv run --env-file .env.local node scripts/live-model-smoke.mjs",
  );
  process.exit(2);
}

const stateDir = mkdtempSync(join(tmpdir(), "gatehold-live-model-"));
const leases = [];

function gatehold(args, allowedExitCodes) {
  const result = spawnSync(
    "uv",
    ["run", "gatehold", "--state-dir", stateDir, ...args],
    {
      cwd: process.cwd(),
      encoding: "utf8",
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  if (result.error || !allowedExitCodes.includes(result.status ?? -1)) {
    throw new Error(
      `Gatehold smoke command failed safely with exit ${result.status ?? "unknown"}`,
    );
  }

  try {
    return JSON.parse(result.stdout);
  } catch {
    throw new Error("Gatehold smoke command returned invalid JSON");
  }
}

function rememberLease(outcome, owner) {
  if (outcome?.lease?.lease_id && outcome.lease.heartbeat_token) {
    leases.push({
      leaseId: outcome.lease.lease_id,
      owner,
      token: outcome.lease.heartbeat_token,
    });
  }
}

try {
  const firstOwner = "gatehold-smoke-agent-a";
  const first = gatehold(
    [
      "claim",
      "--owner",
      firstOwner,
      "--workstream",
      "repair access token refresh retries",
      "--scope",
      "packages/auth/refresh",
      "--light",
      "--ttl",
      "300",
      "--summary",
      "Fix automatic access-token renewal after expiry before a request retries.",
    ],
    [0],
  );
  rememberLease(first, firstOwner);

  const secondOwner = "gatehold-smoke-agent-b";
  const second = gatehold(
    [
      "claim",
      "--owner",
      secondOwner,
      "--workstream",
      "harden session renewal after expiration",
      "--scope",
      "services/identity/session-renewal",
      "--light",
      "--ttl",
      "300",
      "--summary",
      "Prevent stale sessions by renewing expired access credentials before retry.",
    ],
    [0, 73],
  );
  rememberLease(second, secondOwner);

  const safeEvidence = {
    model: second.semantic?.model ?? null,
    decision: second.decision,
    semantic_verdict: second.semantic?.verdict ?? null,
    semantic_reason: second.semantic?.reason ?? null,
    semantic_confidence: second.semantic?.confidence ?? null,
    receipt_sha256: second.receipt?.receipt_sha256 ?? null,
    estimated_savings: second.receipt?.estimated_savings ?? null,
    deterministic_conflicts: second.conflicts?.length ?? 0,
    secret_values_printed: false,
  };
  console.log(JSON.stringify(safeEvidence, null, 2));

  if (
    second.decision !== "SEMANTIC_HOLD" ||
    second.semantic?.verdict !== "HOLD" ||
    second.semantic?.model !== "gpt-5.6-sol"
  ) {
    process.exitCode = 1;
  }
} finally {
  for (const lease of leases.reverse()) {
    spawnSync(
      "uv",
      [
        "run",
        "gatehold",
        "--state-dir",
        stateDir,
        "release",
        lease.leaseId,
        "--owner",
        lease.owner,
      ],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        env: {
          ...process.env,
          GATEHOLD_HEARTBEAT_TOKEN: lease.token,
        },
        stdio: "ignore",
      },
    );
  }
  rmSync(stateDir, { recursive: true, force: true });
}
