import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';
process.chdir(fileURLToPath(new URL('../..', import.meta.url)));
mkdirSync('dist/terra-webapp-fixes', { recursive: true });
import assert from 'node:assert/strict';
import { chromium } from './browser.mjs';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
const root = process.cwd();
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined, headless: true, args: ['--no-sandbox'] });
const health = (state, reason = '', extra = {}) => ({ state, reason, manual_excluded: false, quarantined: false, placeholder: false, ...extra });
const camera = (id, label, h) => ({ id, label, type: 'ip', enabled: true, path: id, addresses: { rtsp_url: `rtsp://example.test/${id}`, webrtc_url: `http://example.test/${id}` }, process: null, health: h, ptz: { enabled: true, access: 'viewer' } });
const cameras = [camera('cam1', 'Front entrance', health('healthy', 'OK')), camera('cam2', 'Back door', health('unhealthy', 'Network timeout')), camera('cam3', 'Garage', health('excluded', 'Manually excluded', { manual_excluded: true, placeholder: true }))];
const views = [{ id: 'all-cameras', index: 0, sources: ['cam1', 'cam2', 'cam3'], source_items: cameras.map(c => ({ path: c.path, label: c.label, type: 'ip', health: c.health })), rtsp_url: 'rtsp://example.test/all', webrtc_url: 'http://example.test/all' }];
const status = { updated_at: 1700000000, views: [{ id: 'all-cameras', state: 'degraded', restart_count: 2, decode_error_count: 5, inputs: [{ path: 'cam1', state: 'healthy', failures: 0, isolated: false }, { path: 'cam2', state: 'no_stream', failures: 3, isolated: false, reason: 'Network timeout' }, { path: 'cam3', state: 'isolated', failures: 1, isolated: true }] }] };
const config = { auth: { provider: 'local', viewer_auth_required: true, local: { admin: { username: 'admin' }, viewer: { username: 'viewer' } } }, ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: true }, recording: { enabled: true, managed_storage: true, record_root: '/tmp/Sample', max_bytes: 50e9, record_delete_after: '168h', show_previous: true }, cameras: [], multiview: { enabled: true } };
const info = { api: { swagger_url: 'http://example.test/docs', redoc_url: 'http://example.test/redoc', openapi_url: 'http://example.test/openapi.json' }, rtsp_base_url: 'rtsp://example.test:8554', webrtc_base_url: 'http://example.test:8889', generated_at: 1700000000, snapshot: { timeout_sec: 5, thumbnail_refresh_interval_sec: 10 }, cameras: cameras.map(c => ({ ...c, settings: { width: '1920', height: '1080', fps: '30', bitrate: '4M', encoder: 'h264' } })), multiview: { enabled: true, output_prefix: 'multi', tile_count: 4, canvas_width: 1920, canvas_height: 1080, fps: 30, bitrate: '4M', encoder: 'h264', quality_preset: 'balanced' } };
const cap = { supported: true, pan_tilt: true, zoom: true, current: { zoom: 0.5 }, selected_profile_name: 'Main profile', modes: { pan_tilt: { continuous: true, relative: false, absolute: false }, zoom: { continuous: true, relative: false, absolute: false } } };
async function start(role, width, height = 900, opts = {}) {
    let requests = [], errors = [], cams = [...cameras];
    const ctx = await browser.newContext({ viewport: { width, height } });
    ctx.on('page', p => p.on('pageerror', e => errors.push(String(e))));
    await ctx.route('**/*', async (route) => {
        const q = route.request(), u = new URL(q.url());
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
        requests.push([q.method(), u.pathname]);
        let v = { items: [] }, s = 200;
        if (u.pathname === '/api/v1/status/monitoring') v = { state: 'running', color: 'green', label: 'Running', message: 'Receiving video', desired_running: true, busy: false, phase: 'running', resume_on_startup: false, counts: { configured: 0, targets: 0, receiving: 0, recording: 0 }, cameras: [] };
        else if (u.pathname === '/api/v1/monitoring/preferences') v = { resume_on_startup: false };
        else if (u.pathname === '/api/v1/build') v = { version: '1.1.1', release: '1.1.1', channel: 'stable', commit: null, dirty: false };
        else if (u.pathname === '/api/v1/auth/me')
            v = { authenticated: role !== 'public', role: role === 'public' ? null : role, username: role, viewer_auth_required: role !== 'public', setup_required: false, provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
        else if (u.pathname === '/api/v1/config/effective' || u.pathname === '/api/v1/config/runtime')
            v = config;
        else if (u.pathname === '/api/v1/viewer/cameras')
            v = { items: cams };
        else if (u.pathname === '/api/v1/viewer/info')
            v = info;
        else if (u.pathname === '/api/v1/multiview/views')
            v = { items: views };
        else if (u.pathname === '/api/v1/multiview/status')
            v = status;
        else if (u.pathname === '/api/v1/status')
            v = { mediamtx: { running: true, status: 'running', mode: 'direct' }, cameras_enabled: 3, cameras_total: 3, multiview_enabled: true, running_processes: 3, processes: { items: [{ id: 'camera-cam1', kind: 'camera', status: 'running', pid: 1234, restart_count: 0 }] } };
        else if (u.pathname.endsWith('/snapshot')) {
            s = 503;
            v = { detail: 'Synthetic snapshot unavailable' };
        }
        else if (u.pathname.endsWith('/ptz/capabilities')) {
            if (u.pathname.includes('/cam1/'))
                await new Promise(r => setTimeout(r, 2500));
            v = { ...cap, pan_tilt: true, zoom: u.pathname.includes('/cam1/'), selected_profile_name: u.pathname.includes('/cam1/') ? 'Front profile' : 'Back profile' };
        }
        else if (u.pathname.endsWith('/ptz/move')) {
            await new Promise(r => setTimeout(r, 1800));
            v = { ok: true };
        }
        else if (u.pathname.includes('/ptz/') || u.pathname.endsWith('/exclude') || u.pathname.endsWith('/restore'))
            v = { ok: true };
        else if (u.pathname === '/api/v1/storage/status')
            v = { message: '' };
        else if (u.pathname === '/api/v1/updates')
            v = { available: false };
        else if (u.pathname === '/api/v1/recordings')
            v = { items: [], total: 0, limit: 50, offset: 0 };
        else if (u.pathname === '/api/v1/desktop')
            v = { folder_picker: true };
        return route.fulfill({ status: s, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(v) });
    });
    const p = await ctx.newPage();
    await p.goto('http://127.0.0.1:12345');
    await p.waitForTimeout(500);
    const closeContext = ctx.close.bind(ctx);
    ctx.close = async () => { await closeContext(); assert.deepEqual(errors, [], 'unexpected page errors'); };
    return { ctx, p, requests, errors, removeFirst: () => { cams = cams.slice(1); } };
}
try {
    const { ctx, p, requests } = await start('admin', 1440);
    await p.locator('.sidebar').getByRole('button', { name: 'Live View', exact: true }).click();
    await p.locator('.thumb-select').filter({ hasText: 'Back door' }).click();
    const up = p.getByRole('button', { name: 'Tilt up' });
    await up.waitFor();
    await up.focus();
    await p.keyboard.down('Enter');
    await p.keyboard.up('Enter');
    await p.waitForTimeout(300);
    assert.ok(requests.some(([, path]) => path.endsWith('/ptz/move')));
    assert.ok(requests.some(([, path]) => path.endsWith('/ptz/stop')));
    assert.doesNotMatch(await p.locator('.ptz-state').innerText(), /Sending command/);
    await p.waitForTimeout(2000);
    assert.doesNotMatch(await p.locator('.ptz-state').innerText(), /Sending command/);
    console.log('PASS PTZ quick key release');
    await ctx.close();
}
catch (e) {
    console.error('FAIL PTZ quick key release', e);
    process.exitCode = 1;
}
finally {
    await browser.close();
}
