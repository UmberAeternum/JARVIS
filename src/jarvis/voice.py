"""Mark II - the ears and mouth: microphone capture, speech-to-text, offline TTS.

Design:
- Push-to-talk, not always-listening: the user presses Enter on an empty line,
  the microphone records up to 10 s, silence is trimmed, and transcription
  runs locally. Audio never leaves the machine.
- STT is pluggable, best available wins:
    1. faster-whisper (best accuracy, multilingual) when its wheels exist for
       the running Python (currently <= 3.13),
    2. Vosk (Kaldi, wheel-independent - installs on any CPython) otherwise,
       with the small English model downloaded once (~40 MB) into the config
       directory. The download goes through the same SSRF-guarded fetcher as
       every other outbound request, and extraction is member-by-member with
       an explicit containment check (zip-slip proof).
- TTS is offline SAPI via pyttsx3; markdown is stripped before speaking and
  replies are capped at a spoken-length limit.
- Every component degrades gracefully: when a dependency, model or device is
  missing, listen() returns None and speak() returns False with the reason in
  last_error. The text chat path never depends on voice being available.

All heavy imports happen lazily inside methods, so the module can be imported
(and tested) on machines with no voice stack installed.
"""

from __future__ import annotations

import json
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import safety
from .config import config_dir

SAMPLE_RATE = 16_000
MAX_RECORD_S = 10
SPEECH_LIMIT = 600
SILENCE_FLOOR = 0.008

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
MAX_MODEL_BYTES = 300_000_000

# Spellings the small English model produces for "Jarvis"; the wake matcher
# accepts any of them so a slightly-off transcription still triggers.
WAKE_VARIANTS = ("jarvis", "jervis", "javis", "jarvic", "jarvez")


def wake_hit(partial_text: str, phrase: str = "") -> bool:
    """True when the wake phrase (or a JARVIS alias) appears in a partial.

    With a configured phrase (Mark XXVIII), the phrase's key word (its last
    word, e.g. 'umbra' from 'Hey UMBRA') triggers; the JARVIS aliases stay
    accepted as the in-experience alias.
    """
    lowered = (partial_text or "").lower()
    if phrase:
        words = phrase.lower().split()
        if words and words[-1] in lowered:
            return True
    return any(variant in lowered for variant in WAKE_VARIANTS)


def stt_available() -> tuple[bool, str]:
    """(ok, reason) for the best available speech-to-text stack."""
    missing = []
    for module in ("sounddevice", "numpy"):
        try:
            __import__(module)
        except Exception as exc:
            missing.append(f"{module} ({type(exc).__name__})")
    if missing:
        return False, (
            "voice STT unavailable - missing "
            + ", ".join(missing)
            + " - install it with: pip install jarvis-ai[voice]"
        )
    for module in ("faster_whisper", "vosk"):
        try:
            __import__(module)
            return True, ""
        except Exception:
            continue
    return False, (
        "voice STT unavailable - no backend (Whisper or Vosk) installed - "
        "install it with: pip install jarvis-ai[voice]"
    )


def tts_available() -> tuple[bool, str]:
    """(ok, reason) for the text-to-speech stack."""
    try:
        import pyttsx3  # noqa: F401 - availability probe only
    except Exception as exc:
        return False, (
            f"voice TTS unavailable ({type(exc).__name__}: {exc}) - "
            "install it with: pip install jarvis-ai[voice]"
        )
    return True, ""


def _barge_triggered(levels: list[float], floor: float = SILENCE_FLOOR, frames: int = 3) -> bool:
    """Barge-in detector (Mark XXVII): True when `frames` consecutive mic
    levels exceed the speech floor - the user is talking over the reply."""
    run = 0
    for value in levels:
        run = run + 1 if value > floor * 8 else 0
        if run >= frames:
            return True
    return False


def strip_markdown(text: str) -> str:
    """Reduce a markdown reply to something sane to speak aloud."""
    text = re.sub(r"```.*?```", " (code block omitted) ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> their label
    text = re.sub(r"[#>*_|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:SPEECH_LIMIT]


def _models_dir() -> Path:
    return config_dir() / "models"


def _vosk_model_path() -> Path:
    return _models_dir() / VOSK_MODEL_NAME


def _vosk_model_installed() -> bool:
    return (_vosk_model_path() / "am" / "final.mdl").exists()  # acoustic-model marker


def _ensure_vosk_model(on_status: Callable[[str], None]) -> tuple[bool, str]:
    """Download + extract the Vosk model once. Returns (ok, reason)."""
    if _vosk_model_installed():
        return True, ""
    on_status("downloading Vosk speech model (~40 MB, one time)")
    data, reason = safety.guarded_fetch_bytes(VOSK_MODEL_URL, MAX_MODEL_BYTES)
    if data is None:
        return False, f"Vosk model download failed: {reason}"
    root = _models_dir()
    root.mkdir(parents=True, exist_ok=True)
    on_status("extracting speech model")
    archive = root / "vosk-model.zip"
    archive.write_bytes(data)  # fixed constant filename inside the models dir
    try:
        resolved_root = root.resolve()
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.namelist()
            for member in members:
                resolved = (resolved_root / member).resolve()
                if not resolved.is_relative_to(resolved_root):
                    return False, "unsafe archive entry: " + member  # zip-slip guard
            for member in members:
                resolved = (resolved_root / member).resolve()
                if member.endswith("/"):
                    resolved.mkdir(parents=True, exist_ok=True)
                    continue
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(bundle.read(member))  # no extractall: per-member writes
    except Exception as exc:
        return False, f"Vosk model extraction failed: {exc}"
    finally:
        try:
            archive.unlink(missing_ok=True)
        except OSError:
            pass
    if not _vosk_model_installed():
        return False, "model extraction did not produce the expected folder"
    return True, ""


class VoiceIO:
    """Voice input/output with lazy, per-call imports and graceful failures."""

    def __init__(
        self,
        stt_model: str = "base",
        tts_enabled: bool = True,
        mic_device: int | None = None,
        on_status: Callable[[str], None] | None = None,
        profile: str = "",
    ):
        self.stt_model = stt_model  # whisper model size; ignored by the vosk backend
        self.tts_enabled = tts_enabled
        self.mic_device = mic_device
        self.on_status = on_status or (lambda status: None)
        self.profile = profile  # Mark XXIX: "" | "jarvis" (British butler)
        self.last_error = ""
        self._whisper = None  # cached WhisperModel
        self._vosk = None  # cached vosk Model
        self._backend = ""  # resolved once on first listen()

    # ------------------------------------------------------------------ ears

    def _pick_backend(self) -> str:
        """Resolve the best STT backend once: whisper if present, else vosk."""
        if self._backend:
            return self._backend
        try:
            from faster_whisper import WhisperModel  # noqa: F401

            self._backend = "whisper"
        except Exception:
            try:
                from vosk import Model  # noqa: F401

                self._backend = "vosk"
            except Exception:
                self._backend = "none"
        return self._backend

    def listen(self) -> str | None:
        """Record from the microphone and transcribe. Returns text or None."""
        ok, reason = stt_available()
        if not ok:
            self.last_error = reason
            return None
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:
            self.last_error = f"voice import failed: {exc}"
            return None

        backend = self._pick_backend()
        if backend == "none":
            self.last_error = "no STT backend - install one with: pip install jarvis-ai[voice]"
            return None

        try:
            self.on_status("listening - speak now (up to 10 s)")
            recording = sd.rec(
                int(SAMPLE_RATE * MAX_RECORD_S),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self.mic_device,
            )
            sd.wait()
        except Exception as exc:
            self.last_error = f"microphone capture failed: {exc}"
            return None

        pcm = np.squeeze(recording)  # int16 PCM
        audio = self._trim_silence(np, pcm.astype("float32") / 32768.0)
        if audio is None:
            self.last_error = "no speech detected (silence)"
            return None

        try:
            if backend == "whisper":
                text = self._transcribe_whisper(audio)
            else:
                text = self._transcribe_vosk(pcm)
        except Exception as exc:
            self.last_error = f"transcription failed: {exc}"
            return None
        return text or None

    def _transcribe_whisper(self, audio) -> str:
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self.on_status(f"loading Whisper model '{self.stt_model}' (first run downloads it)")
            self._whisper = WhisperModel(self.stt_model, device="cpu", compute_type="int8")
        self.on_status("transcribing (Whisper)")
        segments, _info = self._whisper.transcribe(audio, beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _transcribe_vosk(self, pcm) -> str:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        ok, reason = _ensure_vosk_model(self.on_status)
        if not ok:
            raise RuntimeError(reason)
        if self._vosk is None:
            SetLogLevel(-1)
            self._vosk = Model(str(_vosk_model_path()))
        self.on_status("transcribing (Vosk)")
        recognizer = KaldiRecognizer(self._vosk, SAMPLE_RATE)
        recognizer.AcceptWaveform(pcm.tobytes())  # int16 PCM bytes
        result = json.loads(recognizer.FinalResult())
        return str(result.get("text", "")).strip()

    @staticmethod
    def _trim_silence(np, audio):
        """Trim leading/trailing low-energy audio; None when all silence."""
        frame = SAMPLE_RATE // 10  # 0.1 s frames
        if audio.shape[0] <= frame * 2:
            return None
        energies = np.array(
            [
                float(np.sqrt(np.mean(audio[i : i + frame] ** 2)))
                for i in range(0, audio.shape[0] - frame, frame)
            ]
        )
        threshold = max(SILENCE_FLOOR, float(energies.max()) * 0.06)
        loud = np.nonzero(energies > threshold)[0]
        if loud.size == 0:
            return None
        start = max(0, int(loud[0]) * frame - SAMPLE_RATE // 10)
        end = min(audio.shape[0], (int(loud[-1]) + 1) * frame + SAMPLE_RATE // 5)
        return audio[start:end]

    def listen_wake(self, max_command_s: float = 8.0, phrase: str = "") -> str | None:
        """Hands-free: block until the wake phrase is heard, then capture the
        command until trailing silence or the time cap. Returns the command
        text with the wake word stripped, or None (reason in last_error).

        Requires the Vosk backend: it is the only streaming recognizer here.
        The phrase is configurable (Mark XXVIII); empty = the JARVIS aliases.
        """
        ok, reason = stt_available()
        if not ok:
            self.last_error = reason
            return None
        if self._pick_backend() != "vosk":
            self.last_error = (
                "wake word mode needs the Vosk backend (its streaming recognizer) - "
                "install it with: pip install jarvis-ai[voice]"
            )
            return None
        try:
            import numpy as np
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except Exception as exc:
            self.last_error = f"voice import failed: {exc}"
            return None
        ok, reason = _ensure_vosk_model(self.on_status)
        if not ok:
            self.last_error = reason
            return None
        if self._vosk is None:
            SetLogLevel(-1)
            self._vosk = Model(str(_vosk_model_path()))

        recognizer = KaldiRecognizer(self._vosk, SAMPLE_RATE)
        self.on_status(f"listening for the wake word ('{phrase or 'Jarvis'}')")
        triggered_at: float | None = None
        last_speech = 0.0
        chunks_after: list = []
        idle_deadline = time.time() + 300  # absolute idle cap: 5 minutes

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=4000,  # 0.25 s frames
                device=self.mic_device,
            ) as stream:
                while time.time() < idle_deadline:
                    frames, _overflow = stream.read(4000)
                    pcm = np.squeeze(frames)
                    if triggered_at is None:
                        recognizer.AcceptWaveform(pcm.tobytes())
                        partial = json.loads(recognizer.PartialResult()).get("partial", "")
                        if wake_hit(partial, phrase):
                            triggered_at = time.time()
                            last_speech = triggered_at
                            chunks_after = [pcm]
                            self.on_status("wake word detected - go ahead, Sir")
                    else:
                        chunks_after.append(pcm)
                        rms = float(np.sqrt(np.mean(pcm.astype("float32") ** 2)))
                        if rms > SILENCE_FLOOR:
                            last_speech = time.time()
                        elapsed = time.time() - triggered_at
                        silent_long_enough = (time.time() - last_speech) > 1.2
                        if elapsed > max_command_s or (silent_long_enough and elapsed > 1.5):
                            for chunk in chunks_after:
                                recognizer.AcceptWaveform(chunk.tobytes())
                            result = json.loads(recognizer.FinalResult())
                            text = str(result.get("text", "")).strip()
                            lowered = text.lower()
                            keys = (*WAKE_VARIANTS,
                                    *(phrase.lower().split()[-1:] if phrase.split() else ()))
                            for variant in keys:
                                if lowered.startswith(variant):
                                    text = text[len(variant):].strip(" ,.!?")
                                    break
                            return text or None
        except Exception as exc:
            self.last_error = f"wake listening failed: {exc}"
            return None
        self.last_error = "wake timeout - no wake word heard"
        return None

    # ------------------------------------------------------------------ mouth

    def speak(self, text: str, barge_in: bool = False) -> bool:
        """Speak a reply aloud. Returns False (with last_error set) on failure.

        profile (Mark XXIX): "jarvis" selects a British-English SAPI voice
        (dry, precise butler register) at a slightly reduced rate; any other
        profile value falls back to the system default voice - the text path
        never depends on a matching voice existing.

        barge_in (Mark XXVII): while speaking, the microphone is monitored and
        the user talking over the reply stops the speech immediately.
        """
        if not self.tts_enabled or not text.strip():
            return False
        ok, reason = tts_available()
        if not ok:
            self.last_error = reason
            return False
        spoken = strip_markdown(text)
        if not spoken:
            return False
        try:
            import pyttsx3

            engine = pyttsx3.init()  # fresh engine per utterance: reliable on SAPI5
            if self.profile == "jarvis":
                _apply_jarvis_voice(engine)
            monitor_stop = threading.Event()
            if barge_in:
                def monitor() -> None:
                    try:
                        import numpy as np
                        import sounddevice as sd

                        levels: list[float] = []
                        with sd.InputStream(
                            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=4000, device=self.mic_device,
                        ):
                            while not monitor_stop.is_set():
                                frames, _overflow = sd.read(4000)
                                pcm = np.squeeze(frames)
                                levels.append(
                                    float(np.sqrt(np.mean(pcm.astype("float32") ** 2)))
                                )
                                if _barge_triggered(levels[-8:]):
                                    try:
                                        engine.stop()
                                    except Exception:
                                        pass
                                    return
                    except Exception:
                        return  # no microphone: barge-in unavailable this round

                threading.Thread(target=monitor, daemon=True).start()
            try:
                engine.say(spoken)
                engine.runAndWait()
            finally:
                engine.stop()
                monitor_stop.set()
            return True
        except Exception as exc:
            self.last_error = f"TTS failed: {exc}"
            return False


def _apply_jarvis_voice(engine) -> None:
    """Best-effort British-butler voice profile: prefer an en-GB SAPI voice
    (Hazel/George on Windows), slightly slower rate. Silent fallback to the
    system default when no British voice exists."""
    try:
        wanted = ("en-gb", "hazel", "george", "british", "gbr")
        for voice in engine.getProperty("voices"):
            haystack = (str(getattr(voice, "id", "")) + " " + str(getattr(voice, "name", ""))).lower()
            if any(tag in haystack for tag in wanted):
                engine.setProperty("voice", voice.id)
                break
        rate = engine.getProperty("rate")
        if isinstance(rate, (int, float)) and rate > 150:
            engine.setProperty("rate", int(rate * 0.92))
    except Exception:
        pass  # profile is cosmetic - never break the spoken reply
