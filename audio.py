"""Windows output capture. No microphone capture and no audio saved to disk."""
import asyncio
import math
import queue
import struct
import time
from fractions import Fraction

from aiortc import AudioStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame, AudioResampler


class ToneTrack(AudioStreamTrack):
    """Explicit synthetic test source, never a fallback for failed capture."""
    def __init__(self):
        super().__init__()
        self.samples = 0
        self.started = time.monotonic()

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        await asyncio.sleep(max(0, self.started + self.samples / 48000 - time.monotonic()))
        frame = AudioFrame(format="s16", layout="stereo", samples=960)
        data = bytearray()
        for i in range(960):
            value = int(2000 * math.sin(2 * math.pi * 440 * (self.samples + i) / 48000))
            data.extend(struct.pack("<hh", value, value))
        frame.planes[0].update(bytes(data))
        frame.sample_rate = 48000
        frame.time_base = Fraction(1, 48000)
        frame.pts = self.samples
        self.samples += 960
        return frame


class LoopbackTrack(AudioStreamTrack):
    def __init__(self, device_index=None):
        super().__init__()
        import pyaudiowpatch as pa
        self.pa = pa.PyAudio()
        self.stream = None
        self.frames = queue.Queue(maxsize=5)  # About 100 ms; discard stale audio.
        self.samples = 0
        self.dropped = 0
        self.overflows = 0
        try:
            device = (self.pa.get_device_info_by_index(device_index)
                      if device_index is not None
                      else self.pa.get_default_wasapi_loopback())
            if not device.get("isLoopbackDevice"):
                raise ValueError("Select a loopback output device, not a microphone.")
            self.channels = int(device["maxInputChannels"])
            if self.channels not in (1, 2):
                raise ValueError("Set this Windows output to mono/stereo first (surround is unsupported).")
            self.rate = int(device["defaultSampleRate"])
            self.device_name = device["name"]
            self.device_index = int(device["index"])

            def callback(data, count, timing, status):
                if self.readyState != "live":
                    return (None, pa.paComplete)
                if status:
                    self.overflows += 1
                packet = (self.samples, count, data)
                self.samples += count
                try:
                    self.frames.put_nowait(packet)
                except queue.Full:
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                    self.dropped += 1
                    self.frames.put_nowait(packet)
                return (None, pa.paContinue)

            self.stream = self.pa.open(format=pa.paInt16, channels=self.channels,
                                       rate=self.rate, input=True,
                                       input_device_index=device["index"],
                                       frames_per_buffer=self.rate // 50,
                                       stream_callback=callback)
        except Exception:
            self.stop()
            raise

    async def recv(self):
        while self.readyState == "live":
            try:
                pts, count, data = await asyncio.to_thread(self.frames.get, True, 0.25)
            except queue.Empty:
                if self.stream is None or not self.stream.is_active():
                    raise MediaStreamError("Windows audio output stopped; reconnect after selecting an output.")
                continue
            if self.readyState != "live":
                break
            frame = AudioFrame(format="s16", layout="mono" if self.channels == 1 else "stereo", samples=count)
            frame.planes[0].update(data)
            frame.sample_rate = self.rate
            frame.time_base = Fraction(1, self.rate)
            frame.pts = pts
            return frame
        raise MediaStreamError

    def stop(self):
        super().stop()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.pa is not None:
            self.pa.terminate()
            self.pa = None


def list_outputs():
    import pyaudiowpatch as pa
    with pa.PyAudio() as devices:
        return [{"index": int(d["index"]), "name": d["name"],
                 "channels": int(d["maxInputChannels"]), "rate": int(d["defaultSampleRate"])}
                for d in devices.get_loopback_device_info_generator()]


def list_playback_outputs():
    """Physical and virtual Windows render endpoints, using WASAPI only."""
    import pyaudiowpatch as pa
    with pa.PyAudio() as devices:
        host = devices.get_host_api_info_by_type(pa.paWASAPI)["index"]
        return [{"index": i, "name": d["name"], "channels": int(d["maxOutputChannels"]),
                 "rate": int(d["defaultSampleRate"])}
                for i in range(devices.get_device_count())
                if (d := devices.get_device_info_by_index(i))["hostApi"] == host
                and d["maxOutputChannels"] > 0 and not d.get("isLoopbackDevice")]


def select_mic_output(index=None):
    outputs = list_playback_outputs()
    if index is not None:
        matches = [d for d in outputs if d["index"] == index]
    else:
        matches = [d for d in outputs if d["name"] == "CABLE Input (VB-Audio Virtual Cable)"]
    if len(matches) != 1:
        raise ValueError("Install VB-CABLE and restart Windows, or use --list-playback-devices "
                         "and --mic-output INDEX to select your virtual cable's playback endpoint.")
    return matches[0]


class MicrophoneOutput:
    """Render received microphone frames to an explicitly selected Windows endpoint."""
    def __init__(self, device_index):
        import pyaudiowpatch as pa
        self.pa = pa.PyAudio()
        self.stream = None
        self.frames = queue.Queue(maxsize=5)
        self.pending = bytearray()
        self.dropped = 0
        self.closed = False
        try:
            device = self.pa.get_device_info_by_index(device_index)
            self.name = device["name"]
            self.loopback_index = int(self.pa.get_wasapi_loopback_analogue_by_index(device_index)["index"])
            channels = min(2, int(device["maxOutputChannels"]))
            if channels < 1 or device.get("isLoopbackDevice"):
                raise ValueError("Microphone destination must be a Windows playback endpoint.")
            rate = int(device["defaultSampleRate"])
            self.channels = channels
            self.resampler = AudioResampler(format="s16", layout="stereo" if channels == 2 else "mono",
                                            rate=rate, frame_size=rate // 50)

            def callback(data, count, timing, status):
                size = count * channels * 2
                while len(self.pending) < size:
                    try:
                        self.pending.extend(self.frames.get_nowait())
                    except queue.Empty:
                        break
                output = bytes(self.pending[:size])
                del self.pending[:size]
                return (output.ljust(size, b"\0"), pa.paComplete if self.closed else pa.paContinue)

            self.stream = self.pa.open(format=pa.paInt16, channels=channels, rate=rate,
                                       output=True, output_device_index=device_index,
                                       frames_per_buffer=rate // 50, stream_callback=callback)
        except Exception:
            self.close()
            raise

    def write(self, frame):
        if self.closed:
            raise RuntimeError("Virtual microphone output is closed.")
        if not self.stream.is_active():
            raise RuntimeError("Virtual microphone device stopped. Reconnect after checking Windows audio devices.")
        for normalized in self.resampler.resample(frame):
            data = bytes(normalized.planes[0])[:normalized.samples * self.channels * 2]
            try:
                self.frames.put_nowait(data)
            except queue.Full:
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                self.dropped += 1
                self.frames.put_nowait(data)

    def close(self):
        self.closed = True
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.pa is not None:
            self.pa.terminate()
            self.pa = None
