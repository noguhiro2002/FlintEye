from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flinteye_app.workers.multiview_input_to_rtsp import _redact_log_line, build_command, select_onvif_profile
from flinteye_app.workers.multiview_buffer_to_rtsp import WallClockFrameBuffer, choose_output_frame, memory_limited_frame_count, parse_args as parse_buffer_args, synchronized_target_at
from flinteye_app.workers.multiview_raw_compositor import build_views as build_raw_views, compose_view, parse_args as parse_raw_args, write_status as write_raw_status
from flinteye_app.workers.multiview_to_rtsp import (
    InputHealth,
    ViewRuntime,
    ViewSpec,
    build_page_command,
    build_views,
    detect_input_stall_timeout_option,
    parse_args,
    poll_input_health,
    resolve_sources,
    view_startup_grace_sec,
)
from flinteye_app.orchestrator_api import _merge_multiview_buffer_status, _sanitize_multiview_status_payload
from flinteye_app.orchestrator_recording import _resolve_record_paths
from flinteye_app.orchestrator_models import RuntimeConfig
from flinteye_app.orchestrator_supervisor import (
    OrchestratorSupervisor,
    _multiview_buffer_path,
    _configured_multiview_sources,
    _multiview_effective_sources,
    _plan_multiview,
)


def runtime_config() -> RuntimeConfig:
    return RuntimeConfig.model_validate(
        {
            "mediamtx": {
                "rtsp_base_url": "rtsp://127.0.0.1:8554",
                "internal_rtsp_base_url": "rtsp://127.0.0.1:8554",
            },
            "cameras": [
                {
                    "id": "ipcam1",
                    "type": "ip",
                    "path": "ipcam1",
                    "ip": {
                        "source_url": "rtsp://user:secret@camera.local/stream1",
                        "relay_mode": "copy",
                        "timestamp_mode": "wallclock",
                    },
                }
            ],
            "multiview": {"enabled": True, "source_paths": ["ipcam1", "external"]},
        }
    )


class MultiviewModelTests(unittest.TestCase):
    def test_defaults_preserve_primary_path_and_use_ten_fps(self) -> None:
        config = runtime_config()
        self.assertEqual(config.multiview.input_defaults.mode, "primary")
        self.assertEqual(config.multiview.quality.fps, 10)
        self.assertEqual(config.cameras[0].ip.multiview_input.mode, "inherit")
        self.assertEqual(_configured_multiview_sources(config), ["ipcam1", "external"])
        self.assertFalse(config.multiview.sync_buffer.enabled)
        self.assertEqual(config.multiview.sync_buffer.delay_sec, 3.0)

    def test_multiview_override_does_not_change_main_camera_command(self) -> None:
        config = runtime_config()
        supervisor = object.__new__(OrchestratorSupervisor)
        supervisor.workspace_dir = str(Path(__file__).resolve().parents[1])
        supervisor.python_bin = "python"
        supervisor.env_file = ".env"
        supervisor._processes = {}
        before = supervisor._camera_command(config, config.cameras[0])

        updated = config.model_copy(deep=True)
        updated.cameras[0].ip.multiview_input.mode = "normalized_primary"
        after = supervisor._camera_command(updated, updated.cameras[0])
        self.assertEqual(before, after)
        self.assertEqual(_configured_multiview_sources(updated), ["__mv_input/ipcam1", "external"])

        input_command = supervisor._multiview_input_command(updated, updated.cameras[0])
        self.assertIn("rtsp://127.0.0.1:8554/ipcam1", input_command)
        self.assertIn("rtsp://127.0.0.1:8554/__mv_input/ipcam1", input_command)

        view_command = supervisor._multiview_command(updated)
        self.assertIn("--shadowed-source-paths", view_command)
        self.assertIn("ipcam1", view_command)

    def test_sync_buffer_is_opt_in_and_does_not_change_main_camera_relay(self) -> None:
        config = runtime_config()
        supervisor = object.__new__(OrchestratorSupervisor)
        supervisor.workspace_dir = str(Path(__file__).resolve().parents[1])
        supervisor.python_bin = "python"
        supervisor.env_file = ".env"
        supervisor._processes = {}
        main_before = supervisor._camera_command(config, config.cameras[0])

        config.multiview.sync_buffer.enabled = True
        main_after = supervisor._camera_command(config, config.cameras[0])
        self.assertEqual(main_before, main_after)
        self.assertEqual(_configured_multiview_sources(config), ["ipcam1", "external"])
        self.assertEqual(
            _multiview_effective_sources(config),
            ["ipcam1", "external"],
        )

        view_command = supervisor._multiview_command(config)
        self.assertEqual(view_command[2:4], ["--worker", "multiview_raw_compositor"])
        self.assertEqual(view_command[view_command.index("--source-paths") + 1], "ipcam1,external")
        self.assertFalse(any("__mv_buffer/" in value for value in view_command))

        supervisor._last_config = config
        multiview_process = SimpleNamespace(desired=True, restart_pending_at=None)
        supervisor._processes = {"multiview": multiview_process}
        supervisor._schedule_multiview_restart(source_key="camera:ipcam1", exit_code=1, now=100)
        self.assertIsNone(multiview_process.restart_pending_at)

    def test_sync_buffer_model_rejects_delay_larger_than_capacity(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeConfig.model_validate({"multiview": {"sync_buffer": {"delay_sec": 6, "buffer_sec": 5}}})

    def test_internal_paths_are_never_recorded(self) -> None:
        config = runtime_config()
        config.recording.record_paths = ["ipcam1", "__mv_input/ipcam1", "__mv_buffer/ipcam1"]
        config.recording.record_all_cameras = False
        self.assertNotIn("__mv_input/ipcam1", _resolve_record_paths(config))
        self.assertNotIn("__mv_buffer/ipcam1", _resolve_record_paths(config))

    def test_api_discovery_hides_internal_and_shadowed_paths(self) -> None:
        args = SimpleNamespace(
            source_paths="__mv_input/ipcam1,external",
            shadowed_source_paths="ipcam1",
            source_mode="hybrid",
            mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
            output_prefix="multiview",
            max_sources=32,
        )
        with patch(
            "flinteye_app.workers.multiview_to_rtsp.fetch_paths_from_api",
            return_value=["ipcam1", "__mv_input/ipcam1", "__mv_input/unknown", "other"],
        ):
            self.assertEqual(resolve_sources(args), ["__mv_input/ipcam1", "external", "other"])

    def test_hybrid_uses_each_camera_once_with_audio_and_private_paths(self) -> None:
        from flinteye_app.camera_audio import live_path

        config = runtime_config()
        config.cameras[0].ip.multiview_input.mode = "normalized_primary"
        reported = ["external", "ipcam1", "__mv_input/ipcam1", live_path("ipcam1"),
                    "__mv_buffer/ipcam1", "multiview_1"]
        self.assertEqual(_plan_multiview(config, reported), (["__mv_input/ipcam1", "external"], None))
        self.assertEqual(_plan_multiview(config, [*reported, "third"]),
                         (["__mv_input/ipcam1", "external", "third"], None))

    def test_standard_and_raw_compositors_use_the_same_slots(self) -> None:
        geometry = ["--source-paths", "left,right", "--canvas-width", "8", "--canvas-height", "4", "--tile-count", "4"]
        expected = [(0, 0, 4, 4), (4, 0, 4, 4)]
        standard = build_views(parse_args(geometry), ["left", "right"])[0]
        raw = build_raw_views(parse_raw_args(geometry), ["left", "right"])[0]
        self.assertEqual(standard.slots, expected)
        self.assertEqual([row.slot for row in raw.inputs], expected)

        options = geometry + ["--source-slots-json", '[["right",null,null,"left"]]']
        args = parse_args(options)
        standard = build_views(args, ["left", "right"])[0]
        raw = build_raw_views(parse_raw_args(options), ["left", "right"])[0]
        self.assertEqual(standard.placements, ["right", None, None, "left"])
        self.assertEqual([(entry.source, entry.slot_index) for entry in raw.inputs], [("right", 0), ("left", 3)])
        command = build_page_command(args, standard, 'libx264')
        inputs = [value for flag, value in zip(command, command[1:]) if flag == "-i"]
        self.assertTrue(inputs[0].endswith("/right"))
        self.assertTrue(inputs[3].endswith("/left"))
        self.assertTrue(all(value.startswith("color=c=black") for value in inputs[1:3]))

class WallClockBufferTests(unittest.TestCase):
    def test_shared_target_is_quantized_to_server_epoch(self) -> None:
        self.assertEqual(synchronized_target_at(100.349, 3.0, 10), 97.3)
        self.assertEqual(synchronized_target_at(100.399, 3.0, 10), 97.3)

    def test_selects_latest_frame_not_newer_than_shared_target(self) -> None:
        buffer = WallClockFrameBuffer(max_frames=10, retention_sec=5)
        buffer.append(100.0, b"a")
        buffer.append(100.1, b"b")
        buffer.append(100.2, b"c")
        self.assertIsNone(buffer.select(99.9))
        self.assertEqual(buffer.select(100.15).data, b"b")
        self.assertEqual(buffer.select(100.2).data, b"c")

    def test_last_frame_holds_only_until_configured_wallclock_age(self) -> None:
        buffer = WallClockFrameBuffer(max_frames=10, retention_sec=5)
        buffer.append(100.0, b"frame")
        frame, last, state = choose_output_frame(buffer, target_at=100.1, last_selected=None, late_frame_policy="hold", max_hold_sec=10, fps=10)
        self.assertEqual((frame.data, state), (b"frame", "healthy"))
        frame, last, state = choose_output_frame(buffer, target_at=105.0, last_selected=last, late_frame_policy="hold", max_hold_sec=10, fps=10)
        self.assertEqual((frame.data, state), (b"frame", "holding"))
        frame, _last, state = choose_output_frame(buffer, target_at=111.0, last_selected=last, late_frame_policy="hold", max_hold_sec=10, fps=10)
        self.assertIsNone(frame)
        self.assertEqual(state, "no_stream")

    def test_no_stream_policy_does_not_hold_stale_frame(self) -> None:
        buffer = WallClockFrameBuffer(max_frames=10, retention_sec=5)
        buffer.append(100.0, b"frame")
        frame, _last, state = choose_output_frame(buffer, target_at=101.0, last_selected=None, late_frame_policy="no_stream", max_hold_sec=10, fps=10)
        self.assertIsNone(frame)
        self.assertEqual(state, "no_stream")

    def test_retention_and_memory_limit_bound_rgb_frames(self) -> None:
        args = parse_buffer_args([
            "--source-url", "rtsp://127.0.0.1/source",
            "--source-path", "source",
            "--output-url", "rtsp://127.0.0.1/__mv_buffer/source",
            "--buffer-path", "__mv_buffer/source",
            "--width", "640", "--height", "360",
            "--fps", "10", "--buffer-sec", "5",
            "--delay-sec", "3", "--memory-limit-mb", "20",
        ])
        self.assertLess(memory_limited_frame_count(args), 52)
        frame_limit = memory_limited_frame_count(args)
        buffer = WallClockFrameBuffer(max_frames=frame_limit, retention_sec=5)
        for index in range(100):
            buffer.append(index / 10, bytes([index % 255]))
        self.assertLessEqual(buffer.stats()[0], frame_limit)

    def test_internal_buffer_path_is_stable_and_nested(self) -> None:
        self.assertEqual(_multiview_buffer_path("__mv_input/ipcam1"), "__mv_buffer/__mv_input/ipcam1")


class RawCompositorTests(unittest.TestCase):
    def test_composes_selected_raw_frames_without_intermediate_rtsp(self) -> None:
        args = parse_raw_args([
            "--source-paths", "left,right",
            "--canvas-width", "4", "--canvas-height", "2",
            "--tile-count", "2", "--fps", "10",
            "--delay-sec", "1", "--buffer-sec", "2",
            "--memory-limit-mb", "1",
        ])
        view = build_raw_views(args, ["left", "right"])[0]
        view.inputs[0].frame_buffer.append(99.0, bytes([1]) * 12)
        view.inputs[1].frame_buffer.append(99.0, bytes([2]) * 12)
        canvas, states = compose_view(args, view, 99.0)
        self.assertEqual(states, ["healthy", "healthy"])
        self.assertEqual(canvas, bytes([1]) * 6 + bytes([2]) * 6 + bytes([1]) * 6 + bytes([2]) * 6)

    def test_one_missing_input_does_not_discard_other_tile(self) -> None:
        args = parse_raw_args([
            "--source-paths", "missing,live",
            "--canvas-width", "4", "--canvas-height", "2",
            "--tile-count", "2", "--fps", "10",
            "--delay-sec", "1", "--buffer-sec", "2",
            "--memory-limit-mb", "1",
        ])
        view = build_raw_views(args, ["missing", "live"])[0]
        view.inputs[1].frame_buffer.append(99.0, bytes([7]) * 12)
        canvas, states = compose_view(args, view, 99.0)
        self.assertEqual(states, ["buffering", "healthy"])
        self.assertEqual(canvas[:6], bytes(6))
        self.assertEqual(canvas[6:12], bytes([7]) * 6)

    def test_status_replace_lock_never_terminates_compositor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = parse_raw_args([
                "--source-paths", "one",
                "--canvas-width", "2", "--canvas-height", "2",
                "--tile-count", "1", "--fps", "10",
                "--delay-sec", "1", "--buffer-sec", "2",
                "--memory-limit-mb", "1",
                "--status-file", str(Path(directory) / "status.json"),
            ])
            view = build_raw_views(args, ["one"])[0]
            encoder = SimpleNamespace(snapshot=lambda: {
                "running": True,
                "restart_count": 0,
                "frames_published": 1,
                "last_published_at": 9999999999,
                "reason": None,
            })
            with patch("flinteye_app.workers.multiview_raw_compositor.os.replace", side_effect=PermissionError("locked")), patch("flinteye_app.workers.multiview_raw_compositor.time.sleep"):
                write_raw_status(args, [view], [encoder])
            self.assertFalse((Path(directory) / "status.json.tmp").exists())


class ProfileSelectionTests(unittest.TestCase):
    def test_selects_smallest_profile_that_meets_tile_and_fps(self) -> None:
        profiles = [
            {"token": "main", "encoding": "H264", "width": 2880, "height": 1620, "fps": 20, "bitrate_kbps": 4000, "stream_uri": "rtsp://camera/main"},
            {"token": "small", "encoding": "H264", "width": 640, "height": 360, "fps": 15, "bitrate_kbps": 500, "stream_uri": "rtsp://camera/sub"},
            {"token": "jpeg", "encoding": "JPEG", "width": 640, "height": 360, "fps": 20, "stream_uri": "rtsp://camera/jpeg"},
        ]
        selected = select_onvif_profile(
            profiles,
            target_width=640,
            target_height=360,
            target_fps=10,
        )
        self.assertEqual(selected["token"], "small")

    def test_manual_profile_token_overrides_ranking(self) -> None:
        profiles = [
            {"token": "a", "encoding": "H264", "width": 640, "height": 360, "fps": 10, "stream_uri": "rtsp://camera/a"},
            {"token": "b", "encoding": "H265", "width": 1280, "height": 720, "fps": 20, "stream_uri": "rtsp://camera/b"},
        ]
        self.assertEqual(
            select_onvif_profile(
                profiles,
                target_width=640,
                target_height=360,
                target_fps=10,
                profile_token="b",
            )["token"],
            "b",
        )

    def test_lower_bitrate_breaks_equal_size_ties_before_codec(self) -> None:
        profiles = [
            {"token": "h264", "encoding": "H264", "width": 640, "height": 360, "fps": 10, "bitrate_kbps": 900, "stream_uri": "rtsp://camera/h264"},
            {"token": "h265", "encoding": "H265", "width": 640, "height": 360, "fps": 10, "bitrate_kbps": 400, "stream_uri": "rtsp://camera/h265"},
        ]
        selected = select_onvif_profile(profiles, target_width=640, target_height=360, target_fps=10)
        self.assertEqual(selected["token"], "h265")

    def test_conversion_does_not_upscale_and_log_redacts_credentials(self) -> None:
        args = SimpleNamespace(
            fps=10,
            width=640,
            height=360,
            ffmpeg_bin="ffmpeg",
            loglevel="error",
            stall_timeout_arg="rw_timeout",
            stall_timeout_sec=15,
            thread_queue_size=128,
            encoder="libx264",
            quality_preset="standard",
            x264_preset="veryfast",
            bitrate="800k",
            maxrate="1M",
            bufsize="2M",
            output_url="rtsp://127.0.0.1:8554/__mv_input/ipcam1",
            onvif_password="onvif-secret",
            camera_source_url="rtsp://camera-user:camera-secret@camera/stream1",
            manual_url="rtsp://manual-user:manual-secret@camera/stream2",
            primary_url="rtsp://127.0.0.1:8554/ipcam1",
        )
        command = build_command(args, args.manual_url)
        filter_graph = command[command.index("-vf") + 1]
        self.assertIn("min(iw,640)", filter_graph)
        line = "Input from rtsp://manual-user:manual-secret@camera/stream2 onvif-secret"
        redacted = _redact_log_line(args, line)
        self.assertNotIn("manual-secret", redacted)
        self.assertNotIn("onvif-secret", redacted)
        self.assertIn("rtsp://***@camera/stream2", redacted)


class InputHealthTests(unittest.TestCase):
    def test_health_startup_grace_uses_the_same_serial_input_budget(self) -> None:
        args = SimpleNamespace(
            input_stall_timeout_sec=15.0,
            health_placeholder_map={},
            mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
            status_file="",
            output_prefix="multiview",
            input_retry_interval_sec=30.0,
            input_isolation_threshold=3,
        )
        sources = [f"ipcam{index}" for index in range(1, 8)]
        runtime = ViewRuntime(
            ViewSpec(index=1, sources=sources, slots=[]),
            process=SimpleNamespace(poll=lambda: None),
            started_at=100,
        )
        self.assertEqual(view_startup_grace_sec(args, runtime), 45.0)

        state = InputHealth(source="ipcam1", last_progress_at=0)
        metrics = ({"ipcam1": {"ready": True, "bytesReceived": 100}}, set())
        with patch("flinteye_app.workers.multiview_to_rtsp.fetch_input_metrics", return_value=metrics):
            self.assertEqual(poll_input_health(args, [runtime], {"ipcam1": state}, now=130), set())
        self.assertEqual(state.state, "starting")
        self.assertEqual(state.failures, 0)

    def test_rtsp_timeout_includes_serial_input_startup_budget(self) -> None:
        args = parse_args(
            [
                "--no-env",
                "--source-mode",
                "env",
                "--source-paths",
                "ipcam1,ipcam2,ipcam3",
                "--tile-count",
                "3",
                "--input-stall-timeout-sec",
                "15",
            ]
        )
        args.input_stall_timeout_arg = "timeout"
        view = ViewSpec(
            index=1,
            sources=["ipcam1", "ipcam2", "ipcam3"],
            slots=[(0, 0, 640, 360), (640, 0, 640, 360), (0, 360, 640, 360)],
        )
        command = build_page_command(args, view, "libx264")
        timeout_values = [
            int(command[index + 1])
            for index, value in enumerate(command)
            if value == "-timeout"
        ]
        self.assertEqual(timeout_values, [25_000_000, 20_000_000, 15_000_000])

    def test_missing_reader_restarts_view_without_isolating_healthy_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
                status_file=str(Path(directory) / "status.json"),
                output_prefix="multiview",
                input_stall_timeout_sec=15.0,
                input_retry_interval_sec=30.0,
                input_isolation_threshold=3,
                health_placeholder_map={},
            )
            running_process = SimpleNamespace(poll=lambda: None)
            view = ViewRuntime(
                ViewSpec(index=1, sources=["ipcam1"], slots=[(0, 0, 640, 360)]),
                process=running_process,
                started_at=0,
            )
            state = InputHealth(source="ipcam1", last_progress_at=0.0)
            states = {"ipcam1": state}

            metrics = [
                ({"ipcam1": {"ready": True, "bytesReceived": 100}}, set()),
                ({"ipcam1": {"ready": True, "bytesReceived": 200}}, set()),
                ({"ipcam1": {"ready": True, "bytesReceived": 300}}, set()),
            ]
            with patch("flinteye_app.workers.multiview_to_rtsp.fetch_input_metrics", side_effect=metrics):
                self.assertEqual(poll_input_health(args, [view], states, now=20), set())
                self.assertEqual(poll_input_health(args, [view], states, now=36), {1})
                self.assertEqual(poll_input_health(args, [view], states, now=52), {1})

            self.assertFalse(state.isolated)
            self.assertEqual(state.failures, 0)
            self.assertNotIn("ipcam1", args.health_placeholder_map)
            self.assertTrue(Path(args.status_file).is_file())

    def test_view_process_failure_does_not_penalize_inputs(self) -> None:
        args = SimpleNamespace(
            mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
            status_file="",
            output_prefix="multiview",
            input_stall_timeout_sec=15.0,
            input_retry_interval_sec=30.0,
            input_isolation_threshold=3,
            health_placeholder_map={},
        )
        stopped_process = SimpleNamespace(poll=lambda: 1)
        view = ViewRuntime(ViewSpec(index=1, sources=["ipcam1"], slots=[]), process=stopped_process, started_at=0)
        state = InputHealth(source="ipcam1", last_progress_at=0)
        with patch("flinteye_app.workers.multiview_to_rtsp.fetch_input_metrics", return_value=({"ipcam1": {"ready": True, "bytesReceived": 100}}, set())):
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=100), set())
        self.assertEqual(state.state, "starting")
        self.assertEqual(state.failures, 0)

    def test_missing_reader_isolates_only_when_view_output_remains_ready(self) -> None:
        args = SimpleNamespace(
            mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
            status_file="",
            output_prefix="multiview",
            input_stall_timeout_sec=15.0,
            input_retry_interval_sec=30.0,
            input_isolation_threshold=3,
            health_placeholder_map={},
        )
        running_process = SimpleNamespace(poll=lambda: None)
        view = ViewRuntime(ViewSpec(index=1, sources=["ipcam1"], slots=[]), process=running_process, started_at=0)
        state = InputHealth(source="ipcam1", last_progress_at=0)
        metrics = [
            (
                {
                    "ipcam1": {"ready": True, "bytesReceived": received},
                    "multiview_1": {"ready": True, "bytesReceived": received},
                },
                set(),
            )
            for received in (100, 200, 300, 400)
        ]

        with patch("flinteye_app.workers.multiview_to_rtsp.fetch_input_metrics", side_effect=metrics):
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=20), set())
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=36), set())
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=52), set())
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=68), {1})

        self.assertTrue(state.isolated)
        self.assertEqual(state.failures, 3)
        self.assertEqual(
            args.health_placeholder_map["ipcam1"],
            "Input isolated after repeated Multiview reader failures",
        )

    def test_publisher_failure_still_isolates_the_failed_input(self) -> None:
        args = SimpleNamespace(
            mtx_api_url="http://127.0.0.1:9997/v3/paths/list",
            status_file="",
            output_prefix="multiview",
            input_stall_timeout_sec=15.0,
            input_retry_interval_sec=30.0,
            input_isolation_threshold=3,
            health_placeholder_map={},
        )
        running_process = SimpleNamespace(poll=lambda: None)
        view = ViewRuntime(ViewSpec(index=1, sources=["ipcam1"], slots=[]), process=running_process, started_at=0)
        state = InputHealth(source="ipcam1", last_progress_at=0)
        unavailable = ({"ipcam1": {"ready": False, "bytesReceived": 0}}, set())

        with patch("flinteye_app.workers.multiview_to_rtsp.fetch_input_metrics", return_value=unavailable):
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=20), set())
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=36), {1})
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=52), {1})
            self.assertEqual(poll_input_health(args, [view], {"ipcam1": state}, now=68), {1})

        self.assertTrue(state.isolated)
        self.assertEqual(state.failures, 3)
        self.assertEqual(args.health_placeholder_map["ipcam1"], "Input isolated after repeated recovery failures")

    def test_timeout_auto_detection_uses_rtsp_demuxer_option(self) -> None:
        def advertised(_ffmpeg: str, _target: str, option: str) -> bool:
            return option == "timeout"

        with patch("flinteye_app.workers.multiview_to_rtsp.ffmpeg_help_contains_option", side_effect=advertised):
            self.assertEqual(detect_input_stall_timeout_option("ffmpeg"), "timeout")

    def test_status_payload_is_fixed_schema_and_redacts_credentials(self) -> None:
        payload = _sanitize_multiview_status_payload(
            {
                "secret": "must-not-leak",
                "views": [
                    {
                        "id": "multiview_1",
                        "state": "degraded",
                        "unexpected": "hidden",
                        "inputs": [
                            {
                                "path": "ipcam1",
                                "state": "degraded",
                                "failures": 1,
                                "reason": "failed rtsp://user:password@camera/stream",
                                "source_url": "rtsp://user:password@camera/stream",
                            }
                        ],
                    }
                ],
            }
        )
        serialized = str(payload)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("source_url", serialized)
        self.assertIn("rtsp://***:***@camera/stream", serialized)

    def test_buffer_status_maps_internal_path_back_to_original_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "multiview_status.json"
            (Path(directory) / "multiview_buffer_1.json").write_text(
                '{"updated_at":9999999999,"buffer_path":"__mv_buffer/ipcam1","source_path":"ipcam1","state":"holding","buffer_delay_sec":3,"buffered_frames":30}',
                encoding="utf-8",
            )
            payload = {
                "views": [{
                    "id": "multiview_1",
                    "state": "healthy",
                    "inputs": [{"path": "__mv_buffer/ipcam1", "state": "healthy"}],
                }]
            }
            _merge_multiview_buffer_status(payload, status_path)
            item = payload["views"][0]["inputs"][0]
            self.assertEqual(item["path"], "ipcam1")
            self.assertEqual(item["state"], "holding")
            self.assertEqual(item["buffered_frames"], 30)
            self.assertEqual(payload["views"][0]["state"], "degraded")

    def test_fresh_healthy_buffers_restore_view_health_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "multiview_status.json"
            (Path(directory) / "multiview_buffer_1.json").write_text(
                '{"updated_at":9999999999,"buffer_path":"__mv_buffer/ipcam1","source_path":"ipcam1","state":"healthy","buffer_delay_sec":5,"buffered_frames":50}',
                encoding="utf-8",
            )
            payload = {
                "updated_at": 1,
                "views": [{
                    "id": "multiview_1",
                    "state": "degraded",
                    "inputs": [{"path": "__mv_buffer/ipcam1", "state": "starting"}],
                }],
            }
            _merge_multiview_buffer_status(payload, status_path)
            self.assertEqual(payload["views"][0]["state"], "healthy")
            self.assertEqual(payload["views"][0]["inputs"][0]["state"], "healthy")
            self.assertEqual(payload["updated_at"], 9999999999)


if __name__ == "__main__":
    unittest.main()
