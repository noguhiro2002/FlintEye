# License and permitted uses

[日本語](LICENSING.ja.md)

[Documentation](README.md) · [Authoritative terms](../LICENSE)

FlintEye uses the Sustainable Use License 1.0 plus an explicit permission for internal use and paid services on customer-controlled infrastructure.
It is source available, not OSI-approved open-source software.

| Example | Permission |
| --- | --- |
| Monitor your home | Allowed |
| Internal use by a university, public research institute, nonprofit organization or company | Allowed |
| Individuals and organizations modify FlintEye for their own permitted use | Allowed |
| Charge for installation, configuration, modification, operation or maintenance on a customer's server or cloud account that the customer contracts for and controls | Allowed under the additional permission |
| Supply copies needed for those services without charging for FlintEye itself | Allowed; each recipient receives the license directly |
| Sell FlintEye, a modified version, or a bundled appliance whose price includes a FlintEye license | Separate permission required |
| Operate FlintEye as a paid hosted monitoring service for customers | Separate permission required |
| Redistribute third-party FFmpeg or MediaMTX independently | Their original licenses govern |

Service fees pay for the work performed, not for FlintEye or a modified version. A customer account in a provider's paid hosted service does not make that service customer-controlled infrastructure. The additional permission covers both nonprofit and for-profit customers, including individuals, universities, public research institutes and companies.

The English LICENSE file is authoritative. For uses outside its grant, contact the repository owner through the project's GitHub profile.

## Earlier versions

The first repository commit contained Apache-2.0 terms; later development removed that file while MIT wording remained in UI defaults.
The new terms apply prospectively to code the FlintEye licensor owns. They do not revoke rights already granted under Apache-2.0, MIT, or another license.
Retain applicable original notices for externally contributed or incorporated material.

## Third-party components

FlintEye launches FFmpeg and MediaMTX as separate executables through standard process/protocol interfaces.
The restriction on selling FlintEye does not restrict your rights to use, modify, reverse engineer, or redistribute those components under their own terms.

- MediaMTX: MIT; keep copyright and license notices.
- FFmpeg with libx264: GPL; provide the exact corresponding source, patches, configuration, and build instructions for the distributed binary.
- Python, Tcl/Tk, frontend dependencies, packaging runtimes, fonts, and native dependencies retain their own terms.

Release assets include notices and corresponding-source archives. An upstream homepage link alone is not a substitute for providing the required source.
Builds with FFmpeg `--enable-nonfree` are rejected.

Sources: [SUL](https://raw.githubusercontent.com/n8n-io/n8n/master/LICENSE.md), [FFmpeg](https://www.ffmpeg.org/legal.html), [MediaMTX](https://github.com/bluenviron/mediamtx/blob/main/LICENSE), [PyInstaller exception](https://pyinstaller.org/en/stable/license.html), [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0).
