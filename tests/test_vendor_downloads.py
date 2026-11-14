from __future__ import annotations

import hashlib
import io
from pathlib import Path
import ssl
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging'))
import vendor


class VendorDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'source.tar.gz'
        self.content = b'pinned upstream content'
        self.expected = hashlib.sha256(self.content).hexdigest()
        self.url = 'https://example.invalid/source.tar.gz'

    def response(self, content=None, url=None):
        response = io.BytesIO(self.content if content is None else content)
        response.url = url or self.url
        return response

    def test_transient_tls_timeout_retries_then_verifies(self):
        with patch('vendor.urllib.request.urlopen', side_effect=[URLError(TimeoutError('TLS handshake timed out')), self.response()]) as open_url, \
             patch('vendor.time.sleep'):
            self.assertEqual(vendor.fetch(self.url, self.target, self.expected), self.target)
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_retry_limit_has_actionable_cache_guidance(self):
        with patch('vendor.urllib.request.urlopen', side_effect=URLError(TimeoutError('TLS handshake timed out'))) as open_url, \
             patch('vendor.time.sleep'), self.assertRaisesRegex(RuntimeError, 'docs/DOCKER.md'):
            vendor.fetch(self.url, self.target, self.expected)
        self.assertEqual(open_url.call_count, 3)
        self.assertFalse(self.target.exists())

    def test_release_source_cache_is_verified_without_extracting_arbitrary_paths(self):
        hls = b'pinned hls bundle'
        license_text = b'pinned MIT license'
        media = io.BytesIO()
        with tarfile.open(fileobj=media, mode='w:gz') as archive:
            for name, data in {'VERSION':b'v-test', 'HASH':hashlib.sha256(hls).hexdigest().encode()}.items():
                member = tarfile.TarInfo('mediamtx/internal/servers/hls/hlsjsdownloader/'+name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        contents = {'mediamtx-test.tar.gz':media.getvalue(), 'hls-v-test.zip':hls, 'hls-license.txt':license_text}
        lock = {'sources':{'mediamtx':{'filename':'mediamtx-test.tar.gz',
                'sha256':hashlib.sha256(media.getvalue()).hexdigest()}},
                'assets':{'hls_license':{'version':'v-test','filename':'hls-license.txt',
                'sha256':hashlib.sha256(license_text).hexdigest()}}}
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                source = self.root/f'sources-{corrupt}.tar.gz'
                output = self.root/f'cache-{corrupt}'
                with tarfile.open(source, 'w:gz') as archive:
                    entries = {'vendor/downloads/'+name:data for name,data in contents.items()}
                    entries['../../unexpected-file'] = b'never extracted'
                    if corrupt:
                        entries['vendor/downloads/hls-v-test.zip'] = b'tampered'
                    for name,data in entries.items():
                        member = tarfile.TarInfo(name); member.size = len(data)
                        archive.addfile(member,io.BytesIO(data))
                with patch('vendor.LOCK',lock), patch('vendor.urllib.request.urlopen') as open_url:
                    if corrupt:
                        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                            vendor.media_cache(output,source)
                        self.assertFalse((output/'hls-v-test.zip').exists())
                    else:
                        vendor.media_cache(output,source)
                        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()},contents)
                    open_url.assert_not_called()
                self.assertFalse(list(output.glob('*.partial')))

    def test_checksum_failure_does_not_replace_cache_or_retry(self):
        self.target.write_bytes(b'old invalid file')
        with patch('vendor.urllib.request.urlopen', return_value=self.response(b'wrong content')) as open_url, \
             self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            vendor.fetch(self.url, self.target, self.expected)
        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(self.target.read_bytes(), b'old invalid file')
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_valid_cache_avoids_network(self):
        self.target.write_bytes(self.content)
        with patch('vendor.urllib.request.urlopen') as open_url:
            vendor.fetch(self.url, self.target, self.expected)
        open_url.assert_not_called()

    def test_https_and_certificate_errors_never_fall_back_to_insecure_downloads(self):
        for error in (URLError(ssl.SSLCertVerificationError('untrusted certificate')),
                      HTTPError(self.url, 404, 'Not found', {}, None)):
            with self.subTest(error=error), patch('vendor.urllib.request.urlopen', side_effect=error) as open_url, \
                 self.assertRaises(URLError):
                vendor.fetch(self.url, self.target, self.expected)
            self.assertEqual(open_url.call_count, 1)
        with patch('vendor.urllib.request.urlopen', return_value=self.response(url='http://example.invalid/source')), \
             self.assertRaisesRegex(ValueError, 'non-HTTPS'):
            vendor.fetch(self.url, self.target, self.expected)
