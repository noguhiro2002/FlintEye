# README assets

- `FlintEyeLogo.png`: original transparent PNG supplied by the project owner; preserved unchanged.
- `FlintEyeLogo-white.png`: opaque white-backed logo for dark backgrounds and previews that do not support theme selection.
- `getting-started.png`: real FlintEye first-run UI, captured at 1440×900.
- `getting-started.webm`: real browser recording of the five English tour steps.

The screenshots/video were captured using an isolated local profile with no cameras configured.
They contain no camera footage or real account credentials. Refresh them when the onboarding UI changes.
The README uses an inline GIF so GitHub readers can see all five steps without opening a video file view.

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

`getting-started.gif` is the five-step README animation (960 px wide, 8 fps). `getting-started.mp4` is the full-resolution H.264/yuv420p download, with metadata at the start for streaming. `getting-started.webm` remains the original recording; GitHub's file view does not embed it as a player. Both READMEs use the GIF and link to the MP4 download.
