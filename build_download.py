"""Package a portable app and bounded-size assets for a static Cloudflare Pages site."""
import hashlib
import argparse
import importlib.metadata as metadata
import json
import shutil
import io
import zipfile
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "download-site" / "dist"
VERSION = "0.1.1-restored"


def prepare_licenses():
    notices = ROOT / ".local" / "licenses"
    notices.mkdir(parents=True, exist_ok=True)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--licenses-only", action="store_true")
    parser.add_argument("--app-directory", type=Path, default=ROOT / "dist" / "WiFiAudio")
    args = parser.parse_args()
    if args.licenses_only:
        prepare_licenses()
        return
    filename = f"WiFiAudio-{VERSION}-Windows-x64.zip"
    executable = args.app_directory / "WiFiAudio.exe"
    if not executable.is_file():
        raise SystemExit("Run Build.cmd before packaging the download.")
    SITE.mkdir(parents=True, exist_ok=True)
    # These files are generated release parts, never user data or configuration.
    for old_part in SITE.glob("WiFiAudio-*-Windows-x64.*.part*"):
        if old_part.is_file() and old_part.parent.resolve() == SITE.resolve():
            old_part.unlink()
    for name in ("index.html", "download.js", "_headers"):
        shutil.copy2(ROOT / "download-site" / name, SITE / name)
    shutil.copy2(ROOT / "LICENSE", SITE / "LICENSE.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", SITE / "THIRD_PARTY_NOTICES.txt")
    if not (args.app_directory / "_internal" / "python310.dll").is_file():
        raise SystemExit("The portable app must include its _internal runtime directory.")
    prepare_licenses()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for source in sorted(args.app_directory.rglob("*")):
            if source.is_file():
                bundle.write(source, Path("WiFiAudio") / source.relative_to(args.app_directory))
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
            bundle.write(ROOT / name, "WiFiAudio/" + name)
        for source in sorted((ROOT / ".local" / "licenses").rglob("*")):
            if source.is_file():
                bundle.write(source, Path("WiFiAudio/THIRD_PARTY_LICENSES") / source.relative_to(ROOT / ".local/licenses"))
    payload = archive.getvalue()
    parts = []
    for index, start in enumerate(range(0, len(payload), 20 * 1024 * 1024)):
        data = payload[start:start + 20 * 1024 * 1024]
        part = f"{filename}.part{index + 1}"
        (SITE / part).write_bytes(data)
        parts.append({"url": part, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"version": VERSION, "filename": filename, "mime": "application/zip", "bytes": len(payload),
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "sha256": hashlib.sha256(payload).hexdigest(), "parts": parts}
    (SITE / "download.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (SITE / "SHA256SUMS.txt").write_text(f"{manifest['sha256']}  {filename}\n", encoding="utf-8")
    print(f"Download ready: {executable} ({len(payload)} bytes, {len(parts)} static assets)")


if __name__ == "__main__":
    main()
