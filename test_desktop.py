"""Hidden-window GUI lifecycle test using synthetic audio, not a physical microphone."""
import contextlib
import io
import time
import tkinter as tk
import urllib.request
from unittest.mock import patch

import desktop


def pump(root, condition, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(.02)
    raise AssertionError("Desktop state transition timed out")


def main():
    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = desktop.Desktop(root)
    real_serve = desktop.serve
    def serve(argv, **kwargs):
        return real_serve(argv + ["--test-tone", "--host", "127.0.0.1"], **kwargs)
    try:
        pump(root, lambda: bool(app.device_map))
        try:
            target = desktop.select_mic_output()
        except ValueError:
            target = None
        if target:
            import pyaudiowpatch as pa
            with pa.PyAudio() as audio:
                loopback = int(audio.get_wasapi_loopback_analogue_by_index(target["index"])["index"])
            previous = app.device.get()
            app.device.set(next(name for name, index in app.device_map.items() if index == loopback))
            app.mode.set("meeting")
            with patch.object(desktop, "microphone_access", return_value=True):
                app.start()
            assert app.state == "idle" and "feedback" in app.message.get()
            app.mode.set("listen")
            app.device.set(previous)
        with patch.object(desktop, "serve", serve), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                app.start()
                pump(root, lambda: app.state == "running")
                assert app.image is not None
                with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5) as response:
                    assert response.status == 200
                    response.read()
                app.stop()
                pump(root, lambda: app.state == "idle" and not app.worker.is_alive())
            app.start()
            app.stop()  # stop during startup, before ready callback
            pump(root, lambda: app.state == "idle" and not app.worker.is_alive())
        assert not errors, errors
        print("PASS: desktop device list, pairing QR, start/stop/restart and stop during startup")
    finally:
        app.stop()
        if app.worker:
            pump(root, lambda: not app.worker.is_alive())
        root.destroy()


if __name__ == "__main__":
    main()
