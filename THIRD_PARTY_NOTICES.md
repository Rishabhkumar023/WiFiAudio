# Third-party rights and distribution review

The [WiFiAudio license](LICENSE) covers only the original WiFiAudio materials.
It does not claim ownership of dependencies or replace their licenses. Third-party
license texts and package versions are collected by `build_download.py` and
included in download ZIPs under `THIRD_PARTY_LICENSES`.

The original WiFiAudio materials are maintained by Rishabh Kumar
(@Rishabhkumar023). This notice does not claim exclusive ownership of software
ideas, third-party code, or material that applicable law does not protect.

## Observations on the existing Windows preview

On 20 November 2026, the installed PyAV 17.1.0 package identified its Python
wrapper as BSD-3-Clause. Its bundled FFmpeg `avcodec`, `avformat`, `avfilter`,
`avutil` and `swresample` DLLs reported **LGPL version 3 or later** through their
runtime license functions. The wheel also contains separate codec libraries,
including libx264 and libx265. A Python package's metadata alone is therefore
not a complete license inventory of its native binary dependencies.

The repository's existing notice collector copies available license files; that
does **not** establish satisfaction of every native-library requirement. Matching
source availability, the actual codec-library licensing, and replacement/relinking
requirements for binary packaging (including the previous single-EXE release) have not been fully verified. A complete
binary-distribution review remains necessary before describing this bundle as
legally cleared for proprietary distribution. The original-materials license must
not be presented as prohibiting rights granted by the bundled libraries.

Relevant primary references:

- [FFmpeg licensing and compliance checklist](https://ffmpeg.org/legal.html)
- [GNU LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html)
- [PyAV](https://github.com/PyAV-Org/PyAV)
- [VB-CABLE publisher and licensing](https://vb-audio.com/Cable/)

The restored listening release does not install or download VB-CABLE. Earlier meeting releases offered its separate setup. Its publisher
owns it and supplies the governing terms. WiFiAudio's license does not license it.
