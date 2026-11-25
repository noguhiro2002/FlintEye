import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { extname } from 'node:path';
import { chromium } from './browser.mjs';
import { chooseSettingsCategory } from './settings-navigation.mjs';

const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
const origin = 'http://127.0.0.1:12345';
const mediaUrl = origin + '/fixture-player';
const now = 1_760_000_000;
const longName = ('長い名前の機器エラー' + 'withoutbreak'.repeat(16)).slice(0, 200);
const cameraIds = ['one', 'two', 'three'];
const settingsCameras = cameraIds.map(id => ({
  id, path: id, display_name: 'Camera '+id, enabled: true, type: 'ip',
  ip: {source_url: 'rtsp://example.test/'+id},
})).concat({
  id: 'retained-usb', path: 'saved-usb-stream', display_name: 'Retained USB', enabled: true, type: 'uvc',
  uvc: {profile: 'cam1', env: {DEVICE: '/dev/video99'}},
});
const cameras = settingsCameras.slice(0, 3).map(camera => ({
  id: camera.id, label: camera.display_name, type: camera.type, enabled: true, path: camera.path,
  addresses: {webrtc_url: mediaUrl}, health: {state: 'healthy'},
}));
const view = {id: 'multiview_1', sources: cameraIds, webrtc_url: mediaUrl, source_items: cameras.map(camera => ({
  path: camera.path, label: camera.label, health: {state: 'healthy'},
}))};
const recording = {file_id: 'clip-1', relative_path: 'one/'+longName+'.mp4', stream_id: 'one',
  size_bytes: 4096, modified_at: now, started_at: now, is_stable: true};
const mode = {width: 640, height: 480, fps: 30, input_format: 'mjpeg'};
const usbDevices = [
  {device_id: 'usb-denied', driver: 'v4l2', display_name: 'Blocked USB', ffmpeg_device: '/dev/video1',
    modes: [], recommended: mode, probe_state: 'permission_denied', mode_warning: 'Camera access denied for the FlintEye process.'},
  {device_id: 'usb-ready', driver: 'v4l2', display_name: 'Replacement USB', ffmpeg_device: '/dev/video2',
    stable_device: '/dev/v4l/by-id/usb-qa-video-index0', modes: [mode], recommended: mode, probe_state: 'available'},
];

function merge(base, patch) {
  for (const [key, value] of Object.entries(patch)) {
    base[key] = value && typeof value === 'object' && !Array.isArray(value)
      ? merge({...base[key]}, value) : value;
  }
  return base;
}

async function scenario(options, test) {
  const { width = 1440, height = 900, setup = false, guide = false, colorScheme = 'light', role = 'admin' } = options;
  const ctx = await browser.newContext({viewport: {width, height}, colorScheme});
  const page = await ctx.newPage();
  page.setDefaultTimeout(7_000);
  const errors = [], patches = [], bindings = [];
  let authenticated = !setup, pending = setup, signedIn = !setup;
  let config = {
    ui: {app_title: 'FlintEye', onboarding_done: !guide}, cameras: structuredClone(settingsCameras),
    auth: {provider: 'local', viewer_auth_required: true}, logging: {level: 'WARNING'},
    recording: {enabled: true, record_root: '/sample/recordings', record_delete_after: '168h'},
    multiview: {enabled: true, source_mode: 'env', source_paths: cameraIds, tile_count: 4, layout: {canvas_width: 1280,
      grid_columns: 2, source_slots: [['one', null, 'two', 'three']]}, quality: {quality_preset: 'standard'}},
  };
  page.on('pageerror', error => errors.push(error.message));
  await ctx.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/fixture-player') return route.fulfill({status: 200, contentType: 'text/html', body: '<p>Player fixture</p>'});
    if (!url.pathname.startsWith('/api/')) {
      const file = url.pathname === '/' ? '/index.html' : url.pathname;
      const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript'};
      const body = await readFile(new URL('../dist'+file, import.meta.url)).catch(() => null);
      return route.fulfill({status: body ? 200 : 404, contentType: types[extname(file)], body: body ?? ''});
    }
    let json = {items: []};
    const method = route.request().method();
    switch (url.pathname) {
      case '/api/v1/auth/me':
        json = {authenticated: signedIn, role: signedIn ? role : null, username: signedIn ? role : '',
          setup_required: !authenticated, viewer_auth_required: true, provider: 'local', local: {admin_username: 'admin', viewer_username: 'viewer'}};
        break;
      case '/api/v1/setup': authenticated = true; json = {ok: true}; break;
      case '/api/v1/auth/login': signedIn = true; json = {ok: true}; break;
      case '/api/v1/config/runtime':
        if (method === 'PATCH') {
          const patch = route.request().postDataJSON();
          patches.push(patch);
          config = merge(config, patch);
        }
        json = {ok: true, runtime: config, effective: config};
        break;
      case '/api/v1/config/effective': json = config; break;
      case '/api/v1/status':
        json = {mediamtx: {running: true, status: 'running', mode: 'direct'}, cameras_enabled: 3,
          cameras_total: 3, multiview_enabled: true, running_processes: 2,
          processes: {items: [{id: 'camera-one', pid: 42, kind: 'camera', status: 'running', restart_count: 0}]}};
        break;
      case '/api/v1/status/monitoring':
        json = {desired_running: true, phase: 'running', state: 'running', counts: {targets: 3, receiving: 3, recording: 1},
          cameras: [], label: 'Receiving cameras'};
        break;
      case '/api/v1/network':
        json = {saved: {enabled: true, address: '192.0.2.1', allowed_subnets: ['192.0.2.2/32']},
          local_url: origin, lan_url: 'https://192.0.2.1:18080', restart_required: pending,
          lan_state: pending ? 'pending' : 'active', fingerprint: 'a'.repeat(64), ca_expires: '2030-01-01'};
        break;
      case '/api/v1/viewer/info':
        json = {cameras: [], webrtc_base_url: '/media', api: {swagger_url: '/docs', redoc_url: '/redoc', openapi_url: '/openapi.json'},
          snapshot: {timeout_sec: 2, thumbnail_refresh_interval_sec: 10}, generated_at: now,
          multiview: {enabled: true}};
        break;
      case '/api/v1/cameras':
      case '/api/v1/viewer/cameras': json = {items: cameras}; break;
      case '/api/v1/uvc/devices': json = {items: usbDevices}; break;
      case '/api/v1/uvc/devices/usb-ready/apply':
        bindings.push(route.request().postDataJSON());
        json = {ok: true}; break;
      case '/api/v1/multiview/views': json = {items: [view]}; break;
      case '/api/v1/multiview/status': json = {views: []}; break;
      case '/api/v1/recordings': json = {items: [recording], record_root: '/sample/recordings', total: 1}; break;
      case '/api/v1/recordings/streams': json = {items: ['one'], record_root: '/sample/recordings'}; break;
      case '/api/v1/recordings/files/clip-1/prepare': json = {ok: true, has_audio: false}; break;
      case '/api/v1/recording-events':
        json = {items: [{id: 'fixture-event', label: longName, status: 'completed', occurred_at: now,
          requested_from: now - 60, detail: 'Fixture', cameras: [], clips: []}]};
        break;
      case '/api/v1/updates': json = {available: false, current: '1.2.0-preview.10'}; break;
      case '/api/v1/recording-events/settings': json = {enabled: false, allowed_camera_ids: []}; break;
    }
    return route.fulfill({json, headers: {ETag: '"qa-revision"'}});
  });
  try {
    await page.goto(origin);
    await test({page, patches, bindings, restart: () => { pending = false; }});
    assert.deepEqual(errors, []);
  } finally {
    await ctx.close();
  }
}

async function navigate(page, name) {
  await page.locator('.sidebar').getByRole('button', {name, exact: true}).click();
}

async function search(page, query, result) {
  await page.getByRole('searchbox', {name: 'Find a setting'}).fill(query);
  await page.getByRole('button', {name: result}).click();
}

async function theme(page, name) {
  await page.locator('summary[aria-label="Appearance"]').click();
  await page.getByRole('radio', {name, exact: true}).check();
  await page.keyboard.press('Escape');
}

async function assertWidth(page, name, width) {
  assert(await page.evaluate(() => document.documentElement.scrollWidth) <= width+1, name+' overflows '+width);
}

try {
  await scenario({width: 390, guide: true, setup: true, colorScheme: 'dark'}, async ({page, restart}) => {
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await theme(page, 'Light');
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
    await theme(page, 'Use system setting');
    await page.emulateMedia({colorScheme: 'light'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await page.emulateMedia({colorScheme: 'dark'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await page.getByText('Optional LAN or VPN access for other devices', {exact: true}).click();
    await page.getByRole('checkbox', {name: /^Allow access from other devices/}).check();
    await page.getByText(/Restart FlintEye to activate HTTPS/).waitFor();
    await assertWidth(page, 'Initial setup', 390);
    await page.getByLabel('Server IPv4 address').fill('192.0.2.1');
    await page.getByLabel('Permitted source networks').fill('192.0.2.2/32');
    await page.getByLabel(/setup token/i).fill('synthetic-token');
    await page.getByLabel('Password', {exact: true}).fill('qa-password-174');
    await page.getByLabel('Confirm password', {exact: true}).fill('qa-password-174');
    await page.getByRole('button', {name: 'Create administrator account', exact: true}).click();
    await page.getByRole('region', {name: 'LAN or VPN connection'}).getByText(/Restart FlintEye to apply them/).waitFor();

    const guide = page.getByRole('complementary', { name: 'Getting started' });
    await guide.getByRole('button', {name: 'Next', exact: true}).click();
    await page.getByRole('heading', {name: 'UVC Camera Discovery'}).waitFor();
    await guide.getByRole('button', {name: 'Next', exact: true}).click();
    await page.locator('#recording-folder').waitFor();
    await guide.getByRole('button', {name: 'Skip for now', exact: true}).click();
    await guide.waitFor({state: 'hidden'});
    assert.equal(await page.locator('.topbar-guide').count(), 0);
    await navigate(page, 'Information');
    await page.getByRole('button', {name: 'Getting started', exact: true}).click();
    await guide.waitFor();
    await guide.getByRole('button', {name: 'Skip for now', exact: true}).click();
    await guide.waitFor({state: 'hidden'});
    await page.getByRole('button', {name: 'Check for updates', exact: true}).click();
    await page.getByText(/No newer release is available/).waitFor();
    await page.getByRole('link', {name: 'Save diagnostics', exact: true}).waitFor();

    await navigate(page, 'Settings');
    await search(page, 'Tailscale', /^LAN and VPN connection/);
    await page.getByText('Restart required', {exact: true}).waitFor();
    assert.equal(await page.getByRole('link', {name: 'https://192.0.2.1:18080'}).count(), 0);
    restart();
    await page.getByRole('button', {name: 'Refresh connection status'}).click();
    await page.getByRole('link', {name: 'https://192.0.2.1:18080'}).waitFor();
    assert.equal(await page.getByText('Connect an iPhone or iPad', {exact: true}).count(), 0);
    await search(page, 'APIキー', /^API access/);
    assert.equal(await page.getByRole('combobox', {name: 'Settings category'}).inputValue(), 'integrations');
    await page.getByLabel('API key name', {exact: true}).waitFor();
    await search(page, 'イベント録画', /^Event recordings/);
    await page.locator('#event-settings').waitFor();
  });
  console.log('PASS theme preference, LAN activation, guide visibility and direct Settings destinations');

  await scenario({}, async ({page, patches, bindings}) => {
    await navigate(page, 'Settings');
    const level = page.getByRole('group', {name: 'Settings level'});
    assert.equal(await level.getByRole('button', {name: 'Basic', exact: true}).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.getByRole('textbox', {name: 'MediaMTX Path', exact: true}).count(), 0);
    const usb = page.locator('.settings-section-cameras').filter({has: page.getByRole('heading', {name: 'UVC Camera Discovery'})});
    await usb.getByRole('button', {name: /^Blocked USB/}).click();
    assert(await usb.getByRole('button', {name: 'Apply Device', exact: true}).isDisabled());
    await usb.getByRole('button', {name: /^Replacement USB/}).click();
    assert(await usb.getByRole('checkbox', {name: 'Enable USB camera', exact: true}).isChecked());
    await usb.getByRole('checkbox', {name: 'Enable USB camera', exact: true}).uncheck();
    await usb.getByRole('combobox', {name: 'Use this device for'}).selectOption('retained-usb');
    await usb.getByRole('button', {name: 'Reconnect camera', exact: true}).click();
    await page.getByRole('dialog').getByText(/Replace the capture device for Retained USB/).waitFor();
    await page.getByRole('dialog').getByRole('button', {name: 'Cancel', exact: true}).click();
    assert.deepEqual(bindings, []);
    await usb.getByRole('button', {name: 'Reconnect camera', exact: true}).click();
    await page.getByRole('dialog').getByRole('button', {name: 'Confirm replacement', exact: true}).click();
    await page.getByText('Saved USB camera reconnected.', {exact: true}).waitFor();
    assert.deepEqual(bindings, [{replace_camera_id: 'retained-usb', expected_device: usbDevices[1].stable_device}]);

    await chooseSettingsCategory(page, 'Logging');
    await page.getByRole('combobox', {name: /^Log Level/}).selectOption('ERROR');
    await chooseSettingsCategory(page, 'Multiview', {advanced: false});
    assert.equal(await page.getByRole('combobox', {name: /^Source Mode/}).count(), 0);
    await page.getByLabel('Layout preset').selectOption({label: '2 × 1'});
    await page.getByRole('button', {name: 'Save changes', exact: true}).click();
    await page.getByText('All changes saved', {exact: true}).waitFor();
    assert.equal(patches.at(-1).logging.level, 'ERROR');
    assert.equal(patches.at(-1).multiview.layout.canvas_width, 1280);
    assert.deepEqual(patches.at(-1).multiview.layout.source_slots, [['one', 'two'], ['three', null]]);
    await chooseSettingsCategory(page, 'Multiview');
    assert.equal(await page.getByRole('combobox', {name: /^Source Mode/}).inputValue(), 'env');
    await chooseSettingsCategory(page, 'Cameras', {advanced: false});
    await page.getByRole('button', {name: 'Add IP Camera'}).click();
    assert.equal(await page.locator('.ip-camera-card:visible').count(), 1);
    await page.waitForFunction(() => document.activeElement?.id === 'ip-name-ipcam1');
  });
  console.log('PASS Basic editing preserves Advanced values, USB rebind confirmation and camera focus');

  for (const [width, height] of [[1440, 900], [1024, 768], [320, 720], [390, 844], [430, 932], [844, 390]]) {
    await scenario({width, height, colorScheme: 'dark'}, async ({page}) => {
      const mobile = width <= 900;
      await page.getByText(/Receiving cameras$/).waitFor();
      assert.equal(await page.locator('.responsive-details').getAttribute('open') !== null, !mobile);
      await assertWidth(page, 'Dashboard', width);
      if (mobile) {
        const nav = await page.locator('.sidebar .nav').evaluate(element => ({
          height: element.getBoundingClientRect().height, scrollWidth: element.scrollWidth,
        }));
        assert(nav.height < 57, 'Phone navigation uses more than one row');
      }
      await navigate(page, 'Information');
      await page.getByText('System and API details', {exact: true}).waitFor();
      assert.equal(await page.locator('.responsive-details').first().getAttribute('open') !== null, !mobile);
      await assertWidth(page, 'Information', width);
      await navigate(page, 'Live View');
      const live = page.locator('iframe.webrtc-frame');
      await live.waitFor();
      await assertWidth(page, 'Live View', width);
      const player = await live.boundingBox();
      assert(player.y < height, 'Live player starts below the first screen');
      if (width <= 1200) {
        const strip = await page.locator('.thumb-grid').boundingBox();
        assert(player.y < strip.y, 'Live player should be above camera choices');
      }
      await navigate(page, 'Multiview');
      await live.waitFor();
      const composite = await live.boundingBox();
      assert(composite.height < 620 && composite.y < height);
      await assertWidth(page, 'Multiview', width);
      await navigate(page, 'Recordings');
      await page.getByRole('button', {name: 'Event recordings', exact: true}).click();
      await page.getByRole('heading', {name: new RegExp(longName)}).waitFor();
      await assertWidth(page, 'Long event names', width);
      await page.getByRole('button', {name: 'Loop recordings', exact: true}).click();
      if (mobile) {
        await page.getByRole('button', {name: 'Show filters and sorting'}).click();
      }
      const field = page.getByRole('combobox', {name: 'Sort field'});
      await field.waitFor();
      assert((await field.boundingBox()).height >= 44);
      const playback = page.locator('.recording-card-actions button').first();
      await playback.click();
      const modal = page.getByRole('dialog');
      await modal.waitFor();
      const close = modal.getByRole('button', {name: 'Close player', exact: true});
      const closeBox = await close.boundingBox();
      assert(closeBox.y >= 0 && closeBox.y + closeBox.height <= height+1);
      await close.click();
      await navigate(page, 'Settings');
      if (mobile) await page.getByRole('combobox', {name: 'Settings category'}).waitFor();
      await assertWidth(page, 'Settings', width);
    });
    console.log('PASS responsive dark mode', width+'x'+height);
  }
} finally {
  await browser.close();
}
