"""Probe the owner's local HTTP listener; LAN TLS never weakens this check."""
import urllib.request
urllib.request.urlopen('http://127.0.0.1:18080/api/v1/health', timeout=5).close()
