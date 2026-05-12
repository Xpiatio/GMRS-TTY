# Third-Party Notices

GMRS-TTY is licensed under the MIT License (see [LICENSE](LICENSE)).
It depends on and/or redistributes the following third-party components,
each under its own license. This file is provided to satisfy attribution
requirements and to make redistribution terms transparent.

## Runtime dependencies (installed via pip, not redistributed)

| Package | License | Project |
|---|---|---|
| PySide6 | LGPL v3 / commercial | https://wiki.qt.io/Qt_for_Python |
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| soundfile | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| numpy | BSD-3-Clause | https://numpy.org/ |
| piper-tts | MIT | https://github.com/rhasspy/piper |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| silero-vad | MIT | https://github.com/snakers4/silero-vad |
| noisereduce | MIT | https://github.com/timsainb/noisereduce |

These are installed at the user's site via `pip` and are not bundled in
this repository. Each retains its own license terms.

## Bundled voice models (`Voices/`)

The `.onnx` voice models in `Voices/` are pre-trained Piper TTS voices
redistributed from the `rhasspy/piper-voices` collection on Hugging Face.
Each voice has its own model card and license — please consult the upstream
source for authoritative terms.

Upstream: https://huggingface.co/rhasspy/piper-voices

| Voice file | Dataset | Upstream license (as published) | Attribution required |
|---|---|---|---|
| `en_US-amy-medium.onnx` | Amy | MIT | No |
| `en_US-arctic-medium.onnx` | CMU Arctic | Public domain / BSD-style (CMU Arctic terms) | No |
| `en_US-lessac-high.onnx` | Blizzard Challenge 2013 (Lessac) | BSD-3-Clause (per upstream model card) | Recommended |
| `en_US-libritts-high.onnx` | LibriTTS | **CC BY 4.0** | **Yes** |
| `en_US-ryan-high.onnx` | Ryan | MIT | No |

### Attribution for CC BY 4.0 voices

The LibriTTS-derived voice (`en_US-libritts-high`) is distributed under the
Creative Commons Attribution 4.0 International license. If you redistribute
or use this voice, you must:

- Credit the original creators of the LibriTTS dataset
  (Zen et al., "LibriTTS: A Corpus Derived from LibriSpeech for Text-to-Speech")
- Indicate that the voice model was trained on LibriTTS
- Link to the license: https://creativecommons.org/licenses/by/4.0/
- Indicate if changes were made

The Piper project provides per-voice `MODEL_CARD` files at:
https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US

## Models downloaded at runtime

`faster-whisper` downloads OpenAI Whisper model weights on first run
(default: `small.en`). Whisper model weights are released by OpenAI under
the MIT License. See: https://github.com/openai/whisper

`silero-vad` downloads its VAD model on first run, released under the
MIT License. See: https://github.com/snakers4/silero-vad

These models are not redistributed by this repository.
