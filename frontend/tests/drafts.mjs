import { chooseSettingsCategory } from './settings-navigation.mjs';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';
process.chdir(fileURLToPath(new URL('../..', import.meta.url)));
mkdirSync('dist/terra-webapp-fixes', { recursive: true });
import assert from 'node:assert/strict';
import { chromium } from './browser.mjs';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
const root = process.cwd();
let patchMode = 'ok', folderMode = 'cancel', probeMode = 'ok', calls = [];
let pendingPatch = null;
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined, headless: true, args: ['--no-sandbox'] });
const config = { auth: { provider: 'local', viewer_auth_required: true, local: { admin: { username: 'admin' }, viewer: { username: 'viewer' } } }, ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: true }, recording: { enabled: true, managed_storage: true, record_root: '/tmp/Sample recordings', max_bytes: 50e9, record_delete_after: '168h', show_previous: true }, cameras: [], multiview: { enabled: false } };
const syntheticCameras = [{ id: 'usb1', type: 'uvc', enabled: true, path: 'usb1', display_name: 'Front USB Camera', uvc: { profile: 'usb1', env: { DEVICE: '/dev/video99' }, extra_args: [] }, ip: null, addresses: { rtsp_url: 'rtsp://example.test/usb1', webrtc_url: 'http://example.test/usb1' }, process: null }, { id: 'ipcam1', type: 'ip', enabled: true, path: 'ipcam1', display_name: 'Lobby IP Camera', uvc: null, ip: { source_url: 'rtsp://example.test/stream1' }, addresses: { rtsp_url: 'rtsp://example.test/ipcam1', webrtc_url: 'http://example.test/ipcam1' }, process: null }, { id: 'ipcam2', type: 'ip', enabled: true, path: 'ipcam2', display_name: 'Yard IP Camera', uvc: null, ip: { source_url: 'rtsp://example.test/stream2' }, addresses: { rtsp_url: 'rtsp://example.test/ipcam2', webrtc_url: 'http://example.test/ipcam2' }, process: null }];
config.cameras = syntheticCameras.map(({ id, type, enabled, path, display_name, uvc, ip }) => ({ id, type, enabled, path, display_name, uvc, ip }));
const device = { device_id: '/dev/video99', driver: 'v4l2', display_name: 'Front USB Camera', index: '99', ffmpeg_device: '/dev/video99', ffmpeg_device_index: '99', modes: [{ width: 1280, height: 720, fps: 30 }, { width: 640, height: 480, fps: 15 }], recommended: { width: 1280, height: 720, fps: 30 } };
const info = { api: { swagger_url: 'http://example.test/docs', redoc_url: 'http://example.test/redoc', openapi_url: 'http://example.test/openapi.json' }, rtsp_base_url: 'rtsp://example.test:8554', webrtc_base_url: 'http://example.test:8889', generated_at: 1700000000, snapshot: { timeout_sec: 5, thumbnail_refresh_interval_sec: 10 }, cameras: [], multiview: { enabled: false, output_prefix: 'multi', tile_count: 4, canvas_width: 1920, canvas_height: 1080, fps: 30, bitrate: '4M', encoder: 'h264', quality_preset: 'balanced' } };
async function context(scenario, width = 1440, height = 900, colorScheme = 'light') {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme });
    let errors = [];
    ctx.on('page', p => p.on('pageerror', e => errors.push(String(e))));
    await ctx.route('**/*', async (route) => {
        const req = route.request(), u = new URL(req.url());
        if (u.hostname !== '127.0.0.1')
            return route.abort();
        if (!u.pathname.startsWith('/api/')) {
            try {
                const f = resolve(root, 'frontend/dist', '.' + (u.pathname === '/' ? '/index.html' : u.pathname));
                return route.fulfill({ status: 200, contentType: ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(f)] || 'application/octet-stream', body: await readFile(f) });
            }
            catch {
                return route.fulfill({ status: 404 });
            }
        }
        let v = { items: [] }, status = 200;
        calls.push([req.method(), u.pathname, req.postData()]);
        switch (u.pathname) {
            case '/api/v1/status/monitoring':
                v = { state: 'running', color: 'green', label: 'Running', message: 'Receiving video', desired_running: true, busy: false, phase: 'running', resume_on_startup: false, counts: { configured: 0, targets: 0, receiving: 0, recording: 0 }, cameras: [] };
                break;
            case '/api/v1/monitoring/preferences':
                v = { resume_on_startup: false };
                break;
            case '/api/v1/build':
                v = { version: '1.1.1', release: '1.1.1', channel: 'stable', commit: null, dirty: false };
                break;
            case '/api/v1/auth/me':
                v = { authenticated: scenario === 'admin', role: scenario === 'admin' ? 'admin' : null, username: 'admin', viewer_auth_required: true, setup_required: scenario === 'setup', provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
                break;
            case '/api/v1/cameras':
                v = { items: syntheticCameras };
                break;
            case '/api/v1/uvc/devices':
                v = { items: [device], warning: '', driver: 'v4l2', ffmpeg_bin: 'ffmpeg' };
                break;
            case '/api/v1/ip-cameras/probe':
                await new Promise(r => setTimeout(r, 1800));
                if (probeMode === 'error') {
                    v = { detail: 'Permission denied while probing sample camera' };
                    status = 403;
                }
                else {
                    v = { ok: true, source: 'rtsp://example.test/stream1', inspected_at: 1700000000, elapsed_sec: 1.5, rtsp: { available: true, codec: 'h264', width: 1280, height: 720, observed_fps: 30, timestamp_healthy: true, frame_count: 30 }, onvif: { status: 'ok', supported: true, message: 'Synthetic ONVIF', profiles: [], ptz: { supported: false, service_available: false, message: 'PTZ unavailable' } }, recommendation: { timestamp_mode: 'source', cfr_fps: 30 } };
                }
                break;
            case '/api/v1/storage/pick-folder':
                if (folderMode === 'cancel')
                    v = { path: '' };
                else {
                    v = { detail: 'Folder picker unavailable' };
                    status = 500;
                }
                ;
                break;
            case '/api/v1/storage/suggest':
                v = { detail: 'Storage permission denied' };
                status = 403;
                break;
            case '/api/v1/config/effective':
            case '/api/v1/config/runtime':
                if (req.method() === 'PATCH' && pendingPatch) await pendingPatch;
                if (req.method() === 'PATCH' && patchMode === 'conflict') {
                    v = { detail: 'Configuration changed. Reload and try again.' };
                    status = 412;
                    break;
                }
                v = config;
                break;
            case '/api/v1/status':
                v = { mediamtx: { running: true, status: 'running', mode: 'direct' }, cameras_enabled: 0, cameras_total: 0, multiview_enabled: false, running_processes: 1, processes: { items: [] } };
                break;
            case '/api/v1/viewer/info':
                v = info;
                break;
            case '/api/v1/multiview/status':
                v = { updated_at: null, views: [] };
                break;
            case '/api/v1/recordings':
                v = { items: [], total: 0, limit: 50, offset: 0 };
                break;
            case '/api/v1/recordings/streams':
                v = { items: [], record_root: '/tmp/Sample recordings' };
                break;
            case '/api/v1/desktop':
                v = { folder_picker: true };
                break;
            case '/api/v1/storage/status':
                v = { message: '' };
                break;
            case '/api/v1/updates':
                v = { available: false, current: '1.1.1' };
                break;
            case '/api/v1/auth/login':
                v = { detail: 'Incorrect username or password' };
                status = 401;
                break;
        }
        return route.fulfill({ status, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(v) });
    });
    const p = await ctx.newPage();
    await p.goto('http://127.0.0.1:12345');
    await p.waitForTimeout(500);
    const closeContext = ctx.close.bind(ctx);
    ctx.close = async () => { await closeContext(); assert.deepEqual(errors, [], 'unexpected page errors'); };
    return { ctx, p, errors };
}
async function run(n, fn) { try {
    await fn();
    console.log('PASS', n);
}
catch (e) {
    console.error('FAIL', n, e.message);
    process.exitCode = 1;
} }
try {
    for (const conflict of [false, true]) {
        await run(conflict ? 'navigation stays after a rejected save' : 'navigation follows a completed save', async () => {
            const { ctx, p } = await context('admin');
            const sidebar = p.locator('.sidebar');
            const dashboard = sidebar.getByRole('button', { name: 'Dashboard', exact: true });
            const settings = sidebar.getByRole('button', { name: 'Settings', exact: true });
            const confirmation = p.getByRole('dialog', { name: 'Discard unsaved changes?' });
            let releasePatch;
            try {
                await settings.click();
                await chooseSettingsCategory(p, 'General');
                const title = p.getByRole('textbox', { name: /^App Title/ });
                await title.fill('Pending save title');
                patchMode = conflict ? 'conflict' : 'ok';
                pendingPatch = new Promise(resolve => { releasePatch = resolve; });
                const sent = p.waitForRequest(request => request.method() === 'PATCH' && request.url().endsWith('/api/v1/config/runtime'));
                await p.getByRole('button', { name: 'Save changes', exact: true }).first().click();
                await sent;
                await dashboard.click();
                assert.equal(await settings.getAttribute('aria-current'), 'page');
                assert.equal(await confirmation.count(), 0);
                releasePatch();

                if (conflict) {
                    await p.getByText(/Settings changed in another session/).first().waitFor();
                    assert.equal(await settings.getAttribute('aria-current'), 'page');
                    assert.equal(await title.inputValue(), 'Pending save title');
                } else {
                    await sidebar.locator('button[aria-current="page"]').filter({ hasText: /^Dashboard$/ }).waitFor();
                    assert.equal(await confirmation.count(), 0);
                }
            } finally {
                releasePatch?.();
                pendingPatch = null;
                patchMode = 'ok';
                await ctx.close();
            }
        });
    }
    await run('1-refresh', async () => { const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); let title = p.getByRole('textbox', { name: /^App Title/ }); await title.fill('Unsaved test title'); await p.getByRole('button', { name: 'Refresh', exact: true }).first().click(); await p.getByRole('button', { name: 'Continue editing' }).click(); assert.equal(await title.inputValue(), 'Unsaved test title', 'refresh discarded draft'); await p.screenshot({ path: 'dist/terra-webapp-fixes/1-draft.png', fullPage: true }); await ctx.close(); });
    await run('1-navigation', async () => { const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); await p.getByRole('textbox', { name: /^App Title/ }).fill('Unsaved test title'); await p.locator('.sidebar').getByRole('button', { name: 'Dashboard', exact: true }).click(); await p.getByRole('button', { name: 'Continue editing' }).click(); if (await p.getByRole('textbox', { name: /^App Title/ }).count() === 0) {
        await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
        await chooseSettingsCategory(p, 'General');
    } assert.equal(await p.getByRole('textbox', { name: /^App Title/ }).inputValue(), 'Unsaved test title'); await ctx.close(); });
    await run('1-conflict', async () => { patchMode = 'conflict'; const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); const title = p.getByRole('textbox', { name: /^App Title/ }); await title.fill('Conflicting draft'); await p.getByRole('button', { name: 'Save changes', exact: true }).first().click(); await p.getByText(/Settings changed in another session/).first().waitFor(); assert.equal(await title.inputValue(), 'Conflicting draft'); await p.getByRole('button', { name: 'Refresh', exact: true }).first().click(); await p.getByRole('button', { name: 'Continue editing' }).click(); assert.equal(await title.inputValue(), 'Conflicting draft'); patchMode = 'ok'; await ctx.close(); });
    await run('1-device', async () => { calls.length = 0; const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); await p.getByRole('textbox', { name: /^App Title/ }).fill('Device protection draft'); await chooseSettingsCategory(p, 'Cameras'); await p.getByRole('button', { name: 'Ignore / Remove' }).first().click(); await p.getByText(/Save or discard/).first().waitFor(); assert.equal(calls.filter(x => x[0] === 'PATCH').length, 0); await chooseSettingsCategory(p, 'General'); assert.equal(await p.getByRole('textbox', { name: /^App Title/ }).inputValue(), 'Device protection draft'); await ctx.close(); });
    await run('1-discard-both', async () => { const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); await p.getByRole('textbox', { name: /^App Title/ }).fill('Both drafts'); await chooseSettingsCategory(p, 'Runtime JSON'); let editor = p.getByRole('textbox', { name: 'Full runtime JSON', exact: true }); const initial = await editor.inputValue(); await editor.fill(initial + ' '); await chooseSettingsCategory(p, 'Recording', { advanced: false }); const discard = p.locator('.settings-header-actions').getByRole('button', { name: 'Discard', exact: true }); await discard.click(); await p.getByRole('button', { name: 'Continue editing' }).click(); await chooseSettingsCategory(p, 'General'); assert.equal(await p.getByRole('textbox', { name: /^App Title/ }).inputValue(), 'Both drafts'); await chooseSettingsCategory(p, 'Runtime JSON'); assert.equal(await editor.inputValue(), initial + ' '); await chooseSettingsCategory(p, 'Recording', { advanced: false }); await discard.click(); await p.getByRole('button', { name: 'Discard changes' }).click(); await chooseSettingsCategory(p, 'General'); await p.waitForTimeout(300); assert.equal(await p.getByRole('textbox', { name: /^App Title/ }).inputValue(), 'FlintEye'); await chooseSettingsCategory(p, 'Runtime JSON'); assert.equal(await editor.inputValue(), initial); await ctx.close(); });
    await run('1-save', async () => { calls.length = 0; const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); await p.getByRole('textbox', { name: /^App Title/ }).fill('Saved test title'); await p.getByRole('button', { name: 'Save changes', exact: true }).first().click(); await p.waitForTimeout(400); assert.ok(calls.some(x => x[0] === 'PATCH' && x[1] === '/api/v1/config/runtime')); await ctx.close(); });
    await run('2-json-save', async () => { calls.length = 0; const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'Runtime JSON'); const editor = p.getByRole('textbox', { name: 'Full runtime JSON', exact: true }); const data = JSON.parse(await editor.inputValue()); data.ui.app_title = 'Saved JSON'; await editor.fill(JSON.stringify(data, null, 2)); await p.getByRole('button', { name: 'Save changes', exact: true }).first().click(); await p.waitForTimeout(400); assert.ok(calls.some(x => x[0] === 'PUT' && x[1] === '/api/v1/config/runtime')); await ctx.close(); });
    await run('2-advanced', async () => { const { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'Runtime JSON'); const editor = p.getByRole('textbox', { name: 'Full runtime JSON', exact: true }); const before = await editor.inputValue(); await editor.fill(before + ' '); assert.ok((await editor.getAttribute('aria-label')) || (await editor.getAttribute('aria-labelledby')) || await editor.evaluate(e => e.labels?.length), 'editor has no accessible name'); assert.doesNotMatch(await p.locator('.settings-save-state').innerText(), /All changes saved/i); await ctx.close(); });
}
finally {
    await browser.close();
}
