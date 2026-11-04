# UMBRA

[![CI](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml/badge.svg)](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml)

**The shadow that works for you.** A local-first AI assistant for your PC and your pocket — it hears you, sees your screen, remembers what you tell it, anticipates, and speaks. Built on a safety architecture where every powerful action passes a human confirmation gate.

UMBRA works with a **cloud brain** (Z.AI GLM, OpenAI, Google Gemini, or any OpenAI-compatible API) or a **local brain** (Ollama / LM Studio) — and can chain both with automatic failover.

## Two editions

| | **LITE** — free | **PRO** — license key |
|---|---|---|
| Chat, voice, memory | ✓ | ✓ |
| Health Oracle (HR/HRV screening) | ✓ | ✓ |
| Reminders + morning briefing | ✓ | ✓ |
| `/look` screenshots | ✓ | ✓ |
| Avatar (web face) | ✓ | ✓ |
| `/live` screen sharing | — | ✓ |
| **Bridge** — full agent over your LAN | — | ✓ |
| **Portal** — WebXR room for headsets | — | ✓ |
| **Screen control** — click/type/scroll | — | ✓ |
| **Watchtower** — ambient rules | — | ✓ |

## Install (LITE — free)

Requires Python 3.10+.

```bash
git clone https://github.com/UmberAeternum/JARVIS.git
cd JARVIS
pip install .
umbra        # or: python -m jarvis
```

The setup wizard walks you through the brain: pick a provider, paste your API key (validated live), done. Keys and all data stay on your machine.

Optional extras: `pip install ".[all]"` — voice, vision, screen control deps, keychain storage.

## PRO

PRO features are unlocked by a signed license key:

```bash
jarvis license activate UMBRA-xxxx.yyyy
jarvis license status
```

Keys are Ed25519-signed by the publisher — they cannot be forged, and they never leave your machine after activation. See the EULA (`LICENSE`) for terms.

## The bodies

| Surface | Command |
|---|---|
| Desktop CLI (all tools, confirmations) | `umbra` / `jarvis` / `python -m jarvis` |
| Phone HUD ([launcher repo](https://github.com/UmberAeternum/jarvis-launcher)) | APK from releases; DESK ⌁ connects to the Bridge |
| Avatar (web face with lip sync) | `jarvis face` |
| Portal (WebXR room for headsets) | `jarvis portal` |
| Sentinel (proactive daemon) | `jarvis sentinel` |
| The Oracle (health report) | `jarvis health` |

## Security model

- **Bring your own key.** No API key ships with this software; keys are stored encrypted on-device and only sent to the provider you configure.
- **The gate lives in code, not prompts.** Dangerous actions trigger an interactive confirmation — including remotely, over the Bridge, as APPROVE/DENY on your phone.
- **Argument-list execution only.** No shell ever parses model-generated text.
- **Outbound URLs are guarded** (scheme, host, resolved-IP, no redirects). Local-first everywhere else.

## Privacy

Local-first: license, memories, health samples, reminders and voice transcription are stored on your device. Only your AI-provider traffic leaves the machine, using your own key.

## Health disclaimer

The Oracle is an informational heuristic against your own recorded baseline. It is not medical advice, not a diagnosis, and not a medical device.

## License

Proprietary — see [LICENSE](LICENSE) (freemium EULA: LITE free for personal use; PRO per-key). Third-party attributions: [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
