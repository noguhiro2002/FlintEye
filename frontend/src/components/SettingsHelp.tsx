import {
  Children,
  cloneElement,
  isValidElement,
  useId,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
} from "react";

const SETTING_HELP: Record<string, string> = {
  "App Title": "Name shown in the application header.",
  "Sidebar Title": "Name shown at the top of the navigation sidebar.",
  "Footer Text": "Text displayed in the footer on every page.",
  "API Host": "Network interface on which the Orchestrator API listens. Use 0.0.0.0 to listen on all interfaces.",
  "API Port": "TCP port used by the Orchestrator API.",
  "Auth Provider": "Authentication method used for administrator and viewer sessions.",
  "Session TTL (sec)": "How long an authenticated browser session remains valid.",
  "Session Cookie Name": "Browser cookie name used to store the authenticated session.",
  "Admin Username": "Local administrator account name. Administrators can change all settings.",
  "Viewer Username": "Local viewer account name. Viewers normally have read-only access.",
  "Snapshot Timeout (sec)": "Maximum time allowed when generating a snapshot before the request fails.",
  "Thumbnail Refresh Interval (sec)": "Default interval between Live View thumbnail updates.",
  "Log Directory": "Directory in which Orchestrator and FFmpeg log files are stored.",
  "Log Level": "Minimum severity written to logs. ERROR is quieter; INFO and DEBUG provide more detail.",
  "Log Retention": "How long rotated log files are retained. Leave empty to use the application default.",
  "Control Mode": "How MediaMTX is managed: as a system service, a direct child process, or externally.",
  "Service Name": "Operating-system service name used when MediaMTX control mode is service-based.",
  "RTSP Base URL": "Public RTSP address clients use to read camera and Multiview streams.",
  "Internal RTSP Base URL": "Loopback or private RTSP address used by FlintEye processes. This does not change public addresses.",
  "WebRTC Base URL": "Public MediaMTX WebRTC/WHEP address used by browser playback.",
  "Additional Record Paths": "Extra MediaMTX paths to record in addition to configured cameras.",
  "Recording folder": "Directory on the computer running FlintEye in which recording files are written.",
  "Record Format": "Container format used for recording segments.",
  "Segment Duration": "Target duration of each completed recording segment.",
  "Recording Delete After": "Retention period after which completed recordings are deleted.",
  "Playback Cache Delete After": "Retention period for temporary files created for browser playback.",
  "Record Part Duration": "Duration of smaller parts MediaMTX uses while a segment is being written.",
  "Record Max Part Size": "Maximum size allowed for an in-progress recording part.",
  "Multiview Enabled": "Starts or stops only the Multiview compositor. Public camera relays are not restarted.",
  "Source Mode": "Where Multiview obtains its input list.\n\nOptions:\n- hybrid: combine selected paths with MediaMTX discovery.\n- env: use only explicitly selected/saved paths.\n- api: use paths discovered through the MediaMTX API.",
  "MediaMTX API URL": "MediaMTX control API used to discover paths and monitor Publisher and Reader state.",
  "Output Prefix": "Prefix for generated Multiview paths, for example multiview_1.",
  "Extra Source Paths": "Additional MediaMTX paths not represented by a configured camera.",
  "Tile Count": "Maximum number of input tiles placed in one Multiview output.",
  "Max Sources": "Maximum number of sources Multiview accepts after filtering.",
  "Default IP Input": "Default route for IP cameras that use 'Use Multiview default'.\n\nOptions:\n- Primary: read the existing public camera path directly; recommended with raw synchronized composition because that worker already decodes into its frame ring.\n- Normalize existing primary: create a private CFR/re-encoded path first; no extra camera connection, but adds a redundant H.264 encode, RTSP hop, and decode.\n- ONVIF: use a selected camera profile, usually a low-resolution substream; adds a second camera RTSP connection.\n- Manual: use an explicitly entered secondary RTSP URL; usually adds a second camera connection.",
  "Enable synchronized raw composition": "Each source gets an independent decoder and bounded raw-frame ring. One server-wall-clock target is selected for every tile, the complete canvas is assembled in memory, and only that canvas is H.264 encoded. A failed source reconnects independently and cannot close the other inputs.",
  "Normalized Input FPS": "Default fixed frame rate for normalized, ONVIF, and manual Multiview inputs.",
  "Normalized Resolution": "Default output size of a normalized input. Auto uses the target tile size without upscaling.",
  "Normalized Input Quality": "Default quality profile for normalized Multiview inputs.",
  "FPS": "Fixed output frame rate of the final Multiview stream. New configurations default to 10 fps.",
  "Quality Preset": "Multiview output quality/resource profile.\n\nOptions:\n- high: higher quality and resource/bandwidth use.\n- standard: balanced default.\n- low: lower bitrate/resource use and reduced detail.",
  "Encoder": "Video encoder used for the final Multiview stream.\n\nTypical options:\n- auto: select a supported encoder automatically.\n- libx264: CPU-based H.264; broadly compatible.\n- h264_qsv/NVENC/VideoToolbox: hardware H.264 when supported.",
  "Latency Preset": "Buffering versus latency policy.\n\nOptions:\n- low: minimal buffering and lower delay, but less tolerant of Wi-Fi jitter.\n- normal: more buffering and better tolerance of arrival variation.",
  "Input Stall Timeout (sec)": "Steady-state period without progress before an input is stalled. Startup receives a separate input-count-based allowance.",
  "Input Stall Option": "FFmpeg RTSP timeout mechanism.\n\nOptions:\n- auto: choose an option supported by the installed RTSP demuxer.\n- timeout/stimeout/rw_timeout: force that FFmpeg option.\n- none: disable FFmpeg socket timeout and rely on external health monitoring.",
  "Input Queue": "Frames buffered for each Multiview input to absorb short network-arrival variations.",
  "Sync delay (sec)": "Common presentation delay. Every input worker selects the newest frame at or before server wall-clock minus this value. 3 seconds is recommended for Wi-Fi cameras.",
  "Buffer capacity (sec)": "Wall-clock ring-buffer retention per camera. It must be at least as large as Sync delay. 5 seconds is the recommended starting value.",
  "Sync / output FPS": "Frame rate used for raw-frame selection, canvas composition, and the final Multiview output. 10 fps is normally sufficient and limits memory and CPU use.",
  "Late frame policy": "Behavior when the target wall-clock frame is missing.\n\nOptions:\n- Hold last frame, then No Stream: keep the most recent frame up to Maximum hold.\n- Show No Stream immediately: replace the tile as soon as no target frame is available.",
  "Buffer width": "Width decoded into each in-memory RGB ring buffer. 640 is recommended for a 1920x1080 Multiview grid.",
  "Buffer height": "Height decoded into each in-memory RGB ring buffer. 360 is recommended for a 16:9 Multiview tile.",
  "Maximum hold (sec)": "How long the last delayed frame remains visible during a camera outage before the worker outputs No Stream.",
  "Memory limit / input (MB)": "Hard limit used to reduce the number of RGB frames retained by each camera worker. 640x360 at 10 fps for 5 seconds needs about 35 MB.",
  "Source reconnect (sec)": "Delay before one input decoder reconnects to its MediaMTX source. Other tiles and the final compositor continue during this retry.",
  "Maxrate": "Maximum instantaneous encoder bitrate.",
  "Buffer Size": "Rate-control buffer size. A larger buffer tolerates bitrate bursts but can add latency.",
  "Health Check / Isolation / Retry": "Input check interval, repeated-failure isolation threshold, and retry interval for isolated inputs.",
  "Input RTSP Base URL": "MediaMTX RTSP address from which the Multiview compositor reads inputs.",
  "Output RTSP Base URL": "MediaMTX RTSP address to which the Multiview compositor publishes outputs.",
  "Grid Columns": "Number of columns in the automatically generated Multiview tile layout.",
  "Restart Interval (sec)": "Optional maintenance interval between scheduled Multiview restarts.",
  "Restart Offset (sec)": "Offset used to place maintenance restarts away from recording boundaries.",
  "Camera Name": "Human-readable name used in Live View and Multiview labels.",
  "Path": "MediaMTX path name. Changing it changes the public RTSP and WebRTC addresses.",
  "Profile": "Saved UVC capture profile used for this camera.",
  "Supported Mode": "Resolution and frame-rate mode exposed by the selected UVC device.",
  "Width": "Captured video width in pixels.",
  "Height": "Captured video height in pixels.",
  "Bitrate": "Target video bitrate. Higher values improve quality but increase bandwidth and storage use.",
  "Display Name": "Human-readable IP camera name displayed throughout the UI.",
  "MediaMTX Path": "Public path used for this individual camera's RTSP and WebRTC output.",
  "Source URL": "Camera RTSP source address. Credentials are used by the backend and are not included in public URLs.",
  "ONVIF discovery": "How ONVIF information is obtained.\n\nOptions:\n- Auto detect: discover a matching device and also try the Source URL host.\n- Manual address: use the entered Device Service URL.\n- Disabled: do not contact ONVIF; RTSP relay still works.",
  "ONVIF device service address": "Manual ONVIF Device Service URL, usually ending in /onvif/device_service.",
  "ONVIF Username": "ONVIF account name. When empty, Source URL credentials are reused where possible.",
  "ONVIF Password": "ONVIF account password. When empty, Source URL credentials are reused where possible.",
  "Control access": "Who may operate this camera's PTZ controls.\n\nOptions:\n- Admin only: only administrators can move the camera.\n- Admin + Viewer: authenticated viewers may also operate PTZ.\nPublic viewers are always denied.",
  "Pan / Tilt speed": "Normalized speed used by ContinuousMove Pan and Tilt operations.",
  "Zoom speed": "Normalized speed used by continuous Zoom operations.",
  "Relative step": "Normalized distance used when the camera supports RelativeMove.",
  "Input mode": "Route used only by Multiview. The public individual camera RTSP/WebRTC path never changes.\n\nOptions:\n- Use Multiview default: inherit the global Default IP Input setting.\n- Primary path: read the existing public MediaMTX path directly; lowest extra CPU.\n- Normalize existing primary path: decode/re-encode the existing public path to a private CFR stream. It does not add a camera connection, but adds CPU and does not by itself isolate the final compositor.\n- ONVIF substream: use a selected ONVIF profile, typically a smaller stream; adds a second camera RTSP connection.\n- Manual substream URL: use an entered RTSP URL; usually adds a second camera connection.",
  "ONVIF media profile": "ONVIF stream profile used for the Multiview-only secondary connection.",
  "Manual RTSP URL": "Explicit secondary RTSP source used only when Multiview input mode is Manual.",
  "FPS override": "Per-camera Multiview frame-rate override. Leave empty to inherit the global default.",
  "Resolution override": "Per-camera size such as 640x360. Leave empty or use auto for tile-aware sizing.",
  "Quality override": "Per-camera normalized-stream quality.\n\nOptions:\n- Inherit: use the global Normalized Input Quality.\n- high: retain more detail with higher bitrate/CPU.\n- standard: balanced default.\n- low: reduce bitrate and resource use.",
  "thread queue": "Per-camera FFmpeg input queue override. Leave empty to inherit the Multiview default.",
  "stall timeout": "Per-camera RTSP stall timeout override. Leave empty to inherit the Multiview default.",
  "Timestamp mode": "How the main public camera relay handles timestamps.\n\nOptions:\n- Auto: probe timing and choose Source or Wall-clock/CFR policy.\n- Source: preserve camera timestamps; lowest intervention, suitable only for well-behaved cameras.\n- Wall-clock: replace timestamps using arrival time without video re-encoding; recommended for unstable camera timestamps.\n- CFR: decode and re-encode at a fixed FPS; strongest normalization and highest CPU cost.",
  "Relay mode": "How the main public camera video is published.\n\nOptions:\n- Copy: preserve the camera H.264 stream; lowest CPU and no generation loss.\n- libx264: decode and re-encode; higher CPU, but can normalize codec/bitstream compatibility.\nWall-clock + Copy can repair timestamps without re-encoding.",
  "CFR FPS": "Fixed output frame rate used only when Timestamp mode is CFR.",
  "Interval / Timeout / Failures": "Snapshot watchdog check interval, per-check timeout, and consecutive failure threshold.",
  "GOP": "Distance between keyframes. Smaller values improve seek and recovery but increase bitrate.",
  "Preset": "x264 speed/quality trade-off. Faster presets reduce CPU use but compress less efficiently.",
};

function HelpTip({ label, text }: { label: string; text: string }): JSX.Element {
  const id = useId();
  const [open, setOpen] = useState(false);

  const toggle = (event: MouseEvent<HTMLSpanElement>): void => {
    event.preventDefault();
    event.stopPropagation();
    setOpen((value) => !value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLSpanElement>): void => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      setOpen((value) => !value);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <span
      className={`setting-help${open ? " is-open" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`Help for ${label}`}
      aria-describedby={id}
      aria-expanded={open}
      onMouseDown={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      onClick={toggle}
      onKeyDown={onKeyDown}
      onBlur={() => setOpen(false)}
    >
      <span aria-hidden="true">?</span>
      <span id={id} className="setting-help-popup" role="tooltip">
        <strong>{label}</strong>
        {text}
      </span>
    </span>
  );
}

function normalizedText(node: ReactNode): string | null {
  if (typeof node !== "string") {
    return null;
  }
  const value = node.replace(/\s+/g, " ").trim();
  return value || null;
}

function enrichNode(node: ReactNode): ReactNode {
  if (!isValidElement(node)) {
    return node;
  }
  const element = node as ReactElement<{ children?: ReactNode; className?: string }>;
  const children = Children.toArray(element.props.children);
  const isLabel = element.type === "label";
  const labelIndex = isLabel ? children.findIndex((child) => normalizedText(child) !== null) : -1;
  const label = labelIndex >= 0 ? normalizedText(children[labelIndex]) : null;
  const help = label ? SETTING_HELP[label] : undefined;
  const enrichedChildren: ReactNode[] = [];

  children.forEach((child, index) => {
    if (help && label && index === labelIndex) {
      enrichedChildren.push(
        <span className="setting-label-title" key={`title-${label}`}>
          {child}
          <HelpTip label={label} text={help} />
        </span>,
      );
    } else {
      enrichedChildren.push(enrichNode(child));
    }
  });

  const className = element.props.className;
  if (children.length === 0) {
    return cloneElement(element, { className });
  }
  return cloneElement(element, { className }, enrichedChildren);
}

export function SettingsHelp({ children }: { children: ReactNode }): JSX.Element {
  return <>{enrichNode(children)}</>;
}
