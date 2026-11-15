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
const config = { ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: true }, recording: { enabled: true, managed_storage: true, record_root: '/tmp/Synthetic', max_bytes: 50e9, record_delete_after: '168h' }, cameras: [], multiview: { enabled: false } };
const items = Array.from({ length: 55 }, (_, i) => ({ file_id: 'file' + i, relative_path: `${i % 2 ? 'rear' : 'front'}/2026-11-15/file${i}.mp4`, stream_id: i % 2 ? 'rear' : 'front', size_bytes: 1234567 + i * 100, modified_at: 1760000000 - i * 1800, age_sec: i * 1800, is_stable: i !== 0 }));
async function create(role = 'admin', width = 1440, height = 900, mode = 'normal') {
    const ctx = await browser.newContext({ viewport: { width, height } }), requests = [], errors = [];
    let listCalls = 0;
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(String(e)));
    await ctx.route('**/*', async (route) => {
        const u = new URL(route.request().url());
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
        requests.push(u.pathname + u.search);
        if (u.pathname === '/api/v1/status/monitoring') v = { state: 'stopped', color: 'gray', label: 'Monitoring stopped', message: 'Monitoring is stopped.', desired_running: false, busy: false, phase: 'stopped', resume_on_startup: false, counts: { configured: 0, targets: 0, receiving: 0, recording: 0 }, cameras: [] };
        else if (u.pathname === '/api/v1/monitoring/preferences') v = { resume_on_startup: false };
        else if (u.pathname === '/api/v1/build') v = { version: '1.1.1', release: '1.1.1', channel: 'stable', commit: null, dirty: false };
        else if (u.pathname === '/api/v1/auth/me')
            v = { authenticated: role !== 'public', role: role === 'public' ? null : role, username: role, viewer_auth_required: role !== 'public', setup_required: false, provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
        else if (u.pathname === '/api/v1/config/effective')
            v = config;
        else if (u.pathname === '/api/v1/status')
            v = { mediamtx: { running: true, status: 'running', mode: 'direct' }, cameras_enabled: 2, cameras_total: 2, multiview_enabled: false, running_processes: 1, processes: { items: [] } };
        else if (u.pathname === '/api/v1/recordings/streams') {
            if (mode === 'streamerror') {
                status = 503;
                v = { detail: 'Synthetic stream failure' };
            }
            else {
                if (mode === 'slow')
                    await new Promise(r => setTimeout(r, 2500));
                v = { record_root: '/tmp/Synthetic', count: 2, items: ['front', 'rear'] };
            }
        }
        else if (u.pathname === '/api/v1/recordings') {
            listCalls++;
            if (mode === 'stale' && listCalls === 1)
                await new Promise(r => setTimeout(r, 1800));
            if (mode === 'error') {
                status = 503;
                v = { detail: 'Recording service unavailable' };
            }
            else {
                let filtered = items.filter(i => (!u.searchParams.get('stream_id') || i.stream_id === u.searchParams.get('stream_id')) && (u.searchParams.get('status') === 'all' || i.is_stable === (u.searchParams.get('status') === 'stable')) && (!u.searchParams.get('recorded_from') || i.modified_at >= Number(u.searchParams.get('recorded_from'))) && (!u.searchParams.get('recorded_to') || i.modified_at <= Number(u.searchParams.get('recorded_to'))));
                const key = u.searchParams.get('sort_by'), dir = u.searchParams.get('sort_dir') === 'asc' ? 1 : -1;
                filtered.sort((a, b) => dir * (key === 'stream' ? a.stream_id.localeCompare(b.stream_id) : key === 'size' ? a.size_bytes - b.size_bytes : a.modified_at - b.modified_at));
                let offset = Number(u.searchParams.get('offset') || 0), limit = Number(u.searchParams.get('limit') || 50);
                v = { record_root: '/tmp/Synthetic', total: filtered.length, offset, limit, items: filtered.slice(offset, offset + limit) };
            }
        }
        else if (u.pathname.endsWith('/prepare')) {
            if (mode === 'playerror') {
                status = 500;
                v = { detail: 'Synthetic conversion failure' };
            }
            else if (mode === 'playslow') {
                await new Promise(r => setTimeout(r, 3000));
                v = { ok: true };
            }
            else
                v = { ok: true };
        }
        else if (u.pathname.endsWith('/thumbnail') || u.pathname.endsWith('/playable'))
            return route.fulfill({ status: 404, contentType: 'text/plain', body: 'synthetic missing media' });
        else if (u.pathname === '/api/v1/storage/status')
            v = { message: '' };
        else if (u.pathname === '/api/v1/updates')
            v = { available: false, current: '1.1.1' };
        return route.fulfill({ status, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(v) });
    });
    await p.goto('http://127.0.0.1:12345');
    await p.locator('.sidebar').getByRole('button', { name: 'Recordings' }).click();
    const closeContext = ctx.close.bind(ctx);
    ctx.close = async () => { await closeContext(); assert.deepEqual(errors, [], 'unexpected page errors'); };
    return { ctx, p, requests, errors };
}
async function checkWidth(page, label, width) {
    const measurement = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth,
        offenders: [...document.querySelectorAll('body *')].map(el => ({ tag: el.tagName, className: String(el.className), right: Math.round(el.getBoundingClientRect().right) })).filter(el => el.right > innerWidth + 1).slice(-12) }));
    assert.ok(measurement.scrollWidth <= measurement.viewport + 1, `${label} ${width}: ${JSON.stringify(measurement)}`);
}
async function reachable(locator, width) {
    await locator.scrollIntoViewIfNeeded();
    const box = await locator.boundingBox();
    assert.ok(box && box.x >= -1 && box.x + box.width <= width + 1, JSON.stringify(box));
    assert.ok(await locator.isEnabled());
}
let failed = false;
try {
    for (const width of [320, 390, 768, 1440]) {
        let ctx;
        try {
            const result = await create('admin', width, 844);
            ctx = result.ctx;
            const page = result.p;
            await page.locator('.recording-card').nth(1).waitFor();
            await checkWidth(page, 'Recordings', width);
            const stream = page.locator('.recording-filter-controls select').first();
            await reachable(stream, width);
            await stream.selectOption('rear');
            await page.locator('.recording-card').first().locator('.recording-card-heading strong').filter({ hasText: /^rear$/ }).waitFor();
            const play = page.locator('.recording-card-actions button').first();
            await reachable(play, width);
            await play.click();
            await page.getByRole('dialog').waitFor();
            const close = page.getByRole('button', { name: 'Close player' });
            await reachable(close, width);
            await close.click();
            await checkWidth(page, 'Recordings filtered', width);
            await page.screenshot({ path: `dist/terra-webapp-fixes/recordings-layout-${width}.png`, fullPage: true });
            console.log('PASS 4 populated Recordings', width);
        }
        catch (e) {
            failed = true;
            console.error('FAIL 4 populated Recordings', width, e.message);
        }
        finally {
            if (ctx)
                await ctx.close();
        }
    }
}
finally {
    await browser.close();
}
if (failed)
    process.exitCode = 1;
