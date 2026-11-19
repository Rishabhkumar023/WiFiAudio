"use strict";
const button = document.querySelector("#download");
const status = document.querySelector("#status");
const progress = document.querySelector("#progress");
let manifest;
const hex = bytes => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, "0")).join("");

async function init() {
  const response = await fetch("download.json", {cache: "no-store"});
  if (!response.ok) throw new Error("Package information is temporarily unavailable.");
  manifest = await response.json();
  if (!manifest.parts?.length || !Number.isSafeInteger(manifest.bytes) || manifest.bytes <= 0) {
    throw new Error("Invalid download information.");
  }
  document.querySelector("#package").textContent = `Windows x64 · ${(manifest.bytes / 1048576).toFixed(1)} MB · ${manifest.version}`;
  button.textContent = "Download for Windows";
  button.disabled = false;
  status.textContent = "Ready. Download this on your Windows PC.";
}

button.onclick = async () => {
  button.disabled = true;
  progress.hidden = false;
  progress.value = 0;
  let received = 0;
  const chunks = [];
  try {
    for (const part of manifest.parts) {
      const response = await fetch(part.url);
      if (!response.ok) throw new Error("Download interrupted. Please retry.");
      const data = await response.arrayBuffer();
      if (data.byteLength !== part.bytes || hex(await crypto.subtle.digest("SHA-256", data)) !== part.sha256) {
        throw new Error("Download verification failed. Please retry.");
      }
      chunks.push(data);
      received += data.byteLength;
      progress.value = received / manifest.bytes * 100;
      status.textContent = `Downloaded ${(received / 1048576).toFixed(1)} of ${(manifest.bytes / 1048576).toFixed(1)} MB…`;
    }
    if (received !== manifest.bytes) throw new Error("Incomplete download. Please retry.");
    const blob = new Blob(chunks, {type: "application/zip"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = manifest.filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    status.textContent = "Download ready. Extract the entire ZIP, then open WiFiAudio.exe.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
init().catch(error => { status.textContent = error.message; button.textContent = "Download unavailable"; });
