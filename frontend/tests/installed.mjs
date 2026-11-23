// Exercises a REAL installed API. Do not add route.fulfill or an API mock here.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';

const { values } = parseArgs({ options: {
  url: { type: 'string' }, profile: { type: 'string' }, output: { type: 'string' },
  release: { type: 'string' }, commit: { type: 'string' }, retained: { type: 'boolean', default: false },
  'fixture-url': { type: 'string' }, 'synthetic-uvc': { type: 'boolean', default: false },
  'onvif-url': { type: 'string' }, 'archive-folder': { type: 'string' },
  'preview-9': { type: 'boolean', default: false },
}});
assert(values.url && values.profile && values.output && values.release);
const origin = new URL(values.url);
assert(['127.0.0.1', 'localhost'].includes(origin.hostname), 'QA must target an isolated local installation');
const output = resolve(values.output);
await mkdir(output, { recursive: true });
const password = 'FlintEye-synthetic-QA-admin-174';
const viewerPassword = 'FlintEye-synthetic-QA-viewer-174';
const onvif = values['onvif-url'] && new URL(values['onvif-url']);
const eventFolder = values['archive-folder'];
const eventApi = '/api/v1/recording-events';
const eventLabel = 'Synthetic equipment fault';
const preview9 = values['preview-9'];
if (onvif) assert.equal(onvif.hostname, '127.0.0.1');
const renamedIp = '入口 IP – QA';
const renamedSecond = '作業台 カメラ – QA';
const branding = { app_title: 'FlintEye QA – 設定', sidebar_title: 'QA Cameras', footer_text: 'QA fixture footer' };
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
const header = page.locator('.settings-page-header');
const settingsReady = () => until(() => header.getByRole('button', { name: 'Refresh', exact: true }).isEnabled(),
  value => value, 'Settings save/reload completion');

async function saveCameraForm() {
  await header.getByRole('button', { name: 'Save changes', exact: true }).click();
  await header.getByText('All changes saved', { exact: true }).waitFor();
  await settingsReady();
}

async function addIpCamera(index) {
  await page.getByRole('button', { name: 'Add IP Camera', exact: true }).click();
  const card = page.locator('.ip-camera-card').last();
  await card.getByLabel('Display Name', { exact: true }).fill(`QA camera ${index}`);
  await card.getByLabel('MediaMTX Path', { exact: true }).fill(`qa-camera-${index}`);
  const discover = card.getByRole('combobox', { name: /^ONVIF discovery/ });
  await discover.selectOption(onvif && index === 1 ? 'manual' : 'disabled');
  if (onvif && index === 1) {
    await card.getByLabel(/^ONVIF device service address/).fill(new URL('/full/device', onvif).href);
    await card.getByLabel(/^ONVIF Username/).fill('qa-camera');
    await card.getByLabel(/^ONVIF Password/).fill('qa-onvif-password-only');
  }
  await card.getByLabel('Source URL', { exact: true }).fill(`${values['fixture-url']}/qa-input-${index}`);
  return card;
}

function usbDiscovery() {
  return page.getByRole('heading', { name: 'UVC Camera Discovery', exact: true }).locator('..');
}

async function archivePlayback() {
  await nav('Recordings');
  const loop = page.getByRole('button', { name: 'Loop recordings', exact: true });
  const events = page.getByRole('button', { name: 'Event recordings', exact: true });
  if (preview9) {
    assert.equal(await loop.getAttribute('aria-pressed'), 'true');
    assert.equal(await events.getAttribute('aria-pressed'), 'false');
  }
  await events.click();
  if (preview9) {
    assert.equal(await events.getAttribute('aria-pressed'), 'true');
    assert.equal(await loop.getAttribute('aria-pressed'), 'false');
    assert.notEqual(await loop.evaluate(el => getComputedStyle(el).backgroundColor),
                    await events.evaluate(el => getComputedStyle(el).backgroundColor));
    await loop.click();
    assert.equal(await loop.getAttribute('aria-pressed'), 'true');
    assert.equal(await events.getAttribute('aria-pressed'), 'false');
    await events.click();
  }
  await page.getByRole('heading', { name: new RegExp('^'+eventLabel) }).waitFor();
  await page.getByRole('button', { name: 'Play QA camera 1', exact: true }).click();
  const video = page.getByRole('dialog').locator('video');
  await video.waitFor();
  await video.evaluate(v => { v.muted = true; void v.play().catch(() => {}); });
  await until(() => video.evaluate(v => ({ width: v.videoWidth, time: v.currentTime, duration: v.duration })),
    v => v.width > 0 && v.time > .1 && Math.abs(v.duration - 1) <= .15, 'Event video playback and duration', 30);
}

async function archiveEvent() {
  await nav('Settings'); await settingsReady(); await category('Recording');
  await page.getByLabel('Enable event recordings', { exact: true }).check();
  await page.getByLabel('Event recording folder', { exact: true }).fill(eventFolder);
  await page.getByLabel('Maximum lookback (seconds)', { exact: true }).fill('90');
  const configured = page.waitForResponse(r => r.url().endsWith(eventApi+'/settings') && r.request().method() === 'PUT');
  await page.getByRole('button', { name: 'Save event settings', exact: true }).click();
  assert.equal((await configured).status(), 200, 'Could not save event recording settings');
  const token = await page.getByLabel('Event token (copy it now)', { exact: true }).inputValue();
  assert(token.length >= 32);
  const settings = await json(eventApi+'/settings');
  assert.equal(settings.enabled, true);
  assert.equal(settings.max_lookback_sec, 90);
  assert.equal(settings.token, undefined);
  const clips = await until(() => json('/api/v1/recordings?status=stable&stream_id=qa-camera-1&time_basis=recorded'),
    value => value.items.some(clip => clip.duration_sec > 1.2), 'Finalized event input');
  const input = clips.items.find(clip => clip.duration_sec > 1.2);
  const occurred = new Date((input.ended_at - .05) * 1000);
  const payload = { camera_ids: ['qa-camera-1'], lookback_sec: 1, occurred_at: occurred.toISOString(), label: eventLabel };
  // A separate request context supplies only the synthetic equipment credential.
  const device = await browser.newContext({ extraHTTPHeaders: { Authorization: 'Bearer '+token } });
  let result;
  try {
    const response = await device.request.post(new URL(eventApi, origin).href, { data: payload,
      headers: { 'Idempotency-Key': 'fixture-fault-01' } });
    assert.equal(response.status(), 202, await response.text());
    const submitted = await response.json();
    assert.equal(submitted.occurred_at, occurred.getTime() / 1000);
    const status = new URL(eventApi+'/'+submitted.id, origin).href;
    result = await until(async () => (await device.request.get(status)).json(),
      value => ['ready','partial','unavailable','failed'].includes(value.status), 'Equipment recording result', 60);
  } finally {
    await device.close();
  }
  assert.equal(result.status, 'ready', result.detail);
  assert.equal(result.clips.length, 1);
  assert.equal(result.clips[0].ended_at - result.clips[0].started_at, 1);
  await archivePlayback();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('dialog').getByRole('link', { name: 'Download', exact: true }).click();
  await (await downloaded).saveAs(join(output, 'event-download.mp4'));
  await writeFile(join(output, 'event-selection.json'), JSON.stringify({ event_id: result.id,
    clip_index: Number(result.clips[0].file_id.split('.').at(-1)) }));
  await page.getByRole('button', { name: 'Close player', exact: true }).click();
  await nav('Settings'); await settingsReady(); await category('Recording');
  const rotated = page.waitForResponse(r => r.url().endsWith(eventApi+'/settings') && r.request().method() === 'PUT');
  await page.getByRole('button', { name: 'Replace event token', exact: true }).click();
  assert.equal((await rotated).status(), 200, 'Could not replace event recording token');
  const replacement = await page.getByLabel('Event token (copy it now)', { exact: true }).inputValue();
  assert.notEqual(replacement, token);
  stages.push('GUI-event-settings-and-equipment-API-archive-playback-and-download');
}

async function applyUvcCamera() {
  const usb = usbDiscovery();
  await usb.getByRole('button', { name: /^FlintEye QA USB camera/ }).click();
  await usb.getByLabel('Path', { exact: true }).fill('qa-camera-2');
  await usb.getByLabel('Camera Name', { exact: true }).fill('QA camera 2');
  await usb.getByRole('button', { name: 'Apply Device', exact: true }).click();
  await page.getByText('UVC device applied.', { exact: true }).waitFor();
  await settingsReady();
}

async function checkBranding() {
  await until(() => page.title(), title => title === branding.app_title, 'Saved browser tab title');
  assert.equal(await page.locator('.topbar-title').innerText(), branding.app_title);
  assert.match(await page.locator('.sidebar').innerText(), /QA Cameras/);
  assert.equal(await page.locator('.app-footer').innerText(), branding.footer_text);
}

async function configureSettings() {
  await nav('Settings'); await settingsReady();
  await category('General');
  for (const [label, key] of [['App Title', 'app_title'], ['Sidebar Title', 'sidebar_title'], ['Footer Text', 'footer_text']]) {
    await page.getByRole('textbox', { name: new RegExp('^'+label) }).fill(branding[key]);
  }
  await category('Quick settings');
  await page.getByRole('combobox', { name: 'Log level', exact: true }).selectOption('WARNING');
  await category('Logging');
  assert.equal(await page.getByRole('combobox', { name: /^Log Level/ }).inputValue(), 'WARNING');
  await page.getByRole('combobox', { name: /^Log Level/ }).selectOption('INFO');
  await category('Quick settings');
  assert.equal(await page.getByRole('combobox', { name: 'Log level', exact: true }).inputValue(), 'INFO');
  await category('Runtime & access');
  await page.getByLabel(/^Session TTL/).fill('7200');
  await page.getByText('Advanced runtime options', { exact: true }).click();
  await page.getByLabel(/^Thumbnail Refresh Interval/).fill('2');
  await category('Recording');
  await page.getByRole('checkbox', { name: 'Recording Enabled', exact: true }).check();
  await page.getByRole('checkbox', { name: 'Record all configured cameras', exact: true }).uncheck();
  await page.getByRole('checkbox', { name: 'Include multiview paths', exact: true }).check();
  await page.getByLabel(/^Additional Record Paths/).fill('qa-camera-1\nqa-camera-2');
  await page.getByLabel(/^Segment Duration/).fill('2s');
  await page.getByLabel(/^Record Part Duration/).fill('200ms');
  if (eventFolder) {
    await header.getByRole('button', { name: 'Save changes', exact: true }).click();
    await nav('Dashboard');
  } else {
    await saveCameraForm();
  }
  const config = await json('/api/v1/config/effective');
  for (const [key, value] of Object.entries(branding)) assert.equal(config.ui[key], value);
  assert.equal(config.logging.level, 'INFO');
  assert.equal(config.auth.session_ttl_sec, 7200);
  assert.equal(config.snapshot.thumbnail_refresh_interval_sec, 2);
  assert.deepEqual(config.recording.record_paths, ['qa-camera-1', 'qa-camera-2']);
  assert.equal(config.recording.record_segment_duration, '2s');
  assert.equal(config.recording.record_part_duration, '200ms');
  assert.equal(config.recording.include_multiview, true);
  await checkBranding();
}

async function configureMultiview() {
  await category('Multiview');
  await page.getByRole('checkbox', { name: /^Multiview Enabled/ }).check();
  await page.getByRole('combobox', { name: /^Source Mode/ }).selectOption('env');
  for (const index of [1, 2]) await page.getByRole('checkbox', { name: new RegExp(`^QA camera ${index}`) }).check();
  await page.getByLabel(/^Tile Count/).fill('2');
  await page.getByRole('spinbutton', { name: /^FPS\b/ }).fill('5');
  await page.getByLabel(/^Encoder/).fill('libx264');
  await page.getByRole('combobox', { name: /^Quality Preset/ }).selectOption('low');
  await saveCameraForm();
  const { multiview: config } = await json('/api/v1/config/effective');
  assert.deepEqual(config.source_paths, ['qa-camera-1', 'qa-camera-2']);
  assert.equal(config.enabled, true);
  assert.equal(config.tile_count, 2);
  assert.equal(config.quality.fps, 5);
  assert.equal(config.quality.encoder, 'libx264');
  assert.equal(config.quality.quality_preset, 'low');
}

async function verifyApiKeys() {
  await nav('Settings'); await category('Runtime & access'); await settingsReady();
  const panel = page.locator('.api-access');
  await panel.locator('summary').click();
  const name = panel.getByLabel('API key name', { exact: true });
  const permissions = panel.getByRole('combobox', { name: /^API key permissions/ });
  const key = panel.getByLabel('New API key (copy it now)', { exact: true });
  const anonymous = await browser.newContext();
  try {
    async function issue(label, scope) {
      await name.fill(label);
      await permissions.selectOption(scope);
      await panel.getByRole('button', { name: 'Create API key', exact: true }).click();
      await key.waitFor();
      const token = await key.inputValue();
      assert(token.startsWith('fe_api_'));
      return { Authorization: 'Bearer '+token };
    }
    const fetch = (path, headers, method = 'GET') =>
      anonymous.request.fetch(new URL(path, origin).href, { method, headers });
    const reader = await issue('QA retained read key', 'read');
    assert.equal((await fetch('/api/v1/status/monitoring', reader)).status(), 200);
    assert.equal((await fetch('/api/v1/control/stop', reader, 'POST')).status(), 403);
    await panel.getByRole('button', { name: 'Hide key', exact: true }).click();
    await key.waitFor({state: 'hidden'});
    const controller = await issue('QA retired monitoring key', 'monitor');
    assert.equal((await fetch('/api/v1/status/monitoring', controller)).status(), 200);
    assert.equal((await fetch('/api/v1/config/runtime', controller)).status(), 403);
    await panel.getByRole('listitem').filter({hasText: 'QA retired monitoring key'})
      .getByRole('button', { name: 'Revoke key', exact: true }).click();
    await panel.getByText('Revoked', { exact: true }).waitFor();
    assert.equal((await fetch('/api/v1/status/monitoring', controller)).status(), 401);
    assert.equal((await fetch('/api/v1/status/monitoring', reader)).status(), 200);
    assert.equal(await key.count(), 0);
  } finally {
    await anonymous.close();
  }
  stages.push('GUI-API-key-issue-read-deny-and-revoke');
}

async function verifyRetainedApiKeys() {
  await nav('Settings'); await category('Runtime & access'); await settingsReady();
  const panel = page.locator('.api-access');
  await panel.locator('summary').click();
  const items = panel.getByRole('listitem');
  await items.filter({hasText: 'QA retained read key'}).getByText('Active', {exact: true}).waitFor();
  await items.filter({hasText: 'QA retired monitoring key'}).getByText('Revoked', {exact: true}).waitFor();
  assert.equal(await panel.getByLabel('New API key (copy it now)', {exact: true}).count(), 0);
  stages.push('retained-API-key-metadata');
}

async function verifyMultiviewPositions() {
  const route = '/api/v1/multiview/views';
  const pair = ['qa-camera-1', 'qa-camera-2'];
  const third = 'qa-camera-3';
  const quadrantCenters = [[.25,.25], [.75,.25], [.25,.75], [.75,.75]];
  const completedClipAfter = async (start, label) => {
    const result = await until(
      () => json('/api/v1/recordings?status=stable&stream_id=multiview_1&recorded_from='+start),
      result => result.items.some(clip => clip.started_at >= start), label);
    return result.items.find(clip => clip.started_at >= start).relative_path;
  };
  const positions = async (sources, slots) => {
    const response = await until(() => json(route), result => result.items.length === 1 &&
      result.items[0].status?.phase !== 'starting' && Boolean(result.items[0].status) &&
      JSON.stringify(result.items[0].sources) === JSON.stringify(sources), 'Current compositor source list');
    const rows = response.items[0].source_items;
    assert.deepEqual(rows.map(row => row.slot), slots);
  };
  await patch({multiview: { source_mode: 'hybrid', tile_count: 4 }});
  await positions(pair, [1, 2]);
  await nav('Multiview');
  await videoProgress('Two independent tiles with camera audio active', {markers: ['red', 'blue', 'black', 'black'],
    points: [[.25,.5], [.75,.5], [.25,.1], [.75,.9]]});
  await page.getByText('2 sources', {exact: false}).first().waitFor();
  const automaticRecording = await completedClipAfter(Date.now()/1000, 'New recording of two horizontal tiles');

  const existing = await json('/api/v1/config/effective');
  await api('/api/v1/cameras', 'POST', {id: third, path: third, display_name: 'QA camera 3', type: 'ip',
    ip: {source_url: values['fixture-url']+'/qa-input-3', onvif_mode: 'disabled'}});
  await positions([...pair, third], [1, 2, 3]);
  await nav('Settings'); await category('Multiview');
  await page.getByRole('checkbox', { name: /^QA camera 3/ }).check();
  const layout = page.getByRole('region', {name: 'Multiview layout preview'});
  await layout.getByRole('button', {name: 'Arrange cameras', exact: true}).click();
  await layout.getByRole('button', {name: 'Slot 1 · QA camera 1'}).dragTo(layout.getByRole('button', {name: 'Slot 4 · Empty'}));
  await layout.getByRole('button', {name: 'Slot 2 · QA camera 2'}).click();
  await layout.getByRole('button', {name: 'Slot 1 · Empty'}).click();
  await saveCameraForm();
  const persisted = ['qa-camera-2', null, third, 'qa-camera-1'];
  assert.deepEqual((await json('/api/v1/config/effective')).multiview.layout.source_slots, [persisted]);
  await layout.getByRole('button', {name: 'Slot 4 · QA camera 1'}).waitFor();
  await positions(persisted.filter(Boolean), [1, 3, 4]);
  const measuredAfter = Date.now()/1000;
  await nav('Multiview');
  await videoProgress('Three different cameras in configured positions with an empty slot',
    {markers: ['blue', 'black', 'green', 'red'], points: quadrantCenters});
  await page.getByText('3 sources', {exact: false}).first().waitFor();
  const arrangedRecording = await completedClipAfter(measuredAfter, 'New recording of arranged Multiview');
  await writeFile(join(output, 'multiview-layout-samples.json'), JSON.stringify({
    automatic: automaticRecording, arranged: arrangedRecording,
  }));
  const viewer = await browser.newContext();
  try {
    const login = await viewer.request.post(new URL('/api/v1/auth/login', origin).href, {
      data: {username: 'viewer', password: viewerPassword}, headers: {Origin: origin.origin},
    });
    assert.equal(login.status(), 200);
    const response = await viewer.request.get(new URL(route, origin).href);
    assert.deepEqual((await response.json()).items[0].sources, persisted.filter(Boolean));
  } finally {
    await viewer.close();
  }
  await page.screenshot({path: join(output, 'Multiview-arranged.png')});
  await api('/api/v1/cameras/'+third, 'DELETE');
  await patch({multiview: existing.multiview});
  await positions(pair, [1, 2]);
  stages.push('Multiview-2-and-3-source-positions-and-audio-isolation');
}

async function verifyPtzMovement() {
  const pan = page.getByRole('button', { name: 'Pan right', exact: true });
  await pan.focus();
  await page.keyboard.down('Enter');
  const events = async () => (await context.request.get(new URL('/events', onvif).href)).json();
  const match = (rows, op) => rows.some(row => row.operation === op && row.profile === 'qa-main');
  try {
    await until(events, rows => match(rows, 'ContinuousMove'), 'Physical-command SOAP received by loopback fixture', 15);
  } finally {
    await page.keyboard.up('Enter');
  }
  await until(events, rows => match(rows, 'Stop'), 'Release sent a PTZ Stop to the fixture', 15);
  stages.push('GUI-ONVIF-inspect-and-PTZ-movement');
}

async function renameCameras() {
  const before = (await json('/api/v1/viewer/cameras')).items;
  const clipIds = (await json('/api/v1/recordings?status=stable&limit=100')).items.map(clip => clip.file_id);
  assert(clipIds.length > 0, 'Camera rename must run with existing finalized clips');
  await nav('Settings'); await category('Cameras'); await settingsReady();
  const ip = page.locator('.ip-camera-card').filter({hasText: 'QA camera 1'});
  await ip.getByLabel('Display Name', { exact: true }).fill(renamedIp);
  if (!values['synthetic-uvc']) {
    await page.locator('.ip-camera-card').filter({hasText: 'QA camera 2'}).getByLabel('Display Name', { exact: true }).fill(renamedSecond);
  }
  await saveCameraForm();
  if (values['synthetic-uvc']) {
    const usb = usbDiscovery();
    await usb.getByRole('row', { name: /QA camera 2/ }).getByRole('button', { name: 'Select Device' }).click();
    await usb.getByLabel('Camera Name', { exact: true }).fill(renamedSecond);
    await usb.getByRole('button', { name: 'Apply Device', exact: true }).click();
    await page.getByText('UVC device applied.', { exact: true }).waitFor();
    await settingsReady();
  }
  const after = (await json('/api/v1/viewer/cameras')).items;
  for (const [index, label, marker] of [[1, renamedIp, 'red'], [2, renamedSecond, 'blue']]) {
    const item = after.find(camera => camera.id === `qa-camera-${index}`);
    assert.equal(item.label, label);
    assert.deepEqual(item.addresses, before.find(camera => camera.id === item.id).addresses);
    await nav('Live View');
    await page.getByRole('button', { name: 'View '+label, exact: true }).click();
    await videoProgress('Renamed camera still shows its original video', { markers: [marker] });
  }
  await nav('Information');
  await page.getByText(renamedIp, { exact: true }).first().waitFor();
  await page.getByText(renamedSecond, { exact: true }).first().waitFor();
  const afterClips = (await json('/api/v1/recordings?status=stable&limit=5000')).items;
  assert(clipIds.every(id => afterClips.some(clip => clip.file_id === id)), 'Renaming hid previously finalized clips');
  stages.push('GUI-camera-rename-preserves-stream-and-recordings');
}

async function verifyPathChange() {
  // Run while monitoring is stopped so this case does not create a second
  // stream in the recording/hash acceptance check.
  await nav('Settings'); await category('Cameras'); await settingsReady();
  const path = page.locator('.ip-camera-card').filter({hasText: renamedIp}).getByLabel('MediaMTX Path', { exact: true });
  await path.fill('qa-camera-2');
  await header.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByText(/Camera paths must be unique/).waitFor();
  assert.deepEqual((await json('/api/v1/config/effective')).recording.record_paths, ['qa-camera-1', 'qa-camera-2']);
  for (const replacement of ['qa-changed-path', 'qa-camera-1']) {
    await path.fill(replacement);
    await saveCameraForm();
    const config = await json('/api/v1/config/effective');
    const camera = config.cameras.find(camera => camera.id === replacement);
    assert.equal(camera.display_name, renamedIp);
    assert.equal(camera.audio.enabled, true);
    assert.equal(camera.ip.ptz.enabled, true);
    assert.deepEqual(config.recording.record_paths, [replacement, 'qa-camera-2']);
    assert.deepEqual(config.multiview.source_paths, [replacement, 'qa-camera-2']);
    const addresses = await json(`/api/v1/cameras/${replacement}/addresses`);
    assert(addresses.webrtc_url?.includes(replacement), JSON.stringify(addresses));
  }
  stages.push('GUI-rejects-duplicate-and-migrates-paths');
}

async function videoProgress(label, { audio = false, markers = [], points = [] } = {}) {
  const frame = page.frameLocator('iframe.webrtc-frame');
  const video = frame.locator('video');
  await until(async () => {
    try {
      return await video.evaluate(async (v, { audio, markers, points }) => {
        v.muted = true;
        if (v.paused) void v.play().catch(() => {});
        if (v.readyState < 2 || !v.videoWidth) return { ready: v.readyState, width: v.videoWidth };
        // Measure progression within a single player. A timestamp read from
        // the previous iframe would be meaningless after navigation.
        const before = v.currentTime;
        await new Promise(resolve => setTimeout(resolve, 750));
        if (!v.isConnected || !v.videoWidth) return { state: 'player reloading' };
        const sample = { elapsed: v.currentTime - before, width: v.videoWidth };
        if (markers.length) {
          const canvas = document.createElement('canvas');
          canvas.width = 1;
          canvas.height = 1;
          const ctx = canvas.getContext('2d');
          sample.markers = markers.map((_, index) => {
            const [x, y] = points[index] ?? [(index + .5) / markers.length, .5];
            ctx.drawImage(v, Math.floor(v.videoWidth*x), Math.floor(v.videoHeight*y), 1, 1, 0, 0, 1, 1);
            const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
            if (r > Math.max(g, b) + 80) return 'red';
            if (b > Math.max(r, g) + 80) return 'blue';
            if (g > Math.max(r, b) + 80) return 'green';
            return Math.max(r, g, b) < 25 ? 'black' : 'unknown';
          });
        }
        if (audio) {
          const stats = await Promise.all((globalThis.__flinteyeQaPeers || []).map(peer => peer.getStats()));
          sample.audioBytes = stats.flatMap(report => [...report.values()])
            .filter(item => item.type === 'inbound-rtp' && item.kind === 'audio')
            .reduce((total, item) => total + (item.bytesReceived || 0), 0);
        }
        return sample;
      }, { audio, markers, points }, { timeout: 2000 });
    } catch (error) {
      if (error.name === 'TimeoutError' || /Execution context was destroyed|frame was detached/i.test(error.message)) {
        return { state: 'waiting for current player' };
      }
      throw error;
    }
  }, sample => sample.elapsed > .25 && markers.every((marker, index) => sample.markers?.[index] === marker) &&
    (!audio || sample.audioBytes > 0), label);
}
try {
  const desktopHandoff = values['synthetic-uvc'] && !values.retained;
  if (desktopHandoff) {
    const launch = join(values.profile, 'qa-browser-url.txt');
    const localSetup = await until(() => readFile(launch, 'utf8').catch(error => {
      if (error.code === 'ENOENT') return '';
      throw error;
    }), value => value.startsWith('file:'), 'Desktop launcher delivered a local setup page', 30);
    const handoff = page.waitForResponse(response => response.url() === new URL('/api/v1/setup/handoff', origin).href);
    await page.goto(localSetup);
    assert.equal((await handoff).status(), 303, 'Local setup page must exchange its one-use code');
    await page.waitForURL(origin.href);
  } else {
    await page.goto(origin.href);
  }
  if (!values.retained) {
    await page.getByRole('heading', { name: 'Welcome to FlintEye' }).waitFor();
    const setupToken = page.getByLabel(/^(Server )?Setup token$/i);
    if (desktopHandoff) {
      assert.equal(await setupToken.count(), 0, 'Desktop setup must only ask for a password');
      stages.push('desktop-browser-one-use-setup-handoff');
    } else {
      await setupToken.fill((await readFile(join(values.profile, 'setup-token'), 'utf8')).trim());
    }
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
    // Pin recording policy so camera removal can be checked without a
    // separate recording configuration change that requires a media restart.
    if (onvif) await configureSettings();
    else await patch({ recording: { enabled: true, record_all_cameras: false, record_paths: ['qa-camera-1', 'qa-camera-2'], record_segment_duration: '2s', record_part_duration: '200ms', include_multiview: true },
      snapshot: { thumbnail_refresh_interval_sec: 2 }, multiview: { enabled: false } });
    await nav('Settings'); await category('Cameras');
    const ptzCamera = await addIpCamera(1);
    if (onvif) {
      const toggle = ptzCamera.getByRole('checkbox', { name: 'Enable PTZ', exact: true });
      assert(await toggle.isDisabled());
      await ptzCamera.getByRole('button', { name: 'Inspect camera', exact: true }).click();
      await ptzCamera.getByText('PTZ is available on 2 media profile(s)', { exact: true }).waitFor({ timeout: 60_000 });
      assert.equal(await toggle.isChecked(), false);
      await toggle.check();
      await ptzCamera.locator('.ip-ptz-panel').getByRole('combobox', { name: /^ONVIF media profile/ }).selectOption('qa-main');
    }
    if (!values['synthetic-uvc']) await addIpCamera(2);
    await saveCameraForm();
    if (values['synthetic-uvc']) await applyUvcCamera();
    await until(() => json('/api/v1/cameras'), value => value.items.filter(c => c.id.startsWith('qa-camera-')).length === 2, 'GUI camera save');
    const effective = await json('/api/v1/config/effective');
    const cameras = effective.cameras;
    assert.equal(cameras.find(c => c.id === 'qa-camera-2').type, values['synthetic-uvc'] ? 'uvc' : 'ip');
    assert(cameras.every(c => c.audio?.enabled !== true), 'Camera audio must default off');
    if (onvif) {
      assert.equal(cameras.find(c => c.id === 'qa-camera-1').ip.ptz.enabled, true);
      await configureMultiview();
      stages.push('GUI-settings-save-and-effective-values');
    } else await patch({ multiview: { enabled: true, source_mode: 'env', source_paths: ['qa-camera-1', 'qa-camera-2'], tile_count: 2,
        input_rtsp_base_url: effective.mediamtx.internal_rtsp_base_url || effective.mediamtx.rtsp_base_url,
        output_rtsp_base_url: effective.mediamtx.internal_rtsp_base_url || effective.mediamtx.rtsp_base_url,
        mtx_api_url: effective.multiview.mtx_api_url,
        quality: { fps: 5, encoder: 'libx264', gop: 5, quality_preset: 'low' }, layout: { canvas_width: 640, canvas_height: 360, grid_columns: 2 } } });
    stages.push('GUI-register-two-cameras-and-save');
    await nav('Information'); await nav('Settings'); await category('Cameras');
    const audioCard = page.locator('.ip-camera-card').first();
    if (preview9) {
      const panel = audioCard.locator('.camera-audio-toolbar');
      assert.equal(await audioCard.getByRole('button', { name: 'Save camera audio', exact: true }).count(), 0);
      const compact = await panel.boundingBox();
      assert(compact && compact.height < 150, 'Camera audio occupies more than two compact rows');
    }
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
    if (onvif) {
      assert.equal(config.cameras.find(camera => camera.id === 'qa-camera-1').display_name, renamedIp);
      assert.equal(config.cameras.find(camera => camera.id === 'qa-camera-2').display_name, renamedSecond);
      assert.equal(config.cameras.find(camera => camera.id === 'qa-camera-1').ip.ptz.profile_token, 'qa-main');
      await checkBranding();
      await nav('Live View');
      await page.getByRole('button', { name: 'View '+renamedIp, exact: true }).click();
      await videoProgress('Retained renamed camera receives its original video', {markers: ['red']});
      assert.equal((await json('/api/v1/cameras/qa-camera-1/ptz/capabilities')).supported, true);
      stages.push('retained-branding-rename-and-PTZ');
    }
  }
  // Every main screen is served by the installed application, not Vite or a mock.
  for (const name of ['Dashboard', 'Information', 'Settings', 'Live View', 'Multiview', 'Recordings']) {
    await nav(name); await page.locator('.page').first().waitFor();
    await page.screenshot({ path: join(output, name.replaceAll(' ', '-')+'.png'), fullPage: true });
  }
  stages.push('all-six-main-screens');
  if (values.retained && eventFolder) {
    const settings = await json(eventApi+'/settings');
    assert.equal(settings.enabled, true);
    assert.equal(settings.token_configured, true);
    await archivePlayback();
    await page.getByRole('button', { name: 'Close player', exact: true }).click();
    stages.push('retained-event-recording-settings-and-playback');
  }
  if (values.retained && preview9) await verifyRetainedApiKeys();
  if (!values.retained) {
    await until(() => json('/api/v1/viewer/cameras'), value => value.items.length === 2 && value.items.every(c => c.health?.state === 'healthy'), 'Two receiving camera workers', 120);
    await nav('Live View');
    for (const [i, marker] of [[1, 'red'], [2, 'blue']]) {
      await page.getByRole('button', { name: 'View QA camera '+i, exact: true }).click();
      await videoProgress('Live camera '+i, { audio: i === 1, markers: [marker] });
      if (onvif && i === 1) await verifyPtzMovement();
    }
    stages.push('both-live-cameras-show-their-own-marker');
    await page.screenshot({ path: join(output, 'Live-View-playing.png') });
    await nav('Multiview'); await videoProgress('Both camera tiles in one advancing Multiview frame', { markers: ['red', 'blue'] });
    await page.screenshot({ path: join(output, 'Multiview-playing.png') });
    stages.push('live-and-multiview-real-WebRTC-frame-progress', 'multiview-shows-both-camera-markers');
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
    if (eventFolder) await archiveEvent();
    if (preview9) stages.push('GUI-compact-camera-audio-and-recording-tab-selection');

    const redBefore = (await json('/api/v1/status/processes')).items.find(stream => stream.id === 'camera:qa-camera-1');
    assert.equal(redBefore.status, 'running');
    await nav('Settings'); await category('Cameras'); await settingsReady();
    if (values['synthetic-uvc']) {
      await usbDiscovery().getByRole('row', { name: /QA camera 2/ }).getByRole('button', { name: 'Ignore / Remove', exact: true }).click();
      await settingsReady();
    } else {
      await page.locator('.ip-camera-card').filter({ hasText: 'QA camera 2' }).getByRole('button', { name: 'Remove', exact: true }).click();
      await saveCameraForm();
    }
    await until(() => json('/api/v1/viewer/cameras'), value => value.items.length === 1 && value.items[0].id === 'qa-camera-1' && value.items[0].health?.state === 'healthy', 'Remaining camera receiving after removal');
    const afterRemoval = (await json('/api/v1/status/processes')).items;
    assert(afterRemoval.every(stream => stream.id !== 'camera:qa-camera-2' || stream.status !== 'running'), 'Removed publisher is still running');
    assert.equal(afterRemoval.find(stream => stream.id === 'camera:qa-camera-1').pid, redBefore.pid, 'Removing a camera restarted the other publisher');
    await nav('Live View');
    await page.getByRole('button', { name: 'View QA camera 1', exact: true }).click();
    await videoProgress('Remaining camera after removal', { markers: ['red'] });
    assert.equal(await page.getByRole('button', { name: 'View QA camera 2', exact: true }).count(), 0);
    await nav('Settings'); await category('Cameras'); await settingsReady();
    if (values['synthetic-uvc']) {
      await usbDiscovery().getByRole('button', { name: /^FlintEye QA USB camera/ }).click();
      await usbDiscovery().getByRole('button', { name: 'Restore to Discovery', exact: true }).click();
      await settingsReady();
      await applyUvcCamera();
    } else {
      await addIpCamera(2);
      await saveCameraForm();
    }
    await until(() => json('/api/v1/viewer/cameras'), value => value.items.length === 2 && value.items.every(c => c.health?.state === 'healthy'), 'Re-added camera receives video', 120);
    if (preview9) await patch({multiview: {source_paths: ['qa-camera-1', 'qa-camera-2']}});
    await nav('Multiview');
    await videoProgress('Both camera tiles after re-adding the second camera', { markers: ['red', 'blue'] });
    stages.push('GUI-remove-and-readd-camera-keeps-other-publisher');
    if (values['synthetic-uvc']) stages.push('synthetic-USB-and-IP-live-multiview-and-removal');

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
    if (preview9) {
      await verifyApiKeys();
      await verifyMultiviewPositions();
    }
    if (onvif) await renameCameras();
    await nav('Dashboard');
    await page.getByRole('button', { name: 'Stop monitoring', exact: true }).click();
    await until(() => json('/api/v1/status/monitoring'), value => value.desired_running === false && value.phase === 'stopped' && !value.busy, 'GUI monitoring Stop', 90);
    assert.equal((await api('/api/v1/health')).status(), 200);
    assert.equal((await json('/api/v1/status/mediamtx')).running, false);
    await patch({ ui: { onboarding_done: true } });
    assert.equal((await json('/api/v1/status/mediamtx')).running, false);
    assert((await json('/api/v1/status/processes')).items?.every(p => p.status !== 'running' && p.pid === null) ?? false, 'Owned publishers survived Stop');
    stages.push('GUI-stop-keeps-API-and-saved-settings-cannot-restart-monitoring');
    if (onvif) {
      await verifyPathChange();
      await nav('Dashboard');
    }
    const resumedAfter = Date.now() / 1000;
    await page.getByRole('button', { name: 'Start monitoring', exact: true }).click();
    const expectedStreams = ['qa-camera-1', 'qa-camera-2', 'multiview_1'];
    await until(async () => {
      const recordings = await json(`/api/v1/recordings?status=stable&recorded_from=${resumedAfter}`);
      const monitoring = await json('/api/v1/status/monitoring');
      return { streams: [...new Set(recordings.items.map(clip => clip.stream_id))], monitoring };
    }, ({ streams, monitoring }) => expectedStreams.every(stream => streams.includes(stream)) &&
      monitoring.desired_running && !monitoring.busy && monitoring.counts.receiving === 2 &&
      monitoring.counts.recording > 0, 'New recordings from both cameras and Multiview before normal Quit', 120);
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
