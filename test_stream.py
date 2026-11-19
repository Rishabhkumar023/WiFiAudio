import asyncio
import unittest

from aiohttp.test_utils import TestClient, TestServer
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from audio import ToneTrack
from server import AudioServer


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tracks = []
        def source():
            track = ToneTrack()
            self.tracks.append(track)
            return track
        self.server = AudioServer(source, token="test-only-secret")
        self.client = TestClient(TestServer(self.server.app()))
        await self.client.start_server()
        self.peers = []

    async def asyncTearDown(self):
        await asyncio.gather(*(pc.close() for pc in self.peers))
        await asyncio.wait_for(self.client.close(), 10)
        self.assertIsNone(self.server.active)
        self.assertFalse(self.server.tasks)
        self.assertTrue(all(t.readyState == "ended" for t in self.tracks))

    async def authenticated(self):
        ws = await self.client.ws_connect("/connect")
        await ws.send_json({"token": self.server.token})
        self.assertEqual(await ws.receive_json(), {"type": "ready"})
        return ws

    async def receive_audio(self):
        ws = await self.authenticated()
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers.append(pc)
        remote = asyncio.get_running_loop().create_future()
        @pc.on("track")
        def on_track(track):
            remote.set_result(track)
        pc.addTransceiver("audio", direction="recvonly")
        await pc.setLocalDescription(await pc.createOffer())
        await ws.send_json({"type": "offer", "sdp": pc.localDescription.sdp})
        answer = await asyncio.wait_for(ws.receive_json(), 10)
        self.assertEqual(answer.get("type"), "answer", answer)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
        track = await asyncio.wait_for(remote, 10)
        frames = [await asyncio.wait_for(track.recv(), 10) for _ in range(5)]
        self.assertEqual(frames[0].sample_rate, 48000)
        self.assertGreater(frames[-1].pts, frames[0].pts)
        self.assertTrue(any(bytes(f.planes[0]).strip(b"\0") for f in frames))
        return ws, pc

    async def test_audio_disconnect_reconnect_and_exclusive_listener(self):
        for _ in range(2):
            ws, pc = await self.receive_audio()
            other = await self.client.ws_connect("/connect")
            await other.send_json({"token": self.server.token})
            self.assertIn("Another phone", (await other.receive_json())["error"])
            await other.close()
            await ws.close()
            await pc.close()
            for _ in range(100):
                if self.server.active is None:
                    break
                await asyncio.sleep(.01)
            self.assertIsNone(self.server.active)

    async def test_invalid_auth_and_malformed_offer_never_capture(self):
        ws = await self.client.ws_connect("/connect")
        await ws.send_json({"token": "wrong"})
        self.assertIn("Invalid pairing", (await ws.receive_json())["error"])
        await ws.close()
        ws = await self.authenticated()
        await ws.send_json({"type": "offer", "sdp": 3})
        self.assertIn("error", await ws.receive_json())
        await ws.close()
        self.assertEqual(self.tracks, [])

    async def test_shutdown_while_waiting_for_offer(self):
        await self.authenticated()
        await asyncio.wait_for(self.client.close(), 10)
        self.assertIsNone(self.server.active)

    async def test_shutdown_with_active_audio(self):
        await self.receive_audio()
        await asyncio.wait_for(self.client.close(), 10)
        self.assertTrue(all(t.readyState == "ended" for t in self.tracks))

    async def test_receiver_and_pairing_page(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("Connect audio", await response.text())
        self.server.urls = ["http://127.0.0.1/#token=test"]
        response = await self.client.get("/pair")
        self.assertIn("data:image/png;base64,", await response.text())


if __name__ == "__main__":
    unittest.main()
