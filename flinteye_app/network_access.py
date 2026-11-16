"""Opt-in LAN TLS, owner-local certificate management and bootstrap budgets."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import secrets
import threading
import time
import uuid

CERTIFICATE_LOCK = threading.RLock()


def private_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)
    os.replace(temporary, path)


def installation_id(root: Path) -> str:
    path = root / 'installation-id'
    if not path.exists():
        private_write(path, str(uuid.uuid4()).encode())
    return str(uuid.UUID(path.read_text().strip()))


def backup_profile(root: Path) -> None:
    """First upgrade only; contains secrets and must stay in the private profile."""
    backup = root / 'backup-before-1.2.0'
    for name in ('runtime.json', 'monitoring.json'):
        source = root / name
        target = backup / name
        if source.is_file() and not target.exists():
            private_write(target, source.read_bytes())


def ensure_certificates(root: Path, address: str, *, rotate_ca=False) -> dict:
    with CERTIFICATE_LOCK:
        return _ensure_certificates(root, address, rotate_ca=rotate_ca)


def _ensure_certificates(root: Path, address: str, *, rotate_ca=False) -> dict:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    folder = root / 'tls'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        # No inherited Users/Everyone read access to the CA or server keys.
        import subprocess
        from flinteye_app.subprocess_utils import background_process_options
        sid = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True,
                                      **background_process_options()).strip().split(',')[-1].strip('"')
        if not sid.startswith('S-1-'):
            raise ValueError('Could not verify the certificate owner')
        subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F'],
                       check=True, capture_output=True, **background_process_options())
    now = datetime.now(timezone.utc)
    ca_path, ca_key_path = folder / 'ca.crt', folder / 'ca.key'
    ca, ca_key = None, None
    if ca_path.exists() and not rotate_ca:
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        if ca.public_key().public_numbers() != ca_key.public_key().public_numbers():
            raise ValueError('LAN certificate and private key do not match. Renew trust on the server.')
        if ca.not_valid_after_utc <= now:
            raise ValueError('LAN trust certificate expired. Renew trust on the server and reconnect clients.')
    if ca is None:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FlintEye ' + installation_id(root)[:8])])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
              .not_valid_after(now + timedelta(days=1825))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
              .sign(ca_key, hashes.SHA256()))
        private_write(ca_key_path, ca_key.private_bytes(serialization.Encoding.PEM,
                      serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        private_write(ca_path, ca.public_bytes(serialization.Encoding.PEM))
    cert_path, key_path = folder / 'server.crt', folder / 'server.key'
    renew = True
    if cert_path.exists() and key_path.exists() and not rotate_ca:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        renew = (cert.not_valid_after_utc < now + timedelta(days=30)
                 or ipaddress.ip_address(address) not in sans.get_values_for_type(x509.IPAddress)
                 or cert.issuer != ca.subject)
    if renew:
        key = ec.generate_private_key(ec.SECP256R1())
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FlintEye')]))
                .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address)),
                               x509.IPAddress(ipaddress.ip_address('127.0.0.1')), x509.DNSName('localhost')]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        private_write(key_path, key.private_bytes(serialization.Encoding.PEM,
                      serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        private_write(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return {'certfile': str(cert_path), 'keyfile': str(key_path),
            'fingerprint': ca.fingerprint(hashes.SHA256()).hex(),
            'ca_expires': ca.not_valid_after_utc.isoformat(), 'server_expires': cert.not_valid_after_utc.isoformat()}


def export_guide(root: Path, address: str, port: int) -> Path:
    """Only public trust material; deliberately excludes the bootstrap token."""
    metadata = ensure_certificates(root, address)
    folder = root / 'connection-guide'
    ca = (root / 'tls/ca.crt').read_bytes()
    private_write(folder / 'FlintEye-CA.crt', ca)
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    cert = x509.load_pem_x509_certificate(ca).public_bytes(Encoding.DER)
    identity = installation_id(root)
    profile = {'PayloadType': 'Configuration', 'PayloadVersion': 1, 'PayloadIdentifier': 'community.flinteye.' + identity,
               'PayloadUUID': identity, 'PayloadDisplayName': 'FlintEye LAN trust', 'PayloadContent': [{
                   'PayloadType': 'com.apple.security.root', 'PayloadVersion': 1,
                   'PayloadIdentifier': 'community.flinteye.' + identity + '.ca', 'PayloadUUID': str(uuid.uuid4()),
                   'PayloadDisplayName': 'FlintEye ' + identity[:8], 'PayloadContent': cert}]}
    private_write(folder / 'FlintEye.mobileconfig', plistlib.dumps(profile))
    for source in ('LAN_ACCESS.md', 'LAN_ACCESS.ja.md'):
        from flinteye_app.flinteye_runtime import application_dir
        document = application_dir() / 'docs' / source
        if document.exists():
            private_write(folder / source, document.read_bytes())
    private_write(folder / 'connection.txt', (
        f'FlintEye: https://{address}:{port}\nCA SHA-256: {metadata["fingerprint"]}\n'
        f'CA expires: {metadata["ca_expires"]}\n'
        'Compare this fingerprint on the server before trusting the certificate.\n'
        '接続前にサーバー側の証明書指紋と照合してください。\n'
        'Do not share passwords, setup tokens or private keys.\n'
        'Trust instructions: https://github.com/noguhiro2002/FlintEye/blob/main/docs/LAN_ACCESS.md\n').encode())
    return folder


class Bootstrap:
    def __init__(self, root: Path, token: str):
        self.root, self.token = root, token
        self.expires = time.monotonic() + 1800
        self.lock = threading.Lock()
        self.attempts = defaultdict(deque)
        self.global_attempts = deque()

    def verify(self, supplied, host: str):
        from fastapi import HTTPException
        now = time.monotonic()
        with self.lock:
            self.attempts = defaultdict(deque, {key: value for key, value in self.attempts.items()
                                               if value and value[-1] > now - 60})
            attempts = self.attempts[host]
            for queue in (attempts, self.global_attempts):
                while queue and queue[0] <= now - 60:
                    queue.popleft()
            if len(attempts) >= 5 or len(self.global_attempts) >= 30:
                raise HTTPException(429, 'Too many setup attempts. Wait one minute.', headers={'Retry-After': '60'})
            attempts.append(now)
            self.global_attempts.append(now)
            if not self.token or now >= self.expires:
                raise HTTPException(403, 'Setup token expired. Generate a new token on the server.')
            if not isinstance(supplied, str) or not secrets.compare_digest(supplied, self.token):
                raise HTTPException(403, 'Enter the setup token shown on the server')

    def renew(self) -> None:
        with self.lock:
            self.token = secrets.token_urlsafe(32)
            self.expires = time.monotonic() + 1800
            private_write(self.root / 'setup-token', self.token.encode())

    def consume(self):
        self.token = ''
        (self.root / 'setup-token').unlink(missing_ok=True)


def permitted_source(host: str, ranges: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or any(ip in ipaddress.ip_network(item) for item in ranges)
    except ValueError:
        return False
