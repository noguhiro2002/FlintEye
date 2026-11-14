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

    @app.middleware('http')
    async def same_origin_mutations(request: Request, call_next):
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
            if not setup_token or not isinstance(supplied, str) or not hmac.compare_digest(supplied, setup_token):
                raise HTTPException(403, 'Enter the setup token from the server')
            password = payload.get('password', '')
            if not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise HTTPException(422, 'Use a password with 12–1024 characters')
            context.store.patch_runtime({'auth': {'provider': 'local', 'viewer_auth_required': True,
                'session_secret': generate_session_secret(),
                'local': {'admin': {'username': 'admin', 'password_hash': hash_password(password)}}}})
            setup_token = ''
            (data / 'setup-token').unlink(missing_ok=True)
            from flinteye_app.orchestrator_api import _on_startup
            _on_startup()
        return {'ok': True}

    @app.post('/api/v1/accounts/viewer', dependencies=[Depends(require_admin)])
    def viewer_password(payload: dict):
        password = payload.get('password', '')
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise HTTPException(422, 'Use a password with 12–1024 characters')
        context.store.patch_runtime({'auth': {'local': {'viewer': {'username': 'viewer', 'password_hash': hash_password(password)}},
                                            'session_secret': generate_session_secret()}})
        return {'ok': True, 'login_required': True}

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
        return {'folder_picker': bool(desktop and local)}

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
