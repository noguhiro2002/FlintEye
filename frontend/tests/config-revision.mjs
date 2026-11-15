import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../..', import.meta.url));
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
  headless: true,
  args: ['--no-sandbox'],
});

async function scenario({ conflict = false, timeout = false } = {}) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  let revision = 2;
  let hangAuth = timeout;
  let authStarted;
  const started = new Promise(resolve => { authStarted = resolve; });
  const patches = [];
  let config = {
    ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: !conflict },
    cameras: ['first', 'second'].map(id => ({
      id, path: id, type: 'ip', enabled: true, display_name: id,
      ip: { source_url: `rtsp://example.test/${id}`, cfr_fps: 20 },
    })),
    recording: { managed_storage: false },
  };
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname !== '127.0.0.1') return route.abort();
    if (!url.pathname.startsWith('/api/')) {
      const path = resolve(root, 'frontend/dist', '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
      return route.fulfill({
        contentType: ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)],
        body: await readFile(path),
      });
    }
    let body = { items: [] }, status = 200;
    switch (url.pathname) {
      case '/api/v1/auth/me':
        if (hangAuth) {
          authStarted();
          return; // Deliberately unresolved until the client's timeout aborts it.
        }
        body = { authenticated: true, role: timeout ? 'viewer' : 'admin', username: timeout ? 'viewer' : 'admin',
          viewer_auth_required: true, setup_required: false, provider: 'local',
          local: { admin_username: 'admin', viewer_username: 'viewer' } };
        break;
      case '/api/v1/config/effective':
        body = timeout ? { detail: 'Admin only' } : config;
        status = timeout ? 403 : 200;
        break;
      case '/api/v1/cameras':
        // Older list deliberately disagrees with the configuration snapshot.
        body = { items: config.cameras.slice(0, 1) };
        break;
      case '/api/v1/config/runtime': {
        const payload = request.postDataJSON();
        const expected = request.headers()['if-match'];
        patches.push({ payload, expected });
        if (expected !== `"${revision}"`) {
          status = 409; body = { detail: 'Configuration changed' };
        } else {
          config = { ...config, ...payload, ui: { ...config.ui, ...payload.ui } };
          revision++;
          body = { ok: true, effective: config };
        }
        break;
      }
      case '/api/v1/status':
        body = { mediamtx: { running: false, status: 'stopped', mode: 'direct' }, cameras_enabled: 0,
          cameras_total: 0, multiview_enabled: false, running_processes: 0, processes: { items: [] } };
        break;
      case '/api/v1/multiview/status': body = { views: [], updated_at: null }; break;
      case '/api/v1/desktop': body = { folder_picker: false }; break;
      case '/api/v1/updates': body = { available: false }; break;
      case '/api/v1/storage/status': body = { message: '' }; break;
    }
    return route.fulfill({ status, contentType: 'application/json', headers: { ETag: `"${revision}"` }, body: JSON.stringify(body) });
  });
  if (timeout) await page.clock.install();
  await page.goto('http://127.0.0.1:12345');
  return { page, patches, started, retry: () => { hangAuth = false; }, close: async () => {
    await context.close();
    assert.deepEqual(errors, [], 'Unexpected page errors');
  } };
}

try {
  for (const conflict of [false, true]) {
    const test = await scenario({ conflict });
    const page = test.page;
    await page.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByRole('complementary', { name: 'Settings categories' }).getByRole('button', { name: 'General', exact: true }).click();
    const title = page.getByRole('textbox', { name: /^App Title/ });
    await title.fill('Protected edit');
    if (conflict) {
      await page.getByRole('button', { name: 'Skip for now' }).click();
      await page.locator('.first-run').waitFor({ state: 'hidden' });
    }
    await page.getByRole('button', { name: 'Save changes', exact: true }).first().click();
    if (conflict) {
      await page.getByText('Settings changed in another session.', { exact: false }).waitFor();
      assert.equal(test.patches.at(-1).expected, '"2"', 'Editor must retain its own revision after onboarding saves');
      assert.equal(await title.inputValue(), 'Protected edit');
    } else {
      await page.getByText('All changes saved', { exact: true }).waitFor();
      assert.deepEqual(test.patches.at(-1).payload.cameras.map(camera => camera.path), ['first', 'second']);
      assert.equal(await title.inputValue(), 'Protected edit');
    }
    await test.close();
    console.log('PASS', conflict ? 'editor revision isolated from onboarding' : 'camera draft and configuration share one snapshot');
  }
  const test = await scenario({ timeout: true });
  await test.started;
  await test.page.clock.fastForward(31000);
  await test.page.getByRole('button', { name: 'Retry connection' }).waitFor();
  assert.match(await test.page.locator('body').innerText(), /timed out/);
  test.retry();
  await test.page.getByRole('button', { name: 'Retry connection' }).click();
  await test.page.locator('.session-meta').waitFor();
  assert.match(await test.page.locator('.session-meta').innerText(), /viewer/);
  assert.doesNotMatch(await test.page.locator('body').innerText(), /Public viewer/);
  await test.close();
  console.log('PASS authentication timeout, retry and viewer session without config access');
} finally {
  await browser.close();
}
