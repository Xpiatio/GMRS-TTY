While working on an idea of "detecting call signs" during check ins.  It got me thinking of the community who it hard of hearing, deaf or mute. I remember my sister using a TTY for communication over the telephone lines.  I'm wondering if going down this road to allow live transcription of the radio freq from a SDR/HT/Mobile unit into a computer/device with a software (built with Python and PyQt/PySide) that will live transcribe on screen.  It should also be able to text to speech transmit and always add the users call sign and name at the end of the text.

There should be a configuration page that allows the user to enter in their Callsign and their name and their location.  This should be saved to a config file. There should also be a separate screen accessible via a menu to manually add, modify, or remove known callsigns and names. The main page should show the configured call sign, name and location of the user at the top.  Main section of the screen should show incoming message stream, like a chat room style. And a text box at the bottom for new messages with an enter screen.
When sending messages, add the user's call sign and name to the end of the message if it has been more than 15 minutes since the call sign was last transmitted.

Since we don't have have a radio hooked up yet, I want to be able to trigger my laptops mic to simulate incoming audio from the radio.  When sending a message I want to be able hear the message through my laptop speakers.

We need to follow FCC rules for GMRS.

---

## Features built on top of the original brief

The shipped app has grown past this initial statement. The following capabilities are now part of the product (see `technical_spec.md` for the detailed spec and `README.md` for user-facing docs):

- **Fully offline operation** — no runtime network access; STT, VAD, and TTS models are pre-staged via `bootstrap_models.py` and loaded from `Models/` and `Voices/`. The app never attempts to download anything.
- **Voice activity detection (Silero VAD)** — only transcribes when a human is speaking; ignores static and kerchunks. VAD threshold is tunable.
- **Narrowband-FM audio preprocessing** — 300–3000 Hz bandpass + spectral-gating noise reduction applied per utterance before STT.
- **Auto-pause during TX** — STT pauses while the app is transmitting so the TTS isn't transcribed back.
- **PTT control (real hardware)** — Manual / VOX / USB FTDI–Serial (RTS or DTR) modes with lead-in/tail silence padding. The app keys the radio around TTS playback.
- **Voice preview** in the Configuration dialog.
- **Output device picker** — separate from the input device so TTS audio can be routed to a USB sound card / Signalink / Digirig channel feeding the radio.
- **NATO phonetic & digit readout for callsigns** — TTS spells callsign digits one at a time; the standalone ID button reads the call letters in NATO phonetic ("Whiskey Sierra Lima Zulu 2 3 3").
- **Standalone "This is" ID button** — one-click station ID that also resets the 15-minute ID timer.
- **Pending stations bar** — one-click `+ Add` pills for callsigns detected on RX that aren't yet in your contact list. Supports compact (`WSLZ233`), spaced (`W S L Z 2 3 3`), separator (`WSLZ-233`, `WSLZ.233`), and NATO-phonetic forms.
- **Cross-platform target list** — Raspberry Pi, Linux desktop, Windows. Multi-arch Docker image planned.