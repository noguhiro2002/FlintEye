"""Enumerate UVC capabilities without configuring or starting a capture."""
from __future__ import annotations

import errno
import os
import struct
from fractions import Fraction
from pathlib import Path


# These structures contain only fixed-width fields in the Linux V4L2 ABI.
def _query(fd: int, number: int, size: int, *fields: int) -> bytes | None:
    import fcntl

    data = bytearray(size)
    struct.pack_into(f"={len(fields)}I", data, 0, *fields)
    direction = 2 if number == 0 else 3
    request = (direction << 30) | (size << 16) | (ord("V") << 8) | number
    try:
        fcntl.ioctl(fd, request, data, True)
    except OSError as error:
        if error.errno == errno.EINVAL:
            return None
        raise
    return bytes(data)


_INPUT_FORMATS = {
    b"MJPG": "mjpeg", b"JPEG": "mjpeg", b"YUYV": "yuyv422", b"UYVY": "uyvy422",
    b"NV12": "nv12", b"NV21": "nv21", b"YU12": "yuv420p", b"YV12": "yuv420p",
    b"H264": "h264", b"HEVC": "hevc", b"RGB3": "rgb24", b"BGR3": "bgr24", b"GREY": "gray",
}


def _sizes(fd: int, pixel_format: int):
    for index in range(256):
        data = _query(fd, 74, 44, index, pixel_format)
        if data is None:
            return
        kind, w_min, w_max, w_step, h_min, h_max, h_step = struct.unpack_from("=7I", data, 8)
        if kind == 1:
            yield w_min, w_max  # The discrete union contains only width and height.
            continue
        if kind in (2, 3):
            # A range may contain millions of combinations. Offer its bounds and
            # common sizes only if both dimensions are within the reported grid.
            candidates = {(w_min, h_min), (w_max, h_max), (640, 480), (1280, 720),
                          (1920, 1080), (2560, 1440), (3840, 2160)}
            for width, height in sorted(candidates):
                if (w_min <= width <= w_max and h_min <= height <= h_max
                        and (width - w_min) % max(1, w_step) == 0
                        and (height - h_min) % max(1, h_step) == 0):
                    yield width, height
        return


def _rates(fd: int, pixel_format: int, width: int, height: int):
    for index in range(256):
        data = _query(fd, 75, 52, index, pixel_format, width, height)
        if data is None:
            return
        kind, numerator, denominator, max_n, max_d = struct.unpack_from("=5I", data, 16)
        if numerator and denominator:
            yield float(Fraction(denominator, numerator))
        if kind != 1:
            if kind in (2, 3) and max_n and max_d and (max_n, max_d) != (numerator, denominator):
                yield float(Fraction(max_d, max_n))
            return


def enumerate_modes(path: Path) -> list[dict] | None:
    """Return None for nodes that cannot capture video."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        capability = _query(fd, 0, 104)
        if capability is None:
            return None
        capabilities, device_caps = struct.unpack_from("=2I", capability, 84)
        caps = device_caps if capabilities & 0x80000000 else capabilities
        capture_type = 1 if caps & 1 else 9 if caps & 0x1000 else None
        if capture_type is None:
            return None
        modes = []
        for index in range(128):
            data = _query(fd, 2, 64, index, capture_type)
            if data is None:
                break
            fourcc = data[44:48]
            input_format = _INPUT_FORMATS.get(fourcc)
            if not input_format:
                continue
            code = struct.unpack("=I", fourcc)[0]
            for width, height in _sizes(fd, code):
                for fps in dict.fromkeys(_rates(fd, code, width, height)):
                    modes.append({"width": width, "height": height, "fps": fps,
                                  "input_format": input_format})
        return modes
    finally:
        os.close(fd)
