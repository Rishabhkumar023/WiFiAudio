# Wi-Fi Audio — Windows to Android prototype

Stream Windows system audio over Wi-Fi to an Android browser, which plays it
through the phone's paired Bluetooth earphones. The desktop does not need Bluetooth.
The phone supplies the Bluetooth radio. It cannot connect a Wi-Fi-only PC directly
to Bluetooth-only earbuds.

The Windows sender and Chrome receiver are implemented. This is an early prototype,
not a verified Android background-audio application.

## Run the Windows app

Build from source using the instructions below, then open
`dist/WiFiAudio/WiFiAudio.exe`. **Copy the entire `dist/WiFiAudio` folder when moving
the app; copying only the EXE will not work.** Keep `_internal` beside the EXE.
This packaged build does not require a separate Python installation. The PC browser
opens a QR page; the console must stay open while listening.

1. Pair your earbuds with the Android phone and select them for media playback.
2. Connect the PC and phone to the same private Wi-Fi, or connect the PC to the phone hotspot.
3. Scan the PC's QR with the phone and open the link in Chrome.
4. Tap **Connect audio**, then start YouTube on the desktop. Tap the player's Play button if necessary.
5. Keep the phone page open and awake. Use **Disconnect** to stop; close the PC sender when done.

If more than one QR is shown, use the PC's Wi-Fi adapter address. If Windows asks
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
it does not capture a microphone or save audio. All sound on that output,
including notifications, can be transmitted.

`Start-Audio.cmd --test-tone` selects synthetic 440 Hz audio instead of capture.
`Start-Audio.cmd --list-devices` lists loopback output indices; `--device INDEX`
selects one explicitly. `--advertise-host PC_IPV4` selects the address in the QR.
Ctrl+C stops the sender. A new launch creates a new pairing token.

To build: install `pyinstaller==6.22.3` into `.venv`, then run `Build.cmd`.
For browser checks, install `playwright==1.65.2` into `.venv`; tests use existing
Google Chrome and do not download a browser.

## Verification

- Five local integration tests passed: real WebRTC test-tone frame delivery,
  disconnect/reconnect, exclusive listener, invalid authentication/malformed offer,
  receiver/QR pages, shutdown during negotiation and shutdown with active audio.
- Actual desktop Chrome received/played the synthetic stream and reconnected;
  no JavaScript errors. Mobile-sized layout inspected at 390 pixels wide.
- Windows Realtek WASAPI loopback opened and closed at 48 kHz, stereo.
  This was an open/close check, not a recorded YouTube-audio comparison.
- Python compilation, JavaScript syntax and dependency consistency checks passed.
- Packaged EXE listed Windows output devices, served its bundled QR/receiver pages,
  and streamed synthetic audio to actual desktop Chrome successfully.
- Android Chrome, physical Bluetooth earbuds, Wi-Fi/hotspot traversal, screen-off
  behavior and video/audio sync remain unverified. Desktop Chrome is not Android evidence.

Run `.venv/Scripts/python.exe -m unittest -v test_stream`,
`.venv/Scripts/python.exe test_browser.py`, and
`.venv/Scripts/python.exe test_package.py` to repeat the local checks.

The receiver uses Chrome rather than a native Android app. Keep the page open
and phone awake. Headset disconnect can cause Android to play through the phone
speaker. Bluetooth and network buffering add unmeasured latency. Changing the
Windows output requires reconnecting. Protected audio may not be capturable.

WebRTC media uses DTLS-SRTP, but this prototype serves its page and signaling over
HTTP. It is not authenticated against an active LAN attacker. Use only a trusted
private network; do not expose it to the Internet. No STUN/TURN server is configured.
Pairing links authorize listening: keep them private. Windows Firewall may need
user-approved access for this Python process on private networks (TCP signaling
and WebRTC UDP); this prototype does not modify firewall settings.

## References

- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://github.com/s0d3s/PyAudioWPatch
- https://aiortc.readthedocs.io/en/latest/api.html
- https://www.bluetooth.com/learn-about-bluetooth/tech-overview/

No code was copied from FlyingCarpet or BTAndroidApp.
