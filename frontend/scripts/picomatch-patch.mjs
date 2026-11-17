import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = new URL('../', import.meta.url);
const originalHash = '4e1e05447668aa1e94366c5516a2bcd8f5fff800cc92b1d0cd7d77703b8618c4';
const before = `    const analysis = analyzeRepeatedExtglob(body, opts);

    if ((token.type === 'plus' || token.type === 'star') && analysis.risky) {`;
const after = `    const analysis = analyzeRepeatedExtglob(body, opts);

    // FlintEye backport for GHSA-fc5q-39xc-vjpf. Reuse the parsed tokens so
    // quoted, escaped and unmatched brackets have their actual glob meaning.
    tokens[token.tokensIndex].flinteyeUnbounded = token.type === 'plus' || token.type === 'star';
    if (opts.maxExtglobRecursion !== false && !analysis.risky) {
      analysis.risky = tokens.slice(token.tokensIndex + 1).some(part =>
        part.flinteyeUnbounded || (part.type === 'plus' && part.value) ||
        ((part.type === 'star' || part.type === 'globstar') && part.output));
    }

    if ((token.type === 'plus' || token.type === 'star') && analysis.risky) {`;
const beforeOutput = '      open.output = safeOutput || utils.escapeRegex(literal);';
const afterOutput = `${beforeOutput}
      open.flinteyeUnbounded = Boolean(safeOutput);`;
const beforeClear = '        delete tokens[i].suffix;';
const afterClear = `${beforeClear}
        delete tokens[i].flinteyeUnbounded;`;
const edits = [[before, after], [beforeOutput, afterOutput], [beforeClear, afterClear]];
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

// Both verification and installation derive the expected bytes from the pinned
// upstream file. An altered or partially patched dependency fails closed.
export function verifyPicomatch({ apply = false } = {}) {
  const lock = JSON.parse(readFileSync(new URL('package-lock.json', root), 'utf8'));
  const paths = Object.keys(lock.packages).filter(path => path.endsWith('/picomatch'));
  assert(paths.length > 0, 'Review and remove the backport when picomatch is replaced');
  for (const path of paths) {
    assert.equal(lock.packages[path].version, '4.0.7', 'Review the backport for a changed version');
    const manifest = JSON.parse(readFileSync(new URL(`${path}/package.json`, root), 'utf8'));
    assert.equal(manifest.name, 'picomatch');
    assert.equal(manifest.version, '4.0.7');
    const target = new URL(`${path}/lib/parse.js`, root);
    let source = readFileSync(target, 'utf8');
    if (hash(source) === originalHash) {
      assert(apply, `Missing picomatch backport at ${path}. Run npm ci.`);
      for (const [preimage, patched] of edits) {
        assert.equal(source.split(preimage).length, 2, 'Unexpected upstream patch location');
        source = source.replace(preimage, patched);
      }
      writeFileSync(target, source);
    }
    for (const [preimage, patched] of edits) {
      assert.equal(source.split(patched).length, 2, `Missing or modified backport at ${path}`);
      source = source.replace(patched, preimage);
    }
    assert.equal(hash(source), originalHash, `Unexpected picomatch code at ${path}`);
  }
  return paths;
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const paths = verifyPicomatch({ apply: true });
  console.log(`Verified picomatch security backport in ${paths.length} installed copy/copies.`);
}
