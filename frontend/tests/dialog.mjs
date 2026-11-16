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
const config = { ui: { app_title: 'FlintEye', sidebar_title: 'FlintEye', onboarding_done: true }, recording: { enabled: true, managed_storage: true, record_root: '/tmp/Synthetic', max_bytes: 50e9, record_delete_after: '168h' }, cameras: [], multiview: { enabled: false } };
const items = Array.from({ length: 55 }, (_, i) => ({ file_id: 'file' + i, relative_path: `${i % 2 ? 'rear' : 'front'}/2026-11-15/file${i}.mp4`, stream_id: i % 2 ? 'rear' : 'front', size_bytes: 1234567 + i * 100, modified_at: 1760000000 - i * 1800, age_sec: i * 1800, is_stable: i !== 0 }));
async function create(role = 'admin', width = 1440, height = 900, mode = 'normal') {
    const ctx = await browser.newContext({ viewport: { width, height } }), requests = [], errors = [];
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
        if (u.pathname === '/api/v1/status/monitoring') v = { state: 'running', color: 'green', label: 'Running', message: 'Receiving video', desired_running: true, busy: false, phase: 'running', resume_on_startup: false, counts: { configured: 0, targets: 0, receiving: 0, recording: 0 }, cameras: [] };
        else if (u.pathname === '/api/v1/monitoring/preferences') v = { resume_on_startup: false };
        else if (u.pathname === '/api/v1/build') v = { version: '1.1.1', release: '1.1.1', channel: 'stable', commit: null, dirty: false };
        else if (u.pathname === '/api/v1/auth/me')
            v = { authenticated: role !== 'public', role: role === 'public' ? null : role, username: role, viewer_auth_required: role !== 'public', setup_required: false, provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
        else if (u.pathname === '/api/v1/config/effective')
            v = config;
        else if (u.pathname === '/api/v1/status')
            v = { mediamtx: { running: true, status: 'running', mode: 'direct' }, cameras_enabled: 2, cameras_total: 2, multiview_enabled: false, running_processes: 1, processes: { items: [] } };
        else if (u.pathname === '/api/v1/recordings/streams') {
            if (mode === 'slow')
                await new Promise(r => setTimeout(r, 2500));
            v = { record_root: '/tmp/Synthetic', count: 2, items: ['front', 'rear'] };
        }
        else if (u.pathname === '/api/v1/recordings') {
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
try {
    let { ctx, p } = await create();
    const play = p.locator('.recording-card').nth(1).locator('.recording-card-actions button');
    await play.click();
    const dialog = p.locator('[role=dialog]');
    await dialog.waitFor();
    assert.ok(await dialog.evaluate(e => e.contains(document.activeElement)), 'initial focus outside dialog');
    for (let i = 0; i < 8; i++) {
        await p.keyboard.press('Tab');
        assert.ok(await dialog.evaluate(e => e.contains(document.activeElement)), 'Tab escaped dialog');
    }
    for (let i = 0; i < 8; i++) {
        await p.keyboard.press('Shift+Tab');
        assert.ok(await dialog.evaluate(e => e.contains(document.activeElement)), 'Shift+Tab escaped dialog');
    }
    await p.screenshot({ path: 'dist/terra-webapp-fixes/16-dialog.png' });
    await p.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    assert.ok(await play.evaluate(e => e === document.activeElement), 'focus not restored');
    console.log('PASS 16 dialog focus');
    await ctx.close();
}
catch (e) {
    console.error('FAIL 16', e);
    process.exitCode = 1;
}
finally {
    await browser.close();
}
