"""Local-only Wi-Fi Audio prototype. Start explicitly to enable connections."""
import argparse
import asyncio
import base64
import html
import io
import ipaddress
import json
import secrets
import socket
import sys
import webbrowser
from pathlib import Path

import qrcode
from aiohttp import web, WSMsgType
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from audio import LoopbackTrack, ToneTrack, list_outputs, MicrophoneOutput, select_mic_output, list_playback_outputs
from local_tls import prepare_tls

ROOT = Path(__file__).resolve().parent


class AudioServer:
    def __init__(self, source_factory, token=None, sink_factory=None):
        self.source_factory = source_factory
        self.token = token or secrets.token_urlsafe(24)
        self.active = None
        self.sockets = set()
        self.tasks = set()
        self.cleanups = set()
        self.urls = []
        self.sink_factory = sink_factory
        self.ca_file = None
        self.ca_fingerprint = None
        self.certificate_urls = []

    async def index(self, request):
        return web.FileResponse(ROOT / "receiver.html", headers={"Cache-Control": "no-store"})

    async def javascript(self, request):
        return web.FileResponse(ROOT / "receiver.js")

    async def pair(self, request):
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Open pairing on the Windows PC using 127.0.0.1.")
        cards = []
        if self.ca_file:
            cards.append("<h2>One-time Android microphone setup</h2><p>First download the local CA certificate using "
                         "the certificate QR. In Android Settings, search for Install certificate, then choose CA certificate. "
                         "Install only this PC's WiFiAudio certificate. Check its SHA-256 fingerprint against the PC:</p><code>"
                         + html.escape(self.ca_fingerprint) + "</code><p>Then scan the HTTPS receiver QR. "
                         "Do not bypass browser certificate errors. Meeting microphone: CABLE Output. "
                         "Meeting speaker: your normal Windows output, NOT CABLE Input.</p>")
        for url in self.certificate_urls + self.urls:
            image = qrcode.make(url)
            output = io.BytesIO()
            image.save(output, format="PNG")
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
            cards.append(f'<p><img width="260" src="data:image/png;base64,{encoded}" alt="Pairing QR"></p>'
                         f'<p><a href="{html.escape(url)}">{html.escape(url)}</a></p>')
        return web.Response(text="<!doctype html><meta name='viewport' content='width=device-width'>"
                            "<title>Wi-Fi Audio pairing</title><body style='font:18px system-ui;padding:32px;overflow-wrap:anywhere'>"
                            "<h1>Connect your phone</h1><p>Pair earphones with Android. Join the same private Wi-Fi or phone hotspot. "
                            "Scan the QR for your PC's Wi-Fi address, then tap Connect.</p>"
                            "<p>Anyone with this link can listen while the sender runs. Close the sender to revoke it.</p>"
                            + "".join(cards) + "</body>", content_type="text/html",
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    async def certificate(self, request):
        return web.FileResponse(self.ca_file, headers={
            "Content-Type": "application/x-x509-ca-cert",
            "Content-Disposition": 'attachment; filename="WiFiAudio-CA.crt"'})

    async def connect(self, request):
        # No cross-site browser initiation. Non-browser clients still need the token.
        origin = request.headers.get("Origin")
        if origin is not None and origin != f"{request.scheme}://{request.host}":
            raise web.HTTPForbidden(text="Open the receiver from the sender's own link.")
        if len(self.sockets) >= 4:
            raise web.HTTPServiceUnavailable(text="Too many pending connections.")
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=65536)
        await ws.prepare(request)
        self.sockets.add(ws)
        task = asyncio.current_task()
        self.tasks.add(task)
        pc = None
        track = None
        sink = None
        mic_task = None
        incoming_audio = []
        try:
            auth = await asyncio.wait_for(ws.receive_json(), 10)
            if not isinstance(auth, dict) or not isinstance(auth.get("token"), str) or not secrets.compare_digest(auth["token"], self.token):
                await ws.send_json({"error": "Invalid pairing link. Scan the QR on the PC again."})
                return ws
            if self.active is not None:
                await ws.send_json({"error": "Another phone is connected. Disconnect it first."})
                return ws
            self.active = ws
            await ws.send_json({"type": "ready", "microphone": self.sink_factory is not None})
            offer = await asyncio.wait_for(ws.receive_json(), 90)
            if not isinstance(offer, dict) or offer.get("type") != "offer" or not isinstance(offer.get("sdp"), str):
                raise ValueError("Expected an audio connection offer.")
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

            @pc.on("track")
            def incoming(remote_track):
                if remote_track.kind == "audio":
                    incoming_audio.append(remote_track)

            @pc.on("connectionstatechange")
            async def changed():
                if pc.connectionState in ("failed", "closed"):
                    await ws.close()

            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type="offer"))
            if not any(t.kind == "audio" and t.direction in ("recvonly", "sendrecv")
                       for t in pc.getTransceivers()):
                # aiortc local directions are initially recvonly for remote offers.
                raise ValueError("Receiver must request audio.")
            track = self.source_factory()
            wants_microphone = offer.get("microphone", False)
            if not isinstance(wants_microphone, bool):
                raise ValueError("Microphone request must be true or false.")
            if wants_microphone:
                if not self.sink_factory:
                    raise ValueError("Restart the PC sender in --meeting mode to enable microphone return.")
                if len(incoming_audio) != 1:
                    raise ValueError("Meeting mode requires exactly one microphone audio track.")
                sink = self.sink_factory()
                if getattr(track, "device_index", -1) == getattr(sink, "loopback_index", -2):
                    raise ValueError("Feedback loop: use normal speakers for PC playback, not the virtual microphone cable.")
            @track.on("ended")
            async def source_ended():
                await ws.close()
            pc.addTrack(track)
            await pc.setLocalDescription(await pc.createAnswer())
            await ws.send_json({"type": pc.localDescription.type, "sdp": pc.localDescription.sdp,
                                "source": getattr(track, "device_name", "Synthetic 440 Hz test tone")})
            if sink is not None:
                async def receive_microphone():
                    first = True
                    try:
                        while True:
                            frame = await incoming_audio[0].recv()
                            sink.write(frame)
                            if first:
                                first = False
                                await ws.send_json({"type": "mic-active", "output": sink.name})
                    except asyncio.CancelledError:
                        raise
                    except (MediaStreamError, RuntimeError, ValueError, OSError) as error:
                        if not ws.closed:
                            await ws.send_json({"error": f"Microphone stopped: {error}. Reconnect to resume."})
                            await ws.close()
                mic_task = asyncio.create_task(receive_microphone())
            while not ws.closed:
                message = await ws.receive()
                if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        except (ValueError, TypeError, AssertionError, asyncio.TimeoutError, RuntimeError, OSError) as error:
            if not ws.closed:
                await ws.send_json({"error": f"Could not start audio: {error}"})
        finally:
            async def release():
                if mic_task is not None:
                    mic_task.cancel()
                try:
                    try:
                        if sink is not None:
                            sink.close()
                    finally:
                        if track is not None:
                            track.stop()
                finally:
                    try:
                        if mic_task is not None:
                            await asyncio.gather(mic_task, return_exceptions=True)
                        if pc is not None:
                            await pc.close()
                    finally:
                        await ws.close()
                        if self.active is ws:
                            self.active = None
                        self.sockets.discard(ws)
                        self.tasks.discard(task)
            # aiohttp can cancel a request after the browser has closed its socket.
            # Keep finalization owned by the app until native audio and WebRTC close.
            cleanup = asyncio.create_task(release())
            self.cleanups.add(cleanup)
            cleanup.add_done_callback(self.cleanups.discard)
            await asyncio.shield(cleanup)
        return ws

    async def shutdown(self, app):
        await asyncio.gather(*(ws.close(code=1001, message=b"Sender stopped") for ws in list(self.sockets)))
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.cleanups:
            await asyncio.gather(*list(self.cleanups), return_exceptions=True)

    def app(self):
        app = web.Application(client_max_size=65536)
        app.router.add_get("/", self.index)
        app.router.add_get("/receiver.js", self.javascript)
        app.router.add_get("/pair", self.pair)
        app.router.add_get("/connect", self.connect)
        app.on_shutdown.append(self.shutdown)
        return app


def main():
    parser = argparse.ArgumentParser(description="Windows output -> Wi-Fi -> Android browser -> earphones")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address; default all local IPv4 interfaces")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--advertise-host", help="PC IPv4 address reachable by the phone")
    parser.add_argument("--device", type=int, help="Loopback device index from --list-devices")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--meeting", action="store_true", help="Enable HTTPS and phone microphone return through a virtual audio cable")
    parser.add_argument("--mic-output", type=int, help="WASAPI virtual cable playback endpoint index")
    parser.add_argument("--list-playback-devices", action="store_true")
    parser.add_argument("--pair-port", type=int, default=8766, help="Local pairing page and CA download port in meeting mode")
    parser.add_argument("--tls-dir", type=Path, help="Directory for this installation's private TLS identity")
    parser.add_argument("--test-tone", action="store_true", help="Synthetic audio only; never capture Windows output")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        print(json.dumps(list_outputs(), indent=2))
        return
    if args.list_playback_devices:
        print(json.dumps(list_playback_outputs(), indent=2))
        return
    if args.mic_output is not None and not args.meeting:
        parser.error("--mic-output requires --meeting")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    if args.advertise_host:
        addresses = [str(ipaddress.IPv4Address(args.advertise_host))]
    elif args.host != "0.0.0.0":
        addresses = [str(ipaddress.IPv4Address(args.host))]
    else:
        addresses = sorted({result[4][0] for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                            if not ipaddress.ip_address(result[4][0]).is_loopback})
    if not addresses:
        parser.error("No LAN IPv4 address found. Connect Wi-Fi, then use --advertise-host YOUR_PC_IP.")
    sink_factory = None
    ssl_context = None
    if args.meeting:
        if not 1 <= args.pair_port <= 65535 or args.pair_port == args.port:
            parser.error("Pairing port must be valid and different from the audio port.")
        try:
            destination = select_mic_output(args.mic_output)
        except ValueError as error:
            parser.error(str(error))
        sink_factory = lambda: MicrophoneOutput(destination["index"])
    server = AudioServer(ToneTrack if args.test_tone else lambda: LoopbackTrack(args.device), sink_factory=sink_factory)
    scheme = "https" if args.meeting else "http"
    server.urls = [f"{scheme}://{address}:{args.port}/#token={server.token}" for address in addresses]
    if args.meeting:
        directory = args.tls_dir or ((Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT) / ".local" / "tls")
        ssl_context, server.ca_file, server.ca_fingerprint = prepare_tls(directory, addresses)
        server.certificate_urls = [f"http://{address}:{args.pair_port}/certificate.crt" for address in addresses]
    app = server.app()

    async def started(app):
        print("\nWi-Fi Audio - TEST TONE" if args.test_tone else "\nWi-Fi Audio - Windows output (capture starts after pairing)")
        if args.meeting:
            print("Meeting mode: install this PC's CA on Android using the pairing page, then allow microphone access.")
            print("Meeting microphone: CABLE Output. Meeting speaker: normal Windows speakers (NOT CABLE Input).")
            print("Phone microphone destination:", destination["name"])
        else:
            print("Private LAN only: pairing uses HTTP; WebRTC encrypts the media, not this page.")
        print("Connect phone and PC to the same network. Phone: pair Bluetooth earphones first.")
        print("Pairing links (keep private):\n" + "\n".join(server.urls))
        print("Ctrl+C stops the sender and revokes these links.\n")
        if not args.no_browser:
            pair_host = "127.0.0.1" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
            if pair_host == "127.0.0.1":
                asyncio.get_running_loop().call_later(1, webbrowser.open, f"http://{pair_host}:{args.pair_port if args.meeting else args.port}/pair")

    app.on_startup.append(started)
    if args.meeting:
        async def pairing_context(app):
            pairing = web.Application()
            pairing.router.add_get("/pair", server.pair)
            pairing.router.add_get("/certificate.crt", server.certificate)
            runner = web.AppRunner(pairing, access_log=None)
            await runner.setup()
            try:
                await web.TCPSite(runner, args.host, args.pair_port).start()
                yield
            finally:
                await runner.cleanup()
        app.cleanup_ctx.append(pairing_context)
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context, access_log=None)


if __name__ == "__main__":
    main()
