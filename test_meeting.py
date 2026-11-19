"""HTTPS, browser mic lifecycle, return-audio and muted-sample checks (synthetic mic)."""
import asyncio
import argparse
from array import array
from collections import deque
import ssl
import tempfile
from pathlib import Path

from aiohttp import web, ClientSession, TCPConnector
from playwright.async_api import async_playwright

from audio import ToneTrack, MicrophoneOutput, select_mic_output
from local_tls import prepare_tls
from server import AudioServer


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-cable", action="store_true", help="Verify installed CABLE Output with synthetic browser microphone")
    args = parser.parse_args()
    sinks = []
    levels = deque(maxlen=50)
    capture = None
    pa = None
    output_device = select_mic_output() if args.real_cable else None
    if args.real_cable:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        host = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
        inputs = [d for i in range(pa.get_device_count())
                  if (d := pa.get_device_info_by_index(i))["hostApi"] == host
                  and d["name"] == "CABLE Output (VB-Audio Virtual Cable)" and d["maxInputChannels"] > 0]
        assert len(inputs) == 1, "Expected installed CABLE Output recording endpoint"
        device = inputs[0]
        def callback(data, count, timing, status):
            values = array("h", data)
            levels.append(max((abs(v) for v in values), default=0))
            return (None, pyaudio.paContinue)
        capture = pa.open(format=pyaudio.paInt16, channels=2, rate=int(device["defaultSampleRate"]),
                          input=True, input_device_index=int(device["index"]), frames_per_buffer=960,
                          stream_callback=callback)
    class Sink:
        name = "Test virtual microphone"
        loopback_index = -2
        def __init__(self):
            self.count = 0
            self.closed = False
            self.real = MicrophoneOutput(output_device["index"]) if output_device else None
        def write(self, frame):
            self.count += 1
            if self.real:
                self.real.write(frame)
        def close(self):
            self.closed = True
            if self.real:
                self.real.close()
    def factory():
        sink = Sink()
        sinks.append(sink)
        return sink

    with tempfile.TemporaryDirectory() as directory:
        context, ca, fingerprint = prepare_tls(Path(directory), ["127.0.0.1"])
        old = ca.read_bytes()
        prepare_tls(Path(directory), ["127.0.0.1"])
        assert ca.read_bytes() == old, "Repeated startup must preserve CA trust"
        server = AudioServer(ToneTrack, "meeting-test", sink_factory=factory)
        runner = web.AppRunner(server.app())
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context).start()
        port = runner.addresses[0][1]
        base = f"https://127.0.0.1:{port}"
        try:
            trust = ssl.create_default_context(cafile=str(ca))
            async with ClientSession(connector=TCPConnector(ssl=trust)) as client:
                async with client.get(base) as response:
                    assert response.status == 200
            async with async_playwright() as p:
                # This context bypass is ONLY for this synthetic browser test; Android
                # users must install/trust their generated CA instead.
                browser = await p.chromium.launch(channel="chrome", headless=True,
                    args=["--use-fake-device-for-media-stream"])
                try:
                    browser_context = await browser.new_context(ignore_https_errors=True, permissions=["microphone"])
                    page = await browser_context.new_page()
                    await page.goto(base + "/#token=meeting-test")
                    await page.locator("#audio").evaluate("a => a.volume = 0")
                    await page.locator("#use-mic").check()
                    for _ in range(2):
                        await page.locator("#connect").click()
                        await page.wait_for_function("session && session.pc.connectionState === 'connected'", timeout=15000)
                        await page.wait_for_function("document.querySelector('#mic-status').textContent.includes('Reaching desktop')", timeout=15000)
                        await page.wait_for_function("document.querySelector('audio').currentTime > 0.1", timeout=15000)
                        assert sinks[-1].count > 0
                        if args.real_cable:
                            levels.clear()
                            await asyncio.sleep(1)
                            assert max(levels, default=0) > 500, list(levels)
                            print("CABLE Output received browser microphone; peak:", max(levels))
                        await page.locator("#mute").click()
                        assert await page.evaluate("session.media.getAudioTracks()[0].enabled === false")
                        if args.real_cable:
                            await asyncio.sleep(1)
                            levels.clear()
                            await asyncio.sleep(.5)
                            assert levels and max(levels) < 100, list(levels)
                            print("CABLE Output muted; peak:", max(levels))
                        await page.locator("#mute").click()
                        assert await page.evaluate("session.media.getAudioTracks()[0].enabled === true")
                        await page.evaluate("window.savedMic = session.media.getAudioTracks()[0]")
                        await page.locator("#stop").click()
                        assert await page.evaluate("window.savedMic.readyState === 'ended'")
                        for _ in range(100):
                            if server.active is None:
                                break
                            await asyncio.sleep(.01)
                        assert sinks[-1].closed
                    # Browser permission refusal must release the server listener slot.
                    await browser_context.clear_permissions()
                    await page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Permission denied', 'NotAllowedError'); }; }")
                    await page.locator("#connect").click()
                    await page.wait_for_function("document.querySelector('#status').textContent.includes('Permission denied')")
                    print("PASS: verified TLS chain, persistent CA, bidirectional browser media, mute/unmute, reconnect, mic-track cleanup and denied permission")
                finally:
                    await browser.close()
        finally:
            await runner.cleanup()
            if capture:
                capture.close()
            if pa:
                pa.terminate()
        assert all(s.closed for s in sinks)


if __name__ == "__main__":
    asyncio.run(main())
