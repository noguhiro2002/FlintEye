"""Build on each target OS/CPU with vetted native FFmpeg and MediaMTX binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import platform
import tarfile
from release_lib import version, binary_architecture
from collect_licenses import collect

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--vendor', type=Path, required=True, help='Directory containing bin/ and THIRD_PARTY_NOTICES.txt')
args = parser.parse_args()
vendor = args.vendor.resolve()
app_version = version()
architecture = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
if architecture is None:
    raise SystemExit('Only native x86-64 and ARM64 builds are supported')
suffix = '.exe' if sys.platform == 'win32' else ''
for name in ('ffmpeg', 'ffprobe', 'mediamtx'):
    if not (vendor / 'bin' / (name + suffix)).is_file():
        raise SystemExit(f'Missing native {name} binary')
    if binary_architecture(vendor / 'bin' / (name + suffix)) != architecture:
        raise SystemExit(f'{name} does not match the package CPU architecture')
if not (vendor / 'THIRD_PARTY_NOTICES.txt').is_file():
    raise SystemExit('Provide notices, source/build links and redistribution terms for the exact vendor binaries')
for required in ('licenses', 'corresponding-source.tar.gz', 'vendor-lock.json', 'ffmpeg-buildconf.txt'):
    if not (vendor / required).exists():
        raise SystemExit(f'Missing vendor redistribution material: {required}')
# Fail before packaging if ffmpeg is not suitable for the existing pipelines.
ffmpeg = str(vendor / 'bin' / ('ffmpeg' + suffix))
configuration = subprocess.check_output([ffmpeg, '-hide_banner', '-buildconf'], text=True, stderr=subprocess.STDOUT)
if '--enable-nonfree' in configuration:
    raise SystemExit('FFmpeg --enable-nonfree binaries cannot be redistributed')
for option, required in [('-filters', 'drawtext'), ('-encoders', 'libx264')]:
    result = subprocess.run([ffmpeg, '-hide_banner', option], capture_output=True, text=True, check=True)
    if required not in result.stdout + result.stderr: raise SystemExit(f'FFmpeg must include {required}')
subprocess.run([sys.executable, str(ROOT / 'packaging/smoke_private_input.py'),
                '--ffmpeg', ffmpeg, '--ffprobe', str(vendor / 'bin' / ('ffprobe' + suffix)),
                '--mediamtx', str(vendor / 'bin' / ('mediamtx' + suffix))], check=True, cwd=ROOT)
subprocess.run(['npm.cmd' if sys.platform == 'win32' else 'npm', 'ci'], cwd=ROOT / 'frontend', check=True)
subprocess.run(['npm.cmd' if sys.platform == 'win32' else 'npm', 'run', 'build'], cwd=ROOT / 'frontend', check=True)
collect(vendor / 'licenses/runtime')
sep = os.pathsep
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'FlintEye',
           '--exclude-module', 'readline',
           '--add-data', f'{ROOT / "frontend/dist"}{sep}frontend/dist',
           '--add-data', f'{vendor / "THIRD_PARTY_NOTICES.txt"}{sep}.',
           '--add-data', f'{ROOT / "LICENSE"}{sep}.',
           '--add-data', f'{ROOT / "THIRD_PARTY_NOTICES.md"}{sep}.',
           '--add-data', f'{vendor / "licenses"}{sep}licenses',
           '--add-data', f'{vendor / "vendor-lock.json"}{sep}.',
           '--add-data', f'{vendor / "ffmpeg-buildconf.txt"}{sep}.',
           '--add-binary', f'{vendor / "bin"}{sep}bin', '--hidden-import', 'tkinter',
           '--hidden-import', 'tkinter.filedialog', '--hidden-import', 'tkinter.messagebox',
           '--collect-all', 'onvif', '--hidden-import',
           'pystray.' + ('_win32' if sys.platform == 'win32' else '_darwin' if sys.platform == 'darwin' else '_xorg')]
for name in ('uvc_to_rtsp', 'ip_camera_to_rtsp', 'multiview_input_to_rtsp', 'multiview_buffer_to_rtsp', 'multiview_raw_compositor', 'multiview_to_rtsp'):
    command += ['--hidden-import', 'flinteye_app.workers.' + name]
if sys.platform in ('win32', 'darwin'): command += ['--windowed']
if sys.platform == 'darwin': command += ['--osx-bundle-identifier', 'community.flinteye']
command += [str(ROOT / 'flinteye.py')]
subprocess.run(command, cwd=ROOT, check=True)
if sys.platform.startswith('linux'):
    from native_sources import collect as collect_native_sources
    collect_native_sources(ROOT / 'dist/FlintEye', vendor / 'system-sources', vendor / 'licenses/runtime/system')
    shutil.copytree(vendor / 'licenses', ROOT / 'dist/FlintEye/_internal/licenses', dirs_exist_ok=True)
if sys.platform == 'darwin':
    import plistlib
    info = ROOT / 'dist/FlintEye.app/Contents/Info.plist'
    payload = plistlib.loads(info.read_bytes())
    payload.update({'NSCameraUsageDescription': 'FlintEye uses connected cameras for live monitoring and recording.', 'LSMinimumSystemVersion': '14.0',
                    'CFBundleShortVersionString': app_version, 'CFBundleVersion': app_version})
    info.write_bytes(plistlib.dumps(payload))
    # Ad-hoc signing is required for local ARM64 executable integrity; no Developer ID/notarization.
    # PyInstaller signs nested native code. Only the outer seal changed above.
    subprocess.run(['codesign', '--force', '--sign', '-', str(ROOT / 'dist/FlintEye.app')], check=True)
    from verify_macos import verify_app
    verify_app(ROOT / 'dist/FlintEye.app')
    dmg_contents = ROOT / 'build/dmg-contents'
    if dmg_contents.exists():
        shutil.rmtree(dmg_contents)
    dmg_contents.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'dist/FlintEye.app', dmg_contents / 'FlintEye.app', dirs_exist_ok=True, symlinks=True)
    if not (dmg_contents / 'Applications').is_symlink():
        (dmg_contents / 'Applications').symlink_to('/Applications', target_is_directory=True)
    subprocess.run(['hdiutil', 'create', '-ov', '-volname', 'FlintEye', '-srcfolder', str(dmg_contents),
                    str(ROOT / f'dist/FlintEye-{app_version}-macos-{architecture}.dmg')], check=True)
manifest = {str(p.relative_to(vendor)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (vendor / 'bin').rglob('*') if p.is_file()}
(ROOT / 'dist/vendor-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
target_os = {'win32': 'windows', 'darwin': 'macos'}.get(sys.platform, 'linux')
source_output = ROOT / f'dist/FlintEye-{app_version}-{target_os}-{architecture}-sources.tar.gz'
if sys.platform.startswith('linux'):
    with tarfile.open(source_output, 'w:gz') as archive:
        archive.add(vendor / 'corresponding-source.tar.gz', arcname='media-sources.tar.gz')
        archive.add(vendor / 'system-sources', arcname='system-sources')
else:
    shutil.copy2(vendor / 'corresponding-source.tar.gz', source_output)
shutil.make_archive(str(ROOT / f'dist/FlintEye-{app_version}-{target_os}-{architecture}-licenses'), 'zip', vendor / 'licenses')
