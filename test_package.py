"""Exercise the packaged executable's pages, pairing and WebRTC using a test tone."""
import asyncio
import argparse
import re
import socket
from pathlib import Path

from aiohttp import ClientSession, ClientError
from playwright.async_api import async_playwright


async def main():
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path(__file__).parent / "dist/WiFiAudio/WiFiAudio.exe")
    exe = parser.parse_args().exe.resolve()
    process = await asyncio.create_subprocess_exec(
        str(exe), "--test-tone", "--no-browser", "--host", "127.0.0.1", "--port", str(port),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        async with ClientSession() as client:
            for _ in range(100):
                if process.returncode is not None:
                    raise RuntimeError((await process.stderr.read()).decode(errors="replace"))
                try:
                    async with client.get(base + "/pair") as response:
                        pairing = await response.text()
                        assert response.status == 200, pairing
                        break
                except ClientError:
                    await asyncio.sleep(.2)
            else:
                raise TimeoutError("Packaged sender did not start")
        token = re.search(r'#token=([A-Za-z0-9_-]+)', pairing).group(1)
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page()
                await page.goto(base + "/#token=" + token)
                await page.locator("#audio").evaluate("a => a.volume = 0")
                await page.locator("#connect").click()
                await page.wait_for_function("session && session.pc.connectionState === 'connected'", timeout=15000)
                await page.wait_for_function("document.querySelector('audio').currentTime > 0.2", timeout=15000)
                await page.locator("#stop").click()
                print("PASS: packaged EXE served QR/receiver and streamed test audio to Chrome")
            finally:
                await browser.close()
    finally:
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.wait(), 10)


if __name__ == "__main__":
    asyncio.run(main())
