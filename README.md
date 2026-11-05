# UMBRA

[![CI](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml/badge.svg)](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/UmberAeternum/JARVIS)](https://github.com/UmberAeternum/JARVIS/releases/latest)

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
| Dashboard (local web mission control) | ✓ | ✓ |
| `/live` screen sharing | — | ✓ |
| **Bridge** — full agent over your LAN | — | ✓ |
| **Portal** — WebXR room for headsets | — | ✓ |
| **Screen control** — click/type/scroll | — | ✓ |
| **Watchtower** — ambient rules | — | ✓ |

## Install (LITE — free)

**No Python?** Grab the standalone [UMBRA.exe from the latest release](https://github.com/UmberAeternum/JARVIS/releases/latest) — double-click and the setup wizard handles the rest. Verify the download with the attached `SHA256SUMS`.

From source, requires Python 3.10+:

```bash
git clone https://github.com/UmberAeternum/JARVIS.git
cd JARVIS
pip install .
umbra        # or: python -m jarvis
```

The setup wizard walks you through the brain: pick a provider, paste your API key (validated live), optional voice, optional PRO activation — done. Re-run it any time with `jarvis setup` (non-interactive for CI: `jarvis setup --yes --provider zai --api-key ...`, or `--local` for Ollama). Inspect or change settings later with `jarvis settings show | set <key>=<value> | reset`. Updates: `jarvis update check` verifies a signed release manifest and prints release notes + URL — report-only, nothing is ever auto-installed (disable the startup check with `jarvis settings set updates.check_on_start=false`). Keys and all data stay on your machine.

Optional extras: `pip install ".[all]"` — voice, vision, screen control deps, keychain storage.

## PRO

PRO features are unlocked by a signed license key:

```bash
jarvis license activate UMBRA-xxxx.yyyy
jarvis license status
```

Keys are Ed25519-signed by the publisher — they cannot be forged, and they never leave your machine after activation. See the EULA (`LICENSE`) for terms.

## Profiles

UMBRA supports isolated profiles — each with its own brain config, memories, conversations, health data and license. Your existing data is the `default` profile; nothing moves or migrates.

```bash
jarvis profile list                 # see profiles, active one marked
jarvis profile create work
jarvis profile use work             # switch; first run there starts the wizard
jarvis profile delete work
```

Move data between machines or profiles:

```bash
jarvis export --out backup.json     # secrets excluded by default
jarvis export --include-secrets     # requires confirmation; the file holds plaintext keys
jarvis import backup.json           # restores into the active profile (merge, never destroy)
```

## The bodies

| Surface | Command |
|---|---|
| Desktop CLI (all tools, confirmations) | `umbra` / `jarvis` / `python -m jarvis` |
| Phone HUD ([launcher repo](https://github.com/UmberAeternum/jarvis-launcher)) | APK from releases; DESK ⌁ = full agent over the LAN + session history |
| Avatar (web face with lip sync) | `jarvis face` |
| **Dashboard** (local web mission control: **full agent** with tools + in-browser APPROVE/DENY, session resume, Oracle, memory, kanban, watchtower, settings) | `jarvis dashboard` |
| Portal (WebXR room for headsets) | `jarvis portal` |
| Sentinel (proactive daemon) | `jarvis sentinel` |
| The Oracle (health report) | `jarvis health` |
| Diagnostics (redacted support bundle) | `jarvis diagnostics bundle` |

## Security model

- **Bring your own key.** No API key ships with this software; keys are stored encrypted on-device and only sent to the provider you configure.
- **The gate lives in code, not prompts.** Dangerous actions trigger an interactive confirmation — including remotely, over the Bridge, as APPROVE/DENY on your phone.
- **Argument-list execution only.** No shell ever parses model-generated text.
- **Outbound URLs are guarded** (scheme, host, resolved-IP, no redirects). Local-first everywhere else.

## Privacy

Local-first: license, memories, health samples, reminders and voice transcription are stored on your device. Only your AI-provider traffic leaves the machine, using your own key. Diagnostics bundles are built locally and fully redacted (no keys, no message bodies unless you explicitly pass `--include-conversations`); crash reports are opt-in (`jarvis settings set diagnostics.crash_reports=true`) and never leave the machine.

## Health disclaimer

The Oracle is an informational heuristic against your own recorded baseline. It is not medical advice, not a diagnosis, and not a medical device.

## Releases

<!-- RELEASES:BEGIN -->
- **3.8.0** - jarvis_ai-3.8.0-py3-none-any.whl, UMBRA.exe (see `dist/SHA256SUMS`)
<!-- RELEASES:END -->

## Support

Troubleshooting, log locations, diagnostics bundles, and the support/refund policy: [SUPPORT.md](SUPPORT.md).

## License

Proprietary — see [LICENSE](LICENSE) (freemium EULA: LITE free for personal use; PRO per-key). Third-party attributions: [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
