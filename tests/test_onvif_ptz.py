from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request

from flinteye_app.orchestrator_api import _authorized_ptz_camera, require_ptz_identity
from flinteye_app.orchestrator_auth import AuthIdentity
from flinteye_app.orchestrator_ip_camera_probe import _probe_media_profiles, probe_ptz_profiles
from flinteye_app.orchestrator_models import CameraConfig, RuntimeConfig
from flinteye_app.orchestrator_onvif_ptz import (
    OnvifPtzController,
    PtzBusyError,
    PtzCacheEntry,
    PtzRateLimitError,
)


def axis_space(*, x=(-1.0, 1.0), y=None):
    value = {"URI": "urn:test", "XRange": {"Min": x[0], "Max": x[1]}}
    if y is not None:
        value["YRange"] = {"Min": y[0], "Max": y[1]}
    return value


def make_camera(*, access="viewer", enabled=True, profile_token=None):
    return CameraConfig.model_validate(
        {
            "id": "cam1",
            "type": "ip",
            "enabled": True,
            "path": "cam1",
            "ip": {
                "source_url": "rtsp://user:secret@camera.local/stream1",
                "onvif_mode": "manual",
                "onvif_address": "http://camera.local/onvif/device_service",
                "ptz": {
                    "enabled": enabled,
                    "access": access,
                    "profile_token": profile_token,
                },
            },
        }
    )


class FakeMedia:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def GetProfiles(self):
        self.calls += 1
        return [
            {
                "token": f"{self.name}-profile",
                "Name": self.name,
                "Configurations": {
                    "VideoEncoder": {
                        "Encoding": "H264",
                        "Resolution": {"Width": 1920, "Height": 1080},
                        "RateControl": {"FrameRateLimit": 20},
                    },
                    "PTZ": {"token": f"{self.name}-ptz", "NodeToken": f"{self.name}-node"},
                },
            }
        ]

    def GetStreamUri(self, **kwargs):
        return {"Uri": f"rtsp://camera.local/{self.name.lower()}"}


class FakePtz:
    def __init__(self, spaces_by_token):
        self.spaces_by_token = spaces_by_token
        self.calls = []
        self.position = {"pan": 0.0, "tilt": 0.0, "zoom": 0.0}

    def GetNodes(self):
        return []

    def GetConfigurationOptions(self, ConfigurationToken):
        return {"Spaces": self.spaces_by_token.get(ConfigurationToken, {})}

    def ContinuousMove(self, **kwargs):
        self.calls.append(("ContinuousMove", kwargs))

    def RelativeMove(self, **kwargs):
        self.calls.append(("RelativeMove", kwargs))

    def AbsoluteMove(self, **kwargs):
        self.calls.append(("AbsoluteMove", kwargs))

    def Stop(self, **kwargs):
        self.calls.append(("Stop", kwargs))

    def GetStatus(self, **kwargs):
        return {
            "Position": {
                "PanTilt": {"x": self.position["pan"], "y": self.position["tilt"]},
                "Zoom": {"x": self.position["zoom"]},
            }
        }


class FakeClient:
    def __init__(self, media1=None, media2=None, ptz=None):
        self.media_service = media1
        self.media2_service = media2
        self.ptz_service = ptz
        self.services = [
            {"Namespace": "http://www.onvif.org/ver10/media/wsdl"},
            {"Namespace": "http://www.onvif.org/ver20/media/wsdl"},
        ]

    def media(self):
        return self.media_service

    def media2(self):
        return self.media2_service

    def ptz(self):
        return self.ptz_service


class FakeClock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


def capability_profile(*, pan_tilt=True, zoom=True, pt_mode="continuous", zoom_mode="continuous"):
    modes = {
        "pan_tilt": {"continuous": False, "relative": False, "absolute": False},
        "zoom": {"continuous": False, "relative": False, "absolute": False},
    }
    if pan_tilt:
        modes["pan_tilt"][pt_mode] = True
    if zoom:
        modes["zoom"][zoom_mode] = True
    spaces = {
        "continuous_pan_tilt": [axis_space(y=(-1, 1))] if pan_tilt and pt_mode == "continuous" else [],
        "relative_pan_tilt": [axis_space(y=(-1, 1))] if pan_tilt and pt_mode == "relative" else [],
        "absolute_pan_tilt": [axis_space(y=(-1, 1))] if pan_tilt and pt_mode == "absolute" else [],
        "continuous_zoom": [axis_space()] if zoom and zoom_mode == "continuous" else [],
        "relative_zoom": [axis_space()] if zoom and zoom_mode == "relative" else [],
        "absolute_zoom": [axis_space(x=(0, 1))] if zoom and zoom_mode == "absolute" else [],
    }
    return {
        "token": "profile1",
        "name": "mainStream",
        "stream_uri": "rtsp://camera.local/stream1",
        "ptz": {
            "supported": pan_tilt or zoom,
            "pan_tilt": pan_tilt,
            "zoom": zoom,
            "modes": modes,
            "spaces": spaces,
        },
    }


class ProbeCapabilityTests(unittest.TestCase):
    def test_media1_and_media2_are_both_inspected(self):
        media1 = FakeMedia("Media")
        media2 = FakeMedia("Media2")
        client = FakeClient(media1=media1, media2=media2)
        profiles, primary, errors, contacted = _probe_media_profiles(client, "rtsp://camera.local/stream1")
        self.assertTrue(contacted)
        self.assertEqual(primary, "Media2")
        self.assertEqual(errors, [])
        self.assertEqual({p["media_service"] for p in profiles}, {"Media", "Media2"})
        self.assertEqual(media1.calls, 1)
        self.assertEqual(media2.calls, 1)

    def test_supported_spaces_detect_pt_only_zoom_only_and_modes(self):
        profiles = [
            {"token": "pt", "name": "PT", "ptz_configuration_token": "pt-cfg", "ptz_node_token": "pt-node"},
            {"token": "z", "name": "Z", "ptz_configuration_token": "z-cfg", "ptz_node_token": "z-node"},
        ]
        service = FakePtz(
            {
                "pt-cfg": {"ContinuousPanTiltVelocitySpace": [axis_space(y=(-1, 1))]},
                "z-cfg": {
                    "AbsoluteZoomPositionSpace": [axis_space(x=(0, 1))],
                    "RelativeZoomTranslationSpace": [axis_space()],
                },
            }
        )
        result = probe_ptz_profiles(FakeClient(ptz=service), profiles, "rtsp://camera.local/stream1")
        self.assertTrue(result["supported"])
        self.assertTrue(result["pan_tilt"])
        self.assertTrue(result["zoom"])
        self.assertTrue(profiles[0]["ptz"]["modes"]["pan_tilt"]["continuous"])
        self.assertFalse(profiles[0]["ptz"]["zoom"])
        self.assertTrue(profiles[1]["ptz"]["modes"]["zoom"]["absolute"])
        self.assertTrue(profiles[1]["ptz"]["modes"]["zoom"]["relative"])

    def test_no_spaces_is_not_ptz_capable(self):
        profiles = [{"token": "none", "name": "None", "ptz_configuration_token": "cfg"}]
        result = probe_ptz_profiles(FakeClient(ptz=FakePtz({"cfg": {}})), profiles, "rtsp://camera.local/x")
        self.assertFalse(result["supported"])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.service = FakePtz({})
        self.profile = capability_profile()

        def inspector(camera):
            return PtzCacheEntry(
                signature="",
                client=object(),
                service=self.service,
                profiles=[self.profile],
                ptz={"supported": True, "service_available": True, "message": "ok"},
                connection={},
                expires_at=0,
            )

        self.controller = OnvifPtzController(clock=self.clock, inspector=inspector)
        self.camera = make_camera()
        self.viewer1 = AuthIdentity("viewer1", "viewer", "local")
        self.viewer2 = AuthIdentity("viewer2", "viewer", "local")
        self.admin = AuthIdentity("admin", "admin", "local")

    def test_continuous_move_uses_one_second_timeout_and_stop_is_idempotent(self):
        self.controller.move(self.camera, self.viewer1, operation_id="op1", pan=1)
        name, payload = self.service.calls[-1]
        self.assertEqual(name, "ContinuousMove")
        self.assertEqual(payload["Timeout"], "PT1S")
        self.controller.stop(self.camera, self.viewer1, operation_id="op1")
        self.controller.stop(self.camera, self.viewer1, operation_id="op1")
        self.assertGreaterEqual(sum(name == "Stop" for name, _ in self.service.calls), 2)

    def test_lease_conflict_expiry_and_admin_preemption(self):
        self.controller.move(self.camera, self.viewer1, operation_id="op1", pan=1)
        with self.assertRaises(PtzBusyError):
            self.controller.move(self.camera, self.viewer2, operation_id="op2", pan=-1)
        self.controller.move(self.camera, self.admin, operation_id="admin-op", pan=-1)
        self.assertTrue(any(name == "Stop" for name, _ in self.service.calls))
        self.controller.stop(self.camera, self.admin, operation_id="admin-op")
        self.controller.move(self.camera, self.viewer1, operation_id="op3", pan=1)
        self.clock.value += 3
        self.controller.move(self.camera, self.viewer2, operation_id="op4", pan=-1)

    def test_rate_limit_is_per_camera(self):
        for _ in range(10):
            self.controller.move(self.camera, self.viewer1, operation_id="op", pan=1)
        with self.assertRaises(PtzRateLimitError):
            self.controller.move(self.camera, self.viewer1, operation_id="op", pan=1)

    def test_relative_and_absolute_fallbacks(self):
        relative_service = FakePtz({})
        relative_profile = capability_profile(zoom=False, pt_mode="relative")
        relative = OnvifPtzController(
            clock=self.clock,
            inspector=lambda camera: PtzCacheEntry("", object(), relative_service, [relative_profile], {"supported": True}, {}, 0),
        )
        relative.move(self.camera, self.viewer1, operation_id="rel", tilt=1)
        self.assertEqual(relative_service.calls[-1][0], "RelativeMove")

        absolute_service = FakePtz({})
        absolute_profile = capability_profile(pan_tilt=False, zoom=True, zoom_mode="absolute")
        absolute = OnvifPtzController(
            clock=self.clock,
            inspector=lambda camera: PtzCacheEntry("", object(), absolute_service, [absolute_profile], {"supported": True}, {}, 0),
        )
        result = absolute.position(self.camera, self.viewer1, operation_id="abs", zoom=0.75)
        self.assertEqual(result["zoom"], 0.75)
        self.assertEqual(absolute_service.calls[-1][0], "AbsoluteMove")


class AuthorizationAndModelTests(unittest.TestCase):
    def test_old_camera_config_defaults_to_disabled_ptz(self):
        camera = CameraConfig.model_validate(
            {"id": "legacy", "type": "ip", "path": "legacy", "ip": {"source_url": "rtsp://camera/stream"}}
        )
        self.assertFalse(camera.ip.ptz.enabled)
        self.assertEqual(camera.ip.ptz.access, "admin")

    def test_camera_access_matrix(self):
        camera = make_camera(access="admin")
        config = RuntimeConfig(cameras=[camera])
        context = SimpleNamespace(store=SimpleNamespace(get_effective=lambda: config))
        self.assertEqual(_authorized_ptz_camera(context, "cam1", AuthIdentity("a", "admin", "local")), camera)
        with self.assertRaises(HTTPException) as denied:
            _authorized_ptz_camera(context, "cam1", AuthIdentity("v", "viewer", "local"))
        self.assertEqual(denied.exception.status_code, 403)
        camera.ip.ptz.access = "viewer"
        self.assertEqual(_authorized_ptz_camera(context, "cam1", AuthIdentity("v", "viewer", "local")), camera)

    def test_public_local_viewer_cannot_get_ptz_identity(self):
        config = RuntimeConfig.model_validate(
            {
                "auth": {
                    "provider": "local",
                    "viewer_auth_required": False,
                    "session_secret": "test-secret",
                    "local": {"admin": {"username": "admin", "password_hash": "configured"}},
                }
            }
        )
        context = SimpleNamespace(store=SimpleNamespace(get_effective=lambda: config))
        app = SimpleNamespace(state=SimpleNamespace(context=context))
        request = Request({"type": "http", "app": app, "headers": []})
        with self.assertRaises(HTTPException) as denied:
            require_ptz_identity(request, None)
        self.assertEqual(denied.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
