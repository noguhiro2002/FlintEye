#!/usr/bin/env python3
"""Estimate RTSP stream latency by OCR-reading on-screen sender timestamp."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass


TIMESTAMP_PATTERN = re.compile(r"(\d{4}[/-]\d{2}[/-]\d{2})\s+(\d{2}:\d{2}:\d{2})")


@dataclass
class SampleResult:
    index: int
    ok: bool
    latency_sec: float | None
    ocr_text: str
    timestamp_text: str | None
    error: str | None


def resolve_binary(path_or_name: str) -> str | None:
    if os.path.sep in path_or_name:
        return path_or_name if os.path.isfile(path_or_name) else None
    return shutil.which(path_or_name)


def capture_frame(
    ffmpeg_bin: str,
    rtsp_url: str,
    output_path: str,
    crop: str | None,
    timeout_sec: float,
) -> tuple[bool, str]:
    timeout_us = str(int(timeout_sec * 1_000_000))
    timeout_option_candidates: list[list[str]] = [
        ["-rw_timeout", timeout_us],  # newer builds
        ["-stimeout", timeout_us],  # older builds
        [],  # fallback when neither option exists
    ]

    last_message = "ffmpeg failed"
    for timeout_opt in timeout_option_candidates:
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            *timeout_opt,
            "-fflags",
            "+nobuffer",
            "-flags",
            "low_delay",
            "-i",
            rtsp_url,
            "-frames:v",
            "1",
        ]
        if crop:
            cmd += ["-vf", f"crop={crop}"]
        cmd += ["-q:v", "2", "-y", output_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(timeout_sec + 3.0, 5.0),
            )
        except subprocess.TimeoutExpired:
            return False, "ffmpeg timeout"

        if result.returncode == 0:
            return True, ""

        message = (result.stderr or result.stdout or "").strip()
        last_message = f"ffmpeg failed (exit={result.returncode}): {message}"
        msg_lower = message.lower()
        opt_name = timeout_opt[0].lstrip("-") if timeout_opt else ""
        option_not_found = bool(timeout_opt) and (
            f"option {opt_name} not found" in msg_lower
            or f"unrecognized option '{opt_name}'" in msg_lower
            or (
                "error splitting the argument list" in msg_lower
                and "option not found" in msg_lower
            )
        )
        if option_not_found and timeout_opt:
            continue
        return False, last_message

    return False, last_message


def run_ocr(tesseract_bin: str, image_path: str, psm: int) -> tuple[bool, str]:
    cmd = [
        tesseract_bin,
        image_path,
        "stdout",
        "--psm",
        str(psm),
        "-c",
        "tessedit_char_whitelist=0123456789/:- ",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return False, f"tesseract failed (exit={result.returncode}): {message}"
    return True, (result.stdout or "").strip()


def parse_overlay_timestamp(ocr_text: str) -> tuple[dt.datetime | None, str | None]:
    normalized = " ".join(ocr_text.split())
    m = TIMESTAMP_PATTERN.search(normalized)
    if not m:
        return None, None
    date_text = m.group(1).replace("-", "/")
    time_text = m.group(2)
    stamp_text = f"{date_text} {time_text}"
    try:
        parsed = dt.datetime.strptime(stamp_text, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None, stamp_text
    return parsed, stamp_text


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = int(round((len(ordered) - 1) * 0.95))
    return ordered[idx]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Estimate one-way latency by reading sender timestamp overlay "
            "(YYYY/MM/DD hh:mm:ss) from RTSP frames."
        )
    )
    p.add_argument("--rtsp-url", required=True, help="Target RTSP URL (camera or multiview)")
    p.add_argument("--samples", type=int, default=20, help="Number of samples to take")
    p.add_argument("--interval", type=float, default=0.5, help="Seconds between samples")
    p.add_argument(
        "--crop",
        default="960:120:0:0",
        help="Optional crop region for OCR: w:h:x:y (default: 960:120:0:0)",
    )
    p.add_argument("--timeout-sec", type=float, default=3.0, help="RTSP capture timeout per sample")
    p.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg binary path")
    p.add_argument("--tesseract-bin", default="tesseract", help="tesseract binary path")
    p.add_argument("--psm", type=int, default=7, help="tesseract page segmentation mode")
    p.add_argument("--json", action="store_true", help="Print JSON output")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.samples <= 0:
        print("--samples must be > 0", file=sys.stderr)
        return 2
    if args.interval < 0:
        print("--interval must be >= 0", file=sys.stderr)
        return 2
    if args.timeout_sec <= 0:
        print("--timeout-sec must be > 0", file=sys.stderr)
        return 2

    ffmpeg_bin = resolve_binary(args.ffmpeg_bin)
    if not ffmpeg_bin:
        print(f"ffmpeg not found: {args.ffmpeg_bin}", file=sys.stderr)
        return 127
    tesseract_bin = resolve_binary(args.tesseract_bin)
    if not tesseract_bin:
        print(
            f"tesseract not found: {args.tesseract_bin}\n"
            "Install it first (e.g. macOS: brew install tesseract).",
            file=sys.stderr,
        )
        return 127

    results: list[SampleResult] = []
    latencies: list[float] = []

    for idx in range(1, args.samples + 1):
        started = time.monotonic()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            frame_path = tmp.name
        try:
            ok_capture, cap_err = capture_frame(
                ffmpeg_bin=ffmpeg_bin,
                rtsp_url=args.rtsp_url,
                output_path=frame_path,
                crop=args.crop or None,
                timeout_sec=args.timeout_sec,
            )
            if not ok_capture:
                result = SampleResult(
                    index=idx,
                    ok=False,
                    latency_sec=None,
                    ocr_text="",
                    timestamp_text=None,
                    error=cap_err,
                )
                results.append(result)
                print(f"[sample {idx:02d}] error: {cap_err}", file=sys.stderr)
                continue

            ok_ocr, ocr_payload = run_ocr(tesseract_bin, frame_path, args.psm)
            if not ok_ocr:
                result = SampleResult(
                    index=idx,
                    ok=False,
                    latency_sec=None,
                    ocr_text="",
                    timestamp_text=None,
                    error=ocr_payload,
                )
                results.append(result)
                print(f"[sample {idx:02d}] error: {ocr_payload}", file=sys.stderr)
                continue

            overlay_dt, stamp_text = parse_overlay_timestamp(ocr_payload)
            if overlay_dt is None:
                result = SampleResult(
                    index=idx,
                    ok=False,
                    latency_sec=None,
                    ocr_text=ocr_payload,
                    timestamp_text=stamp_text,
                    error="timestamp not recognized by OCR",
                )
                results.append(result)
                print(
                    f"[sample {idx:02d}] error: timestamp not recognized (ocr='{ocr_payload}')",
                    file=sys.stderr,
                )
                continue

            now = dt.datetime.now()
            latency = (now - overlay_dt).total_seconds()
            latencies.append(latency)
            result = SampleResult(
                index=idx,
                ok=True,
                latency_sec=latency,
                ocr_text=ocr_payload,
                timestamp_text=stamp_text,
                error=None,
            )
            results.append(result)
            print(
                f"[sample {idx:02d}] latency={latency:.3f}s stamp='{stamp_text}'",
                file=sys.stderr,
            )
        finally:
            try:
                os.unlink(frame_path)
            except OSError:
                pass

        elapsed = time.monotonic() - started
        sleep_sec = args.interval - elapsed
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    ok_count = len(latencies)
    fail_count = len(results) - ok_count
    summary = {
        "rtsp_url": args.rtsp_url,
        "samples": args.samples,
        "ok_samples": ok_count,
        "failed_samples": fail_count,
        "mean_sec": statistics.fmean(latencies) if latencies else None,
        "median_sec": statistics.median(latencies) if latencies else None,
        "min_sec": min(latencies) if latencies else None,
        "max_sec": max(latencies) if latencies else None,
        "p95_sec": p95(latencies) if latencies else None,
        "note": (
            "OCR is based on second-level overlay; expected quantization error is about +/-1s. "
            "Run NTP sync on sender/receiver before measurement."
        ),
    }

    if args.json:
        payload = {
            "summary": summary,
            "samples": [asdict(item) for item in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Latency summary")
        print(f"- rtsp_url: {summary['rtsp_url']}")
        print(f"- samples: {summary['samples']} (ok={ok_count}, failed={fail_count})")
        if latencies:
            print(
                "- mean/median/min/max/p95: "
                f"{summary['mean_sec']:.3f}s / "
                f"{summary['median_sec']:.3f}s / "
                f"{summary['min_sec']:.3f}s / "
                f"{summary['max_sec']:.3f}s / "
                f"{summary['p95_sec']:.3f}s"
            )
        else:
            print("- no successful samples")
        print(f"- note: {summary['note']}")

    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
