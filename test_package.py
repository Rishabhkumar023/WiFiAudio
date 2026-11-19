"""Exercise the packaged executable's pages, pairing and WebRTC using a test tone."""
import asyncio
import argparse
import re
import socket
import tempfile
from pathlib import Path

from aiohttp import ClientSession, ClientError
from playwright.async_api import async_playwright
import psutil
from process_test_utils import stop_owned_process


async def main():
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path(__file__).parent / "dist/WiFiAudio.exe")
    parser.add_argument("--meeting", action="store_true", help="Test packaged HTTPS and real virtual-cable rendering")
    args = parser.parse_args()
    exe = args.exe.resolve()
    tls = tempfile.TemporaryDirectory()
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        pair_port = reserve.getsockname()[1]
    extra = ["--meeting", "--pair-port", str(pair_port), "--tls-dir", tls.name] if args.meeting else []
    process = await asyncio.create_subprocess_exec(
        str(exe), "--test-tone", "--no-browser", "--host", "127.0.0.1", "--port", str(port),
        *extra,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    owned = psutil.Process(process.pid)
    try:
        base = f"{'https' if args.meeting else 'http'}://127.0.0.1:{port}"
        pairing_base = f"http://127.0.0.1:{pair_port}" if args.meeting else base
        async with ClientSession() as client:
            for _ in range(100):
                if process.returncode is not None:
                    raise RuntimeError((await process.stderr.read()).decode(errors="replace"))
                try:
                    async with client.get(pairing_base + "/pair") as response:
                        pairing = await response.text()
                        assert response.status == 200, pairing
                        break
                except ClientError:
                    await asyncio.sleep(.2)
            else:
                raise TimeoutError("Packaged sender did not start")
        token = re.search(r'#token=([A-Za-z0-9_-]+)', pairing).group(1)
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True,
                args=["--use-fake-device-for-media-stream"] if args.meeting else [])
            try:
                page = await browser.new_page(ignore_https_errors=args.meeting,
                    permissions=["microphone"] if args.meeting else [])
                await page.goto(base + "/#token=" + token)
                await page.locator("#audio").evaluate("a => a.volume = 0")
                if args.meeting:
                    await page.locator("#use-mic").check()
                await page.locator("#connect").click()
                await page.wait_for_function("session && session.pc.connectionState === 'connected'", timeout=15000)
                await page.wait_for_function("document.querySelector('audio').currentTime > 0.2", timeout=15000)
                if args.meeting:
                    await page.wait_for_function("document.querySelector('#mic-status').textContent.includes('Reaching desktop')", timeout=15000)
                await page.locator("#stop").click()
                print("PASS: packaged EXE served QR/receiver and streamed test audio to Chrome" +
                      ("; HTTPS microphone returned to real VB-CABLE" if args.meeting else ""))
            finally:
                await browser.close()
    finally:
        if process.returncode is None:
            await asyncio.to_thread(stop_owned_process, owned)
        await asyncio.wait_for(process.wait(), 10)
        tls.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
