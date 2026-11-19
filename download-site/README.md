# Public Windows download page

Production: https://wifiaudio-rishabh.pages.dev/

Build the Windows app with `Build.cmd`, then run
`.venv/Scripts/python.exe build_download.py` from the repository root.
Build.cmd bundles the GUI, audio runtime and dependency licenses in one EXE.
The download builder writes static assets into this directory's ignored `dist/`
folder. The EXE is split into 20 MiB assets because Cloudflare Pages limits individual
assets to 25 MiB. The browser verifies each part and saves one standalone EXE.

Check locally with `.venv/Scripts/python.exe test_download.py`. From this directory,
publish with `wrangler pages deploy dist --project-name wifiaudio-rishabh --branch main`.
Validate the public download using `test_download.py --url https://wifiaudio-rishabh.pages.dev/`.
Cloudflare login is required for deployment; credentials are not stored here.

The page hosts downloads only. It never captures microphone audio or connects to
the user's private app session. Private GitHub source visibility is unchanged.
