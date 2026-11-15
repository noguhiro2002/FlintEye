import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  MagnifyingGlassMinusIcon,
  MagnifyingGlassPlusIcon,
  StopIcon,
} from "@heroicons/react/24/outline";
import type { ApiClient } from "../api/client";
import type { PtzCapabilities, ViewerCameraItem } from "../types";

interface PtzControlsProps {
  api: ApiClient;
  camera: ViewerCameraItem;
  isAdmin: boolean;
}

interface MoveVector {
  pan?: number;
  tilt?: number;
  zoom?: number;
}

interface ActiveMove {
  operationId: string;
  vector: MoveVector;
  panTilt: boolean;
  zoom: boolean;
}

function operationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `ptz-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function modeLabel(modes: { continuous: boolean; relative: boolean; absolute: boolean }): string {
  if (modes.continuous) return "Continuous";
  if (modes.relative) return "Relative";
  if (modes.absolute) return "Absolute fallback";
  return "Unavailable";
}

export function PtzControls({ api, camera, isAdmin }: PtzControlsProps): JSX.Element {
  const [capabilities, setCapabilities] = useState<PtzCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeLabel, setActiveLabel] = useState("");
  const [zoomPosition, setZoomPosition] = useState(0);
  const [zoomVelocity, setZoomVelocity] = useState(0);
  const activeMoveRef = useRef<ActiveMove | null>(null);
  const heartbeatRef = useRef<number | null>(null);
  const zoomPositionTimerRef = useRef<number | null>(null);
  const pendingZoomPositionRef = useRef<number | null>(null);
  const zoomPositionOperationRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const clearHeartbeat = useCallback((): void => {
    if (heartbeatRef.current !== null) {
      window.clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const sendStop = useCallback(
    async (move: ActiveMove | null, all = false): Promise<void> => {
      clearHeartbeat();
      activeMoveRef.current = null;
      setActiveLabel("");
      setZoomVelocity(0);
      setBusy(false);
      try {
        await api.stopPtz(camera.id, {
          operation_id: move?.operationId,
          pan_tilt: all ? true : move?.panTilt ?? true,
          zoom: all ? true : move?.zoom ?? true,
        });
        if (mountedRef.current && !activeMoveRef.current) setError("");
      } catch (e) {
        if (mountedRef.current && !activeMoveRef.current) setError(e instanceof Error ? e.message : "Failed to stop PTZ movement");
      }
    },
    [api, camera.id, clearHeartbeat],
  );

  const stopActive = useCallback(
    (all = false): void => {
      const move = activeMoveRef.current;
      if (!move && !all) return;
      void sendStop(move, all);
    },
    [sendStop],
  );

  const sendMove = useCallback(
    async (move: ActiveMove): Promise<void> => {
      try {
        await api.movePtz(camera.id, { operation_id: move.operationId, ...move.vector });
        if (mountedRef.current && activeMoveRef.current === move) {
          setBusy(false);
          setError("");
        }
      } catch (e) {
        if (!mountedRef.current || activeMoveRef.current !== move) return;
        clearHeartbeat();
        activeMoveRef.current = null;
        if (mountedRef.current) {
          setBusy(false);
          setActiveLabel("");
          setZoomVelocity(0);
          setError(e instanceof Error ? e.message : "PTZ command failed");
        }
      }
    },
    [api, camera.id, clearHeartbeat],
  );

  const beginMove = useCallback(
    (vector: MoveVector, label: string): void => {
      const current = activeMoveRef.current;
      if (current) {
        void sendStop(current);
      }
      const move: ActiveMove = {
        operationId: operationId(),
        vector,
        panTilt: Boolean(vector.pan || vector.tilt),
        zoom: Boolean(vector.zoom),
      };
      activeMoveRef.current = move;
      setBusy(true);
      setActiveLabel(label);
      void sendMove(move);
      clearHeartbeat();
      heartbeatRef.current = window.setInterval(() => {
        const active = activeMoveRef.current;
        if (active) void sendMove(active);
      }, 400);
    },
    [clearHeartbeat, sendMove, sendStop],
  );

  const updateVelocityZoom = useCallback(
    (value: number): void => {
      setZoomVelocity(value);
      if (Math.abs(value) < 0.01) {
        stopActive();
        return;
      }
      const current = activeMoveRef.current;
      if (current?.zoom && !current.panTilt) {
        current.vector = { zoom: value };
        setActiveLabel(value > 0 ? "Zooming in" : "Zooming out");
        void sendMove(current);
        return;
      }
      beginMove({ zoom: value }, value > 0 ? "Zooming in" : "Zooming out");
    },
    [beginMove, sendMove, stopActive],
  );

  const flushZoomPosition = useCallback(async (): Promise<void> => {
    if (zoomPositionTimerRef.current !== null) {
      window.clearTimeout(zoomPositionTimerRef.current);
      zoomPositionTimerRef.current = null;
    }
    const value = pendingZoomPositionRef.current;
    pendingZoomPositionRef.current = null;
    if (value === null) return;
    const op = zoomPositionOperationRef.current ?? operationId();
    zoomPositionOperationRef.current = op;
    try {
      setBusy(true);
      await api.setPtzPosition(camera.id, { operation_id: op, zoom: value });
      if (mountedRef.current) {
        setBusy(false);
        setError("");
      }
    } catch (e) {
      if (mountedRef.current) {
        setBusy(false);
        setError(e instanceof Error ? e.message : "Zoom position failed");
      }
    }
  }, [api, camera.id]);

  const scheduleZoomPosition = useCallback(
    (value: number): void => {
      setZoomPosition(value);
      pendingZoomPositionRef.current = value;
      if (zoomPositionTimerRef.current === null) {
        zoomPositionTimerRef.current = window.setTimeout(() => {
          zoomPositionTimerRef.current = null;
          void flushZoomPosition();
        }, 120);
      }
    },
    [flushZoomPosition],
  );

  useEffect(() => {
    let current = true;
    mountedRef.current = true;
    setLoading(true);
    setCapabilities(null);
    setError("");
    void api
      .getPtzCapabilities(camera.id)
      .then((result) => {
        if (!current) return;
        setCapabilities(result);
        setZoomPosition(result.current.zoom ?? 0);
      })
      .catch((e) => {
        if (current) setError(e instanceof Error ? e.message : "PTZ is unavailable");
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
      const move = activeMoveRef.current;
      clearHeartbeat();
      activeMoveRef.current = null;
      if (move) void api.stopPtz(camera.id, { operation_id: move.operationId, pan_tilt: move.panTilt, zoom: move.zoom }).catch(() => undefined);
      if (zoomPositionTimerRef.current !== null) window.clearTimeout(zoomPositionTimerRef.current);
      mountedRef.current = false;
    };
  }, [api, camera.id, clearHeartbeat]);

  useEffect(() => {
    const onWindowBlur = (): void => {
      stopActive();
    };
    const onVisibilityChange = (): void => {
      if (document.hidden) stopActive();
    };
    window.addEventListener("blur", onWindowBlur);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("blur", onWindowBlur);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [stopActive]);

  const movementButtonProps = (vector: MoveVector, label: string) => ({
    onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      beginMove(vector, label);
    },
    onPointerUp: () => stopActive(),
    onPointerCancel: () => stopActive(),
    onLostPointerCapture: () => stopActive(),
    onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if ((event.key === "Enter" || event.key === " ") && !event.repeat) {
        event.preventDefault();
        beginMove(vector, label);
      }
    },
    onKeyUp: (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        stopActive();
      }
    },
  });

  if (loading) {
    return <section className="ptz-card ptz-card-loading">Loading ONVIF PTZ controls…</section>;
  }
  if (!capabilities || !capabilities.supported) {
    return isAdmin ? (
      <section className="ptz-card ptz-card-unavailable">
        <strong>ONVIF PTZ unavailable</strong>
        <span>{error || capabilities?.message || "The camera did not return usable PTZ capabilities."}</span>
      </section>
    ) : (
      <></>
    );
  }

  const hasPanTilt = capabilities.pan_tilt;
  const hasZoom = capabilities.zoom;
  const absoluteZoom = hasZoom && capabilities.modes.zoom.absolute;
  const layoutClass = hasPanTilt && hasZoom ? "has-ptz" : hasPanTilt ? "has-pt-only" : "has-zoom-only";

  return (
    <section className={`ptz-card ${layoutClass}`} aria-label={`PTZ controls for ${camera.label || camera.id}`}>
      <header className="ptz-card-header">
        <div>
          <strong>ONVIF PTZ</strong>
          <span>{capabilities.selected_profile_name || capabilities.selected_profile_token}</span>
        </div>
        <span className={`ptz-state ${error ? "is-error" : busy ? "is-busy" : ""}`} aria-live="polite">
          {error || activeLabel || (busy ? "Sending command…" : "Ready")}
        </span>
      </header>

      <div className="ptz-control-layout">
        {hasPanTilt && (
          <div className="ptz-pan-tilt">
            <div className="ptz-control-label">
              <strong>Pan / Tilt</strong>
              <span>{modeLabel(capabilities.modes.pan_tilt)}</span>
            </div>
            <div className="ptz-dpad" role="group" aria-label="Pan and Tilt direction">
              <button type="button" className="ptz-up" aria-label="Tilt up" {...movementButtonProps({ tilt: 1 }, "Tilting up")}>
                <ChevronUpIcon aria-hidden="true" />
              </button>
              <button type="button" className="ptz-left" aria-label="Pan left" {...movementButtonProps({ pan: -1 }, "Panning left")}>
                <ChevronLeftIcon aria-hidden="true" />
              </button>
              <button type="button" className="ptz-stop" aria-label="Stop all PTZ movement" onClick={() => stopActive(true)}>
                <StopIcon aria-hidden="true" />
              </button>
              <button type="button" className="ptz-right" aria-label="Pan right" {...movementButtonProps({ pan: 1 }, "Panning right")}>
                <ChevronRightIcon aria-hidden="true" />
              </button>
              <button type="button" className="ptz-down" aria-label="Tilt down" {...movementButtonProps({ tilt: -1 }, "Tilting down")}>
                <ChevronDownIcon aria-hidden="true" />
              </button>
            </div>
            <small>Press and hold a direction. Release to stop.</small>
          </div>
        )}

        {hasZoom && (
          <div className="ptz-zoom">
            <div className="ptz-control-label">
              <strong>Zoom</strong>
              <span>{absoluteZoom ? "Position" : "Velocity"}</span>
            </div>
            <div className="ptz-zoom-control">
              <MagnifyingGlassPlusIcon aria-hidden="true" />
              {absoluteZoom ? (
                <input
                  className="ptz-vertical-slider"
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={zoomPosition}
                  aria-label="Absolute zoom position"
                  aria-valuetext={`${Math.round(zoomPosition * 100)} percent`}
                  onPointerDown={() => {
                    zoomPositionOperationRef.current = operationId();
                  }}
                  onChange={(event) => scheduleZoomPosition(Number(event.target.value))}
                  onPointerUp={() => {
                    void flushZoomPosition();
                    zoomPositionOperationRef.current = null;
                  }}
                  onPointerCancel={() => {
                    void flushZoomPosition();
                    zoomPositionOperationRef.current = null;
                  }}
                />
              ) : (
                <input
                  className="ptz-vertical-slider ptz-velocity-slider"
                  type="range"
                  min="-1"
                  max="1"
                  step="0.05"
                  value={zoomVelocity}
                  aria-label="Zoom velocity"
                  aria-valuetext={zoomVelocity > 0 ? "Zooming in" : zoomVelocity < 0 ? "Zooming out" : "Stopped"}
                  onChange={(event) => updateVelocityZoom(Number(event.target.value))}
                  onPointerUp={() => stopActive()}
                  onPointerCancel={() => stopActive()}
                  onKeyUp={() => stopActive()}
                  onBlur={() => stopActive()}
                />
              )}
              <MagnifyingGlassMinusIcon aria-hidden="true" />
            </div>
            <output>{absoluteZoom ? `${Math.round(zoomPosition * 100)}%` : zoomVelocity === 0 ? "Center · stopped" : activeLabel}</output>
          </div>
        )}
      </div>
    </section>
  );
}
