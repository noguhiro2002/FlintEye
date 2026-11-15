import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';
process.chdir(fileURLToPath(new URL('../..', import.meta.url)));
mkdirSync('dist/terra-webapp-fixes', { recursive: true });
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
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
        if (opts.delay === u.pathname)
            await new Promise(r => setTimeout(r, 3000));
        if (opts.fail === u.pathname)
            return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic service unavailable' }) });
        let v = { items: [] }, s = 200;
        if (u.pathname === '/api/v1/status/monitoring') v = { state: 'stopped', color: 'gray', label: 'Monitoring stopped', message: 'Monitoring is stopped.', desired_running: false, busy: false, phase: 'stopped', resume_on_startup: false, counts: { configured: 0, targets: 0, receiving: 0, recording: 0 }, cameras: [] };
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
async function run(name, fn) { try {
    await fn();
    console.log('PASS', name);
}
catch (e) {
    console.error('FAIL', name, e.message);
    process.exitCode = 1;
} }
try {
    for (const [name, endpoint, page] of [['Information', '/api/v1/viewer/info', 'Information'], ['Live', '/api/v1/viewer/cameras', 'Live View'], ['Multiview', '/api/v1/multiview/views', 'Multiview']]) {
        await run(`7 ${name} loading`, async () => { const { ctx, p } = await start('admin', 390, 844, { delay: endpoint }); await p.locator('.sidebar').getByRole('button', { name: page, exact: true }).click(); const t = await p.locator('.page').innerText(); assert.match(t, /loading|refreshing/i); assert.doesNotMatch(t, /No information loaded|No multiview outputs available|Select a stream/i); await ctx.close(); });
        await run(`7 ${name} failure`, async () => { const { ctx, p } = await start('admin', 390, 844, { fail: endpoint }); await p.locator('.sidebar').getByRole('button', { name: page, exact: true }).click(); await p.getByText(/Synthetic service unavailable/).first().waitFor(); const t = await p.locator('.page').innerText(); assert.doesNotMatch(t, /No information loaded|No multiview outputs available/i); await ctx.close(); });
    }
    await run('12 PTZ contrast', async () => { const { ctx, p } = await start('admin', 390); await p.locator('.sidebar').getByRole('button', { name: 'Live View', exact: true }).click(); await p.locator('.thumb-select').filter({ hasText: 'Back door' }).click(); await p.getByText('Back profile').waitFor(); const ratios = await p.locator('.ptz-card small,.ptz-card-header span,.ptz-state').evaluateAll(es => es.map(el => { const rgb = s => (s.match(/[\d.]+/g) || []).slice(0, 3).map(Number); const lum = a => a.map(x => { x /= 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; }).reduce((v, x, i) => v + x * [.2126, .7152, .0722][i], 0); let parent = el, bg = ''; while (parent) {
        const c = getComputedStyle(parent).backgroundColor;
        if (c !== 'transparent' && c !== 'rgba(0, 0, 0, 0)') {
            bg = c;
            break;
        }
        parent = parent.parentElement;
    } const a = lum(rgb(getComputedStyle(el).color)), b = lum(rgb(bg)); return { text: el.textContent, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) }; })); assert.ok(ratios.length && ratios.every(x => x.ratio >= 4.5), JSON.stringify(ratios)); await ctx.close(); });
}
finally {
    await browser.close();
}
