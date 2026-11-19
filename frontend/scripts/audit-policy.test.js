import test from "node:test";
import assert from "node:assert/strict";
import { evaluateAudit } from "./audit-policy.js";

const policy = { exceptions: [{
  package: "picomatch", advisory: "GHSA-fc5q-39xc-vjpf", versions: ["4.0.7"],
  expires: "2026-12-01", reason: "Test fixture for a narrowly scoped exception",
}] };
const now = new Date("2026-11-17T00:00:00Z");
const report = (vulnerabilities = {}) => ({ auditReportVersion: 2, vulnerabilities });
const advisory = (changes = {}) => ({
  name: "picomatch", severity: "high",
  url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf", ...changes,
});
const finding = (name, via, severity = "high") => ({ name, severity, via, nodes: [`node_modules/${name}`] });
function fixture() {
  return {
    full: report({
      vite: finding("vite", ["picomatch"]),
      picomatch: finding("picomatch", [advisory()]),
    }),
    lock: { packages: {
      "node_modules/vite": { version: "8.3.7", dev: true },
      "node_modules/picomatch": { version: "4.0.7", dev: true },
    } },
  };
}
function evaluate(full, lock, production = report(), date = now) {
  return evaluateAudit(full, production, lock, policy, date);
}

test("accepts only the documented dev advisory, including inherited findings", () => {
  const { full, lock } = fixture();
  const result = evaluate(full, lock);
  assert.deepEqual(result.blocked, []);
  assert.equal(result.accepted.length, 1);
});

test("a different high advisory on the same package still blocks", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.picomatch.via.push(advisory({ url: "https://github.com/advisories/GHSA-other" }));
  assert.ok(evaluate(full, lock).blocked.some((item) => item.includes("GHSA-other")));
});

test("an unrelated high advisory inherited through an allowed chain still blocks", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.vite.via.push(advisory({ name: "vite", url: "https://github.com/advisories/GHSA-vite" }));
  assert.ok(evaluate(full, lock).blocked.some((item) => item.includes("GHSA-vite")));
});

test("critical findings remain blocking, including this advisory if escalated", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.picomatch.via = [advisory({ severity: "critical" })];
  assert.ok(evaluate(full, lock).blocked.length);
});

for (const severity of ["low", "moderate", "high", "critical"]) {
  test(`production ${severity} findings are never excepted`, () => {
    const { full, lock } = fixture();
    const production = report({ picomatch: finding("picomatch", [advisory({ severity })], severity) });
    assert.ok(evaluate(full, lock, production).blocked.includes("Production dependency: picomatch"));
  });
}

for (const dependency of ["picomatch", "vite"]) {
  test(`a production node for ${dependency} prevents the exception`, () => {
    const { full, lock } = fixture();
    lock.packages[`node_modules/${dependency}`].dev = false;
    assert.ok(evaluate(full, lock).blocked.length);
  });
}

test("an unreviewed package version prevents the exception", () => {
  const { full, lock } = fixture();
  lock.packages["node_modules/picomatch"].version = "4.0.8";
  assert.ok(evaluate(full, lock).blocked.length);
});

test("every installed copy must be a reviewed dev-only version", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.picomatch.nodes.push("node_modules/vitest/node_modules/picomatch");
  lock.packages["node_modules/vitest/node_modules/picomatch"] = { version: "4.0.6", dev: true };
  assert.ok(evaluate(full, lock).blocked.length);
});

test("an absent lockfile node cannot receive an exception", () => {
  const { full, lock } = fixture();
  delete lock.packages["node_modules/picomatch"];
  assert.ok(evaluate(full, lock).blocked.length);
});

test("moderate root advisories retain the existing high threshold", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.vite.via.push(advisory({ name: "minimatch", severity: "moderate", url: "https://github.com/advisories/GHSA-other" }));
  assert.deepEqual(evaluate(full, lock).blocked, []);
});

test("the exception expires at the start of December 1 UTC", () => {
  const { full, lock } = fixture();
  assert.throws(() => evaluate(full, lock, report(), new Date("2026-12-01T00:00:00Z")), /expired/);
});

test("malformed or unavailable audit responses fail closed", () => {
  const { full, lock } = fixture();
  for (const invalid of [null, {}, { error: { code: "NETWORK" } }, { auditReportVersion: 1, vulnerabilities: {} }]) {
    assert.throws(() => evaluate(invalid, lock));
    assert.throws(() => evaluateAudit(full, invalid, lock, policy, now));
  }
});

test("unresolved dependency references fail closed", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.vite.via = ["missing"];
  assert.throws(() => evaluate(full, lock), /Unresolved/);
});

test("cyclic dependency references fail closed", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.picomatch.via.push("vite");
  assert.throws(() => evaluate(full, lock), /cyclic/);
});


test("a high advisory cannot hide behind a lower aggregate severity", () => {
  const { full, lock } = fixture();
  full.vulnerabilities.other = finding("other", [advisory({ name: "other", url: "https://github.com/advisories/GHSA-other" })], "moderate");
  assert.ok(evaluate(full, lock).blocked.some((item) => item.includes("GHSA-other")));
});
