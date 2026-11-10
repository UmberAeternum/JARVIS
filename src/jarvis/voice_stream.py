"""Phase 12 - the streaming voice layer: STT/TTS provider abstraction.

voice.py keeps the hardware paths (push-to-talk, wake word, SAPI speech);
this module layers the *streaming* provider model on top of it:

- STT providers implement accept(pcm16_bytes) -> partial and finalize() ->
  text. Local first (Vosk streams partials); a cloud endpoint is available
  only when the user sets voice.cloud_stt=true AND voice.stt_provider=cloud -
  audio then leaves the machine to THAT endpoint, which is stated in
  `jarvis settings show` and the wizard note. Cloud STT is batch: no
  partials, one final result (documented, not hidden).
- TTS providers speak sentence-by-sentence with a barge-in probe between
  chunks. Cloud TTS refuses sensitive text (the router's sensitivity gate)
  and falls back to the local SAPI voice - a reply that quotes a private
  memory never leaves the machine as audio.
- Latency budget: first partial within 1.2 s of audio, subsequent partials
  at most every 0.7 s. listen_stream measures both (wall clock) and reports
  whether the budget held; tests assert the budget logic with a fake clock.
- Live captions: partials and finals are forwarded to the Orb HUD's caption
  line via hud.HUD (loopback, display only). The listening indicator is the
  HUD's state - set to "listening" for the whole capture and back after.
- Text fallback everywhere: when no provider or device exists the callers
  fall back to typed text; nothing in the text path depends on voice.

Everything here is testable without hardware: listen_stream consumes any
iterator of PCM-16 chunks, so tests feed synthetic bytes and scripted
providers. The only untestable-without-hardware piece is the mic InputStream
in wake_stream_loop - marked MOCKED in the phase report.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Callable, Iterable

from . import safety
from .config import Config
from .voice import SAMPLE_RATE, wake_hit

# Latency budget (documented in SUPPORT.md wording: "measured with mocks").
FIRST_PARTIAL_BUDGET_S = 1.2
PARTIAL_BUDGET_S = 0.7
MAX_CLOUD_AUDIO_BYTES = 10_000_000  # 10 MB per request
BARGE_FRAMES = 3  # consecutive loud frames = barge-in (parity with voice.py)


# ------------------------------------------------------------------ STT


class STTStream:
    """A streaming recognizer: feed PCM-16 mono 16 kHz chunks, read partials."""

    name = "abstract"

    def accept(self, pcm16: bytes) -> str:
        raise NotImplementedError

    def finalize(self) -> str:
        raise NotImplementedError


class VoskStream(STTStream):
    """Local streaming recognizer (Vosk/Kaldi). Partials come for free."""

    name = "local-vosk"

    def __init__(self, on_status: Callable[[str], None] | None = None) -> None:
        self.on_status = on_status or (lambda status: None)
        self._recognizer = None
        self.last_error = ""

    def _ensure(self) -> bool:
        if self._recognizer is not None:
            return True
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            from .voice import _ensure_vosk_model, _vosk_model_path

            ok, reason = _ensure_vosk_model(self.on_status)
            if not ok:
                self.last_error = reason
                return False
            SetLogLevel(-1)
            self._recognizer = KaldiRecognizer(Model(str(_vosk_model_path())), SAMPLE_RATE)
            return True
        except Exception as exc:
            self.last_error = f"vosk stream unavailable: {exc}"
            return False

    def accept(self, pcm16: bytes) -> str:
        if not self._ensure():
            return ""
        try:
            self._recognizer.AcceptWaveform(pcm16)
            return str(json.loads(self._recognizer.PartialResult()).get("partial", "")).strip()
        except Exception:
            return ""

    def finalize(self) -> str:
        if self._recognizer is None:
            return ""
        try:
            result = json.loads(self._recognizer.FinalResult())
            return str(result.get("text", "")).strip()
        except Exception:
            return ""


class CloudCompatSTT(STTStream):
    """Batch cloud transcription against an OpenAI-compatible endpoint.

    Batch by design: audio accumulates locally (size-capped), finalize POSTs
    once. No partials - callers get captions only at the end, which the UI
    states rather than fakes. Audio leaves the machine ONLY when the user
    enabled voice.cloud_stt AND picked voice.stt_provider=cloud.
    """

    name = "cloud-compat"

    def __init__(self, endpoint: str, api_key: str,
                 on_status: Callable[[str], None] | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.on_status = on_status or (lambda status: None)
        self._buf = b""
        self.last_error = ""

    def accept(self, pcm16: bytes) -> str:
        if len(self._buf) + len(pcm16) > MAX_CLOUD_AUDIO_BYTES:
            self.last_error = "audio exceeded the cloud STT size cap - capture stopped"
            return ""
        self._buf += pcm16
        return ""  # batch: no partials

    def finalize(self) -> str:
        if not self._buf:
            return ""
        self.on_status("sending audio for transcription (cloud, opt-in)")
        boundary = "umbra-audio-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="audio.pcm16.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8") + self._buf + f"\r\n--{boundary}--\r\n".encode("utf-8")
        try:
            request = urllib.request.Request(
                self.endpoint + "/audio/transcriptions",
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                },
            )
            opener = build_guarded_opener()
            with opener.open(request, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return str(payload.get("text", "")).strip()
        except Exception as exc:
            self.last_error = f"cloud STT failed: {exc}"
            return ""


def build_guarded_opener():
    """urllib opener with redirects refused (SSRF rule parity with safety.py)."""
    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            return None

    return urllib.request.build_opener(_NoRedirects)


def make_stt_stream(cfg: Config, on_status: Callable[[str], None] | None = None) -> tuple[STTStream | None, str]:
    """Provider factory - the privacy gate lives here. Local is the default;
    cloud requires TWO explicit settings (stt_provider=cloud AND
    cloud_stt=true) plus a valid endpoint."""
    on_status = on_status or (lambda status: None)
    provider = (cfg.voice.stt_provider or "local").lower()
    if provider == "cloud":
        if not cfg.voice.cloud_stt:
            return None, "cloud STT requested but voice.cloud_stt is false (opt-in gate)"
        endpoint = cfg.voice.cloud_stt_url or cfg.brains.primary.base_url
        if not endpoint:
            return None, "cloud STT needs voice.cloud_stt_url or a brain base_url"
        ok, reason = safety.check_brain_endpoint(endpoint)
        if not ok:
            return None, f"cloud STT endpoint rejected: {reason}"
        return CloudCompatSTT(endpoint, cfg.brains.primary.api_key, on_status), ""
    return VoskStream(on_status), ""


# ------------------------------------------------------------------ TTS


def split_for_speech(text: str, limit: int = 240) -> list[str]:
    """Split a reply into sentence-ish chunks a speaker can barge between."""
    pieces = re.split(r"(?<=[.!?])\s+", strip_for_speech(text))
    return [piece for piece in (p.strip() for p in pieces) if piece][:12]


def strip_for_speech(text: str) -> str:
    """Minimal reduction for the chunker; full stripping stays voice.py's."""
    from .voice import strip_markdown

    return strip_markdown(text)


class TTSStream:
    """A speaker: speak_stream(text, barge) -> False when barged/stopped."""

    name = "abstract"

    def speak_stream(self, text: str, barge: Callable[[], bool]) -> bool:
        raise NotImplementedError


class LocalTTS(TTSStream):
    """Sentence-chunked SAPI speech (pyttsx3), one engine, barge between."""

    name = "local-sapi"

    def __init__(self, profile: str = "", on_error: Callable[[str], None] | None = None) -> None:
        self.profile = profile
        self.on_error = on_error or (lambda message: None)

    def speak_stream(self, text: str, barge: Callable[[], bool]) -> bool:
        try:
            import pyttsx3
        except Exception as exc:
            self.on_error(f"TTS unavailable ({exc}) - text fallback")
            return False
        spoken_any = False
        try:
            engine = pyttsx3.init()
            if self.profile == "jarvis":
                from .voice import _apply_jarvis_voice

                _apply_jarvis_voice(engine)
            for chunk in split_for_speech(text):
                if barge():
                    return False  # barged or stopped: something was heard
                engine.say(chunk)
                engine.runAndWait()
                spoken_any = True
            return True
        except Exception as exc:
            self.on_error(f"TTS failed: {exc}")
            return spoken_any


class CloudCompatTTS(TTSStream):
    """OpenAI-compatible speech endpoint, gated: refuses sensitive text."""

    name = "cloud-compat"

    def __init__(self, endpoint: str, api_key: str, voice: str = "",
                 on_status: Callable[[str], None] | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.voice = voice or "alloy"
        self.on_status = on_status or (lambda status: None)

    def allowed(self, text: str) -> tuple[bool, str]:
        from .brain.router import is_sensitive

        if is_sensitive(text):
            return False, "sensitive text never leaves the machine as audio (privacy gate)"
        ok, reason = safety.check_brain_endpoint(self.endpoint)
        if not ok:
            return False, f"cloud TTS endpoint rejected: {reason}"
        return True, ""

    def speak_stream(self, text: str, barge: Callable[[], bool]) -> bool:
        ok, reason = self.allowed(text)
        if not ok:
            self.on_status(f"cloud TTS refused: {reason} - using local voice")
            return False
        self.on_status("synthesizing speech (cloud, opt-in)")
        body = json.dumps({"model": "tts-1", "voice": self.voice,
                           "input": text[:2000]}).encode("utf-8")
        try:
            request = urllib.request.Request(
                self.endpoint + "/audio/speech",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                },
            )
            with build_guarded_opener().open(request, timeout=30) as resp:
                audio = resp.read(MAX_CLOUD_AUDIO_BYTES)
            return play_wav_bytes(audio, barge)
        except Exception as exc:
            self.on_status(f"cloud TTS failed: {exc} - text fallback")
            return False


def play_wav_bytes(audio: bytes, barge: Callable[[], bool]) -> bool:
    """Play WAV/PCM bytes through sounddevice. Hardware path (MOCKED in tests)."""
    try:
        import io

        import sounddevice as sd
        import wave

        with wave.open(io.BytesIO(audio)) as wav:
            frames = wav.readframes(wav.getnframes())
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
        sd.play(frames, samplerate=rate, channels=channels, dtype=f"int{width * 8}")
        while sd.get_stream().active:
            if barge():
                sd.stop()
                return False
            sd.sleep(50)
        return True
    except Exception:
        return False


# ------------------------------------------------------------ orchestration


def listen_stream(
    provider: STTStream,
    chunks: Iterable[bytes],
    on_partial: Callable[[str], None] | None = None,
    on_final: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_state_change: Callable[[str], None] | None = None,
) -> tuple[str, dict]:
    """Feed PCM chunks to the provider, emit distinct partials, measure the
    latency budget. Returns (final_text, latency_report).

    on_state_change gets "listening" before the first chunk and "idle" at the
    end (the HUD listening indicator). should_stop (the kill switch) halts
    the capture immediately.
    """
    on_partial = on_partial or (lambda text: None)
    on_final = on_final or (lambda text: None)
    should_stop = should_stop or (lambda: False)
    on_state_change = on_state_change or (lambda state: None)
    loop_start = time.monotonic()
    last_partial = ""
    first_at: float | None = None
    last_at = 0.0
    max_gap = 0.0
    on_state_change("listening")
    for chunk in chunks:
        if should_stop():
            break
        partial = provider.accept(chunk)
        if partial and partial != last_partial:
            now = time.monotonic()
            if first_at is None:
                first_at = now
            else:
                max_gap = max(max_gap, now - last_at)
            last_at = now
            last_partial = partial
            on_partial(partial)
    final = provider.finalize() if not should_stop() else ""
    on_state_change("idle")
    first_partial_s = None if first_at is None else first_at - loop_start
    within = max_gap <= PARTIAL_BUDGET_S and (
        first_partial_s is None or first_partial_s <= FIRST_PARTIAL_BUDGET_S
    )
    report = {
        "first_partial_s": None if first_partial_s is None else round(first_partial_s, 4),
        "first_partial_budget_s": FIRST_PARTIAL_BUDGET_S,
        "max_partial_gap_s": round(max_gap, 4),
        "budget_s": PARTIAL_BUDGET_S,
        "within_budget": within,
        "provider": getattr(provider, "name", "?"),
        "stopped": should_stop(),
    }
    on_final(final)
    return final, report


def wake_stream_loop(
    provider: STTStream,
    chunks: Iterable[bytes],
    phrase: str,
    on_partial: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_command_s: float = 8.0,
) -> str:
    """Wake-word mode over a streaming provider: partials are checked with
    the existing wake matcher; after the wake word, audio accumulates until
    trailing silence (RMS floor) or the cap, then finalize() returns the
    command. Hardware capture lives in the caller - this is the pure loop.
    """
    on_partial = on_partial or (lambda text: None)
    on_status = on_status or (lambda status: None)
    should_stop = should_stop or (lambda: False)
    triggered = False
    triggered_at = 0.0
    last_speech = 0.0
    # RMS floor on int16 chunks: speech is >> 300, silence ~ 0-100
    floor = 300
    for chunk in chunks:
        if should_stop():
            return ""
        partial = provider.accept(chunk)
        if not triggered:
            if wake_hit(partial, phrase):
                triggered = True
                triggered_at = time.monotonic()
                last_speech = triggered_at
                on_status("wake word detected - go ahead")
            elif partial:
                on_partial(partial)  # captions while waiting for the wake word
        else:
            if rms16(chunk) > floor:
                last_speech = time.monotonic()
            now = time.monotonic()
            elapsed = now - triggered_at
            silent = (now - last_speech) > 1.2
            if elapsed > max_command_s or (silent and elapsed > 1.5):
                break
    if not triggered:
        return ""
    if should_stop():
        return ""
    text = provider.finalize()
    # strip the wake-word prefix (parity with voice.listen_wake)
    lowered = text.lower()
    keys = ("jarvis", "jervis", "javis", "jarvic", "jarvez",
            *(phrase.lower().split()[-1:] if phrase.split() else ()))
    for variant in keys:
        if lowered.startswith(variant):
            text = text[len(variant):].strip(" ,.!?")
            break
    return text


def rms16(pcm16: bytes) -> float:
    """Root mean square of an int16 PCM chunk (speech-energy probe)."""
    import struct

    n = len(pcm16) // 2
    if not n:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm16[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


# ------------------------------------------------------------------ entry


def speak_reply(
    cfg: Config, text: str, barge_in: bool = False,
    on_status: Callable[[str], None] | None = None,
) -> bool:
    """The one call sites use to speak: picks the provider per config,
    applies the privacy gate, feeds the HUD captions, falls back local.
    Returns False when nothing was spoken (text fallback)."""
    from . import hud as hud_module
    from .voice import VoiceIO

    on_status = on_status or (lambda status: None)
    if not cfg.voice.tts_enabled:
        return False  # speech is opt-in; the text reply already went out
    spoken_via_cloud = False
    if (cfg.voice.tts_provider or "local").lower() == "cloud" and cfg.voice.cloud_tts:
        endpoint = cfg.voice.cloud_tts_url or cfg.brains.primary.base_url
        if endpoint:
            cloud = CloudCompatTTS(endpoint, cfg.brains.primary.api_key, on_status=on_status)
            ok, reason = cloud.allowed(text)
            if ok:
                spoken_via_cloud = cloud.speak_stream(text, barge=lambda: False)
            else:
                on_status(f"cloud TTS refused: {reason}")
    if spoken_via_cloud:
        hud_module.HUD.set_caption(strip_for_speech(text)[:400])
        return True
    local = LocalTTS(profile=cfg.voice.profile, on_error=on_status)
    spoken = False
    if barge_in:
        # SAPI barge-in with the mic monitor stays voice.py's battle-tested path.
        vio = VoiceIO(tts_enabled=True, profile=cfg.voice.profile)
        spoken = vio.speak(text, barge_in=True)
    else:
        spoken = bool(local.speak_stream(text, barge=lambda: False))
    if spoken:
        hud_module.HUD.set_caption(strip_for_speech(text)[:400])
        hud_module.set_state("speaking")
    return spoken
