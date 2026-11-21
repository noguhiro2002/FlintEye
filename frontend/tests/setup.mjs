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
async function context(scenario, width = 1440, height = 900, colorScheme = 'light') {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme });
    let errors = [];
    let created = false;
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
                v = { authenticated: scenario === 'admin' || created, role: scenario === 'admin' || created ? 'admin' : null, username: 'admin', viewer_auth_required: true, setup_required: scenario !== 'admin' && !created, setup_mode: scenario.startsWith('desktop') ? 'desktop' : 'server', setup_handoff_ready: ['desktop-handoff', 'desktop-expired'].includes(scenario) && !created, provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
                break;
            case '/api/v1/setup':
                if (scenario === 'desktop-expired') { status = 403; v = { detail: 'Setup expired' }; }
                else { created = true; v = { ok: true }; }
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
                if (created) v = { ok: true, role: 'admin' };
                else { v = { detail: 'Incorrect username or password' }; status = 401; }
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
try {
    for (const width of [320, 1440]) {
        const { ctx, p } = await context('setup', width, 844);
        await p.locator('.login-card input').first().waitFor();
        const card = p.locator('.login-card');
        assert.match(await card.innerText(), /FlintEye/);
        const inputs = card.locator('input');
        const n = await inputs.count();
        assert.ok(n >= 3);
        for (let i = 0; i < n; i++) {
            const input = inputs.nth(i);
            assert.ok(await input.evaluate(e => e.labels?.length || e.getAttribute('aria-label')), 'input lacks label');
            const box = await input.boundingBox();
            assert.ok(box && box.x >= 0 && box.x + box.width <= width + 1, JSON.stringify(box));
        }
        const a = await inputs.nth(1).boundingBox(), b = await inputs.nth(2).boundingBox();
        assert.ok(a && b && (a.y + a.height <= b.y || b.y + b.height <= a.y || a.x + a.width <= b.x || b.x + b.width <= a.x), 'setup fields overlap');
        await p.screenshot({ path: `dist/terra-webapp-fixes/setup-${width}.png`, fullPage: true });
        assert.equal(await p.title(), 'FlintEye');
        await ctx.close();
        console.log('PASS 9 setup', width);
    }
    for (const scenario of ['desktop-handoff', 'desktop-manual', 'desktop-expired']) {
        const { ctx, p } = await context(scenario, 390);
        try {
            const token = p.getByLabel('Setup token', { exact: true });
            await p.getByRole('heading', { name: 'Welcome to FlintEye' }).waitFor();
            if (scenario === 'desktop-manual') {
                await token.waitFor();
                await p.getByText('Address and setup assistance', { exact: false }).waitFor();
                assert.equal(await token.getAttribute('type'), 'password');
                continue;
            }
            assert.equal(await token.count(), 0);
            await p.getByLabel('Password', { exact: true }).fill('synthetic-setup-password');
            await p.getByLabel('Confirm password', { exact: true }).fill('synthetic-setup-password');
            const request = p.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/api/v1/setup'));
            await p.getByRole('button', { name: 'Create administrator account' }).click();
            assert.deepEqual((await request).postDataJSON(), { password: 'synthetic-setup-password' });
            if (scenario === 'desktop-expired') {
                await p.getByText(/Setup access expired/).waitFor();
                await token.waitFor();
            } else await p.locator('.sidebar').waitFor();
        } finally { await ctx.close(); }
    }
    console.log('PASS desktop setup handoff, expiration, and manual fallback');
    for (const width of [320, 1440]) {
        const { ctx, p } = await context('admin', width, 900);
        await ctx.route('**/api/v1/network', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ saved: { enabled: true, address: '192.168.1.10', allowed_subnets: ['192.168.1.0/24'] }, restart_required: false, local_url: 'http://127.0.0.1:18080', lan_url: 'https://192.168.1.10:18080', fingerprint: '0123456789abcdef'.repeat(4), ca_expires: '2031-11-16T00:00:00Z', guide_url: 'https://example.test/guide', error: '' }) }));
        await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
        await p.getByRole('complementary', { name: 'Settings categories' }).getByRole('button', { name: 'Runtime & access', exact: true }).click();
        await p.getByText('LAN connection and certificate trust', { exact: true }).click();
        const address = p.getByRole('textbox', { name: 'Server IPv4 address', exact: true });
        await address.waitFor();
        const widths = await p.evaluate(() => [innerWidth, document.documentElement.scrollWidth]);
        assert.ok(widths[1] <= widths[0] + 1, `LAN settings overflow: ${widths}`);
        const fields = p.locator('.network-access form label');
        const boxes = await fields.evaluateAll(labels => labels.map(label => {
            const { x, y, width, height } = label.getBoundingClientRect();
            return { x, y, width, height };
        }));
        for (let i = 0; i < boxes.length; i++) {
            const a = boxes[i];
            assert.ok(a.x >= 0 && a.x + a.width <= width + 1, JSON.stringify(a));
            for (const b of boxes.slice(i + 1)) assert.ok(a.y + a.height <= b.y + 1 || b.y + b.height <= a.y + 1 || a.x + a.width <= b.x + 1 || b.x + b.width <= a.x + 1, 'LAN setting labels overlap');
        }
        await p.screenshot({ path: `dist/terra-webapp-fixes/network-settings-${width}.png`, fullPage: true });
        await ctx.route('**/api/v1/network/renew-trust', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, restart_required: true, message: 'Install the new trust certificate on every viewing device.' }) }));
        p.once('dialog', dialog => dialog.accept());
        await p.getByRole('button', { name: 'Renew trust certificate…', exact: true }).click();
        await p.getByText('Install the new trust certificate on every viewing device. Restart FlintEye to apply connection changes.', { exact: true }).waitFor();
        await address.fill('192.168.1.20');
        await p.locator('.sidebar').getByRole('button', { name: 'Dashboard', exact: true }).click();
        await p.getByRole('button', { name: 'Continue editing', exact: true }).click();
        assert.equal(await address.inputValue(), '192.168.1.20');
        await ctx.close();
        console.log('PASS LAN settings layout and unsaved navigation', width);
    }
}
catch (e) {
    console.error('FAIL 9', e);
    process.exitCode = 1;
}
finally {
    await browser.close();
}
