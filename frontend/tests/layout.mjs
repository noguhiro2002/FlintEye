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
const onvifProfile = {
    token: 'qa-main', name: 'Main stream', media_service: 'Media2', encoding: 'h264',
    width: 1280, height: 720, fps: 30, stream_uri: 'rtsp://example.test/' + 'longstream'.repeat(30),
};
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
                    v = { ok: true, source: 'rtsp://example.test/stream1', inspected_at: 1700000000, elapsed_sec: 1.5, rtsp: { available: true, codec: 'h264', width: 1280, height: 720, observed_fps: 30, timestamp_healthy: true, frame_count: 30 }, onvif: { status: 'ok', supported: true, message: 'Synthetic ONVIF', profiles: [onvifProfile], ptz: { supported: false, service_available: false, message: 'PTZ unavailable' } }, recommendation: { timestamp_mode: 'source', cfr_fps: 30 } };
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

async function assertIpCameraLayout(card, label) {
    const issues = await card.evaluate(element => {
        const checked = [element, ...element.querySelectorAll(
            '.ip-camera-panel, .ip-camera-identity-grid, .ip-camera-control-grid, .ip-detail-grid, .ip-onvif-grid, ' +
            '.ip-ptz-panel, .ip-ptz-settings-grid, .ip-probe-metrics, .ip-profile-list > div',
        )];
        const issues = checked.filter(node => node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 1)
            .map(node => `${node.className || node.tagName} overflows (${node.scrollWidth} > ${node.clientWidth})`);
        for (const label of element.querySelectorAll('.ip-camera-enable, .settings-fields > .check')) {
            const checkbox = label.querySelector('input').getBoundingClientRect();
            const caption = label.querySelector('span').getBoundingClientRect();
            if (checkbox.right > caption.left + 1 || checkbox.bottom <= caption.top || checkbox.top >= caption.bottom) {
                issues.push(`${label.className} checkbox should sit beside its caption`);
            }
        }
        const removeLabel = document.createRange();
        removeLabel.selectNodeContents(element.querySelector('.ip-camera-card-head > button').lastChild);
        if (removeLabel.getClientRects().length > 1) issues.push('Remove button label wraps');
        return issues;
    });
    assert.deepEqual(issues, [], label);
}

async function checkRecordingThumbnails() {
    const { ctx, p } = await context('admin', 1440, 1000);
    const { promise: completeThumbnails, resolve: releaseThumbnails } = Promise.withResolvers();
    const matchingThumbnail = url => url.pathname.endsWith('/thumbnail');
    const thumbnailRequests = [];
    const time = Date.now() / 1000;
    const items = Array.from({ length: 30 }, (_, index) => ({
        file_id: `sample-${index}`, relative_path: `sample/${index}.mp4`, stream_id: 'sample',
        size_bytes: 4096, modified_at: time - index, started_at: time - index, is_stable: true,
    }));
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=', 'base64');
    await ctx.route(url => url.pathname === '/api/v1/recordings', route => route.fulfill({
        json: { items, total: items.length, limit: 50, offset: 0, record_root: '/tmp/Sample recordings' },
    }));
    await ctx.route(matchingThumbnail, async route => {
        thumbnailRequests.push(route.request());
        await completeThumbnails;
        await route.fulfill({ contentType: 'image/png', body: png }).catch(() => {});
    });
    await ctx.route(url => url.pathname.endsWith('/prepare'), route => route.fulfill({
        json: { ok: true, has_audio: false },
    }));
    await ctx.route(url => url.pathname.endsWith('/playable'), async route => {
        await completeThumbnails;
        await route.fulfill({ status: 204 }).catch(() => {});
    });
    try {
        const firstThumbnail = p.waitForRequest(request => matchingThumbnail(new URL(request.url())));
        await p.locator('.sidebar').getByRole('button', { name: 'Recordings', exact: true }).click();
        await firstThumbnail;
        await p.screenshot({ fullPage: true });
        assert.equal(thumbnailRequests.length, 2, 'Thumbnail generation filled more than two connections');

        let aborted = 0;
        const { promise: requestsAborted, resolve: onAborted } = Promise.withResolvers();
        p.on('requestfailed', request => {
            if (thumbnailRequests.includes(request) && ++aborted === 2) onAborted();
        });
        const playback = p.waitForRequest(request => new URL(request.url()).pathname.endsWith('/playable'));
        await p.getByRole('button', { name: 'Play sample/0.mp4', exact: true }).last().click();
        await playback;
        const timer = setTimeout(() => onAborted(), 5000);
        await requestsAborted;
        clearTimeout(timer);
        assert.equal(aborted, 2, 'Playback should release connections used by pending thumbnails');
        assert.equal(thumbnailRequests.length, 2, 'Thumbnail requests continued behind the player');

        const nextThumbnail = p.waitForRequest(request => matchingThumbnail(new URL(request.url())));
        await p.getByRole('button', { name: 'Close player' }).click();
        await nextThumbnail;
        releaseThumbnails();
        await p.locator('.recording-thumbnail img').first().waitFor();
    } finally {
        releaseThumbnails();
        await ctx.close();
    }
}

try {
    await checkRecordingThumbnails();
    for (const width of [1280, 1024, 1201, 1440, 320, 390, 768]) {
        const { ctx, p } = await context('admin', width, 844);
        await p.locator('.sidebar').getByRole('button', { name: 'Settings', exact: true }).click();

        const categories = width <= 768 ? ['General', 'MediaMTX', 'Multiview', 'Cameras'] : ['MediaMTX', 'Cameras'];
        for (const category of categories) {
            await chooseSettingsCategory(p, category);
            if (category === 'MediaMTX') {
                const base = await p.getByRole('textbox', { name: 'RTSP Base URL', exact: true }).boundingBox();
                const internal = await p.getByRole('textbox', { name: /^Internal RTSP Base URL/ }).boundingBox();
                assert(base && internal && Math.abs(base.height - internal.height) <= 1, 'RTSP URL inputs should have matching heights');
                if (width > 900) assert(Math.abs(base.y - internal.y) <= 1, 'Desktop RTSP URL inputs should align');
            }
            if (category === 'Cameras') {
                const first = p.locator('.ip-camera-card').first();
                const audio = first.locator('.camera-audio-toolbar');
                assert(await audio.isVisible());
                assert.equal(await first.getByRole('button', {name: 'Save camera audio', exact: true}).count(), 0);
                const toolbar = await audio.boundingBox();
                assert(toolbar && toolbar.height < (width <= 390 ? 190 : 115), 'Camera audio toolbar is too tall');
                await first.getByRole('textbox', { name: /^Display Name/ }).fill('LongCameraNameWithoutAnyBreaks'.repeat(8));
                await first.getByRole('textbox', { name: /^Source URL/ }).fill('rtsp://example.test/' + 'pathsegment'.repeat(30));
                await assertIpCameraLayout(first, `IP camera at ${width}px with automatic ONVIF discovery`);
                await first.getByRole('combobox', { name: /^ONVIF discovery/ }).selectOption('manual');
                await first.getByRole('textbox', { name: /^ONVIF device service address/ }).fill('http://example.test/onvif/device_service');
                await assertIpCameraLayout(first, `IP camera at ${width}px with a manual ONVIF address`);
                if (width === 1024 || width === 1280) {
                    await first.getByRole('button', { name: 'Inspect camera', exact: true }).click();
                    await first.getByText('RTSP timing is healthy.', { exact: true }).waitFor();
                    await first.getByText(onvifProfile.name, { exact: true }).waitFor();
                    for (const summary of await first.locator('.ip-camera-details > summary').all()) await summary.click();
                    await assertIpCameraLayout(first, `IP camera at ${width}px after inspection`);
                }
            }
            const widths = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
            console.log('WIDTH', width, category, JSON.stringify(widths));
            await p.screenshot({ path: `dist/terra-webapp-fixes/width-${width}-${category}.png`, fullPage: true });
            assert.ok(widths[0] <= widths[1] + 1, `${category} ${width}: ${widths}`);
        }
        await ctx.close();
    }
}
catch (e) {
    console.error('FAIL width', e);
    process.exitCode = 1;
}
finally {
    await browser.close();
}
