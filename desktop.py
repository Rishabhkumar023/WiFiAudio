"""Single-window launcher. The GUI owns and stops its in-process audio service."""
import io
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

import qrcode
from PIL import ImageTk

from audio import list_outputs, select_mic_output
from server import main as serve

ROOT = Path(__file__).resolve().parent


def microphone_access():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone") as key:
            if winreg.QueryValueEx(key, "Value")[0] == "Deny":
                return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged") as key:
            if winreg.QueryValueEx(key, "Value")[0] == "Deny":
                return False
        return True
    except OSError:
        return None


class Desktop:
    def __init__(self, root):
        self.root = root
        root.title("WiFiAudio")
        root.geometry("780x760")
        root.minsize(640, 700)
        root.configure(bg="#10151d")
        self.events = queue.Queue()
        self.worker = None
        self.installer = None
        self.stop_event = None
        self.server = None
        self.closing = False
        self.state = "idle"
        self.mode = tk.StringVar(value="listen")
        self.device = tk.StringVar()
        self.network = tk.StringVar()
        self.message = tk.StringVar(value="Choose a mode, then connect your phone.")
        self.health = tk.StringVar(value="Checking Windows audio…")
        self.image = None
        self.device_map = {}
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#10151d")
        style.configure("TLabel", background="#10151d", foreground="#edf3f8", font=("Segoe UI", 11))
        style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
        style.configure("TButton", font=("Segoe UI", 11), padding=(12, 8))
        style.configure("TRadiobutton", background="#10151d", foreground="#edf3f8", font=("Segoe UI", 12))
        body = ttk.Frame(root, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="WiFiAudio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Your Windows audio. Your phone. Your earphones.").pack(anchor="w", pady=(0, 16))
        modes = ttk.Frame(body)
        modes.pack(fill="x")
        self.radios = [ttk.Radiobutton(modes, text=label, value=value, variable=self.mode, command=self.mode_changed)
                       for label, value in (("Listen to PC audio", "listen"), ("Listen + speak in meetings", "meeting"))]
        for radio in self.radios:
            radio.pack(side="left", padx=(0, 22))
        ttk.Label(body, text="Windows audio to send (use normal speakers / HDMI for meetings)").pack(anchor="w", pady=(16, 4))
        self.devices = ttk.Combobox(body, textvariable=self.device, state="readonly", font=("Segoe UI", 10))
        self.devices.pack(fill="x")
        self.meeting_panel = ttk.Frame(body)
        ttk.Label(self.meeting_panel, textvariable=self.health, wraplength=700).pack(anchor="w", pady=6)
        setup = ttk.Frame(self.meeting_panel)
        setup.pack(fill="x")
        self.driver_button = ttk.Button(setup, text="Set up meeting microphone", command=self.install_driver)
        self.driver_button.pack(side="left", padx=(0, 8))
        ttk.Button(setup, text="Windows mic permission", command=lambda: os.startfile("ms-settings:privacy-microphone")).pack(side="left")
        ttk.Button(setup, text="Check again", command=self.refresh_devices).pack(side="left", padx=8)
        self.meeting_panel.pack(fill="x", pady=8)
        controls = ttk.Frame(body)
        self.controls = controls
        controls.pack(fill="x", pady=(12, 8))
        self.start_button = ttk.Button(controls, text="Connect my phone", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="Disconnect", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.help_button = ttk.Button(controls, text="Open setup guide", command=self.guide, state="disabled")
        self.help_button.pack(side="right")
        ttk.Label(body, textvariable=self.message, wraplength=700).pack(anchor="w", pady=8)
        self.networks = ttk.Combobox(body, textvariable=self.network, state="readonly", font=("Segoe UI", 10))
        self.networks.pack(fill="x", pady=4)
        self.networks.bind("<<ComboboxSelected>>", lambda event: self.show_qr())
        self.qr = ttk.Label(body, text="Your pairing QR will appear here.", anchor="center")
        self.qr.pack(fill="both", expand=True, pady=8)
        ttk.Label(body, text="Pair earbuds with your phone. Keep phone and PC on the same Wi-Fi.\n"
                  "Keep the phone page open and awake. Close this app to stop audio.", wraplength=700).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.mode_changed()
        self.refresh_devices()
        root.after(100, self.poll)

    def mode_changed(self):
        if self.mode.get() == "meeting":
            self.meeting_panel.pack(before=self.controls, fill="x", pady=8)
        else:
            self.meeting_panel.pack_forget()
        for child in self.meeting_panel.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(foreground="#edf3f8" if self.mode.get() == "meeting" else "#91a2b6")
        self.driver_button.configure(state="normal" if self.mode.get() == "meeting" and self.state == "idle" else "disabled")

    def refresh_devices(self):
        if self.state != "idle":
            return
        def check():
            try:
                devices = list_outputs()
                import pyaudiowpatch as pa
                with pa.PyAudio() as audio:
                    default = int(audio.get_default_wasapi_loopback()["index"])
                try:
                    select_mic_output()
                    driver = True
                except ValueError:
                    driver = False
                self.events.put(("devices", (devices, default, driver, microphone_access())))
            except Exception as error:
                self.events.put(("error", f"Could not check audio: {error}"))
        threading.Thread(target=check, daemon=True).start()

    def install_driver(self):
        if self.installer and self.installer.is_alive():
            return
        try:
            select_mic_output()
            self.health.set("Meeting driver is already installed. No download needed.")
            return
        except ValueError:
            pass
        if not messagebox.askokcancel("Set up meeting microphone",
            "Download VB-CABLE from vb-audio.com, verify its publisher, and open its installer?\n\n"
            "This adds a third-party virtual audio driver. Windows may ask for administrator approval. "
            "Review the installer's license and click Install Driver. Restart if requested. "
            "WiFiAudio will not restart Windows or change your default audio devices.", parent=self.root):
            return
        self.driver_button.configure(state="disabled")
        self.health.set("Downloading and verifying the meeting driver…")
        def install():
            try:
                from driver_setup import prepare_installer
                installer = prepare_installer()
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(ROOT / "install-driver.ps1"), "-Installer", str(installer)]
                result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "Installer was cancelled.")
                self.events.put(("installed", None))
            except Exception as error:
                self.events.put(("error", f"Driver setup: {error}"))
            finally:
                self.events.put(("driver-done", None))
        self.installer = threading.Thread(target=install, daemon=False)
        self.installer.start()

    def start(self):
        if self.state != "idle":
            return
        selected = self.device.get()
        if selected not in self.device_map:
            self.message.set("Choose a working Windows output first.")
            return
        meeting = self.mode.get() == "meeting"
        if meeting:
            try:
                destination = select_mic_output()
            except ValueError:
                self.message.set("Click Set up meeting microphone first, then Check again.")
                return
            if microphone_access() is False:
                self.message.set("Windows microphone access is off. Open Windows mic permission above and enable it.")
                return
            import pyaudiowpatch as pa
            with pa.PyAudio() as audio:
                microphone_loopback = int(audio.get_wasapi_loopback_analogue_by_index(destination["index"])["index"])
            if self.device_map[selected] == microphone_loopback:
                self.message.set("Choose your normal Speakers / HDMI above and use the same speaker in the meeting app. "
                                 "CABLE Input is reserved for microphone return and would cause feedback.")
                return
        args = ["--no-browser", "--device", str(self.device_map[selected])]
        if meeting:
            args += ["--meeting", "--tls-dir", str(Path(os.environ["LOCALAPPDATA"]) / "WiFiAudio" / "tls")]
        self.stop_event = threading.Event()
        self.set_state("starting")
        self.message.set("Starting audio connection…")
        def work():
            try:
                serve(args, on_ready=lambda server: self.events.put(("ready", server)), stop_event=self.stop_event)
            except BaseException as error:
                self.events.put(("error", f"Could not start: {error}. Close any other WiFiAudio window and try again."))
            finally:
                self.events.put(("finished", None))
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def set_state(self, state):
        self.state = state
        self.start_button.configure(state="normal" if state == "idle" else "disabled")
        self.stop_button.configure(state="normal" if state in ("starting", "running") else "disabled")
        self.devices.configure(state="readonly" if state == "idle" else "disabled")
        for radio in self.radios:
            radio.configure(state="normal" if state == "idle" else "disabled")
        self.mode_changed()

    def show_qr(self):
        if not self.server:
            return
        address = self.network.get()
        url = next((url for url in self.server.urls if url.split("/")[2] == address), None)
        if not url:
            return
        self.image = ImageTk.PhotoImage(qrcode.make(url).resize((240, 240)))
        self.qr.configure(image=self.image, text="")

    def guide(self):
        if self.server:
            webbrowser.open(f"http://127.0.0.1:{8766 if self.mode.get() == 'meeting' else 8765}/pair")

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.state != "idle":
            self.set_state("stopping")
            self.message.set("Stopping audio and releasing devices…")

    def close(self):
        self.closing = True
        self.stop()
        if self.installer and self.installer.is_alive():
            self.message.set("Finishing driver setup. Close the installer to finish closing WiFiAudio.")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "devices":
                    devices, default, driver, access = value
                    self.device_map = {f"{d['name']} ({d['index']})": d["index"] for d in devices}
                    self.devices["values"] = list(self.device_map)
                    if self.device.get() not in self.device_map:
                        self.device.set(next((name for name, index in self.device_map.items() if index == default), next(iter(self.device_map), "")))
                    self.health.set(f"Meeting driver: {'ready' if driver else 'setup needed'}  •  Windows mic: "
                                    + ("blocked" if access is False else "allowed" if access else "check settings"))
                elif kind == "ready":
                    self.server = value
                    if self.closing or self.state == "stopping":
                        self.stop_event.set()
                        continue
                    self.set_state("running")
                    self.help_button.configure(state="normal")
                    self.networks["values"] = [url.split("/")[2] for url in value.urls]
                    self.network.set(self.networks["values"][0])
                    self.show_qr()
                    self.message.set("Scan the QR with your phone, then tap Connect audio." if self.mode.get() == "listen" else
                                     "First use Open setup guide for the one-time phone certificate setup. Then scan this QR.\n"
                                     "Meeting app microphone: CABLE Output. Speaker: your normal Windows output.")
                elif kind == "error":
                    self.message.set(value)
                elif kind == "installed":
                    self.health.set("Installer finished. Restart Windows if it asked you to, then use Check again.")
                    self.refresh_devices()
                elif kind == "driver-done":
                    self.mode_changed()
                elif kind == "finished":
                    self.server = None
                    self.set_state("idle")
                    self.help_button.configure(state="disabled")
                    self.qr.configure(image="", text="Your pairing QR will appear here.")
                    if self.message.get().startswith("Stopping"):
                        self.message.set("Disconnected. Audio devices released.")
        except queue.Empty:
            pass
        if self.closing and not (self.worker and self.worker.is_alive()) and not (self.installer and self.installer.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self.poll)


def main():
    # PyInstaller windowed builds have no standard output streams.
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if len(sys.argv) > 1:
        serve()
        return
    root = tk.Tk()
    Desktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()
