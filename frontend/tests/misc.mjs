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
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined, headless: true, args: ['--no-sandbox'] });
const config = { auth: { provider: 'local', viewer_auth_required: true, local: { admin: { username: 'admin' }, viewer: { username: 'viewer' } } }, ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: true }, recording: { enabled: true, managed_storage: true, record_root: '/tmp/Sample recordings', max_bytes: 50e9, record_delete_after: '168h', show_previous: true }, cameras: [], multiview: { enabled: false } };
const syntheticCameras = [{ id: 'usb1', type: 'uvc', enabled: true, path: 'usb1', display_name: 'Front USB Camera', uvc: { profile: 'usb1', env: { DEVICE: '/dev/video99' }, extra_args: [] }, ip: null, addresses: { rtsp_url: 'rtsp://example.test/usb1', webrtc_url: 'http://example.test/usb1' }, process: null }, { id: 'ipcam1', type: 'ip', enabled: true, path: 'ipcam1', display_name: 'Lobby IP Camera', uvc: null, ip: { source_url: 'rtsp://example.test/stream1' }, addresses: { rtsp_url: 'rtsp://example.test/ipcam1', webrtc_url: 'http://example.test/ipcam1' }, process: null }, { id: 'ipcam2', type: 'ip', enabled: true, path: 'ipcam2', display_name: 'Yard IP Camera', uvc: null, ip: { source_url: 'rtsp://example.test/stream2' }, addresses: { rtsp_url: 'rtsp://example.test/ipcam2', webrtc_url: 'http://example.test/ipcam2' }, process: null }];
config.cameras = syntheticCameras.map(({ id, type, enabled, path, display_name, uvc, ip }) => ({ id, type, enabled, path, display_name, uvc, ip }));
const device = { device_id: '/dev/video99', driver: 'v4l2', display_name: 'Front USB Camera', index: '99', ffmpeg_device: '/dev/video99', ffmpeg_device_index: '99', modes: [{ width: 1280, height: 720, fps: 30 }, { width: 640, height: 480, fps: 15 }], recommended: { width: 1280, height: 720, fps: 30 } };
const info = { api: { swagger_url: 'http://example.test/docs', redoc_url: 'http://example.test/redoc', openapi_url: 'http://example.test/openapi.json' }, rtsp_base_url: 'rtsp://example.test:8554', webrtc_base_url: 'http://example.test:8889', generated_at: 1700000000, snapshot: { timeout_sec: 5, thumbnail_refresh_interval_sec: 10 }, cameras: [], multiview: { enabled: false, output_prefix: 'multi', tile_count: 4, canvas_width: 1920, canvas_height: 1080, fps: 30, bitrate: '4M', encoder: 'h264', quality_preset: 'balanced' } };
async function context(scenario, width = 1440, height = 900, colorScheme = 'light', streamStatus) {
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
                v = { version: '1.2.0', release: '1.2.0-preview.3', channel: 'preview', commit: null, dirty: false };
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
                v = streamStatus ? { ...info, rtsp_base_url: 'rtsp://127.0.0.1:8554', cameras: [{
                    id: 'camera', label: 'Test camera', type: 'uvc', enabled: true,
                    addresses: { rtsp_url: 'rtsp://127.0.0.1:8554/camera',
                        client_rtsp_url: streamStatus === 'ready' ? 'rtsps://192.168.10.20:8322/camera' : null,
                        rtsp_status: streamStatus, webrtc_url: '/media/camera' }, settings: {},
                }] } : info;
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
    p.setDefaultTimeout(5000);
    await p.goto('http://127.0.0.1:12345');
    await p.waitForTimeout(500);
    const closeContext = ctx.close.bind(ctx);
    ctx.close = async () => { await closeContext(); assert.deepEqual(errors, [], 'unexpected page errors'); };
    return { ctx, p, errors };
}
async function run(name, fn) { try {
    await fn();
    console.log('PASS', name);
}
catch (e) {
    console.error('FAIL', name, e.message);
    process.exitCode = 1;
} }
try {
    await run('preview identity and client-facing RTSPS address', async () => {
        for (const status of ['ready', 'disabled']) {
            const { ctx, p } = await context('admin', 1440, 900, 'light', status);
            try {
                await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
                await p.locator('.sidebar').getByRole('button', { name: 'Information', exact: true }).click();
                await p.getByText('FlintEye 1.2.0-preview.3 · preview', { exact: true }).waitFor();
                const table = p.locator('.information-camera-table');
                assert.doesNotMatch(await table.innerText(), /127\.0\.0\.1|8554/);
                if (status === 'ready') {
                    await table.getByRole('button', { name: 'Copy', exact: true }).click();
                    await table.getByRole('status').waitFor();
                    assert.equal(await p.evaluate(() => navigator.clipboard.readText()), 'rtsps://192.168.10.20:8322/camera');
                } else {
                    await table.getByText('Network viewing disabled', { exact: true }).waitFor();
                    assert.equal(await table.getByRole('button', { name: 'Copy', exact: true }).count(), 0);
                }
                assert.equal(await p.getByText('rtsp://127.0.0.1:8554', { exact: true }).isVisible(), false);
            } finally { await ctx.close(); }
        }
    });
    await run('8 encoder search', async () => { let { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); const search = p.getByRole('searchbox', { name: 'Find a setting' }); await search.fill('Encoder'); await p.waitForTimeout(200); assert.doesNotMatch(await p.locator('.settings-page').innerText(), /0 settings found/i); await ctx.close(); });
    await run('10 mandatory login', async () => { let { ctx, p } = await context('viewer'); assert.equal(await p.getByRole('button', { name: 'Back', exact: true }).count(), 0); await ctx.close(); });
    await run('13 unsaved summary', async () => { let { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click(); await chooseSettingsCategory(p, 'General'); await p.getByRole('textbox', { name: /^App Title/ }).fill('Draft'); await chooseSettingsCategory(p, 'Recording', { advanced: false }); const recording = p.getByRole('checkbox', { name: 'Recording Enabled', exact: true }); await recording.setChecked(!await recording.isChecked()); const pending = p.locator('.settings-pending'); await pending.locator('summary').click(); assert.equal(await pending.locator('li').count(), 2); await ctx.close(); });
    await run('5 empty mobile navigation', async () => { let { ctx, p } = await context('admin', 390, 844); for (const name of ['Live View', 'Multiview']) {
        await p.locator('.sidebar').getByRole('button', { name, exact: true }).click();
        const box = await p.locator('.sidebar').boundingBox();
        assert.ok(box && box.height < 220, `${name}: ${JSON.stringify(box)}`);
    } await ctx.close(); });
    await run('15 viewer empty states', async () => { let { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Live View', exact: true }).click(); await p.getByText(/No cameras are configured/).waitFor(); await p.locator('.sidebar').getByRole('button', { name: 'Multiview', exact: true }).click(); await p.getByText(/No multiview outputs are configured/i).waitFor(); assert.doesNotMatch(await p.locator('.page').innerText(), /Select a stream/i); await p.locator('.sidebar').getByRole('button', { name: 'Information', exact: true }).click(); await p.getByText(/No cameras are configured/).waitFor(); await ctx.close(); });
    await run('15 empty recordings', async () => { let { ctx, p } = await context('admin'); await p.locator('.sidebar').getByRole('button', { name: 'Recordings', exact: true }).click(); await p.getByText(/No recordings match/i).waitFor(); assert.equal(await p.getByRole('navigation', { name: /recording pages/i }).count(), 0); await ctx.close(); });
}
finally {
    await browser.close();
}
