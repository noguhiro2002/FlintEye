import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyPicomatch } from '../scripts/picomatch-patch.mjs';

// Bound the entire child process. A regressed parser must fail this test instead
// of hanging the test runner while executing a malicious regular expression.
for (const path of verifyPicomatch()) {
  const entry = fileURLToPath(new URL(`../${path}/index.js`, import.meta.url));
  const result = spawnSync(process.execPath, ['--input-type=commonjs', '-e', `
    const assert = require('node:assert/strict');
    const match = require(process.argv[1]);
    for (const pattern of ['+(*a)', '*(*a)', '+(*)a', '+(*[ab])', '+(a*|b)', '+(+(*(a)|*(b))a)']) {
      assert.equal(match.isMatch('a'.repeat(40) + '!', pattern), false, pattern);
    }
    assert(!match.isMatch('x/' + 'a'.repeat(40) + '!.js', 'x/+(*a).js'));
    assert(!match.isMatch('a'.repeat(40) + '!', '+(+(a))'));
    assert(!match.isMatch('a'.repeat(40) + '!', '+((a+))'));
    assert(!match.isMatch('xa'.repeat(40) + '!', '+(x+(a))'));
    for (const pattern of ['+([*a)', '+("["*a)']) {
      assert(!match.isMatch('[a'.repeat(40) + '!', pattern), pattern);
    }
    assert(match.isMatch('src/components/CameraAudioSettings.tsx', '**/*.{ts,tsx}'));
    assert(!match.isMatch('src/app.css', '**/*.{ts,tsx}'));
    assert(match.isMatch('dist/index.js', '**/*.js'));
    assert(match.isMatch('abab', '+(a|b)'));
    assert(match.isMatch('ab', '+(*(a)|*(b))'));
    assert(match.isMatch('*', '+([*])'));
    assert(match.isMatch('*', '+(\\\\*)'));
    assert(match.isMatch('a+a+', '+(a\\\\+)'));
  `, entry], { encoding: 'utf8', timeout: 2500 });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stdout + result.stderr);
}
console.log('PASS: picomatch rejects repeated-wildcard attacks and preserves build globs');

const directory = mkdtempSync(join(tmpdir(), 'flinteye-audit-test-'));
try {
  const npmFixture = join(directory, 'npm.cjs');
  const gate = fileURLToPath(new URL('../scripts/audit.mjs', import.meta.url));
  const cause = { url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf', range: '<=4.0.7' };
  const patched = { severity: 'high', via: [cause], nodes: ['node_modules/picomatch'] };
  const reports = [
    [0, { picomatch: patched, vite: { severity: 'high', via: ['picomatch'] } }],
    [1, { picomatch: { ...patched, via: [{ ...cause, url: 'https://example.test/new-advisory' }] } }],
    [1, { picomatch: { ...patched, nodes: ['node_modules/other/node_modules/picomatch'] } }],
    [1, { other: { severity: 'critical', via: [{ url: 'https://example.test/new-advisory' }] } }],
    [1, { picomatch: patched, other: { severity: 'high', via: [cause] } }],
  ];
  for (const [expected, vulnerabilities] of reports) {
    writeFileSync(npmFixture, `console.log(${JSON.stringify(JSON.stringify({ auditReportVersion: 2, vulnerabilities }))}); process.exit(1);`);
    const result = spawnSync(process.execPath, [gate], {
      encoding: 'utf8', timeout: 5000, env: { ...process.env, npm_execpath: npmFixture },
    });
    if (result.error) throw result.error;
    assert.equal(result.status, expected, result.stdout + result.stderr);
  }
} finally {
  rmSync(directory, { recursive: true, force: true });
}
console.log('PASS: audit rejects new advisories, unexpected copies and unrelated high/critical findings');
