"""Package a portable app and bounded-size assets for a static Cloudflare Pages site."""
import hashlib
import importlib.metadata as metadata
import json
import shutil
import zipfile
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent
APP = ROOT / "dist" / "WiFiAudio"
SITE = ROOT / "download-site" / "dist"
VERSION = "0.2.0-preview"


def main():
    if not (APP / "WiFiAudio.exe").is_file():
        raise SystemExit("Run Build.cmd before packaging the download.")
    for name in ("README.md", "Start-Meeting.cmd"):
        shutil.copy2(ROOT / name, APP / name)
    notices = APP / "THIRD_PARTY_LICENSES"
    notices.mkdir(exist_ok=True)
    pending = [Requirement(line).name for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip()]
    seen = set()
    summaries = []
    while pending:
        name = pending.pop()
        dist = metadata.distribution(name)
        canonical = dist.metadata["Name"]
        if canonical in seen:
            continue
        seen.add(canonical)
        summaries.append(f"{canonical} {dist.version}\n{dist.metadata.get('Home-page', '')}\n"
                         f"License: {dist.metadata.get('License-Expression') or dist.metadata.get('License', 'See package license files')}\n")
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target = notices / canonical / Path(str(entry))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        for value in dist.requires or []:
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    (notices / "PACKAGES.txt").write_text("\n".join(sorted(summaries)), encoding="utf-8")
    python_license = Path(__import__("sys").base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, notices / "PYTHON-LICENSE.txt")
    filename = f"WiFiAudio-{VERSION}-Windows-x64.zip"
    archive = ROOT / "dist" / filename
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(APP.rglob("*")):
            relative = path.relative_to(APP)
            if path.is_file() and ".local" not in relative.parts:
                output.write(path, Path("WiFiAudio") / relative)
    SITE.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "download.js", "_headers"):
        shutil.copy2(ROOT / "download-site" / name, SITE / name)
    payload = archive.read_bytes()
    parts = []
    for index, start in enumerate(range(0, len(payload), 20 * 1024 * 1024)):
        data = payload[start:start + 20 * 1024 * 1024]
        part = f"{filename}.part{index + 1}"
        (SITE / part).write_bytes(data)
        parts.append({"url": part, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"version": VERSION, "filename": filename, "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "parts": parts}
    (SITE / "download.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (SITE / "SHA256SUMS.txt").write_text(f"{manifest['sha256']}  {filename}\n", encoding="utf-8")
    print(f"Download ready: {archive} ({len(payload)} bytes, {len(parts)} static assets)")


if __name__ == "__main__":
    main()
