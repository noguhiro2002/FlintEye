// Exercises a REAL installed API. Do not add route.fulfill or an API mock here.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';

const { values } = parseArgs({ options: {
  url: { type: 'string' }, profile: { type: 'string' }, output: { type: 'string' },
  release: { type: 'string' }, commit: { type: 'string' }, retained: { type: 'boolean', default: false },
  'fixture-url': { type: 'string' },
}});
assert(values.url && values.profile && values.output && values.release);
const origin = new URL(values.url);
assert(['127.0.0.1', 'localhost'].includes(origin.hostname), 'QA must target an isolated local installation');
const output = resolve(values.output);
await mkdir(output, { recursive: true });
const password = 'FlintEye-synthetic-QA-admin-174';
const viewerPassword = 'FlintEye-synthetic-QA-viewer-174';
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
  recordVideo: { dir: join(output, 'video') }, acceptDownloads: true });
// Observe native WebRTC statistics; no network interception or fake responses.
await context.addInitScript(() => {
  const Native = globalThis.RTCPeerConnection;
  if (!Native) return;
  globalThis.__flinteyeQaPeers = [];
  globalThis.RTCPeerConnection = new Proxy(Native, { construct(target, args) {
    const peer = Reflect.construct(target, args); globalThis.__flinteyeQaPeers.push(peer); return peer;
  } });
});
await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
const page = await context.newPage();
page.setDefaultTimeout(30_000);
const errors = [], stages = [], requests = new Set();
page.on('pageerror', e => errors.push(String(e)));
page.on('request', request => { const url = new URL(request.url()); if (url.origin === origin.origin && url.pathname.startsWith('/api/')) requests.add(request.method()+' '+url.pathname); });
page.on('dialog', dialog => dialog.accept());
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, predicate, label, seconds = 90) {
  const end = Date.now()+seconds*1000; let value;
  while (Date.now() < end) { value = await read(); if (predicate(value)) return value; await pause(500); }
  throw new Error(label+': '+JSON.stringify(value));
}
async function api(path, method = 'GET', data) {
  const response = await context.request.fetch(new URL(path, origin).href, { method, data, headers: { Origin: origin.origin }, timeout: 60_000 });
  assert(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
  return response;
}
async function json(path) { return (await api(path)).json(); }
async function patch(data) {
  const current = await api('/api/v1/config/effective');
  const response = await context.request.patch(new URL('/api/v1/config/runtime', origin).href, {
    data, headers: { Origin: origin.origin, 'If-Match': current.headers().etag }, timeout: 60_000,
  });
  assert(response.ok(), await response.text());
}
async function nav(name) {
  const button = page.locator('.sidebar').getByRole('button', { name, exact: true });
  await button.click();
  await until(() => button.getAttribute('aria-current'), value => value === 'page', 'Navigation to '+name, 30);
}
async function category(name) { await page.getByRole('complementary', { name: 'Settings categories' }).getByRole('button', { name, exact: true }).click(); }
async function login(username, secret) {
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(secret);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.locator('.sidebar').waitFor();
}
async function videoProgress(label, { audio = false, marker } = {}) {
  const frame = page.frameLocator('iframe.webrtc-frame');
  const video = frame.locator('video');
  await until(async () => {
    try {
      return await video.evaluate(async (v, { audio, marker }) => {
        v.muted = true;
        if (v.paused) void v.play().catch(() => {});
        if (v.readyState < 2 || !v.videoWidth) return { ready: v.readyState, width: v.videoWidth };
        // Measure progression within a single player. A timestamp read from
        // the previous iframe would be meaningless after navigation.
        const before = v.currentTime;
        await new Promise(resolve => setTimeout(resolve, 750));
        if (!v.isConnected || !v.videoWidth) return { state: 'player reloading' };
        const sample = { elapsed: v.currentTime - before, width: v.videoWidth };
        if (marker) {
          const canvas = document.createElement('canvas');
          canvas.width = 1;
          canvas.height = 1;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(v, Math.floor(v.videoWidth / 2), Math.floor(v.videoHeight / 2), 1, 1, 0, 0, 1, 1);
          const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
          sample.marker = r > Math.max(g, b) + 80 ? 'red' : b > Math.max(r, g) + 80 ? 'blue' : 'unknown';
        }
        if (audio) {
          const stats = await Promise.all((globalThis.__flinteyeQaPeers || []).map(peer => peer.getStats()));
          sample.audioBytes = stats.flatMap(report => [...report.values()])
            .filter(item => item.type === 'inbound-rtp' && item.kind === 'audio')
            .reduce((total, item) => total + (item.bytesReceived || 0), 0);
        }
        return sample;
      }, { audio, marker }, { timeout: 2000 });
    } catch (error) {
      if (error.name === 'TimeoutError' || /Execution context was destroyed|frame was detached/i.test(error.message)) {
        return { state: 'waiting for current player' };
      }
      throw error;
    }
  }, sample => sample.elapsed > .25 && (!marker || sample.marker === marker) &&
    (!audio || sample.audioBytes > 0), label);
}
try {
  await page.goto(origin.href);
  if (!values.retained) {
    await page.getByRole('heading', { name: 'Welcome to FlintEye' }).waitFor();
    await page.getByLabel('Server setup token', { exact: true }).fill((await readFile(join(values.profile, 'setup-token'), 'utf8')).trim());
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByLabel('Confirm password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Create administrator account', exact: true }).click();
    await page.locator('.sidebar').waitFor();
    // This appears after the asynchronous preferences request, after the sidebar.
    await page.getByRole('button', { name: 'Skip for now', exact: true }).click();
    stages.push('browser-first-run-setup');
  } else { await login('admin', password); stages.push('retained-administrator-login'); }
  const identity = await json('/api/v1/build');
  assert.equal(identity.release, values.release);
  if (values.commit) { assert.equal(identity.commit, values.commit); assert.equal(identity.dirty, false); }
  const unauth = await browser.newContext();
  for (const path of ['/api/v1/config/runtime', '/api/v1/status/monitoring']) {
    const r = await unauth.request.get(new URL(path, origin).href); assert.equal(r.status(), 401);
  }
  await unauth.close();
  stages.push('real-api-build-identity-and-authentication');
  if (!values.retained) {
    await patch({ recording: { enabled: true, record_all_cameras: true, record_segment_duration: '2s', record_part_duration: '200ms', include_multiview: true },
      snapshot: { thumbnail_refresh_interval_sec: 2 }, multiview: { enabled: false } });
    await nav('Settings'); await category('Cameras');
    for (let i = 1; i <= 2; i++) {
      await page.getByRole('button', { name: 'Add IP Camera', exact: true }).click();
      const card = page.locator('.ip-camera-card').last();
      await card.getByLabel('Display Name', { exact: true }).fill(`QA camera ${i}`);
      await card.getByLabel('MediaMTX Path', { exact: true }).fill(`qa-camera-${i}`);
      await card.getByLabel('Source URL', { exact: true }).fill(`${values['fixture-url']}/qa-input-${i}`);
    }
    await page.locator('.settings-page-header').getByRole('button', { name: 'Save changes', exact: true }).click();
    // The API can commit before the UI finishes reloading saved values and USB
    // discovery. Respect the real UI completion signal before navigating away.
    await page.locator('.settings-page-header').getByText('All changes saved', { exact: true }).waitFor();
    await until(() => page.locator('.settings-page-header').getByRole('button', { name: 'Refresh', exact: true }).isEnabled(),
      value => value, 'Settings save/reload completion');
    await until(() => json('/api/v1/cameras'), value => value.items.filter(c => c.id.startsWith('qa-camera-')).length === 2, 'GUI camera save');
    const effective = await json('/api/v1/config/effective');
    const cameras = effective.cameras;
    assert(cameras.every(c => c.audio?.enabled !== true), 'Camera audio must default off');
    await patch({ cameras: cameras.map(c => ({ ...c, ip: { ...c.ip, onvif_mode: 'disabled' } })),
      multiview: { enabled: true, source_mode: 'env', source_paths: ['qa-camera-1', 'qa-camera-2'], tile_count: 2,
        input_rtsp_base_url: effective.mediamtx.internal_rtsp_base_url || effective.mediamtx.rtsp_base_url,
        output_rtsp_base_url: effective.mediamtx.internal_rtsp_base_url || effective.mediamtx.rtsp_base_url,
        mtx_api_url: effective.multiview.mtx_api_url,
        quality: { fps: 5, encoder: 'libx264', gop: 5, quality_preset: 'low' }, layout: { canvas_width: 640, canvas_height: 360 } } });
    stages.push('GUI-register-two-real-synthetic-RTSP-sources-and-save');
    await nav('Information'); await nav('Settings'); await category('Cameras');
    const audioCard = page.locator('.ip-camera-card').first();
    await audioCard.getByRole('button', { name: 'Check audio input', exact: true }).click();
    await until(() => json('/api/v1/cameras/qa-camera-1/audio'), value => value.availability === 'available', 'Synthetic audio detection');
    const toggle = audioCard.getByLabel('Enable camera audio', { exact: true });
    await toggle.setChecked(true);
    await audioCard.getByRole('button', { name: 'Save camera audio', exact: true }).click();
    await until(() => json('/api/v1/cameras/qa-camera-1/audio'), value => value.settings.enabled === true, 'Audio save');
    assert.equal((await json('/api/v1/cameras/qa-camera-2/audio')).settings.enabled, false);
    stages.push('per-camera-audio-default-off-detection-enable-and-save');
  } else {
    const config = await json('/api/v1/config/effective');
    assert.equal(config.cameras.filter(c => c.id.startsWith('qa-camera-')).length, 2);
    assert.equal(config.cameras.find(c => c.id === 'qa-camera-1').audio.enabled, true);
    assert((await json('/api/v1/recordings')).items.length > 0, 'Recording inventory was not retained');
    const monitoring = await json('/api/v1/status/monitoring');
    assert.equal(monitoring.resume_on_startup, false, 'Startup preference was not retained');
    assert.equal(monitoring.desired_running, true, 'The last Start intent was not retained');
    stages.push('retained-config-audio-and-recording-inventory');
  }
  // Every main screen is served by the installed application, not Vite or a mock.
  for (const name of ['Dashboard', 'Information', 'Settings', 'Live View', 'Multiview', 'Recordings']) {
    await nav(name); await page.locator('.page').first().waitFor();
    await page.screenshot({ path: join(output, name.replaceAll(' ', '-')+'.png'), fullPage: true });
  }
  stages.push('all-six-main-screens');
  if (!values.retained) {
    await until(() => json('/api/v1/viewer/cameras'), value => value.items.length === 2 && value.items.every(c => c.health?.state === 'healthy'), 'Two receiving camera workers', 120);
    await nav('Live View');
    for (const [i, marker] of [[1, 'red'], [2, 'blue']]) {
      await page.getByRole('button', { name: 'View QA camera '+i, exact: true }).click();
      await videoProgress('Live camera '+i, { audio: i === 1, marker });
    }
    stages.push('both-live-cameras-show-their-own-marker');
    await page.screenshot({ path: join(output, 'Live-View-playing.png') });
    await nav('Multiview'); await videoProgress('Multiview WebRTC frame progress');
    await page.screenshot({ path: join(output, 'Multiview-playing.png') });
    stages.push('live-and-multiview-real-WebRTC-frame-progress');
    await until(() => json('/api/v1/recordings'), value => value.items.some(r => r.is_stable), 'Completed recordings');
    await nav('Recordings');
    const play = page.locator('.recording-card button[aria-label^="Play "]').first();
    const relativePath = (await play.getAttribute('aria-label')).slice(5);
    await page.getByRole('button', { name: 'Play '+relativePath, exact: true }).click();
    assert.equal(await page.locator('.recording-modal-path').getAttribute('title'), relativePath);
    const player = page.getByRole('dialog').locator('video');
    await player.waitFor();
    await player.evaluate(v => { v.muted = true; void v.play().catch(() => {}); });
    await until(() => player.evaluate(v => ({ width: v.videoWidth, time: v.currentTime })), v => v.width > 0 && v.time > .1, 'Recorded video playback');
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('dialog').getByRole('link', { name: 'Download', exact: true }).click();
    const download = await downloadEvent;
    const savedName = 'recording-download'+(download.suggestedFilename().endsWith('.mp4') ? '.mp4' : '.ts');
    await download.saveAs(join(output, savedName));
    await writeFile(join(output, 'download-selection.json'), JSON.stringify({ relativePath, savedName }));
    await page.getByRole('button', { name: 'Close player', exact: true }).click();
    stages.push('recording-GUI-playback-and-download');
    await nav('Settings'); await category('Runtime & access');
    await page.getByLabel('New viewer password', { exact: true }).fill(viewerPassword);
    await page.getByRole('button', { name: 'Set viewer password and sign in again', exact: true }).click();
    await page.getByRole('button', { name: 'Sign In', exact: true }).waitFor();
    await login('viewer', viewerPassword);
    assert.equal(await page.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).count(), 0);
    const denied = await context.request.patch(new URL('/api/v1/config/runtime', origin).href, { data: { ui: { onboarding_done: true } }, headers: { Origin: origin.origin } });
    assert.equal(denied.status(), 403);
    await page.getByRole('button', { name: 'Logout', exact: true }).click();
    await login('admin', password);
    stages.push('viewer-login-and-real-API-write-denial');
    await nav('Dashboard');
    await page.getByRole('button', { name: 'Stop monitoring', exact: true }).click();
    await until(() => json('/api/v1/status/monitoring'), value => value.desired_running === false && value.phase === 'stopped' && !value.busy, 'GUI monitoring Stop', 90);
    assert.equal((await api('/api/v1/health')).status(), 200);
    assert.equal((await json('/api/v1/status/mediamtx')).running, false);
    await patch({ ui: { onboarding_done: true } });
    assert.equal((await json('/api/v1/status/mediamtx')).running, false);
    assert((await json('/api/v1/status/processes')).items?.every(p => p.status !== 'running' && p.pid === null) ?? false, 'Owned publishers survived Stop');
    stages.push('GUI-stop-keeps-API-and-saved-settings-cannot-restart-monitoring');
    await page.getByRole('button', { name: 'Start monitoring', exact: true }).click();
    await until(() => json('/api/v1/status/monitoring'), value => value.desired_running && !value.busy && value.counts.recording === 2,
      'Active recording before normal Quit', 120);
    stages.push('GUI-start-resumes-recording-before-normal-quit');
  }
  assert.deepEqual(errors, [], 'Uncaught browser errors');
  await writeFile(join(output, 'browser.json'), JSON.stringify({ result: 'passed', identity, retained: values.retained,
    stages, realApiRequests: [...requests].sort(), errors, apiMocked: false }, null, 2)+'\n');
  console.log('PASS: installed application real API and browser workflow ('+stages.length+' checks)');
} catch (error) {
  await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  await writeFile(join(output, 'browser.json'), JSON.stringify({ result: 'failed', stages, errors, error: String(error), apiMocked: false }, null, 2)+'\n');
  throw error;
} finally {
  await context.tracing.stop({ path: join(output, 'trace.zip') });
  await context.close(); await browser.close();
}
