"use strict";
const token = new URLSearchParams(location.hash.slice(1)).get("token");
history.replaceState(null, "", location.pathname);
const audio = document.getElementById("audio");
const status = document.getElementById("status");
const source = document.getElementById("source");
const connectButton = document.getElementById("connect");
const stopButton = document.getElementById("stop");
let session = null;

function stop(message = "Disconnected") {
  const previous = session;
  session = null;
  if (previous) {
    clearTimeout(previous.timer);
    previous.pc.close();
    previous.ws.close();
  }
  audio.pause();
  audio.srcObject = null;
  connectButton.disabled = !token;
  stopButton.disabled = true;
  status.textContent = message;
}

function waitForIce(pc) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      pc.removeEventListener("icegatheringstatechange", changed);
    };
    const changed = () => {
      if (pc.iceGatheringState === "complete") { cleanup(); resolve(); }
    };
    const timer = setTimeout(() => { cleanup(); reject(new Error("Wi-Fi discovery timed out. Reconnect.")); }, 10000);
    pc.addEventListener("icegatheringstatechange", changed);
    changed();
  });
}

connectButton.onclick = () => {
  if (!token) return;
  stop();
  if (!window.RTCPeerConnection) {
    status.textContent = "This browser does not support WebRTC. Try current Android Chrome.";
    return;
  }
  const pc = new RTCPeerConnection({iceServers: []});
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/connect`);
  const current = {pc, ws, timer: null};
  session = current;
  connectButton.disabled = true;
  stopButton.disabled = false;
  status.textContent = "Connecting to your PC…";
  current.timer = setTimeout(() => {
    if (session === current) stop("Connection timed out. Check Wi-Fi and Windows Firewall, then reconnect.");
  }, 25000);
  pc.addTransceiver("audio", {direction: "recvonly"});
  pc.ontrack = event => {
    if (session !== current) return;
    audio.srcObject = new MediaStream([event.track]);
    audio.play().catch(() => {
      if (session === current) status.textContent = "Connected — tap Play below to hear audio";
    });
  };
  pc.onconnectionstatechange = () => {
    if (session !== current) return;
    if (pc.connectionState === "connected") {
      clearTimeout(current.timer);
      status.textContent = audio.paused ? "Connected — tap Play below" : "Connected • listening";
    } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
      stop("Connection lost. Check the PC sender and Wi-Fi, then tap Connect audio.");
    }
  };
  ws.onopen = () => ws.send(JSON.stringify({token}));
  ws.onmessage = async event => {
    if (session !== current) return;
    try {
      const data = JSON.parse(event.data);
      if (data.error) { stop(data.error); return; }
      if (data.type === "ready") {
        await pc.setLocalDescription(await pc.createOffer());
        await waitForIce(pc);
        if (session !== current) return;
        ws.send(JSON.stringify({type: pc.localDescription.type, sdp: pc.localDescription.sdp}));
      } else if (data.type === "answer") {
        source.textContent = data.source;
        await pc.setRemoteDescription({type: data.type, sdp: data.sdp});
      }
    } catch (error) {
      if (session === current) stop(`Connection error: ${error.message}`);
    }
  };
  ws.onclose = () => { if (session === current) stop("Sender disconnected. Keep it running on your PC, then reconnect."); };
  ws.onerror = () => { if (session === current) stop("Cannot reach the PC. Check Wi-Fi and Windows Firewall."); };
};
audio.onplaying = () => { if (session) status.textContent = "Connected • listening"; };
stopButton.onclick = () => stop();
window.addEventListener("pagehide", () => stop());
if (!token) {
  connectButton.disabled = true;
  status.textContent = "Scan the pairing QR on your PC to open this receiver.";
}
