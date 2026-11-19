"use strict";
const token = new URLSearchParams(location.hash.slice(1)).get("token");
history.replaceState(null, "", location.pathname);
const audio = document.getElementById("audio");
const status = document.getElementById("status");
const source = document.getElementById("source");
const connectButton = document.getElementById("connect");
const stopButton = document.getElementById("stop");
const useMic = document.getElementById("use-mic");
const micDevice = document.getElementById("mic-device");
const micStatus = document.getElementById("mic-status");
const muteButton = document.getElementById("mute");
let session = null;

async function listMicrophones() {
  if (!navigator.mediaDevices) return;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const selected = micDevice.value;
  micDevice.replaceChildren(new Option("Phone/browser default microphone", ""));
  for (const device of devices.filter(d => d.kind === "audioinput" && d.deviceId)) {
    micDevice.add(new Option(device.label || "Microphone (permission needed for name)", device.deviceId));
  }
  if ([...micDevice.options].some(o => o.value === selected)) micDevice.value = selected;
}

function stop(message = "Disconnected") {
  const previous = session;
  session = null;
  if (previous) {
    clearTimeout(previous.timer);
    previous.pc.close();
    previous.ws.close();
    previous.media?.getTracks().forEach(track => track.stop());
  }
  audio.pause();
  audio.srcObject = null;
  connectButton.disabled = !token;
  stopButton.disabled = true;
  useMic.disabled = false;
  micDevice.disabled = false;
  muteButton.disabled = true;
  muteButton.textContent = "Mute microphone";
  micStatus.textContent = "Microphone is off.";
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
  if (useMic.checked && (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)) {
    status.textContent = "Microphone needs trusted HTTPS. Start the PC in meeting mode and complete its certificate setup first.";
    return;
  }
  const pc = new RTCPeerConnection({iceServers: []});
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/connect`);
  const current = {pc, ws, timer: null, media: null, microphone: useMic.checked};
  session = current;
  connectButton.disabled = true;
  stopButton.disabled = false;
  useMic.disabled = true;
  micDevice.disabled = true;
  status.textContent = "Connecting to your PC…";
  current.timer = setTimeout(() => {
    if (session === current) stop("Connection timed out. Check Wi-Fi and Windows Firewall, then reconnect.");
  }, current.microphone ? 90000 : 25000);
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
        if (current.microphone) {
          if (!data.microphone) throw new Error("Restart the PC with --meeting to enable microphone return.");
          micStatus.textContent = "Allow microphone permission on your phone…";
          const media = await navigator.mediaDevices.getUserMedia({video: false, audio: {
            echoCancellation: true, noiseSuppression: true, autoGainControl: true,
            ...(micDevice.value ? {deviceId: {exact: micDevice.value}} : {})
          }});
          if (session !== current) { media.getTracks().forEach(t => t.stop()); return; }
          current.media = media;
          const mic = media.getAudioTracks()[0];
          pc.addTrack(mic, media);
          mic.onended = () => { if (session === current) stop("Microphone disconnected. Check the phone audio route and reconnect."); };
          micStatus.textContent = `Active mic: ${mic.label || "browser default"}. Connecting to desktop…`;
          muteButton.disabled = false;
          await listMicrophones();
          if (session !== current) return;
        }
        await pc.setLocalDescription(await pc.createOffer());
        await waitForIce(pc);
        if (session !== current) return;
        ws.send(JSON.stringify({type: pc.localDescription.type, sdp: pc.localDescription.sdp, microphone: current.microphone}));
      } else if (data.type === "answer") {
        source.textContent = data.source;
        await pc.setRemoteDescription({type: data.type, sdp: data.sdp});
      } else if (data.type === "mic-active") {
        const mic = current.media?.getAudioTracks()[0];
        micStatus.textContent = `Active mic: ${mic?.label || "browser default"}. Reaching desktop: ${data.output}. Select CABLE Output in your meeting.`;
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
muteButton.onclick = () => {
  const mic = session?.media?.getAudioTracks()[0];
  if (!mic) return;
  mic.enabled = !mic.enabled;
  muteButton.textContent = mic.enabled ? "Mute microphone" : "Unmute microphone";
  muteButton.setAttribute("aria-pressed", String(!mic.enabled));
  micStatus.textContent = mic.enabled ? `Microphone on: ${mic.label || "browser default"}` : "Microphone muted — sending silence to desktop.";
};
listMicrophones().catch(() => {});
window.addEventListener("pagehide", () => stop());
if (!token) {
  connectButton.disabled = true;
  status.textContent = "Scan the pairing QR on your PC to open this receiver.";
}
