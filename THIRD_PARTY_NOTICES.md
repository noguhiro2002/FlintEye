# Third-party components

FlintEye's own license does not replace the licenses of the components below.
Redistributed artifacts contain a `licenses` directory and a versioned inventory. Consult those for the exact build.

| Component | Purpose | Upstream |
| --- | --- | --- |
| FFmpeg / FFprobe, including libx264 | Capture, encode, probe and convert video | https://ffmpeg.org/ |
| MediaMTX | Media transport and recording | https://github.com/bluenviron/mediamtx |
| HLS.js | MediaMTX's embedded browser playback | https://github.com/video-dev/hls.js |
| FreeType / HarfBuzz | Text rendering in FFmpeg | https://freetype.org/ · https://harfbuzz.github.io/ |
| CPython / Tcl/Tk | Application runtime and native dialogs | https://www.python.org/ · https://www.tcl.tk/ |
| PyInstaller | Runtime packaging, with distribution exception | https://pyinstaller.org/en/stable/license.html |
| React, Heroicons and other npm packages | Browser interface | See frontend package lock and bundled notices |
| FastAPI, Uvicorn, ONVIF and other Python packages | Server and camera control | See pinned requirements and bundled notices |

FFmpeg builds use GPL-enabled libx264 and must not enable nonfree components.
Each release includes corresponding source archives, patches and build instructions.
Source archives and license texts must remain downloadable alongside the binaries, including older releases.
For container images, retain the image's Debian copyright files and the corresponding source archive published with the release.

See [licensing guidance](docs/LICENSING.md) and [release checks](docs/RELEASING.md).
