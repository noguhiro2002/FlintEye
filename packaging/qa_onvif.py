"""Loopback ONVIF fixture used by source tests and the installed application QA."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import hashlib
import hmac
import json
import threading
import time
from xml.etree import ElementTree
from xml.sax.saxutils import escape


SOAP = 'http://www.w3.org/2003/05/soap-envelope'
DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
MEDIA = 'http://www.onvif.org/ver10/media/wsdl'
MEDIA2 = 'http://www.onvif.org/ver20/media/wsdl'
PTZ = 'http://www.onvif.org/ver20/ptz/wsdl'
SCHEMA = 'http://www.onvif.org/ver10/schema'
USERNAME = 'qa-camera'
PASSWORD = 'qa-onvif-password-only'


def _authorized(envelope):
    token = envelope.find('.//{*}UsernameToken')
    if token is None or token.findtext('{*}Username') != USERNAME:
        return False
    nonce = base64.b64decode(token.findtext('{*}Nonce', ''), validate=True)
    created = token.findtext('{*}Created', '').encode()
    digest = base64.b64encode(hashlib.sha1(nonce + created + PASSWORD.encode()).digest())
    return hmac.compare_digest(digest, token.findtext('{*}Password', '').encode())


def _space(element, axis_ranges, *, minimum=-1):
    axis_xml = ''.join(f'<tt:{axis}Range><tt:Min>{minimum}</tt:Min><tt:Max>1</tt:Max></tt:{axis}Range>'
                       for axis in axis_ranges)
    return f'<tt:{element}><tt:URI>urn:flinteye:qa:{element}</tt:URI>{axis_xml}</tt:{element}>'


def _profiles(mode, include_config, *, media2):
    role = 't:Profiles'
    names = [('qa-main', 'QA Main'), ('qa-sub', 'QA Sub')]
    result = []
    for token, name in names:
        config = ''
        if include_config and mode != 'fixed':
            ptz = '<tt:Name>QA PTZ</tt:Name><tt:UseCount>1</tt:UseCount><tt:NodeToken>qa-node</tt:NodeToken>'
            config = (f'<t:Configurations><t:PTZ token="qa-ptz">{ptz}</t:PTZ></t:Configurations>' if media2 else
                      f'<tt:PTZConfiguration token="qa-ptz">{ptz}</tt:PTZConfiguration>')
        name_tag = 't:Name' if media2 else 'tt:Name'
        result.append(f'<{role} token="{token}"><{name_tag}>{name}</{name_tag}>{config}</{role}>')
    return ''.join(result)


@contextmanager
def onvif_fixture(rtsp_url, receipt: Path | None = None, *, excluded_ports=()):
    events = []
    lock = threading.Lock()

    class Camera(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        @property
        def origin(self):
            return f'http://127.0.0.1:{self.server.server_port}'

        def send_body(self, status, body, content_type):
            body = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path != '/events':
                self.send_error(404)
                return
            with lock:
                body = json.dumps(events)
            self.send_body(200, body, 'application/json')

        def do_POST(self):
            try:
                _, mode, endpoint = self.path.split('/')
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 65536:
                    raise ValueError('Invalid SOAP size')
                envelope = ElementTree.fromstring(self.rfile.read(size))
                command, = envelope.find(f'{{{SOAP}}}Body')
            except (ValueError, TypeError, ElementTree.ParseError):
                self.send_error(400)
                return
            namespace, operation = command.tag[1:].split('}', 1)
            endpoints = {'device': DEVICE, 'media': MEDIA, 'media2': MEDIA2, 'ptz': PTZ}
            if endpoints.get(endpoint) != namespace or mode not in {'full', 'media1', 'pan', 'zoom', 'fixed', 'slow'}:
                self.send_error(404)
                return
            if mode == 'slow':
                time.sleep(3)
            if not _authorized(envelope):
                self.send_error(401)
                return
            kinds = [entry.text for entry in command.findall('{*}Type')]
            profile = command.findtext('{*}ProfileToken')
            with lock:
                events.append({'mode': mode, 'endpoint': endpoint, 'operation': operation, 'types': kinds, 'profile': profile})
            body = self.response(mode, endpoint, operation, kinds, profile)
            if body is None:
                self.send_error(404)
                return
            self.send_body(200, f'<s:Envelope xmlns:s="{SOAP}" xmlns:t="{namespace}" xmlns:tt="{SCHEMA}">'
                           f'<s:Body><t:{operation}Response>{body}</t:{operation}Response></s:Body></s:Envelope>',
                           'application/soap+xml; charset=utf-8')

        def response(self, mode, endpoint, operation, kinds, profile):
            if endpoint == 'device' and operation == 'GetServices':
                media_name, namespace = ('media', MEDIA) if mode == 'media1' else ('media2', MEDIA2)
                services = [(media_name, namespace), ('ptz', PTZ)]
                return ''.join(f'<t:Service><t:Namespace>{ns}</t:Namespace>'
                               f'<t:XAddr>{self.origin}/{mode}/{name}</t:XAddr>'
                               '<t:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></t:Version></t:Service>'
                               for name, ns in services)
            if endpoint == 'device' and operation == 'GetDeviceInformation':
                values = {'Manufacturer': 'FlintEye QA', 'Model': 'Local ONVIF', 'FirmwareVersion': '1',
                          'SerialNumber': 'QA', 'HardwareId': 'QA'}
                return ''.join(f'<t:{name}>{value}</t:{name}>' for name, value in values.items())
            if endpoint in {'media', 'media2'} and (endpoint == 'media') == (mode == 'media1'):
                if operation == 'GetProfiles':
                    return _profiles(mode, endpoint == 'media' or kinds == ['All'], media2=endpoint == 'media2')
                if operation == 'GetStreamUri' and profile in {'qa-main', 'qa-sub'}:
                    uri = escape(f'{rtsp_url}/qa-input-{1 if profile == "qa-main" else 2}')
                    if endpoint == 'media':
                        return f'<t:MediaUri><tt:Uri>{uri}</tt:Uri><tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>' \
                               '<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot><tt:Timeout>PT0S</tt:Timeout></t:MediaUri>'
                    return f'<t:Uri>{uri}</t:Uri>'
            if endpoint == 'ptz':
                if operation == 'GetNodes':
                    return ''
                if operation == 'GetStatus' and profile in {'qa-main', 'qa-sub'}:
                    return ('<t:PTZStatus><tt:Position><tt:PanTilt x="0" y="0"/><tt:Zoom x="0"/></tt:Position>'
                            '<tt:UtcTime>2026-01-01T00:00:00Z</tt:UtcTime></t:PTZStatus>')
                if operation == 'GetConfigurationOptions':
                    spaces = _space('AbsoluteZoomPositionSpace', 'X', minimum=0) if mode == 'media1' else ''
                    if mode in {'full', 'pan', 'media1'}:
                        spaces += _space('ContinuousPanTiltVelocitySpace', 'XY')
                    if mode in {'full', 'zoom', 'media1'}:
                        spaces += _space('ContinuousZoomVelocitySpace', 'X')
                    return f'<t:PTZConfigurationOptions><tt:Spaces>{spaces}</tt:Spaces>' \
                           '<tt:PTZTimeout><tt:Min>PT0.1S</tt:Min><tt:Max>PT5S</tt:Max></tt:PTZTimeout></t:PTZConfigurationOptions>'
                if operation in {'ContinuousMove', 'AbsoluteMove', 'Stop'} and profile in {'qa-main', 'qa-sub'}:
                    return ''
            return None

    from lifecycle_common import free_port
    port = free_port(excluded=excluded_ports) if excluded_ports else 0
    with ThreadingHTTPServer(('127.0.0.1', port), Camera) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join(timeout=5)
            if receipt is not None:
                receipt.write_text(json.dumps(events, indent=2) + '\n', encoding='utf-8')
