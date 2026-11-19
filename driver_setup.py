"""Prepare the official driver; installation remains visible and user-confirmed."""
import os
from pathlib import Path
import tempfile
import urllib.request
import zipfile

URL = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack46.zip"


def prepare_installer():
    base = Path(os.environ["LOCALAPPDATA"]) / "WiFiAudio" / "driver"
    base.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="pack46-", dir=base))
    archive = destination / "driver.zip"
    with urllib.request.urlopen(URL, timeout=30) as response, archive.open("xb") as output:
        size = 0
        while data := response.read(65536):
            size += len(data)
            if size > 10 * 1024 * 1024:
                raise ValueError("Publisher package exceeds the expected 10 MB download limit.")
            output.write(data)
    with zipfile.ZipFile(archive) as package:
        total = sum(info.file_size for info in package.infolist())
        if total > 50 * 1024 * 1024:
            raise ValueError("Unexpected driver package size.")
        for info in package.infolist():
            resolved = (destination / info.filename).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe path in driver package.")
        package.extractall(destination)
    installer = destination / "VBCABLE_Setup_x64.exe"
    if not installer.is_file():
        raise ValueError("Publisher package did not contain the expected x64 installer.")
    return installer
