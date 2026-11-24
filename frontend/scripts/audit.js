import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { evaluateAudit } from "./audit-policy.js";

function readJson(path) {
  return JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
}

function audit(args) {
  const result = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["audit", "--json", ...args], {
    encoding: "utf8", timeout: 120_000, maxBuffer: 10 * 1024 * 1024,
  });
  if (result.error || ![0, 1].includes(result.status)) {
    throw new Error(`npm audit failed: ${result.error?.message || result.stderr || result.status}`);
  }
  return JSON.parse(result.stdout);
}

try {
  const production = audit(["--omit=dev"]);
  const full = audit([]);
  console.log("Raw npm audit totals:", JSON.stringify(full.metadata?.vulnerabilities ?? {}));
  const result = evaluateAudit(full, production, readJson("../package-lock.json"), readJson("../audit-exceptions.json"));
  for (const exception of result.accepted) console.warn(`Temporary audit exception: ${exception}`);
  for (const finding of result.blocked) console.error(`Blocked audit finding: ${finding}`);
  if (result.blocked.length) process.exitCode = 1;
  else console.log("Audit passed: no production findings or unexcepted high/critical advisories.");
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
