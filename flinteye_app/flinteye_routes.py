"""Production-only setup, authenticated media bridge, and packaged UI."""
from __future__ import annotations
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import time
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from flinteye_app.orchestrator_auth import generate_session_secret, hash_password, local_auth_is_configured
from flinteye_app.flinteye_runtime import application_dir, launch_command
from flinteye_app.flinteye_storage import suggested_quota


def install_routes(app, context, *, setup_token: str, desktop: bool):
    from flinteye_app.orchestrator_api import require_admin, require_viewer
    data = Path(context.store.runtime_file).resolve().parent
    from flinteye_app.network_access import Bootstrap, permitted_source
    bootstrap = Bootstrap(data, setup_token)
    context.bootstrap = bootstrap
    # Snapshot the effective listener policy. Saved changes apply on restart.
    active_network = context.store.get_effective().network.model_copy(deep=True)

    def owner_local(request):
        if not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, 'Change connection settings on the server itself')

    @app.middleware('http')
    async def same_origin_mutations(request: Request, call_next):
        if active_network.enabled:
            peer = request.client.host if request.client else ''
            if not permitted_source(peer, active_network.allowed_subnets):
                return Response('This device is outside the permitted LAN ranges', status_code=403)
            if peer not in {'127.0.0.1', '::1'} and request.url.scheme != 'https':
                return Response('Use the HTTPS address shown on the server', status_code=403)
            if request.url.hostname not in {'127.0.0.1', 'localhost', '::1', active_network.address}:
                return Response('Unexpected server address', status_code=400)
        # Cookies authenticate media requests too. Reject cross-site form/fetch mutations.
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = request.headers.get('origin')
            if (origin and origin != str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site') == 'cross-site':
                return Response('Cross-origin request rejected', status_code=403)
        return await call_next(request)

    @app.post('/api/v1/setup')
    def setup(request: Request, payload: dict):
        nonlocal setup_token
        with context.lock:
            if local_auth_is_configured(context.store.get_effective().auth):
                raise HTTPException(409, 'Setup is already complete')
            supplied = payload.get('token', '')
            bootstrap.verify(supplied, request.client.host if request.client else 'unknown')
            password = payload.get('password', '')
            if not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise HTTPException(422, 'Use a password with 12–1024 characters')
            connection = {}
            if payload.get('network') is not None:
                owner_local(request)
                from flinteye_app.orchestrator_models import NetworkAccessConfig
                from flinteye_app.network_access import ensure_certificates, lan_media_patch
                try:
                    network = NetworkAccessConfig.model_validate(payload['network'])
                    if network.enabled: ensure_certificates(data, network.address)
                    connection = {'network': network.model_dump(), 'api': {'host': '127.0.0.1'},
                                  **(lan_media_patch(context.store.get_effective()) if network.enabled else {})}
                except (ValueError, OSError) as error:
                    raise HTTPException(422, str(error)) from error
            context.store.patch_runtime({**connection, 'auth': {'provider': 'local', 'viewer_auth_required': True,
                'session_secret': generate_session_secret(),
                'local': {'admin': {'username': 'admin', 'password_hash': hash_password(password)}}}})
            setup_token = ''
            bootstrap.consume()
            from flinteye_app.orchestrator_api import _on_startup
            _on_startup()
        return {'ok': True}

    @app.post('/api/v1/setup/renew')
    def renew_setup(request: Request):
        owner_local(request)
        if local_auth_is_configured(context.store.get_effective().auth):
            raise HTTPException(409, 'Setup is already complete')
        # Requires existing token proof; expired tokens can only be renewed via native CLI.
        raise HTTPException(403, 'Use Renew setup token in the server control window, or restart the server')

    @app.get('/api/v1/network', dependencies=[Depends(require_admin)])
    def network_status(request: Request):
        owner_local(request)
        config = context.store.get_effective()
        listeners = context.listener or {}
        metadata = {}
        if active_network.enabled and (data/'tls/ca.crt').is_file():
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes
            ca = x509.load_pem_x509_certificate((data/'tls/ca.crt').read_bytes())
            metadata = {'fingerprint': ca.fingerprint(hashes.SHA256()).hex(), 'ca_expires': ca.not_valid_after_utc.isoformat()}
        group = getattr(context, 'listener_group', None)
        from flinteye_app.network_access import lan_guide_url
        return {'saved': config.network.model_dump(), 'active': active_network.model_dump(), 'guide_url': lan_guide_url(),
                'restart_required': config.network != active_network,
                'local_url': listeners.get('url'), 'lan_url': listeners.get('lan_url'),
                'error': group.lan_error if group else '', **metadata}

    @app.put('/api/v1/network', dependencies=[Depends(require_admin)])
    def change_network(request: Request, payload: dict):
        owner_local(request)
        from flinteye_app.orchestrator_models import NetworkAccessConfig
        from flinteye_app.network_access import backup_profile, ensure_certificates, lan_media_patch
        try:
            network = NetworkAccessConfig.model_validate(payload)
            if network.enabled and context.store.get_effective().auth.provider != 'local':
                raise ValueError('Built-in LAN access requires local administrator and viewer authentication')
            if network.enabled and context.store.get_effective().api.host != '127.0.0.1':
                raise ValueError('Set API host to 127.0.0.1 before enabling built-in LAN access')
            if network.enabled:
                ensure_certificates(data, network.address)
            backup_profile(data)
            context.store.patch_runtime({'network': network.model_dump(),
                **({'auth': {'viewer_auth_required': True}, **lan_media_patch(context.store.get_effective())} if network.enabled else {})})
        except (ValueError, OSError) as error:
            raise HTTPException(422, str(error)) from error
        return {'ok': True, 'restart_required': True}

    @app.post('/api/v1/network/guide', dependencies=[Depends(require_admin)])
    def connection_guide(request: Request):
        owner_local(request)
        from flinteye_app.network_access import export_guide
        config = context.store.get_effective()
        if not config.network.enabled:
            raise HTTPException(409, 'Enable LAN access first')
        folder = export_guide(data, config.network.address, config.api.port)
        return {'path': str(folder), 'message': 'Public certificate and instructions saved. Transfer them to your viewing devices and compare the fingerprint on this server.'}

    @app.post('/api/v1/network/renew-trust', dependencies=[Depends(require_admin)])
    def renew_trust(request: Request, payload: dict):
        owner_local(request)
        if payload != {'confirm': True}:
            raise HTTPException(422, 'Confirm that every viewing device must trust the new certificate')
        config = context.store.get_effective()
        if not config.network.enabled:
            raise HTTPException(409, 'Enable LAN access first')
        from flinteye_app.network_access import ensure_certificates, export_guide
        ensure_certificates(data, config.network.address, rotate_ca=True)
        export_guide(data, config.network.address, config.api.port)
        return {'ok': True, 'restart_required': True, 'message': 'Install the new trust certificate on every viewing device'}

    @app.post('/api/v1/network/firewall', dependencies=[Depends(require_admin)])
    def firewall(request: Request, payload: dict):
        owner_local(request)
        if payload.get('action') not in {'apply', 'remove'} or set(payload) != {'action'}:
            raise HTTPException(422, 'Choose apply or remove')
        from flinteye_app.windows_maintenance import manage_firewall
        try:
            return manage_firewall(data, context.store.get_effective(), payload['action'])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise HTTPException(409, 'Firewall change was not completed. Local access is still available. Check server diagnostics.') from error

    @app.get('/api/v1/diagnostics', dependencies=[Depends(require_admin)])
    def diagnostics():
        from flinteye_app.diagnostics import diagnostic_archive
        return Response(diagnostic_archive(context), media_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename="FlintEye-diagnostics.zip"', 'Cache-Control': 'no-store'})

    @app.post('/api/v1/accounts/viewer', dependencies=[Depends(require_admin)])
    def viewer_password(payload: dict):
        password = payload.get('password', '')
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise HTTPException(422, 'Use a password with 12–1024 characters')
        context.store.patch_runtime({'auth': {'local': {'viewer': {'username': 'viewer', 'password_hash': hash_password(password)}},
                                            'session_secret': generate_session_secret()}})
        return {'ok': True, 'login_required': True}

    @app.post('/api/v1/media/use-bundled', dependencies=[Depends(require_admin)])
    def use_bundled_media(request: Request):
        owner_local(request)
        from flinteye_app.network_access import private_write, backup_profile
        binary = application_dir()/'bin'/('mediamtx.exe' if sys.platform == 'win32' else 'mediamtx')
        if not binary.is_file():
            raise HTTPException(409, 'Bundled MediaMTX executable is missing. Reinstall the complete package.')
        backup_profile(data)
        configuration = data/'mediamtx.yml'
        if not configuration.exists(): private_write(configuration, b'paths:\n  all_others: {}\n')
        context.store.patch_runtime({'mediamtx': {'control_mode': 'direct',
            'direct': {'source': 'bundled', 'command': [str(binary), str(configuration)], 'working_dir': str(data)},
            'managed': {'enabled': True}}})
        return {'ok': True, 'message': 'Saved bundled MediaMTX. Use Start or Restart on Dashboard to apply it.'}

    update_cache = {}

    @app.get('/api/v1/updates', dependencies=[Depends(require_admin)])
    async def updates():
        from flinteye_app._version import VERSION, RELEASE_VERSION, RELEASE_CHANNEL
        from flinteye_app.release_updates import update_result
        import time
        if RELEASE_CHANNEL == 'source':
            return update_result([], current=VERSION, current_release=RELEASE_VERSION, channel=RELEASE_CHANNEL)
        if update_cache.get('expires', 0) > time.monotonic():
            return update_cache['result']
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                response = await client.get('https://api.github.com/repos/noguhiro2002/FlintEye/releases?per_page=100',
                                            headers={'Accept': 'application/vnd.github+json'})
                response.raise_for_status()
                releases = response.json()
            if not isinstance(releases, list) or any(not isinstance(item, dict) for item in releases):
                raise ValueError('Invalid release response')
            result = update_result(releases, current=VERSION, current_release=RELEASE_VERSION, channel=RELEASE_CHANNEL)
            update_cache.update(expires=time.monotonic() + 21600, result=result)
            return result
        except (httpx.HTTPError, ValueError):
            return {'current': VERSION, 'current_release': RELEASE_VERSION, 'channel': RELEASE_CHANNEL,
                    'available': False, 'message': 'Release information is currently unavailable.'}

    @app.get('/api/v1/desktop', dependencies=[Depends(require_admin)])
    def capabilities(request: Request):
        local = request.client and request.client.host in {'127.0.0.1', '::1'}
        return {'folder_picker': bool(desktop and local), 'startup_settings': bool(desktop and local)}

    def local_desktop(request: Request):
        if not desktop or not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, 'Start at login can only be changed on the installation computer')

    @app.get('/api/v1/desktop/startup', dependencies=[Depends(require_admin)])
    def startup_status(request: Request):
        local_desktop(request)
        from flinteye_app.cli import autostart_status
        return autostart_status()

    @app.put('/api/v1/desktop/startup', dependencies=[Depends(require_admin)])
    def change_startup(request: Request, payload: dict):
        local_desktop(request)
        if set(payload) != {'enabled'} or type(payload['enabled']) is not bool:
            raise HTTPException(422, 'Provide enabled as a boolean')
        from flinteye_app.cli import set_autostart, autostart_status
        try:
            set_autostart(payload['enabled'])
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return autostart_status()

    @app.post('/api/v1/storage/pick-folder', dependencies=[Depends(require_admin)])
    def pick_folder(request: Request):
        if not desktop or not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, 'Choose folders on the installation computer; otherwise enter a server path')
        import tempfile
        with tempfile.TemporaryDirectory(prefix="flinteye-picker-") as directory:
            output = Path(directory) / "selection.json"
            result = run_background(launch_command() + ['--pick-folder', str(output)], **background_process_options(), capture_output=True, text=True, timeout=120)
            if result.returncode or not output.is_file(): raise HTTPException(500, 'Could not open the folder picker')
            return json.loads(output.read_text(encoding='utf-8'))


    @app.get('/api/v1/storage/status', dependencies=[Depends(require_viewer)])
    def storage_status():
        return {'recording_paused': bool(context.storage_problem), 'message': context.storage_problem}

    @app.post('/api/v1/storage/suggest', dependencies=[Depends(require_admin)])
    def storage_suggest(payload: dict):
        path = Path(str(payload.get('path', ''))).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise HTTPException(422, 'Choose an existing absolute folder on the server')
        # Verify permissions without overwriting an existing file.
        import tempfile
        try:
            with tempfile.TemporaryFile(dir=path): pass
            quota = suggested_quota(path)
        except OSError as exc: raise HTTPException(422, 'Folder is not writable or unavailable') from exc
        if quota < 1_000_000_000:
            raise HTTPException(422, 'Not enough free space; choose another folder')
        return {'path': str(path.resolve()), 'max_bytes': quota}

    @app.api_route('/media/{path:path}', methods=['GET', 'HEAD', 'POST', 'PATCH', 'DELETE', 'OPTIONS'], dependencies=[Depends(require_viewer)])
    async def media(path: str, request: Request):
        # Fixed loopback upstream: callers cannot select another host or forward credentials.
        if '..' in path.split('/') or '\\' in path or path.startswith('/'):
            raise HTTPException(400, 'Invalid media path')
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() in {'content-type', 'accept', 'if-match'}}
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                upstream = await client.request(request.method, 'http://127.0.0.1:8889/' + path,
                                                params=request.query_params, headers=headers,
                                                content=await request.body())
        except httpx.HTTPError as exc: raise HTTPException(502, 'Media server is unavailable') from exc
        out = {key: value for key, value in upstream.headers.items()
               if key.lower() in {'content-type', 'etag', 'accept-patch', 'link'}}
        location = upstream.headers.get('location')
        if location:
            from urllib.parse import urljoin
            absolute = urlsplit(urljoin(str(upstream.url), location))
            out['location'] = '/media' + absolute.path + (('?' + absolute.query) if absolute.query else '')
        return Response(upstream.content, status_code=upstream.status_code, headers=out)

    dist = application_dir() / 'frontend/dist'
    if dist.is_dir():
        # API/media routes are registered first; UI has no history-router catch-all.
        app.mount('/', StaticFiles(directory=dist, html=True), name='ui')
