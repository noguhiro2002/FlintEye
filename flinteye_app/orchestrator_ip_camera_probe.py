from __future__ import annotations

import json
import math
import re
import socket
import statistics
import subprocess
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
import time
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import unquote, urlparse, urlunparse
from flinteye_app.flinteye_runtime import private_media_input_command


TimestampMode = Literal["source", "wallclock", "cfr"]


class IpCameraProbeError(RuntimeError):
    pass


def redact_url_credentials(value: str) -> str:
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    if not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"***@{host}" if parsed.username or parsed.password else host
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _safe_error(value: object, source_url: str = "") -> str:
    text = str(value).strip()
    if source_url:
        text = text.replace(source_url, '<camera-source>')
    return re.sub(r'((?:https?|rtsps?)://)[^/\s@]+@', r'\1***@', text, flags=re.IGNORECASE)[:1000]


def _onvif_failure(error: Exception) -> str:
    from requests.exceptions import ConnectionError, SSLError, Timeout

    # onvif-python chains the underlying HTTP/SOAP exception.
    while isinstance(error.__cause__, Exception):
        error = error.__cause__
    if isinstance(error, SSLError):
        return 'trust'
    if isinstance(error, (ConnectionError, Timeout)):
        return 'unreachable'
    status = getattr(error, 'status_code', None)
    if status is None:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
    fault = str(error).lower()
    if status in (401, 403) or any(code in fault for code in ('notauthorized', 'failedauthentication', 'unauthorized')):
        return 'authentication_failed'
    return 'not_connected'


def _fraction(value: object) -> float | None:
    raw = str(value or "").strip()
    if not raw or raw in {"N/A", "0/0"}:
        return None
    try:
        if "/" in raw:
            numerator, denominator = raw.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            result = float(numerator) / denominator_value
        else:
            result = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(math.floor((len(ordered) - 1) * fraction))
    return ordered[index]


def probe_rtsp_timing(
    source_url: str,
    *,
    ffprobe_bin: str = "ffprobe",
    duration_sec: float = 6.0,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    source_url = source_url.strip()
    if not source_url:
        raise IpCameraProbeError("Source URL is required")
    timeout = max(float(timeout_sec or duration_sec + 10.0), duration_sec + 3.0)
    metadata_cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-rw_timeout",
        str(int(timeout * 1_000_000)),
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,profile,width,height,pix_fmt,has_b_frames,r_frame_rate,avg_frame_rate,time_base",
        "-of",
        "json",
        source_url,
    ]
    try:
        with private_media_input_command(metadata_cmd, source_url, force=True) as safe_command:
            metadata_result = run_background(
                safe_command, **background_process_options(),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    except FileNotFoundError as exc:
        raise IpCameraProbeError(f"ffprobe was not found: {ffprobe_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        raise IpCameraProbeError(f"RTSP metadata probe timed out after {timeout:.1f}s") from exc
    if metadata_result.returncode != 0:
        detail = _safe_error(metadata_result.stderr or metadata_result.stdout or "RTSP probe failed", source_url)
        raise IpCameraProbeError(detail)
    try:
        streams = json.loads(metadata_result.stdout or "{}").get("streams", [])
        stream = streams[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise IpCameraProbeError("No video stream was returned by ffprobe") from exc

    frame_cmd = [
        ffprobe_bin,
        "-v",
        "warning",
        "-rw_timeout",
        str(int(timeout * 1_000_000)),
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-read_intervals",
        f"%+{duration_sec:g}",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "csv=p=0",
        source_url,
    ]
    started_at = time.monotonic()
    try:
        with private_media_input_command(frame_cmd, source_url, force=True) as safe_command:
            frame_result = run_background(
                safe_command, **background_process_options(),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        raise IpCameraProbeError(f"RTSP timing probe timed out after {timeout:.1f}s") from exc
    elapsed_sec = max(time.monotonic() - started_at, 0.001)

    timestamps: list[float] = []
    diagnostic_lines: list[str] = []
    for raw_line in (frame_result.stdout + "\n" + frame_result.stderr).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        first = line.split(",", 1)[0]
        try:
            timestamps.append(float(first))
            continue
        except ValueError:
            pass
        lowered = line.lower()
        if any(marker in lowered for marker in ("error while decoding", "corrupt", "invalid nal", "conceal")):
            diagnostic_lines.append(_safe_error(line, source_url))

    if frame_result.returncode != 0 and len(timestamps) < 2:
        detail = _safe_error(frame_result.stderr or frame_result.stdout or "RTSP timing probe failed", source_url)
        raise IpCameraProbeError(detail)
    if len(timestamps) < 2:
        raise IpCameraProbeError("Too few decoded frames were received to measure timing")

    deltas = [timestamps[index] - timestamps[index - 1] for index in range(1, len(timestamps))]
    positive_deltas = [delta for delta in deltas if delta > 0]
    declared_avg_fps = _fraction(stream.get("avg_frame_rate"))
    declared_rate_fps = _fraction(stream.get("r_frame_rate"))
    observed_fps = len(timestamps) / elapsed_sec
    nominal_fps = declared_avg_fps
    if nominal_fps is None or nominal_fps > 240:
        nominal_fps = observed_fps
    nominal_fps = min(max(nominal_fps, 1.0), 240.0)
    expected_delta = 1.0 / nominal_fps
    gap_threshold = max(0.2, expected_delta * 4.0)
    nonpositive_count = sum(1 for delta in deltas if delta <= 0)
    large_gap_count = sum(1 for delta in deltas if delta > gap_threshold)
    max_delta = max(positive_deltas) if positive_deltas else None
    decode_error_count = len(diagnostic_lines)

    timestamp_healthy = nonpositive_count == 0 and large_gap_count == 0 and decode_error_count == 0
    recommended_mode: TimestampMode
    if decode_error_count > 0:
        recommended_mode = "cfr"
    elif nonpositive_count > 0 or large_gap_count > 0:
        recommended_mode = "wallclock"
    else:
        recommended_mode = "source"

    return {
        "available": True,
        "codec": stream.get("codec_name"),
        "profile": stream.get("profile"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "pixel_format": stream.get("pix_fmt"),
        "has_b_frames": int(stream.get("has_b_frames") or 0),
        "time_base": stream.get("time_base"),
        "declared_avg_fps": round(declared_avg_fps, 3) if declared_avg_fps else None,
        "declared_rate_fps": round(declared_rate_fps, 3) if declared_rate_fps else None,
        "observed_fps": round(observed_fps, 3),
        "recommended_cfr_fps": max(1, min(240, int(round(nominal_fps)))),
        "sample_duration_sec": round(elapsed_sec, 3),
        "frame_count": len(timestamps),
        "median_delta_ms": round(statistics.median(positive_deltas) * 1000.0, 3) if positive_deltas else None,
        "p95_delta_ms": round((_percentile(positive_deltas, 0.95) or 0.0) * 1000.0, 3),
        "max_delta_ms": round(max_delta * 1000.0, 3) if max_delta is not None else None,
        "nonpositive_delta_count": nonpositive_count,
        "large_gap_count": large_gap_count,
        "large_gap_threshold_ms": round(gap_threshold * 1000.0, 3),
        "decode_error_count": decode_error_count,
        "diagnostics": diagnostic_lines[:5],
        "timestamp_healthy": timestamp_healthy,
        "recommended_timestamp_mode": recommended_mode,
    }


def _serialized(value: Any) -> Any:
    try:
        from zeep.helpers import serialize_object

        return serialize_object(value, target_cls=dict)
    except Exception:
        return value


def _pick(value: Any, *names: str) -> Any:
    value = _serialized(value)
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        lowered = {str(key).lower(): item for key, item in value.items()}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _as_list(value: Any, *container_names: str) -> list[Any]:
    serialized = _serialized(value)
    if serialized is None:
        return []
    if isinstance(serialized, list):
        return serialized
    if isinstance(serialized, tuple):
        return list(serialized)
    if isinstance(serialized, dict):
        for name in container_names:
            nested = _pick(serialized, name)
            if nested is not None and nested is not serialized:
                return _as_list(nested)
    return [serialized]


def _normalized_host(value: str) -> str:
    return value.strip().strip("[]").rstrip(".").split("%", 1)[0].lower()


@lru_cache(maxsize=256)
def _host_addresses(host: str) -> frozenset[str]:
    normalized = _normalized_host(host)
    addresses = {normalized} if normalized else set()
    if not normalized:
        return frozenset(addresses)
    try:
        for item in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM):
            addresses.add(_normalized_host(str(item[4][0])))
    except OSError:
        pass
    return frozenset(addresses)


def _hosts_match(left: str, right: str) -> bool:
    return bool(_host_addresses(left) & _host_addresses(right))


def _url_host(host: str) -> str:
    normalized = host.strip().strip("[]")
    return f"[{normalized}]" if ":" in normalized else normalized


def _parse_onvif_address(address: str, *, default_host: str) -> tuple[str, int, bool, str]:
    raw = address.strip()
    if not raw:
        return default_host, 80, False, f"http://{_url_host(default_host)}:80/onvif/device_service"
    candidate = raw if "://" in raw else f"http://{raw}"
    parsed = urlparse(candidate)
    host = parsed.hostname or default_host
    use_https = parsed.scheme.lower() == "https"
    port = parsed.port or (443 if use_https else 80)
    path = parsed.path if parsed.path and parsed.path != "/" else "/onvif/device_service"
    return host, port, use_https, f"{'https' if use_https else 'http'}://{_url_host(host)}:{port}{path}"


def _tcp_open(host: str, port: int, timeout_sec: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _discovered_candidates(host: str, timeout_sec: float) -> list[tuple[str, int, bool, str, str]]:
    candidates: list[tuple[str, int, bool, str, str]] = []
    try:
        from onvif import ONVIFDiscovery

        discovery = ONVIFDiscovery(timeout=max(1, int(math.ceil(timeout_sec))))
        for item in discovery.discover():
            item_host = str(item.get("host") or "").strip("[]")
            xaddrs = item.get("xaddrs") or []
            advertised_hosts = [item_host]
            advertised_hosts.extend(
                parsed.hostname
                for parsed in (urlparse(str(xaddr)) for xaddr in xaddrs)
                if parsed.hostname
            )
            if not any(_hosts_match(host, advertised_host) for advertised_host in advertised_hosts):
                continue
            for xaddr in xaddrs:
                parsed = urlparse(str(xaddr))
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                    continue
                if not _hosts_match(host, parsed.hostname):
                    continue
                use_https = parsed.scheme.lower() == "https"
                port = parsed.port or (443 if use_https else 80)
                # Resolve/check discovery aliases once, then use the administrator's
                # configured host. Never resolve an advertised name again at use time.
                pinned_xaddr = urlunparse(parsed._replace(netloc=f"{_url_host(host)}:{port}"))
                candidates.append((host, port, use_https, pinned_xaddr, "ws-discovery"))
            if not xaddrs and _hosts_match(host, item_host):
                port = int(item.get("port") or 80)
                candidates.append((host, port, False, f"http://{_url_host(host)}:{port}/onvif/device_service", "ws-discovery"))
    except Exception:
        pass
    return candidates


def _service_details(client: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for raw_service in _as_list(getattr(client, "services", None), "Service", "Services"):
        service = _serialized(raw_service)
        namespace = _pick(service, "Namespace", "namespace")
        xaddr = _pick(service, "XAddr", "xaddr")
        version = _pick(service, "Version", "version") or {}
        if not namespace and not xaddr:
            continue
        namespace_text = str(namespace or "")
        if "/ver20/media/" in namespace_text:
            name = "Media2"
        elif "/ver10/media/" in namespace_text:
            name = "Media"
        else:
            name = next(
                (part for part in reversed(namespace_text.rstrip("/").split("/")) if part and part not in {"wsdl", "ver10", "ver20"}),
                namespace_text or "Service",
            )
        details.append(
            {
                "name": name,
                "namespace": namespace,
                "xaddr": redact_url_credentials(str(xaddr)) if xaddr else None,
                "version": {
                    "major": _pick(version, "Major", "major"),
                    "minor": _pick(version, "Minor", "minor"),
                },
            }
        )
    return details


def _profile_summary(profile_value: Any, media_service_name: str, media_service: Any) -> dict[str, Any]:
    profile = _serialized(profile_value)
    token = _pick(profile, "token", "Token")
    configurations = _pick(profile, "Configurations", "configurations") or {}
    encoder = (
        _pick(configurations, "VideoEncoder", "videoEncoder")
        or _pick(profile, "VideoEncoderConfiguration", "videoEncoderConfiguration")
        or {}
    )
    resolution = _pick(encoder, "Resolution", "resolution") or {}
    rate_control = _pick(encoder, "RateControl", "rateControl") or {}
    ptz_configuration = (
        _pick(configurations, "PTZ", "ptz")
        or _pick(profile, "PTZConfiguration", "ptzConfiguration")
        or {}
    )
    stream_uri = None
    if token:
        try:
            if media_service_name == "Media2":
                uri_result = media_service.GetStreamUri(Protocol="RTSP", ProfileToken=token)
            else:
                uri_result = media_service.GetStreamUri(
                    ProfileToken=token,
                    StreamSetup={"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                )
            stream_uri = uri_result if isinstance(uri_result, str) else _pick(uri_result, "Uri", "URI")
        except Exception:
            stream_uri = None
    return {
        "token": token,
        "name": _pick(profile, "Name", "name") or str(token or "Profile"),
        "media_service": media_service_name,
        "encoding": _pick(encoder, "Encoding", "encoding"),
        "width": _pick(resolution, "Width", "width"),
        "height": _pick(resolution, "Height", "height"),
        "fps": _pick(rate_control, "FrameRateLimit", "frameRateLimit"),
        "bitrate_kbps": _pick(rate_control, "BitrateLimit", "bitrateLimit"),
        "gov_length": _pick(encoder, "GovLength", "govLength"),
        "stream_uri": redact_url_credentials(str(stream_uri)) if stream_uri else None,
        "ptz_configuration_token": _pick(ptz_configuration, "token", "Token"),
        "ptz_node_token": _pick(ptz_configuration, "NodeToken", "nodeToken"),
    }


def _probe_media_profiles(client: Any, source_url: str) -> tuple[list[dict[str, Any]], str | None, list[str], bool]:
    details = _service_details(client)
    namespaces = [str(item.get("namespace") or "") for item in details]
    advertised_media2 = any("/ver20/media/" in namespace for namespace in namespaces)
    advertised_media1 = any("/ver10/media/" in namespace for namespace in namespaces)
    candidates: list[tuple[str, Any]] = []
    if advertised_media2:
        candidates.append(("Media2", client.media2))
    if advertised_media1:
        candidates.append(("Media", client.media))
    if not advertised_media2:
        candidates.append(("Media2", client.media2))
    if not advertised_media1:
        candidates.append(("Media", client.media))

    failures: list[str] = []
    contacted = False
    all_profiles: list[dict[str, Any]] = []
    contacted_services: list[str] = []
    for service_name, factory in candidates:
        try:
            media_service = factory()
            # Media2 returns only names and tokens when Type is omitted.
            raw_profiles = (media_service.GetProfiles(Type=["All"])
                            if service_name == "Media2" else media_service.GetProfiles()) or []
            contacted = True
            profiles = [
                _profile_summary(profile, service_name, media_service)
                for profile in _as_list(raw_profiles, "Profiles", "Profile")
            ]
            if profiles:
                contacted_services.append(service_name)
                all_profiles.extend(profiles)
        except Exception as exc:
            failures.append(f"{service_name}: {_safe_error(exc, source_url)}")
    primary_service = contacted_services[0] if contacted_services else None
    return all_profiles, primary_service, failures, contacted


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _axis_range(value: Any, axis: str) -> dict[str, float] | None:
    axis_range = _pick(value, f"{axis.upper()}Range", f"{axis.lower()}Range") or {}
    minimum = _float_or_none(_pick(axis_range, "Min", "min"))
    maximum = _float_or_none(_pick(axis_range, "Max", "max"))
    if minimum is None or maximum is None:
        return None
    return {"min": minimum, "max": maximum}


def _space_summaries(spaces: Any, field_name: str, axes: tuple[str, ...]) -> list[dict[str, Any]]:
    raw_spaces = _pick(spaces, field_name) or []
    summaries: list[dict[str, Any]] = []
    for raw_space in _as_list(raw_spaces, field_name):
        summary: dict[str, Any] = {"uri": _pick(raw_space, "URI", "Uri", "uri")}
        for axis in axes:
            axis_value = _axis_range(raw_space, axis)
            if axis_value is not None:
                summary[axis.lower()] = axis_value
        summaries.append(summary)
    return summaries


def _ptz_support_from_spaces(spaces: Any) -> dict[str, Any]:
    absolute_pan_tilt = _space_summaries(spaces, "AbsolutePanTiltPositionSpace", ("X", "Y"))
    absolute_zoom = _space_summaries(spaces, "AbsoluteZoomPositionSpace", ("X",))
    relative_pan_tilt = _space_summaries(spaces, "RelativePanTiltTranslationSpace", ("X", "Y"))
    relative_zoom = _space_summaries(spaces, "RelativeZoomTranslationSpace", ("X",))
    continuous_pan_tilt = _space_summaries(spaces, "ContinuousPanTiltVelocitySpace", ("X", "Y"))
    continuous_zoom = _space_summaries(spaces, "ContinuousZoomVelocitySpace", ("X",))
    pan_tilt = bool(absolute_pan_tilt or relative_pan_tilt or continuous_pan_tilt)
    zoom = bool(absolute_zoom or relative_zoom or continuous_zoom)
    return {
        "supported": pan_tilt or zoom,
        "pan_tilt": pan_tilt,
        "zoom": zoom,
        "modes": {
            "pan_tilt": {
                "continuous": bool(continuous_pan_tilt),
                "relative": bool(relative_pan_tilt),
                "absolute": bool(absolute_pan_tilt),
            },
            "zoom": {
                "continuous": bool(continuous_zoom),
                "relative": bool(relative_zoom),
                "absolute": bool(absolute_zoom),
            },
        },
        "spaces": {
            "absolute_pan_tilt": absolute_pan_tilt,
            "absolute_zoom": absolute_zoom,
            "relative_pan_tilt": relative_pan_tilt,
            "relative_zoom": relative_zoom,
            "continuous_pan_tilt": continuous_pan_tilt,
            "continuous_zoom": continuous_zoom,
        },
    }


def probe_ptz_profiles(client: Any, profiles: list[dict[str, Any]], source_url: str) -> dict[str, Any]:
    try:
        ptz_service = client.ptz()
    except Exception as exc:
        return {
            "supported": False,
            "service_available": False,
            "message": "ONVIF PTZ service is not available",
            "error": _safe_error(exc, source_url),
            "profiles": [],
        }

    node_spaces: dict[str, Any] = {}
    try:
        for raw_node in _as_list(ptz_service.GetNodes() or [], "PTZNode", "Node", "Nodes"):
            node_token = _pick(raw_node, "token", "Token")
            spaces = _pick(raw_node, "SupportedPTZSpaces", "supportedPTZSpaces")
            if node_token and spaces is not None:
                node_spaces[str(node_token)] = spaces
    except Exception:
        pass

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for profile in profiles:
        configuration_token = profile.get("ptz_configuration_token")
        node_token = profile.get("ptz_node_token")
        if not configuration_token and not node_token:
            continue
        spaces = None
        if configuration_token:
            try:
                options = ptz_service.GetConfigurationOptions(ConfigurationToken=configuration_token)
                spaces = _pick(options, "Spaces", "spaces")
            except Exception as exc:
                failures.append(
                    f"{profile.get('token') or profile.get('name')}: {_safe_error(exc, source_url)}"
                )
        if spaces is None and node_token:
            spaces = node_spaces.get(str(node_token))
        support = _ptz_support_from_spaces(spaces or {})
        summary = {
            "profile_token": profile.get("token"),
            "profile_name": profile.get("name"),
            "media_service": profile.get("media_service"),
            "configuration_token": configuration_token,
            "node_token": node_token,
            **support,
        }
        profile["ptz"] = summary
        results.append(summary)

    supported_results = [item for item in results if item.get("supported")]
    if supported_results:
        message = f"PTZ is available on {len(supported_results)} media profile(s)"
    elif not results:
        message = "No inspected ONVIF media profile has a PTZ configuration. Check the camera's profiles and permissions."
    elif failures:
        message = "Could not read PTZ capabilities for the media profiles. Check ONVIF permissions and inspect again."
    else:
        message = "PTZ service was found, but no controllable PTZ spaces were advertised"
    return {
        "supported": bool(supported_results),
        "service_available": True,
        "message": message,
        "pan_tilt": any(bool(item.get("pan_tilt")) for item in supported_results),
        "zoom": any(bool(item.get("zoom")) for item in supported_results),
        "profiles": results,
        "errors": failures[:4],
    }


def _create_onvif_client(
    onvif_client_class: Any,
    *,
    device_xaddr: str,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: int,
    use_https: bool,
    cache: Any,
) -> Any:
    from onvif.services import Device

    class AddressedONVIFClient(onvif_client_class):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._flinteye_device_xaddr = device_xaddr
            super().__init__(*args, **kwargs)

        def devicemgmt(self) -> Any:
            if self._devicemgmt is None:
                self._devicemgmt = Device(xaddr=self._flinteye_device_xaddr, **self.common_args)
            return self._devicemgmt

    return AddressedONVIFClient(
        host=host,
        port=port,
        username=username,
        password=password,
        timeout=timeout,
        use_https=use_https,
        verify_ssl=True,
        cache=cache,
    )


def iter_onvif_clients(
    source_url: str,
    *,
    mode: str = "auto",
    address: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout_sec: float = 4.0,
    trace: dict[str, Any] | None = None,
):
    parsed_source = urlparse(source_url)
    host = parsed_source.hostname
    if not host:
        raise IpCameraProbeError("Source URL has no hostname")
    resolved_username = username if username is not None else unquote(parsed_source.username or "")
    resolved_password = password if password is not None else unquote(parsed_source.password or "")

    from onvif import CacheMode, ONVIFClient

    candidates: list[tuple[str, int, bool, str, str]] = []
    if mode == "manual":
        manual_host, port, use_https, resolved = _parse_onvif_address(address or "", default_host=host)
        candidates.append((manual_host, port, use_https, resolved, "manual"))
    else:
        candidates.extend(_discovered_candidates(host, min(timeout_sec, 3.0)))
        # Tapo exposes ONVIF on 2020, and multicast discovery may not cross VPNs.
        for port, use_https in [(80, False), (443, True), (2020, False), (8000, False), (8080, False), (8443, True)]:
            if _tcp_open(host, port):
                scheme = "https" if use_https else "http"
                candidates.append(
                    (
                        host,
                        port,
                        use_https,
                        f"{scheme}://{_url_host(host)}:{port}/onvif/device_service",
                        "standard-port-fallback",
                    )
                )

    unique_candidates: list[tuple[str, int, bool, str, str]] = []
    seen: set[tuple[str, int, bool, str]] = set()
    for candidate in candidates:
        key = (candidate[0].lower(), candidate[1], candidate[2], candidate[3].lower())
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    if trace is not None:
        trace["attempts"] = len(unique_candidates)

    for candidate_host, port, use_https, resolved_address, discovery_method in unique_candidates:
        try:
            client = _create_onvif_client(
                ONVIFClient,
                device_xaddr=resolved_address,
                host=candidate_host,
                port=port,
                username=resolved_username,
                password=resolved_password,
                timeout=max(1, int(math.ceil(timeout_sec))),
                use_https=use_https,
                cache=CacheMode.MEM,
            )
        except Exception as exc:
            if trace is not None:
                trace.setdefault("errors", []).append(
                    f"{candidate_host}:{port}: {_safe_error(exc, source_url)}"
                )
                trace.setdefault("failures", []).append(_onvif_failure(exc))
            continue
        yield client, {
            "host": candidate_host,
            "port": port,
            "use_https": use_https,
            "resolved_address": resolved_address,
            "discovery_method": discovery_method,
        }


def probe_onvif(
    source_url: str,
    *,
    mode: str = "auto",
    address: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout_sec: float = 4.0,
) -> dict[str, Any]:
    if mode == "disabled":
        return {"status": "disabled", "supported": None, "message": "ONVIF inspection is disabled"}

    trace: dict[str, Any] = {"attempts": 0, "errors": []}
    try:
        candidates = iter_onvif_clients(
            source_url,
            mode=mode,
            address=address,
            username=username,
            password=password,
            timeout_sec=timeout_sec,
            trace=trace,
        )
        for client, connection in candidates:
            candidate_host = str(connection["host"])
            port = int(connection["port"])
            resolved_address = str(connection["resolved_address"])
            discovery_method = str(connection["discovery_method"])
            try:
                device_service = client.devicemgmt()
                device_info = None
                device_info_error = None
                try:
                    device_info = _serialized(device_service.GetDeviceInformation())
                except Exception as exc:
                    device_info_error = _safe_error(exc, source_url)
                    trace.setdefault('failures', []).append(_onvif_failure(exc))
                service_details = _service_details(client)
                profiles, media_service_name, media_errors, media_contacted = _probe_media_profiles(
                    client, source_url
                )
                ptz = probe_ptz_profiles(client, profiles, source_url)
                standard_contact = (
                    bool(service_details)
                    or getattr(client, "capabilities", None) is not None
                    or device_info is not None
                    or media_contacted
                )
                if not standard_contact:
                    detail = "; ".join(
                        [value for value in [device_info_error, *media_errors] if value]
                    ) or "No standard ONVIF operation succeeded"
                    raise IpCameraProbeError(detail)
                service_names = [str(item["name"]) for item in service_details]
                media_note = f" using {media_service_name}" if media_service_name else ""
                return {
                    "status": "connected",
                    "supported": True,
                    "message": f"ONVIF connected via {discovery_method}{media_note}",
                    "discovery_method": discovery_method,
                    "resolved_address": redact_url_credentials(resolved_address),
                    "device": (
                        {
                            "manufacturer": _pick(device_info, "Manufacturer"),
                            "model": _pick(device_info, "Model"),
                            "firmware_version": _pick(device_info, "FirmwareVersion"),
                            "serial_number": _pick(device_info, "SerialNumber"),
                            "hardware_id": _pick(device_info, "HardwareId", "HardwareID"),
                        }
                        if device_info is not None
                        else None
                    ),
                    "device_info_error": device_info_error,
                    "services": service_names,
                    "service_details": service_details,
                    "media_service": media_service_name,
                    "media_errors": media_errors,
                    "profiles": profiles,
                    "ptz": ptz,
                }
            except Exception as exc:
                trace.setdefault("errors", []).append(
                    f"{candidate_host}:{port}: {_safe_error(exc, source_url)}"
                )
                trace.setdefault('failures', []).append(_onvif_failure(exc))
    except ImportError:
        return {
            "status": "unavailable",
            "supported": None,
            "message": "onvif-python is not installed; install requirements.txt",
        }
    except IpCameraProbeError as exc:
        return {"status": "error", "supported": False, "message": _safe_error(exc, source_url)}

    failures = trace.get('failures', [])
    status = 'not_connected'
    if 'authentication_failed' in failures:
        status = 'authentication_failed'
        message = 'ONVIF authentication failed. Check the ONVIF account and inspect again.'
    elif 'trust' in failures:
        status = 'trust'
        message = 'The ONVIF HTTPS certificate could not be verified. Check the camera address and certificate trust.'
    elif 'unreachable' in failures:
        status = 'unreachable'
        message = 'The ONVIF endpoint did not respond. Check the Device Service address, routing, and camera connection.'
    elif not trace.get("attempts"):
        message = "No ONVIF endpoint was discovered. Select Manual address and enter the device service address."
    else:
        message = "The endpoint did not return an ONVIF response. Check the Device Service address and ONVIF permissions."
    return {
        "status": status,
        "supported": None,
        "message": message,
        "attempts": int(trace.get("attempts") or 0),
        "errors": list(trace.get("errors") or [])[:4],
    }


def inspect_ip_camera(
    source_url: str,
    *,
    ffprobe_bin: str = "ffprobe",
    probe_duration_sec: float = 6.0,
    onvif_mode: str = "auto",
    onvif_address: str | None = None,
    onvif_username: str | None = None,
    onvif_password: str | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    rtsp: dict[str, Any]
    try:
        rtsp = probe_rtsp_timing(
            source_url,
            ffprobe_bin=ffprobe_bin,
            duration_sec=probe_duration_sec,
        )
    except IpCameraProbeError as exc:
        rtsp = {"available": False, "error": _safe_error(exc, source_url)}
    onvif = probe_onvif(
        source_url,
        mode=onvif_mode,
        address=onvif_address,
        username=onvif_username,
        password=onvif_password,
    )
    recommendation = rtsp.get("recommended_timestamp_mode") if rtsp.get("available") else None
    return {
        "ok": bool(rtsp.get("available")),
        "source": redact_url_credentials(source_url),
        "inspected_at": started_at,
        "elapsed_sec": round(time.time() - started_at, 3),
        "rtsp": rtsp,
        "onvif": onvif,
        "recommendation": {
            "timestamp_mode": recommendation,
            "cfr_fps": rtsp.get("recommended_cfr_fps") if rtsp.get("available") else None,
        },
    }
