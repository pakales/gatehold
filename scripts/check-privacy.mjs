#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const output = execFileSync(
  "git",
  ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
  { encoding: "utf8" },
);

const files = output.split("\0").filter(Boolean);
const checks = [
  {
    label: "OpenAI API key",
    pattern: /sk-(?!example|placeholder)[A-Za-z0-9_-]{20,}/,
  },
  {
    label: "non-empty OPENAI_API_KEY assignment",
    pattern:
      /^(?:export[ \t]+)?OPENAI_API_KEY[ \t]*=[ \t]*["']?(?!<?(?:redacted|example|placeholder)>?)[^\s"'#]+/im,
  },
  {
    label: "private macOS user path",
    pattern: /\/Users\/vigelis(?:\/|\b)/,
  },
  {
    label: "OpenAI organization id",
    pattern: /\borg-[A-Za-z0-9]{15,}\b/,
  },
  {
    label: "OpenAI project id",
    pattern: /\bproj[_-][A-Za-z0-9]{15,}\b/,
  },
  {
    label: "personal Gmail address",
    pattern: /\b[A-Z0-9._%+-]+@gmail\.com\b/i,
  },
];

const failures = [];

for (const file of files) {
  let content;
  try {
    content = readFileSync(file);
  } catch {
    continue;
  }

  if (content.includes(0)) {
    continue;
  }

  const text = content.toString("utf8");
  for (const check of checks) {
    if (check.pattern.test(text)) {
      failures.push(`${file}: ${check.label}`);
    }
  }
}

if (failures.length > 0) {
  console.error("Privacy check failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Privacy check passed (${files.length} files inspected).`);
