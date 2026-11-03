"""Mark III - the eyes: screen capture, change detection, vision queries.

Design:
- capture(): mss screen grab -> Pillow downscale -> JPEG bytes sized for
  vision-API payloads.
- changed(): cheap perceptual digest (16x16 grayscale threshold hash) so
  watch mode only spends tokens when the screen meaningfully changes.
- build_vision_message(): the OpenAI-compatible multimodal user message
  (text part + base64 JPEG data URL) accepted by every supported provider.

All heavy imports happen lazily, so the module can be imported and tested on
machines with no display stack installed.
"""

from __future__ import annotations

import base64
import io


def available() -> tuple[bool, str]:
    """(ok, reason) for the vision stack."""
    missing = []
    for module in ("mss", "PIL"):
        try:
            __import__(module)
        except Exception as exc:
            missing.append(f"{module} ({type(exc).__name__})")
    if missing:
        return False, (
            "vision unavailable - missing "
            + ", ".join(missing)
            + " - install it with: pip install jarvis-ai[vision]"
        )
    return True, ""


def _resampling():
    from PIL import Image

    return getattr(Image, "Resampling", Image).LANCZOS


def capture(monitor: int = 0, max_width: int = 1280, quality: int = 70) -> bytes:
    """Capture a screen as JPEG bytes. Raises RuntimeError with the reason."""
    try:
        import mss
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(
            f"vision stack missing ({exc}) - install it with: pip install jarvis-ai[vision]"
        ) from exc
    try:
        with mss.mss() as sct:
            index = monitor + 1 if monitor >= 0 else 0  # mss: [0]=all, [1]=primary
            if index >= len(sct.monitors):
                index = 1 if len(sct.monitors) > 1 else 0
            raw = sct.grab(sct.monitors[index])
    except Exception as exc:
        raise RuntimeError(f"screen capture failed: {exc}") from exc

    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * ratio))), _resampling())
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def digest(image_bytes: bytes, size: int = 16) -> str:
    """Cheap perceptual digest: downscaled grayscale threshold hash.

    The mean-relative hash is brightness-blind on uniform frames (every pixel
    equals the mean, so solid black and solid white hash identically), so the
    last 8 texture bits are replaced with the frame's 8-bit mean brightness.
    The digest stays exactly 256 chars; two adjacent brightness levels differ
    by 1-2 bits (under the 2% change threshold), while uniform frames of
    different brightness differ by 8 bits (over it).
    """
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("L").resize((size, size), _resampling())
    pixels = list(image.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel > average else "0" for pixel in pixels)
    return bits[:-8] + format(int(average) & 0xFF, "08b")


def changed(previous: str | None, image_bytes: bytes, threshold: float = 0.02) -> tuple[bool, str]:
    """(did_change, current_digest) by Hamming distance against the last frame."""
    current = digest(image_bytes)
    if previous is None or len(previous) != len(current):
        return True, current
    distance = sum(1 for a, b in zip(previous, current) if a != b)
    return (distance / len(current)) > threshold, current


def build_vision_message(text: str, image_bytes: bytes) -> dict:
    """Build an OpenAI-compatible multimodal user message (text + JPEG part)."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}},
        ],
    }
