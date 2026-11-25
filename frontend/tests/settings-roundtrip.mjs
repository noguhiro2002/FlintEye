import { chooseSettingsCategory } from './settings-navigation.mjs';
// Playwright drives the production Settings form. The real server persists and
// validates edits; cameras and media processes are disabled in this fixture.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium } from './browser.mjs';

const [base, profile, output] = process.argv.slice(2);
assert.equal(new URL(base).hostname, '127.0.0.1');
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(12_000);
const cases = [], pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));
page.on('dialog', dialog => dialog.accept());
const header = page.locator('.settings-page-header');
const category = name => chooseSettingsCategory(page, name);
const section = name => page.locator(`.settings-section-${name}`);
const label = name => new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:\\s|$)`);
const password = 'settings-fixture-admin-only';

async function effective() {
  const response = await context.request.get(base+'/api/v1/config/effective');
  assert.equal(response.status(), 200);
  return response.json();
}

async function save() {
  await header.getByRole('button', {name: 'Save changes', exact: true}).click();
  await header.getByText('All changes saved', {exact: true}).waitFor();
  await page.waitForFunction(() => !document.querySelector('.settings-fields')?.disabled);
  return effective();
}

async function edit(scope, fields) {
  for (const [kind, name, , value] of fields) {
    const field = scope.getByRole(kind, {name: label(name)});
    if (kind === 'checkbox') {
      await field.setChecked(!value);
      assert.equal(await field.isChecked(), !value, name);
      await field.setChecked(value);
    } else if (kind === 'combobox') {
      const options = await field.locator('option').evaluateAll(rows => rows.map(row => [row.value, row.disabled]));
      for (const [choice, disabled] of options) {
        if (disabled) continue;
        await field.selectOption(choice);
        assert.equal(await field.inputValue(), choice, name);
      }
      await field.selectOption(value);
    } else {
      await field.fill(String(value));
    }
  }
}

function verify(data, fields, id) {
  for (const [, name, key, value, expected = value] of fields) {
    assert.deepEqual(key.split('.').reduce((object, segment) => object?.[segment], data), expected, name);
    cases.push({group: id, field: name, path: key, result: 'effective-value-after-GUI-save'});
  }
}

async function run(categoryName, css, fields) {
  await category(categoryName);
  await edit(section(css), fields);
  verify(await save(), fields, css);
}

try {
  await page.goto(base+'/');
  await page.getByLabel(/^(Server )?Setup token$/i).fill((await readFile(join(profile, 'setup-token'), 'utf8')).trim());
  await page.getByLabel('Password', {exact: true}).fill(password);
  await page.getByLabel('Confirm password', {exact: true}).fill(password);
  await page.getByRole('button', {name: 'Create administrator account', exact: true}).click();
  const skip = page.getByRole('button', {name: 'Skip for now', exact: true});
  await skip.click();
  await page.locator('.sidebar').getByRole('button', {name: 'Settings', exact: true}).click();
  const initial = await effective();

  await run('General', 'general', [
    ['textbox', 'App Title', 'ui.app_title', '試験 FlintEye'], ['textbox', 'Sidebar Title', 'ui.sidebar_title', 'QA Sidebar'],
    ['textbox', 'Footer Text', 'ui.footer_text', 'QA footer'],
  ]);
  await page.reload();
  await page.locator('.sidebar').getByRole('button', {name: 'Settings', exact: true}).click();
  assert.equal(await page.locator('.topbar-title').innerText(), '試験 FlintEye');

  await category('Runtime & access');
  await page.getByText('Advanced runtime options', {exact: true}).click();
  assert.equal(await page.getByLabel(label('Admin Username')).isEditable(), false);
  assert.equal(await page.getByLabel(label('Viewer Username')).isEditable(), false);
  const runtime = [
    ['textbox', 'API Host', 'api.host', '127.0.0.2'],
    ['spinbutton', 'API Port', 'api.port', 65535],
    ['spinbutton', 'Session TTL (sec)', 'auth.session_ttl_sec', 7200],
    ['combobox', 'Auth Provider', 'auth.provider', 'local'],
    ['checkbox', 'Viewer authentication required', 'auth.viewer_auth_required', true],
    ['spinbutton', 'Snapshot Timeout (sec)', 'snapshot.timeout_sec', 5.5],
    ['spinbutton', 'Thumbnail Refresh Interval (sec)', 'snapshot.thumbnail_refresh_interval_sec', 4.5],
  ];
  await edit(section('runtime'), runtime);
  verify(await save(), runtime, 'runtime');
  assert.equal(new URL(page.url()).origin, base, 'Saving API fields must not break the active listener');

  await run('Logging', 'logging', [
    ['textbox', 'Log Directory', 'logging.directory', join(profile, 'qa logs')],
    ['combobox', 'Log Level', 'logging.level', 'WARNING'], ['textbox', 'Log Retention', 'logging.retention', '3d'],
  ]);

  await run('MediaMTX', 'mediamtx', [
    ['combobox', 'Control Mode', 'mediamtx.control_mode', 'direct'],
    ['textbox', 'Service Name', 'mediamtx.service_name', 'flinteye-media-qa'],
    ['textbox', 'RTSP Base URL', 'mediamtx.rtsp_base_url', 'rtsp://127.0.0.1:13454'],
    ['textbox', 'Internal RTSP Base URL', 'mediamtx.internal_rtsp_base_url', 'rtsp://127.0.0.1:13455'],
    ['textbox', 'WebRTC Base URL', 'mediamtx.webrtc_base_url', '/media'],
    ['checkbox', 'Auto-start MediaMTX on API startup', 'mediamtx.autostart_on_api_start', false],
  ]);

  await run('Recording', 'recording', [
    ['checkbox', 'Recording Enabled', 'recording.enabled', true],
    ['checkbox', 'Record all configured cameras', 'recording.record_all_cameras', false],
    ['checkbox', 'Auto apply recording config', 'recording.auto_apply', true],
    ['checkbox', 'Include multiview paths', 'recording.include_multiview', true],
    ['textbox', 'Additional Record Paths', 'recording.record_paths', 'qa-one\nqa-two', ['qa-one','qa-two']],
    ['textbox', 'Recording folder', 'recording.record_root', join(profile, 'alternate recordings')],
    ['spinbutton', 'Maximum recording storage (GB)', 'recording.max_bytes', 1.5, 1_500_000_000],
    ['spinbutton', 'Maximum retention (days)', 'recording.record_delete_after', 3, '72h'],
    ['checkbox', 'Show recordings from previous locations', 'recording.show_previous', false],
    ['combobox', 'Record Format', 'recording.record_format', 'mpegts'],
    ['textbox', 'Segment Duration', 'recording.record_segment_duration', '20s'],
    ['textbox', 'Playback Cache Delete After', 'recording.playback_cache_delete_after', '12h'],
    ['textbox', 'Record Part Duration', 'recording.record_part_duration', '500ms'],
    ['textbox', 'Record Max Part Size', 'recording.record_max_part_size', '24M'],
  ]);
  assert((await effective()).recording.previous_roots.some(entry => entry.path === initial.recording.record_root));

  await category('Multiview');
  const multiview = section('multiview');
  const multiviewFields = [
    ['checkbox', 'Multiview Enabled', 'enabled', true], ['combobox', 'Source Mode', 'source_mode', 'env'],
    ['textbox', 'MediaMTX API URL', 'mtx_api_url', 'http://127.0.0.1:14997/v3/paths/list'],
    ['textbox', 'Output Prefix', 'output_prefix', 'qa-view'],
    ['checkbox', 'Auto No Stream placeholders for missing MediaMTX paths', 'auto_placeholder_missing_sources', false],
    ['textbox', 'Extra Source Paths', 'source_paths', 'qa-two\nqa-one', ['qa-two','qa-one']],
    ['spinbutton', 'Tile Count', 'tile_count', 2], ['spinbutton', 'Max Sources', 'max_sources', 8],
    ['combobox', 'Default IP Input', 'input_defaults.mode', 'normalized_primary'],
    ['spinbutton', 'Normalized Input FPS', 'input_defaults.target_fps', 8],
    ['textbox', 'Normalized Resolution', 'input_defaults.resolution', '320x180'],
    ['combobox', 'Normalized Input Quality', 'input_defaults.quality_preset', 'low'],
    ['checkbox', 'Fall back to the public primary path', 'input_defaults.fallback_to_primary', false],
    ['checkbox', 'Enable synchronized raw composition', 'sync_buffer.enabled', true],
    ['spinbutton', 'Sync delay (sec)', 'sync_buffer.delay_sec', 2],
    ['spinbutton', 'Buffer capacity (sec)', 'sync_buffer.buffer_sec', 4],
    ['spinbutton', 'Sync / output FPS', 'sync_buffer.fps', 8],
    ['combobox', 'Late frame policy', 'sync_buffer.late_frame_policy', 'no_stream'],
    ['spinbutton', 'FPS', 'quality.fps', 8], ['combobox', 'Quality Preset', 'quality.quality_preset', 'low'],
    ['textbox', 'Encoder', 'quality.encoder', 'libx264'], ['combobox', 'Latency Preset', 'latency_preset', 'normal'],
    ['spinbutton', 'Input Stall Timeout (sec)', 'input_stall_timeout_sec', 20],
    ['combobox', 'Input Stall Option', 'input_stall_timeout_option', 'rw_timeout'],
    ['checkbox', 'Monitor every Multiview input', 'input_healthcheck_enabled', true],
    ['spinbutton', 'Multiview input health interval', 'input_healthcheck_interval_sec', 3],
    ['spinbutton', 'Multiview input isolation threshold', 'input_isolation_threshold', 5],
    ['spinbutton', 'Multiview input retry interval', 'input_retry_interval_sec', 20],
    ['spinbutton', 'Input Queue', 'input_thread_queue_size', 320],
    ['textbox', 'Bitrate', 'quality.bitrate', '2M'], ['textbox', 'Maxrate', 'quality.maxrate', '3M'],
    ['textbox', 'Buffer Size', 'quality.bufsize', '6M'],
    ['textbox', 'Input RTSP Base URL', 'input_rtsp_base_url', 'rtsp://127.0.0.1:13455'],
    ['textbox', 'Output RTSP Base URL', 'output_rtsp_base_url', 'rtsp://127.0.0.1:13455'],
    ['spinbutton', 'Grid Columns', 'layout.grid_columns', 3],
    ['checkbox', 'Periodic multiview restart', 'maintenance.enabled', true],
    ['spinbutton', 'Restart Interval (sec)', 'maintenance.restart_interval_sec', 900],
    ['checkbox', 'Align with record segments', 'maintenance.align_with_record_segments', false],
    ['spinbutton', 'Restart Offset (sec)', 'maintenance.restart_offset_sec', 4],
  ];
  await edit(multiview, multiviewFields);
  await multiview.getByText('Sync buffer details', {exact:true}).click();
  const buffering = [
    ['spinbutton', 'Memory limit / input (MB)', 'sync_buffer.memory_limit_mb_per_input', 48],
    ['spinbutton', 'Maximum hold (sec)', 'sync_buffer.max_hold_sec', 7],
    ['spinbutton', 'Source reconnect (sec)', 'sync_buffer.reconnect_sec', 4],
  ];
  await edit(multiview, buffering);
  verify((await save()).multiview, [...multiviewFields,...buffering], 'multiview');

  await category('Cameras');
  await page.getByRole('button', {name:'Add IP Camera', exact:true}).click();
  const camera = page.locator('.ip-camera-card').first();
  const cameraFields = [
    ['textbox', 'Display Name', 'display_name', '検証カメラ'],
    ['textbox', 'MediaMTX Path', 'path', 'qa-camera'],
    ['textbox', 'Source URL', 'ip.source_url', 'rtsp://127.0.0.1:15554/qa-fixture'],
    ['combobox', 'ONVIF discovery', 'ip.onvif_mode', 'manual'],
    ['textbox', 'ONVIF device service address', 'ip.onvif_address', 'http://127.0.0.1:12020/onvif/device_service'],
    ['textbox', 'ONVIF Username', 'ip.onvif_username', 'fixture-operator'],
    ['combobox', 'Timestamp mode', 'ip.timestamp_mode', 'cfr'],
    ['combobox', 'Relay mode', 'ip.relay_mode', 'libx264'],
    ['spinbutton', 'CFR FPS', 'ip.cfr_fps', 12],
    ['combobox', 'Input mode', 'ip.multiview_input.mode', 'manual'],
    ['textbox', 'Manual RTSP URL', 'ip.multiview_input.manual_url', 'rtsp://127.0.0.1:15554/qa-substream'],
    ['spinbutton', 'FPS override', 'ip.multiview_input.target_fps', 10],
    ['textbox', 'Resolution override', 'ip.multiview_input.resolution', '320x180'],
    ['combobox', 'Quality override', 'ip.multiview_input.quality_preset', 'low'],
  ];
  await edit(camera, cameraFields);
  await camera.getByLabel(label('ONVIF Password')).fill('fixture-camera-only');
  const details = [
    ['Conversion details', [
      ['textbox', 'encoder', 'ip.multiview_input.encoder', 'libx264'],
      ['textbox', 'bitrate', 'ip.multiview_input.bitrate', '400k'],
      ['textbox', 'maxrate', 'ip.multiview_input.maxrate', '600k'],
      ['textbox', 'bufsize', 'ip.multiview_input.bufsize', '1M'],
      ['textbox', 'x264_preset', 'ip.multiview_input.x264_preset', 'fast'],
      ['spinbutton', 'thread queue', 'ip.multiview_input.thread_queue_size', 256],
      ['spinbutton', 'stall timeout', 'ip.multiview_input.stall_timeout_sec', 20],
    ]],
    ['Stability & watchdog', [
      ['checkbox', 'Auto Restart', 'ip.periodic_restart_enabled', true],
      ['spinbutton', 'Restart Interval (sec)', 'ip.periodic_restart_interval_sec', 900],
      ['checkbox', 'Snapshot Watchdog', 'ip.watchdog_enabled', true],
      ['spinbutton', 'Watchdog interval', 'ip.watchdog_interval_sec', 120],
      ['spinbutton', 'Watchdog timeout', 'ip.watchdog_timeout_sec', 5.5],
      ['spinbutton', 'Failure threshold', 'ip.watchdog_failure_threshold', 4],
    ]],
    ['Encode settings', [
      ['textbox', 'Bitrate', 'ip.bitrate', '2M'],
      ['textbox', 'Maxrate', 'ip.maxrate', '3M'],
      ['textbox', 'Bufsize', 'ip.bufsize', '4M'],
      ['spinbutton', 'GOP', 'ip.gop', 24],
      ['textbox', 'Preset', 'ip.x264_preset', 'fast'],
    ]],
  ];
  for (const [name, fields] of details) {
    const detail = camera.locator('details').filter({has:page.getByText(name, {exact:true})});
    await detail.locator('summary').click();
    await edit(detail, fields);
  }
  const configured = (await save()).cameras.find(item => item.path === 'qa-camera');
  assert(configured, 'Camera added while monitoring is stopped');
  verify(configured, [...cameraFields,...details.flatMap(([, fields]) => fields)], 'cameras');
  assert.equal(configured.ip.onvif_password, 'fixture-camera-only');
  await camera.getByRole('button', {name:'Remove', exact:true}).click();
  assert(!(await save()).cameras.some(item => item.path === 'qa-camera'));
  cases.push({group:'cameras', result:'camera removed and absence verified'});

  await category('Runtime JSON');
  const editor = page.getByRole('textbox', {name: 'Full runtime JSON'});
  const before = await effective();
  const configs = JSON.parse(await editor.inputValue());
  await editor.fill('{ broken JSON');
  await page.getByRole('button', {name:'Replace Runtime & Apply', exact:true}).click();
  await page.locator('.panel-error').waitFor();
  assert.match(await page.locator('.panel-error').innerText(), /JSON|property name|unexpected token/i);
  assert.deepEqual(await effective(), before);
  configs.multiview.layout.canvas_width = 800;
  await editor.fill(JSON.stringify(configs, null, 2));
  await page.getByRole('button', {name:'Replace Runtime & Apply', exact:true}).click();
  await header.getByText('All changes saved', {exact:true}).waitFor();
  assert.equal((await effective()).multiview.layout.canvas_width, 800);
  cases.push({group:'advanced', result:'invalid edit rejected; valid edit read back'});
  await page.reload();
  await page.locator('.sidebar').getByRole('button',{name:'Settings',exact:true}).click();
  assert.equal((await effective()).multiview.layout.canvas_width, 800);
  assert.deepEqual(pageErrors, []);
  await writeFile(join(output, 'settings-roundtrip.json'), JSON.stringify({result:'passed', apiMocked:false, cases}, null, 2)+'\n');
  console.log(`PASS ${cases.length} Settings value checks through the real API`);
} catch (error) {
  await page.screenshot({ path:join(output, 'settings-failure.png'), fullPage:true }).catch(() => {});
  await writeFile(join(output, 'settings-roundtrip.json'), JSON.stringify({result:'failed', cases, error:String(error)}, null, 2)+'\n');
  throw error;
} finally {
  await context.close();
  await browser.close();
}
