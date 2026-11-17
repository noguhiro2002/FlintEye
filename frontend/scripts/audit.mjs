import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { verifyPicomatch } from './picomatch-patch.mjs';

const patchedPaths = verifyPicomatch();
const result = spawnSync(process.execPath, [process.env.npm_execpath, 'audit', '--json'], {
  cwd: new URL('../', import.meta.url), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
});
if (result.error) throw result.error;
assert(result.status === 0 || result.status === 1, result.stderr || 'npm audit failed');
const report = JSON.parse(result.stdout);
assert(!report.error && report.auditReportVersion === 2 && report.vulnerabilities,
  JSON.stringify(report.error) || 'Unexpected npm audit response');

const advisory = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf';
const findings = report.vulnerabilities;
function coveredByBackport(name, visited = new Set()) {
  const finding = findings[name];
  if (!finding || visited.has(name) || !finding.via?.length) return false;
  const next = new Set([...visited, name]);
  return finding.via.every(cause => {
    if (typeof cause === 'string') return coveredByBackport(cause, next);
    return name === 'picomatch' && cause.url === advisory && cause.range === '<=4.0.7'
      && finding.nodes.length > 0 && finding.nodes.every(path => patchedPaths.includes(path));
  });
}

let unresolved = 0;
for (const [name, finding] of Object.entries(findings)) {
  if (coveredByBackport(name)) {
    console.log(`${name}: GHSA-fc5q-39xc-vjpf covered by the verified local backport`);
  } else {
    console.log(`${name}: ${finding.severity} — ${JSON.stringify(finding.via)}`);
    if (finding.severity === 'high' || finding.severity === 'critical') unresolved++;
  }
}
console.log(`Unresolved high/critical findings: ${unresolved}`);
process.exitCode = unresolved ? 1 : 0;
