"""Diagnostic probe for the Mark II voice stack.

Run: python tests/voice_probe.py

Reports STT/TTS availability, lists microphones, records ONE short utterance
from the default microphone (locally - nothing is uploaded), transcribes it,
and speaks a confirmation line through the speakers.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import jarvis.voice as voice  # noqa: E402

voice.MAX_RECORD_S = 4  # keep the probe short

from jarvis.voice import VoiceIO, stt_available, tts_available  # noqa: E402

print("STT available:", stt_available())
print("TTS available:", tts_available())
try:
    import sounddevice as sd

    inputs = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
    print("microphones found:", len(inputs))
    for device in inputs[:5]:
        print("  -", device["name"])
except Exception as exc:
    print("sounddevice probe failed:", exc)
    raise SystemExit(1)

io = VoiceIO(on_status=lambda status: print("  >>", status))
print("\nRecording - say something (e.g. 'jarvis systems check')...")
heard = io.listen()
print("heard:", repr(heard))
print("last_error:", io.last_error or "(none)")

if heard:
    spoken = io.speak("JARVIS Mark Two online. I heard: " + heard)
else:
    spoken = io.speak("JARVIS Mark Two online. All systems nominal.")
print("TTS spoken:", spoken)
