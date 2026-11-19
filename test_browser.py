"""Actual Chromium receiver test with synthetic audio; no system capture."""
import asyncio
from pathlib import Path

from aiohttp import web
from playwright.async_api import async_playwright

from audio import ToneTrack
from server import AudioServer


async def main():
    server = AudioServer(ToneTrack, token="browser-test-only")
    runner = web.AppRunner(server.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    base = f"http://127.0.0.1:{port}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page(viewport={"width": 390, "height": 844})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(base)
                assert await page.locator("#connect").is_disabled()
                # Explicit full navigation to a fresh page, as a QR launch does.
                await page.goto("about:blank")
                await page.goto(base + "/#token=" + server.token)
                await page.locator("#audio").evaluate("a => a.volume = 0")
                for _ in range(2):
                    await page.locator("#connect").click()
                    await page.wait_for_function("session && session.pc.connectionState === 'connected'", timeout=15000)
                    await page.wait_for_function("document.querySelector('audio').currentTime > 0.1", timeout=15000)
                    await page.wait_for_function("""async () => {
                        const reports = await session.pc.getStats();
                        return [...reports.values()].some(s => s.type === 'inbound-rtp' && s.totalSamplesReceived > 0);
                    }""", timeout=15000)
                    stats = await page.evaluate("""async () => {
                      const reports = await session.pc.getStats();
                      return [...reports.values()].filter(s => s.type === 'inbound-rtp').map(s => ({
                        bytesReceived:s.bytesReceived, packetsReceived:s.packetsReceived,
                        totalSamplesReceived:s.totalSamplesReceived
                      }));
                    }""")
                    assert stats and stats[0]["bytesReceived"] > 0, stats
                    print("Chromium decoded incoming audio:", stats)
                    await page.locator("#stop").click()
                    await page.wait_for_function("session === null")
                    for _ in range(100):
                        if server.active is None:
                            break
                        await asyncio.sleep(.01)
                    assert server.active is None
                await page.screenshot(path=str(Path(__file__).parent / "receiver-preview.png"), full_page=True)
                assert not errors, errors
                print("PASS: pairing, real Chromium playback, disconnect and reconnect; no JavaScript errors")
            finally:
                await browser.close()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
