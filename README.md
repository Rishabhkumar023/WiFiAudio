For Use:- https://wifiaudio-rishabh.pages.dev/

# Wi-Fi Audio — Windows to Android prototype

**Windows download:** https://wifiaudio-rishabh.pages.dev/
Share that page with friends. Each person runs the app on their own PC and pairs
their own phone; do not share private receiver links or local TLS keys.

Stream Windows system audio over Wi-Fi to an Android browser, which plays it
through the phone's paired Bluetooth earphones. The desktop does not need Bluetooth.
The phone supplies the Bluetooth radio. It cannot connect a Wi-Fi-only PC directly
to Bluetooth-only earbuds.

The Windows sender and Chrome receiver support listening and optional microphone
return for meetings. This is an early browser-based prototype, not a native Android
app or a verified background-audio application.



## Meetings: listen and speak

The return path is **phone/earbuds microphone -> Wi-Fi -> CABLE Input -> CABLE Output
-> desktop meeting app**. Windows sees a standard recording device, so applications
that let you select a Windows microphone can use it. Meet, Zoom and Teams have not
yet been individually tested; this is not a claim of universal compatibility.

1. Open WiFiAudio and choose **Listen + speak in meetings**. The app checks the driver
   and Windows microphone access. If needed, click **Set up meeting microphone**:
   after confirmation it downloads [VB-CABLE from its publisher](https://vb-audio.com/Cable/),
   checks its Authenticode signature and publisher, then opens the visible installer.
   Review its donationware terms, approve installation and restart if requested.
   The app never restarts Windows or silently changes default audio devices.
2. If mic access is blocked, click **Windows mic permission** and enable device,
   app and desktop-app microphone access. Click **Check again** in WiFiAudio.
3. Choose the Windows output you want to hear and click **Connect my phone**, then
   **Open setup guide**. No command or separate launcher is needed.
4. Complete the **one-time Android certificate setup** on the PC's pairing page:
   scan the certificate QR, download `WiFiAudio-CA.crt`, and install it using Android
   Settings > Security > Encryption & credentials > Install a certificate > CA
   certificate (names vary by phone). Compare its fingerprint to the one on the PC.
   Install only the certificate generated on your own PC. It is a local CA trust
   addition; remove it from Android's user credentials when no longer using the app.
5. Scan the **HTTPS receiver QR**, enable **Send my microphone to the meeting**, then
   tap Connect and allow microphone permission. Do not bypass certificate warnings:
   browser mic capture needs a trusted secure origin. Some managed phones prohibit
   user-installed CAs; this receiver cannot promise support on those phones.
6. In Meet/Zoom/Teams or another meeting app, choose **CABLE Output (VB-Audio Virtual
   Cable)** as the microphone. Choose your **normal Windows speakers/output** for
   meeting playback, not CABLE Input. Do not enable Windows "Listen to this device"
   on the cable: that would feed the microphone back into the outgoing stream.
7. The phone shows the active microphone and confirms when audio reaches the PC
   cable. Use **Mute microphone** to send silence, or Disconnect to release the mic.

Android/Chrome decide which microphones they expose. The mic selector shows the
available inputs after permission is granted; disconnect, select an input and
reconnect to change it. The default may be the **phone mic**, not the earbuds mic.
Guaranteed headset-mic routing and screen-off operation need a native Android app
and device tests; they are not implemented here. Bluetooth headset call mode can
reduce playback quality. Keep the page open and the phone awake.

Meeting mode uses HTTPS/WSS on port 8765 and a separate pairing/certificate service
on port 8766. The desktop interface stores private TLS keys in
`%LOCALAPPDATA%/WiFiAudio/tls`, never in GitHub or the download. Preserve that directory
to avoid trusting a new CA every update. Advanced CLI use retains its `.local/tls`
default, or uses an explicit `--tls-dir`.
Never share its private keys. New PC IP addresses produce a new server certificate
under the same CA; restart the app after changing networks and scan the new QR.

For other virtual cables: use `--list-playback-devices`, then
`--meeting --mic-output INDEX`. The selected device must be the cable's playback
endpoint; choose the matching recording endpoint in the meeting app. The app does
not change Windows default audio devices. `--device INDEX` selects the separate
outgoing desktop loopback device from `--list-devices`.

## Run the Windows app

Download and open the **single EXE** from the download page, or build from source
and open `dist/WiFiAudio.exe`. Version 0.3 includes its runtime: there is no ZIP to
extract, no `_internal` folder to carry and no separate Python install. First launch
may take a few seconds while the bundled runtime extracts to a temporary directory.

1. Pair your earbuds with the Android phone and select them for media playback.
2. Connect the PC and phone to the same private Wi-Fi, or connect the PC to the phone hotspot.
3. In WiFiAudio choose **Listen to PC audio**, choose the Windows output and click
   **Connect my phone**. Scan the app's QR with the phone and open it in Chrome.
4. Tap **Connect audio**, then start YouTube on the desktop. Tap the player's Play button if necessary.
5. Keep the phone page open and awake. Use **Disconnect** to stop; close the PC sender when done.

If the address selector has several entries, choose the PC's Wi-Fi address. If Windows asks
for firewall access, allow the app on your trusted private network. Guest networks
that isolate devices will not work. Do not mute the Windows audio output to silence
the PC: that can also silence captured audio, depending on the driver.

## Run from source

Requires existing Python 3.10+ on Windows and a working Windows audio output.
Clone this repository and open its directory before following these commands.
Run `Setup.cmd`, then `Start-Audio.cmd`. Both devices must share a trusted private
LAN or phone hotspot. Pair the earbuds with Android, scan the PC pairing QR and
tap Connect audio. Tap the audio player's Play button if autoplay is blocked.
The sender captures the selected Windows output only after a phone authenticates;
it does not capture the PC microphone or save audio. All sound on that output,
including notifications, can be transmitted.

`Start-Audio.cmd` opens the desktop interface; passing command-line flags opens the
advanced server instead (for example `Start-Audio.cmd --meeting`).
The standalone download opens the GUI directly. Its **Disconnect** button releases
audio devices; closing the window stops the owned server before exiting.

`Start-Audio.cmd --test-tone` selects synthetic 440 Hz audio instead of capture.
`Start-Audio.cmd --list-devices` lists loopback output indices; `--device INDEX`
selects one explicitly. `--advertise-host PC_IPV4` selects the address in the QR.
Ctrl+C stops the sender. A new launch creates a new pairing token.

To build: install `pyinstaller==6.22.3` into `.venv`, then run `Build.cmd`.
For browser checks, install `playwright==1.65.2` into `.venv`; tests use existing
Google Chrome and do not download a browser. Packaged process-lifecycle tests also
use the development-only `psutil` package.

## Verification

- Version 0.3's standalone EXE opens the actual desktop UI and closes normally.
  Hidden-window GUI tests cover device listing, QR display, start/stop/restart and
  stopping during startup. The desktop interface runs an owned in-process server.
- The driver helper accepted the official signed installer and rejected unsigned
  input and a validly signed executable from another publisher. It was tested in
  verification-only mode; no additional driver install was performed by these tests.
  The in-app downloader also fetched/extracted the official package in an isolated
  temporary folder and passed publisher verification without installing it.

- Seven local integration tests passed: real WebRTC test-tone frame delivery,
  disconnect/reconnect, exclusive listener, invalid authentication/malformed offer,
  receiver/QR pages, shutdown during negotiation and shutdown with active audio,
  microphone return delivery/cleanup and rejection when no destination is configured.
- Actual desktop Chrome received/played the synthetic stream and reconnected;
  no JavaScript errors. Mobile-sized layout inspected at 390 pixels wide.
- Windows Realtek WASAPI loopback opened and closed at 48 kHz, stereo.
  This was an open/close check, not a recorded YouTube-audio comparison.
- Python compilation, JavaScript syntax and dependency consistency checks passed.
- Packaged EXE listed Windows output devices, served its bundled QR/receiver pages,
  and streamed synthetic audio to actual desktop Chrome successfully.
- Meeting tests verified the local TLS chain and persistent CA, two-way desktop
  Chrome media with a synthetic browser microphone, mute/unmute, reconnect,
  microphone-track release and the permission-denied recovery path. Browser tests
  use an isolated certificate-error override; a separate HTTP client verifies the
  real CA chain. This does not establish Android certificate-store behavior.
- VB-CABLE Pack46 was downloaded from the publisher on 2026-11-20; its x64 installer
  had a valid Authenticode signature from BUREL VINCENT. Its render endpoint opened.
  The real recording-endpoint test initially failed while Windows microphone privacy
  was set to Deny. After access was enabled, the complete synthetic browser mic ->
  WebRTC -> CABLE Input -> CABLE Output recording path passed twice, including
  reconnect. The recording endpoint detected test audio and near-silence while muted.
  This verifies the Windows virtual-mic path, not a real Android headset or meeting call.
- Android Chrome, physical Bluetooth earbuds, Wi-Fi/hotspot traversal, screen-off
  behavior and video/audio sync remain unverified. Desktop Chrome is not Android evidence.

Run `.venv/Scripts/python.exe -m unittest -v test_stream`,
`.venv/Scripts/python.exe test_browser.py`, and
`.venv/Scripts/python.exe test_package.py` to repeat the local checks.
Run `.venv/Scripts/python.exe test_meeting.py` for the synthetic meeting test,
or add `--real-cable` to check actual VB-CABLE recording with synthetic browser
audio. The latter requires VB-CABLE and Windows microphone access; it does not
capture the user's physical microphone.

The receiver uses Chrome rather than a native Android app. Keep the page open
and phone awake. Headset disconnect can cause Android to play through the phone
speaker. Bluetooth and network buffering add unmeasured latency. Changing the
Windows output requires reconnecting. Protected audio may not be capturable.

WebRTC media uses DTLS-SRTP. Listening mode serves its page and signaling over
HTTP and is not authenticated against an active LAN attacker. Meeting mode uses
HTTPS with the locally generated CA; its initial certificate download must be
verified against the PC before trust is added. Use only a trusted
private network; do not expose it to the Internet. No STUN/TURN server is configured.
Pairing links authorize listening: keep them private. Windows Firewall may need
user-approved access for this Python process on private networks (TCP signaling
and WebRTC UDP); this prototype does not modify firewall settings.

## References

- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://github.com/s0d3s/PyAudioWPatch
- https://aiortc.readthedocs.io/en/latest/api.html
- https://www.bluetooth.com/learn-about-bluetooth/tech-overview/


