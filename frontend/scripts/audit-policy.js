const levels = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 };

function validateReport(report) {
  if (report?.error || report?.auditReportVersion !== 2 || !report.vulnerabilities
      || typeof report.vulnerabilities !== "object" || Array.isArray(report.vulnerabilities)) {
    throw new Error("Missing or unsupported npm audit report; audit cannot pass.");
  }
  for (const [name, finding] of Object.entries(report.vulnerabilities)) {
    if (!finding || !(finding.severity in levels) || !Array.isArray(finding.via)
        || !Array.isArray(finding.nodes) || finding.nodes.length === 0) {
      throw new Error(`Invalid audit finding: ${name}`);
    }
  }
}

/** Resolve inherited findings to their actual advisories; never allow a package wholesale. */
export function evaluateAudit(full, production, lock, policy, now = new Date()) {
  validateReport(full);
  validateReport(production);
  if (!lock?.packages || !Array.isArray(policy?.exceptions)) {
    throw new Error("Missing lockfile packages or audit exception policy.");
  }
  const exceptions = policy.exceptions;
  for (const exception of exceptions) {
    if (!exception.package || !/^GHSA-[a-z0-9-]+$/.test(exception.advisory)
        || !Array.isArray(exception.versions) || !exception.versions.length || !exception.reason
        || !/^\d{4}-\d{2}-\d{2}$/.test(exception.expires)) {
      throw new Error("Invalid audit exception policy.");
    }
    const expiry = new Date(`${exception.expires}T00:00:00Z`);
    if (!Number.isFinite(expiry.getTime()) || expiry.toISOString().slice(0, 10) !== exception.expires || now >= expiry) {
      throw new Error(`Audit exception ${exception.advisory} expired on ${exception.expires}; remove or review it.`);
    }
  }
  const blocked = new Set();
  const accepted = new Set();
  // No exceptions apply to production dependencies, at any severity.
  for (const name of Object.keys(production.vulnerabilities)) {
    blocked.add(`Production dependency: ${name}`);
  }

  function visit(name, ancestors = []) {
    const finding = full.vulnerabilities[name];
    if (!finding || ancestors.includes(name)) {
      throw new Error(`Unresolved or cyclic audit dependency: ${[...ancestors, name].join(" -> ")}`);
    }
    const path = [...ancestors, name];
    if (!finding.via.length) throw new Error(`Audit finding has no advisory: ${name}`);
    for (const via of finding.via) {
      if (typeof via === "string") {
        visit(via, path);
        continue;
      }
      if (!via || !(via.severity in levels) || typeof via.url !== "string") {
        throw new Error(`Invalid advisory on ${name}`);
      }
      if (levels[via.severity] < levels.high) continue;
      const exception = exceptions.find((entry) => entry.package === name
        && via.name === entry.package
        && via.url === `https://github.com/advisories/${entry.advisory}`
        && via.severity === "high");
      const developmentOnly = path.every((dependency) => full.vulnerabilities[dependency].nodes.every(
        (node) => lock.packages[node]?.dev === true,
      ));
      const pinnedVersions = exception && finding.nodes.every(
        (node) => exception.versions.includes(lock.packages[node]?.version),
      );
      if (exception && developmentOnly && pinnedVersions) {
        accepted.add(`${exception.advisory} (${name} ${exception.versions.join(", ")}, dev only, expires ${exception.expires})`);
      } else {
        blocked.add(`${via.url}: ${path.join(" -> ")}`);
      }
    }
  }

  for (const name of Object.keys(full.vulnerabilities)) visit(name);
  return { blocked: [...blocked], accepted: [...accepted] };
}
