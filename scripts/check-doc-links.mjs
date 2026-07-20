#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";

const output = execFileSync(
  "git",
  ["ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
  { encoding: "utf8" },
);

const markdownFiles = output.split("\0").filter(Boolean);
const failures = [];
const linkPattern = /\[[^\]]*]\(([^)]+)\)/g;

for (const file of markdownFiles) {
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(linkPattern)) {
    let target = match[1].trim();
    if (target.startsWith("<") && target.endsWith(">")) {
      target = target.slice(1, -1);
    }
    target = target.split(/\s+["']/u, 1)[0];

    if (
      target === "" ||
      target.startsWith("#") ||
      /^(?:https?:|mailto:|tel:)/u.test(target)
    ) {
      continue;
    }

    const [pathPart] = target.split("#", 1);
    let decodedPath;
    try {
      decodedPath = decodeURIComponent(pathPart);
    } catch {
      failures.push(`${file}: invalid URL encoding in ${target}`);
      continue;
    }

    const candidate = resolve(dirname(file), decodedPath);
    if (!existsSync(candidate)) {
      failures.push(`${file}: missing ${decodedPath}`);
      continue;
    }

    if (decodedPath.endsWith("/") && !statSync(candidate).isDirectory()) {
      failures.push(`${file}: expected directory ${decodedPath}`);
    }
  }
}

if (failures.length > 0) {
  console.error("Documentation link check failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Documentation links passed (${markdownFiles.length} files inspected).`);
