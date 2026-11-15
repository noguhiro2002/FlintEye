import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const names = ['monitoring', 'auth-settings', 'config-revision', 'drafts', 'dialog', 'recordings', 'ptz', 'ptz-release', 'cameras', 'poll', 'selection', 'navigation', 'states', 'misc', 'setup', 'layout', 'layout-recordings', 'layout-viewers'];
let failed = false;
for (const name of names) {
    console.log(`\n--- ${name} ---`);
    const result = spawnSync(process.execPath, [fileURLToPath(new URL(`${name}.mjs`, import.meta.url))], { stdio: 'inherit', env: process.env });
    if (result.error || result.status !== 0)
        failed = true;
}
process.exitCode = failed ? 1 : 0;
