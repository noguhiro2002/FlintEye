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
let monitoring = { state: 'stopped', color: 'gray', label: 'Monitoring stopped', message: 'Monitoring is stopped.', desired_running: false, busy: false, phase: 'stopped', resume_on_startup: false, counts: { configured: 2, targets: 2, receiving: 0, recording: 0 }, cameras: [] };
let unavailable = false, preference = false, delayControl = false, failControl = false;
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
                v = monitoring; if (unavailable) { status = 503; v = { detail: 'Unavailable' }; }
                break;
            case '/api/v1/monitoring/preferences':
                if (req.method() === 'PATCH') preference = JSON.parse(req.postData()).resume_on_startup; v = { resume_on_startup: preference };
                break;
            case '/api/v1/control/start':
            case '/api/v1/control/stop':
            case '/api/v1/control/restart':
                if (delayControl) await new Promise(r => setTimeout(r, 800)); if (failControl) { status = 409; v = {detail: 'Recording completion could not be verified'}; } else v = { ok: true }; break;
            case '/api/v1/build':
                v = { version: '1.1.1', release: '1.1.1', channel: 'stable', commit: null, dirty: false };
                break;
            case '/api/v1/auth/me':
                v = { authenticated: scenario === 'admin' || scenario === 'viewer', role: scenario === 'admin' ? 'admin' : scenario === 'viewer' ? 'viewer' : null, username: 'admin', viewer_auth_required: true, setup_required: scenario === 'setup', provider: 'local', local: { viewer_username: 'viewer', admin_username: 'admin' } };
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

try {
  let {ctx, p} = await context('admin');
  const panel = p.getByRole('region', {name: 'Monitoring status'});
  await panel.getByText('Monitoring stopped').waitFor();
  assert.equal(await panel.getByRole('button', {name: 'Start monitoring', exact: true}).isEnabled(), true);
  assert.equal(await panel.getByRole('button', {name: 'Stop monitoring'}).isDisabled(), true);
  assert.equal(await panel.getByRole('button', {name: 'Restart monitoring'}).isDisabled(), true);
  for (const pageName of ['Live View', 'Multiview', 'Information', 'Recordings', 'Settings']) {
    await p.locator('.sidebar').getByRole('button', {name: pageName, exact: true}).click();
    assert.equal(await p.getByRole('region', {name: 'Monitoring status'}).count(), 0, 'Dashboard panel leaked into '+pageName);
    if (pageName === 'Live View' || pageName === 'Multiview') {
      assert.equal(await p.locator('iframe.webrtc-frame').count(), 0, 'Stopped monitoring still opens WebRTC');
    }
  }
  await p.locator('.sidebar').getByRole('button', {name:'Dashboard', exact:true}).click();
  delayControl = true;
  await panel.getByRole('button', {name: 'Start monitoring', exact: true}).click();
  await panel.getByText(/Starting monitoring/).waitFor();
  assert.equal(await panel.getByRole('button', {name: 'Start monitoring', exact: true}).isDisabled(), true);
  await p.waitForTimeout(1000); delayControl = false;
  failControl = true;
  await panel.getByRole('button', {name:'Start monitoring', exact:true}).click();
  await panel.getByRole('alert').getByText(/Recording completion could not be verified/).waitFor();
  failControl = false;
  monitoring = {...monitoring, state:'error', color:'red', label:'Monitoring failed', message:'No cameras receiving.', desired_running:true, phase:'running', cameras:[{id:'one', receiving:false, reason:'No reception', last_received_at:null}]};
  await panel.getByText('Monitoring failed').waitFor({timeout:5000});
  assert.equal(await panel.getByRole('button', {name:'Start monitoring', exact:true}).isDisabled(), true);
  assert.equal(await panel.getByRole('button', {name:'Stop monitoring'}).isEnabled(), true);
  await panel.getByText('Camera reception details').click();
  await panel.getByText(/one: No reception/).waitFor();
  monitoring = {...monitoring, state:'running', color:'amber', label:'Partially receiving', message:'One camera unavailable.', counts:{configured:2, targets:2, receiving:1, recording:1}};
  await panel.getByText('Partially receiving').waitFor({timeout:5000});
  await panel.getByText('1 receiving / 2 targets · 1 recording · 2 configured').waitFor();
  monitoring = {...monitoring, busy:true};
  await p.waitForTimeout(2300);
  assert.equal(await panel.getByRole('button', {name:'Stop monitoring'}).isDisabled(), true);
  unavailable = true;
  await panel.getByText('Status unavailable').waitFor({timeout:5000});
  assert.equal(await panel.getByRole('button', {name:'Stop monitoring'}).isDisabled(), true);
  await ctx.close();
  unavailable = false; monitoring = {...monitoring, busy:false};
  ({ctx, p} = await context('viewer'));
  await p.getByRole('region', {name:'Monitoring status'}).getByText('Partially receiving').waitFor();
  assert.equal(await p.getByRole('button', {name:'Stop monitoring'}).count(), 0);
  await ctx.close();
  ({ctx, p} = await context('admin'));
  await p.locator('.sidebar').getByRole('button', {name:'Settings', exact:true}).click();
  const nav = p.getByRole('complementary', {name:'Settings categories'});
  await nav.getByRole('button', {name:'Quick settings', exact:true}).click();
  const resume = p.getByRole('checkbox', {name:'Always resume monitoring when FlintEye starts'});
  assert.equal(await resume.isChecked(), false);
  await resume.click();
  await p.waitForFunction(() => document.querySelector('.startup-settings input')?.checked === true);
  assert.equal(preference, true);
  assert.ok(calls.some(([method, path, body]) => method === 'PATCH' && path === '/api/v1/monitoring/preferences' && JSON.parse(body).resume_on_startup === true));
  await p.keyboard.press('Meta+k');
  assert.equal(await p.evaluate(() => document.activeElement?.getAttribute('placeholder')), 'Find a setting...');
  await nav.getByRole('button', {name:'General', exact:true}).click();
  await p.getByRole('textbox', {name:/^App Title/}).fill('Leave draft');
  await p.locator('.sidebar').getByRole('button', {name:'Dashboard', exact:true}).click();
  await p.getByRole('button', {name:'Continue editing'}).click();
  assert.equal(await p.getByRole('textbox', {name:/^App Title/}).inputValue(), 'Leave draft');
  await p.locator('.sidebar').getByRole('button', {name:'Dashboard', exact:true}).click();
  await p.getByRole('button', {name:'Discard changes'}).click();
  await p.locator('.sidebar').getByRole('button', {name:'Settings', exact:true}).click();
  await nav.getByRole('button', {name:'General', exact:true}).click();
  assert.equal(await p.getByRole('textbox', {name:/^App Title/}).inputValue(), 'FlintEye');
  await ctx.close();
  console.log('PASS monitoring');
} catch (e) { console.error('FAIL monitoring', e); process.exitCode = 1; }
finally { await browser.close(); }
