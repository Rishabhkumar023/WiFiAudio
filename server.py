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
import webbrowser
from pathlib import Path

import qrcode
from aiohttp import web, WSMsgType
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription

from audio import LoopbackTrack, ToneTrack, list_outputs

ROOT = Path(__file__).resolve().parent


class AudioServer:
    def __init__(self, source_factory, token=None):
        self.source_factory = source_factory
        self.token = token or secrets.token_urlsafe(24)
        self.active = None
        self.sockets = set()
        self.tasks = set()
        self.urls = []

    async def index(self, request):
        return web.FileResponse(ROOT / "receiver.html", headers={"Cache-Control": "no-store"})

    async def javascript(self, request):
        return web.FileResponse(ROOT / "receiver.js")

    async def pair(self, request):
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Open pairing on the Windows PC using 127.0.0.1.")
        cards = []
        for url in self.urls:
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
        try:
            auth = await asyncio.wait_for(ws.receive_json(), 10)
            if not isinstance(auth, dict) or not isinstance(auth.get("token"), str) or not secrets.compare_digest(auth["token"], self.token):
                await ws.send_json({"error": "Invalid pairing link. Scan the QR on the PC again."})
                return ws
            if self.active is not None:
                await ws.send_json({"error": "Another phone is connected. Disconnect it first."})
                return ws
            self.active = ws
            await ws.send_json({"type": "ready"})
            offer = await asyncio.wait_for(ws.receive_json(), 20)
            if not isinstance(offer, dict) or offer.get("type") != "offer" or not isinstance(offer.get("sdp"), str):
                raise ValueError("Expected an audio connection offer.")
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

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
            @track.on("ended")
            async def source_ended():
                await ws.close()
            pc.addTrack(track)
            await pc.setLocalDescription(await pc.createAnswer())
            await ws.send_json({"type": pc.localDescription.type, "sdp": pc.localDescription.sdp,
                                "source": getattr(track, "device_name", "Synthetic 440 Hz test tone")})
            while not ws.closed:
                message = await ws.receive()
                if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        except (ValueError, TypeError, AssertionError, asyncio.TimeoutError, RuntimeError, OSError) as error:
            if not ws.closed:
                await ws.send_json({"error": f"Could not start audio: {error}"})
        finally:
            try:
                if track is not None:
                    track.stop()
            finally:
                try:
                    if pc is not None:
                        await pc.close()
                finally:
                    if self.active is ws:
                        self.active = None
                    await ws.close()
                    self.sockets.discard(ws)
                    self.tasks.discard(task)
        return ws

    async def shutdown(self, app):
        await asyncio.gather(*(ws.close(code=1001, message=b"Sender stopped") for ws in list(self.sockets)))
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

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
    parser.add_argument("--test-tone", action="store_true", help="Synthetic audio only; never capture Windows output")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        print(json.dumps(list_outputs(), indent=2))
        return
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
    server = AudioServer(ToneTrack if args.test_tone else lambda: LoopbackTrack(args.device))
    server.urls = [f"http://{address}:{args.port}/#token={server.token}" for address in addresses]
    app = server.app()

    async def started(app):
        print("\nWi-Fi Audio - TEST TONE" if args.test_tone else "\nWi-Fi Audio - Windows output (capture starts after pairing)")
        print("Private LAN only: pairing uses HTTP; WebRTC encrypts the media, not this page.")
        print("Connect phone and PC to the same network. Phone: pair Bluetooth earphones first.")
        print("Pairing links (keep private):\n" + "\n".join(server.urls))
        print("Ctrl+C stops the sender and revokes these links.\n")
        if not args.no_browser:
            pair_host = "127.0.0.1" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
            if pair_host == "127.0.0.1":
                asyncio.get_running_loop().call_later(1, webbrowser.open, f"http://{pair_host}:{args.port}/pair")

    app.on_startup.append(started)
    web.run_app(app, host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
