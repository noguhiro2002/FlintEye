// Inventory the actual Settings JSX. A new control/range/choice must be reviewed
// in the inventory and assigned to an executable scenario or an OS device check.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import ts from 'typescript';

const files = {
  'pages/SettingsPage.tsx': 'settings', 'components/StartupSettings.tsx': 'quick',
  'components/NetworkAccess.tsx': 'runtime-network', 'components/CameraAudioSettings.tsx': 'camera-audio',
  'components/SettingsHelp.tsx': 'settings-help',
  'components/EventRecordings.tsx': 'event-recording',
};
const controls = new Map();
const normalize = value => value.replace(/\s+/g, ' ').trim();
const attributes = node => new Map(node.attributes.properties.filter(ts.isJsxAttribute)
  .map(attr => [attr.name.getText(), attr.initializer ? normalize(attr.initializer.getText().replace(/^["']|["']$/g, '')) : true]));
function visibleText(node) {
  if (ts.isJsxText(node)) return node.getText();
  if (!ts.isJsxElement(node)) return '';
  if (['input', 'select', 'textarea', 'button', 'small'].includes(node.openingElement.tagName.getText())) return '';
  return node.children.map(visibleText).join(' ');
}

for (const [file, defaultSection] of Object.entries(files)) {
  const source = ts.createSourceFile(file, await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const labels = new Map();
  function collectLabels(node) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText() === 'label') {
      const id = attributes(node.openingElement).get('htmlFor');
      if (id) labels.set(id, normalize(visibleText(node)));
    }
    ts.forEachChild(node, collectLabels);
  }
  collectLabels(source);
  function visit(node, section = defaultSection, label = '', variants = []) {
    if (defaultSection === 'event-recording' && ts.isFunctionDeclaration(node) &&
        node.name?.text !== 'EventRecordingOptions') return;
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      const branch = node.left.getText().match(/\bmode === "(quick|advanced)"/);
      if (branch) section = branch[1];
    }
    if (ts.isJsxElement(node)) {
      const name = node.openingElement.tagName.getText();
      const css = attributes(node.openingElement).get('className');
      const match = typeof css === 'string' && css.match(/\bsettings-section-(\w+)/);
      if (match) section = match[1];
      if (name === 'label') label = normalize(visibleText(node));
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'map') {
      let iterable = node.expression.expression;
      while (ts.isParenthesizedExpression(iterable) || ts.isAsExpression(iterable)) iterable = iterable.expression;
      if (ts.isArrayLiteralExpression(iterable)) variants = iterable.elements.map(element => normalize(element.getText()));
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const kind = node.tagName.getText();
      const attrs = attributes(node);
      if (['input', 'select', 'textarea', 'button', 'summary', 'a'].includes(kind) || attrs.get('role') === 'button') {
        const parent = ts.isJsxElement(node.parent) ? node.parent : null;
        const buttonText = ['button', 'summary', 'a'].includes(kind) && parent
          ? normalize(parent.children.map(visibleText).join(' ')) : '';
        const binding = ['checked', 'value', 'onClick', 'href'].map(key => attrs.get(key)).find(Boolean);
        const name = attrs.get('aria-label') || buttonText || label || labels.get(attrs.get('id')) ||
          (typeof binding === 'string' ? binding.slice(0, 105) : attrs.get('className')) || kind;
        const limits = ['type', 'min', 'max', 'step', 'minLength', 'maxLength', 'pattern', 'required',
          'readOnly', 'disabled'].flatMap(key => attrs.has(key) ? [[key, attrs.get(key)]] : []);
        const choices = [];
        if (kind === 'select' && parent) {
          const option = candidate => {
            if (ts.isJsxOpeningElement(candidate) && candidate.tagName.getText() === 'option') {
              const props = attributes(candidate);
              choices.push([props.get('value') ?? normalize(visibleText(candidate.parent)), props.has('disabled')]);
            }
            ts.forEachChild(candidate, option);
          };
          ts.forEachChild(parent, option);
        }
        const details = { file, section, kind, name, limits, choices, variants };
        const base = `${section}/${kind}/${name}`;
        const count = (controls.get(base)?.length || 0) + 1;
        if (!controls.has(base)) controls.set(base, []);
        const id = `${base}#${count}`;
        const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        controls.get(base).push({ id, ...details, line });
      }
    }
    ts.forEachChild(node, child => visit(child, section, label, variants));
  }
  visit(source);
}

const inventory = [...controls.values()].flat().sort((a, b) => a.id.localeCompare(b.id, 'en'));
if (process.argv.includes('--print')) {
  console.log(JSON.stringify(inventory, null, 2));
} else {
  const contract = JSON.parse(await readFile(new URL('settings-controls.json', import.meta.url), 'utf8'));
  const byId = new Map(contract.controls.map(item => [item.id, item]));
  assert.equal(byId.size, contract.controls.length, 'Duplicate Settings inventory IDs');
  const known = new Set(Object.keys(contract.cases));
  const changes = [];
  const rows = [];
  for (const { line, ...item } of inventory) {
    const entry = byId.get(item.id);
    byId.delete(item.id);
    if (!entry) changes.push(`Missing ${item.id} (${item.file}:${line})`);
    else {
      const { cases, ...saved } = entry;
      if (JSON.stringify(saved) !== JSON.stringify(item)) changes.push(`Options or validation changed for ${item.id}`);
      if (!cases.length || cases.some(c => !known.has(c))) changes.push(`Assign a test for ${item.id}`);
      rows.push({ ...item, line, cases });
    }
  }
  for (const id of byId.keys()) changes.push(`Removed ${id}`);
  const output = process.env.FLINTEYE_SETTINGS_INVENTORY || '../dist/settings-coverage/inventory.json';
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify({ cases: contract.cases, count: rows.length, controls: rows, changes }, null, 2)+'\n');
  assert.deepEqual(changes, [], 'Review the changed Settings controls and their scenarios');
  console.log(`PASS ${rows.length} Settings controls have assigned scenarios`);
}
