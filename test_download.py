import asyncio
import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from aiohttp import web
from playwright.async_api import async_playwright, expect


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Verify a deployed download site instead of localhost")
    args = parser.parse_args()
    root = Path(__file__).parent
    site = root / "download-site/dist"
    manifest = json.loads((site / "download.json").read_text())
    app = web.Application()
    async def index(request):
        return web.FileResponse(site / "index.html")
    app.router.add_get("/", index)
    app.router.add_static("/", site)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page(viewport={"width": 390, "height": 844}, accept_downloads=True)
                await page.goto(args.url or f"http://127.0.0.1:{runner.addresses[0][1]}/")
                await expect(page.locator("#download")).to_be_enabled(timeout=15000)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                async with page.expect_download(timeout=60000) as event:
                    await page.locator("#download").click()
                download = await event.value
                assert download.suggested_filename == manifest["filename"]
                with tempfile.TemporaryDirectory() as directory:
                    archive = Path(directory) / "download.zip"
                    await download.save_as(archive)
                    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["sha256"]
                    with zipfile.ZipFile(archive) as contents:
                        names = contents.namelist()
                        assert "WiFiAudio/WiFiAudio.exe" in names
                        assert "WiFiAudio/Start-Meeting.cmd" in names
                        assert "WiFiAudio/_internal/python310.dll" in names
                        assert not any("/.local/" in name or name.endswith(".key") for name in names)
                        assert contents.testzip() is None
                await page.screenshot(path=str(root / "download-preview.png"), full_page=True)
                print("PASS: mobile layout, browser download, complete ZIP checksum, required runtime and no private keys")
            finally:
                await browser.close()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
