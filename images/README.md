# README assets

- `FlintEyeLogo.png`: original transparent PNG supplied by the project owner; preserved unchanged.
- `FlintEyeLogo-white.png`: opaque white-backed logo for dark backgrounds and previews that do not support theme selection.
- `getting-started.png`: real FlintEye first-run UI, captured at 1440×900.
- `getting-started.webm`: preserved original recording of the earlier interface.
- `getting-started-1.1.3.webm`: historical five-step UI tour, captured from the 1.1.3 source with monitoring controls and the 2026-11-15 QA fixes.

The `getting-started` screenshots/video show the built frontend with synthetic API responses and no cameras configured. They illustrate the guide, not actual installation, recording, shutdown or uninstall.
They contain no camera footage or real account credentials. Refresh them when the onboarding UI changes.
The README uses an inline GIF so GitHub readers can see all five steps without opening a video file view.

## Preview 10 screenshots

- `preview10/basic-cameras.png`: Basic camera setup in Preview 10.
- `preview10/recording-playback.png`: an event recording open in Preview 10’s playback dialog.

These screenshots accompany the [Preview 10 first-run guide (Japanese)](../docs/PREVIEW_10_FIRST_RUN.ja.md). They use synthetic footage. The first-run GIF and the 1.1.3 camera workflow above remain historical demonstrations; they do not show Preview 10’s Basic/Advanced settings, theme control or current navigation.

## Logo usage

Both READMEs use a `<picture>` element: light themes select the original transparent
logo, dark themes select the white-backed version. The fallback `<img>` also uses
the white-backed version so a renderer without `<picture>` support stays readable.
Desktop packaging continues to use the original transparent logo.

The white-backed variant was created from `FlintEyeLogo.png` using the built-in
image editor. The original asset was not overwritten.

Editing prompt: preserve the existing FlintEye wordmark, eye symbol, navy/green
palette, alignment and 3:1 composition; apply an opaque white background to the
canvas and transparent gaps; add no text, border, shadow or decorative elements.

## Playback formats

`getting-started.gif` is the five-step README animation (960 px wide, 8 fps). `getting-started.mp4` is the full-resolution H.264/yuv420p download, with metadata at the start for streaming. `getting-started-1.1.3.webm` is the source for the historical first-run GIF/MP4; `getting-started.webm` remains the earlier original; GitHub's file view does not embed it as a player. Both READMEs use the GIF and link to the MP4 download.

## Two-camera workflow and developer demonstrations

`camera-workflow-1.1.3.webm` is the screen-recording source for `camera-workflow.gif` and `camera-workflow.mp4`. The main README animation follows **Live View → Multiview → Recordings**, including live camera switching and actual recording playback. `camera-workflow-live.png`, `camera-workflow-multiview.png` and `camera-workflow-playback.png` show those screens.

`api-webrtc-1.1.3.webm` is the separate developer recording: Swagger's `GET /api/v1/viewer/cameras`, its response, and the returned WebRTC view. `api-webrtc.gif` is its preview and `api-webrtc.mp4` the full-resolution download. `api-webrtc-swagger.png` and `api-webrtc-live.png` are stills.

Captured on Linux from the 1.1.3 source with monitoring controls and the 2026-11-15 QA fixes, using the owner's two connected USB cameras pointed at desk clocks. Each camera produces 640×480 at 15 fps, Multiview is 1280×480, and browser capture is 1440×900. No audio, people, credentials or private camera URLs are included. GIFs are 960 px wide at 8 fps; MP4 uses H.264/yuv420p with fast-start metadata. These are short real-device demonstrations, not all-platform or long-run acceptance. The earlier first-run tour remains available separately.

The earlier `*-1.1.2.webm` recordings are preserved as historical sources. They do not show the new monitoring controls.
