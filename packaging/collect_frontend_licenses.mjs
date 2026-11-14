import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve('frontend/node_modules');
const output = path.resolve(process.argv[2]);
const inventory = [];
function visit(dir) {
  const manifest = path.join(dir, 'package.json');
  if (fs.existsSync(manifest)) {
    const pkg = JSON.parse(fs.readFileSync(manifest, 'utf8'));
    if (pkg.name && pkg.version) inventory.push({name: pkg.name, version: pkg.version, license: pkg.license ?? ''});
  }
  for (const item of fs.readdirSync(dir, {withFileTypes: true})) {
    const source = path.join(dir, item.name);
    if (item.isDirectory()) visit(source);
    else if (item.isFile() && /^(license|copying|notice)/i.test(item.name)) {
      const target = path.join(output, path.relative(root, source));
      fs.mkdirSync(path.dirname(target), {recursive: true});
      fs.copyFileSync(source, target);
    }
  }
}
fs.mkdirSync(output, {recursive: true});
visit(root);
fs.writeFileSync(path.join(output, 'inventory.json'), JSON.stringify(inventory, null, 2) + '\n');
