# UMBRA

[![CI](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml/badge.svg)](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/UmberAeternum/JARVIS)](https://github.com/UmberAeternum/JARVIS/releases/latest)

**The shadow that works for you.** A local-first AI assistant in the Iron Man tradition — it hears you, sees your screen, remembers everything, anticipates, speaks, and lives in every app you use. Built on a safety architecture where every powerful action passes a human gate.

UMBRA is one mind with many bodies: a desk CLI, a web mission control with the full agent, an always-on-top overlay beside your other apps, your phone (native HUD + browser bridge panel), an avatar face, and a WebXR room — **every surface runs the same agent, the same tools, the same gate.**

It works with a **cloud brain** (Z.AI GLM, OpenAI, Google Gemini, or any OpenAI-compatible API) or a **local brain** (Ollama / LM Studio) — chained with automatic failover if you configure both. With a local brain it runs **fully offline**: chat, memory, tools, dashboard, all of it.

> **No holograms.** UMBRA is software — windows, panels, voices and code. Nothing here projects into physical space, and nothing here claims to.

## Two editions

| | **LITE** — free | **PRO** — license key |
|---|---|---|
| Chat, voice, memory | ✓ | ✓ |
| Health Oracle (HR/HRV screening) | ✓ | ✓ |
| Reminders + morning briefing | ✓ | ✓ |
| `/look` screenshots | ✓ | ✓ |
| Avatar (web face) | ✓ | ✓ |
| **Dashboard** — full agent + streamed replies + spoken answers + HUD rings + session resume | ✓ | ✓ |
| Session history — searchable, resumable, on every surface | ✓ | ✓ |
| **App injection** — local API + overlay + plugin scaffolds | ✓ | ✓ |
| Profiles + export/import | ✓ | ✓ |
| Signed update checker + redacted diagnostics | ✓ | ✓ |
| Personality pack (honorific, verbosity, humor) | ✓ | ✓ |
| `/live` screen sharing | — | ✓ |
| **Bridge** — full agent + session history on your phone | — | ✓ |
| **Portal** — WebXR room for headsets | — | ✓ |
| **Screen control** — click/type/scroll | — | ✓ |
| **Watchtower** — ambient rules | — | ✓ |

## Install

**Windows (standalone, no Python):** grab [UMBRA.exe from the latest release](https://github.com/UmberAeternum/JARVIS/releases/latest), double-click, and the setup wizard handles the rest. Verify with the attached `SHA256SUMS`.

**Android:** sideload the [launcher APK](https://github.com/UmberAeternum/jarvis-launcher/releases) and set it as home.

**From source** (Python 3.10+):

```bash
git clone https://github.com/UmberAeternum/JARVIS.git
cd JARVIS
pip install .
umbra        # or: python -m jarvis
```

**On another device — injection, one command from your PC:**

```bash
jarvis inject scan                                    # sweep the LAN, guess OS
jarvis inject install --target 192.168.1.50 --os linux --yes
jarvis inject install --target <adb-device> --os android --apk UMBRA-launcher-*.apk
jarvis inject bundle --out umbra-inject-bundle.zip    # offline installer for anything else
```

SSH keys/agent only — passwords are never asked for or stored; the bundle never contains private material. Thin wrappers: `scripts/inject.sh`, `scripts/inject.ps1`.

The setup wizard walks you through the brain: pick a provider, paste your API key (validated live), optional voice, optional PRO activation. Re-run anytime with `jarvis setup` (`--yes` for CI, `--local` for Ollama). Optional extras: `pip install ".[all]"`.

## App injection — UMBRA inside your other apps

- **Local API** — `jarvis serve --api`: a token-authenticated JSON API on 127.0.0.1 (`/health`, `/tools`, `/chat`). Rotate the token with `jarvis api token rotate`.
- **Overlay** — `jarvis overlay`: an always-on-top companion beside any app — live status, query box, last reply. `--attach <process>` adds working context; `--clickthrough` makes it display-only.
- **Scaffolds** — `jarvis plugin scaffold vscode --out <dir>` / `scaffold browser --out <dir>`: minimal starter extensions that call the API. No auto-install, no store publishing, no token in generated files.

Gated tools are auto-denied over the API — approvals live in the dashboard and Bridge.

## Living presence

- **Wake word** — `jarvis wake`: hands-free, configurable phrase (`jarvis settings set voice.wake_phrase "Hey UMBRA"` — the default), push-to-talk fallback, strictly opt-in.
- **Ambient nudges** — low battery, due reminders, health shifts: one concise line, rate-limited (default 1 per 5 min), quiet hours (23:00–07:00), **default OFF**. Enable: `jarvis settings set ambient.nudges=true`.
- **Personality** — `jarvis personality set --honorific Sir --verbosity concise --humor 5 --proactive 1`: the dry-butler register, yours to tune.
- **Morning briefing** — `jarvis sentinel`: health, board, memory and reminders, spoken.
- **Voice identity** — `jarvis voice set jarvis`: the British-butler TTS profile (silent fallback when no matching voice exists).

## Command reference

| Command | What it does |
|---|---|
| `umbra` / `python -m jarvis` | The assistant — chat with all tools, confirmations, streaming |
| `jarvis dashboard` | Local web mission control (full agent, streaming, SPEAK, HUD, resume) |
| `jarvis serve` / `jarvis serve --api` | PRO: Bridge over your LAN · LITE: local JSON API for other apps |
| `jarvis overlay` | Always-on-top companion window (`--attach`, `--clickthrough`) |
| `jarvis plugin scaffold vscode\|browser` | App-injection starters |
| `jarvis eval run / compare` | The behavior baseline (25 scenarios) |
| `jarvis inject scan / install / bundle` | Put UMBRA on another device |
| `jarvis setup` | Onboarding wizard (`--yes` for CI, `--local` for Ollama) |
| `jarvis settings show / set / reset` | Configuration (secrets always masked) |
| `jarvis profile list / create / use / delete` | Isolated identities |
| `jarvis export` / `jarvis import` | Move data between machines or profiles |
| `jarvis wake` | Hands-free wake-word mode |
| `jarvis personality show / set` | Honorific, verbosity, humor, proactivity |
| `jarvis voice show / set` / `jarvis hud show / theme` | TTS profile · HUD theme |
| `jarvis intro` | The 10-second boot sequence (`--no-audio` works) |
| `jarvis update check` | Newer signed release lookup (report-only) |
| `jarvis diagnostics bundle` | Redacted support bundle |
| `jarvis health` / `jarvis sentinel` | The Oracle · reminders + briefing daemon |
| `jarvis face` / `jarvis portal` | Avatar · WebXR room (portal: PRO) |
| `jarvis license activate / status` | PRO licensing |

## Eval baseline

UMBRA ships a 25-scenario behavior baseline (tool calling, gate enforcement, destructive-action confirmations, memory, prompt-injection plumbing, persona) that proves changes do not regress:

```bash
jarvis eval run                      # offline, scripted fixtures - CI mode
jarvis eval run --category memory    # one category
jarvis eval compare old.json new.json
```

Offline runs replay recorded fixtures against the real agent machinery — deterministic, no network. Two scenarios are honestly marked `known_failure` (the agent-level PRO upgrade hint and the honorific reaching the system prompt — both deferred); the suite counts them separately.

## Security model

- **Bring your own key.** No API key ships with this software; keys are stored encrypted on-device and only sent to the provider you configure.
- **The gate lives in code, not prompts.** Dangerous actions trigger an interactive confirmation — in the CLI, on the dashboard, on your phone, in the room.
- **Argument-list execution only.** No shell ever parses model-generated text; injection targets are regex-validated and remote commands are constants.
- **Loopback is the default.** The API binds 127.0.0.1 with a rotating token; the LAN Bridge is a separate, PRO-gated, token-gated command.
- **Outbound URLs are guarded** (scheme, host, resolved-IP, no redirects). Local-first everywhere else.
- **Zero reach by default.** Device installs and cross-app reach require an interactive, expiring, logged grant — and a per-target confirmation even then. No self-propagation, ever (test-enforced).

## The EDITH protocol (reach, consented)

UMBRA's reach — installing itself onto another device, cross-app attachment, the API's tool endpoints — is **denied by default**. It unlocks only when you type the confirmation phrase interactively:

```bash
jarvis access grant --full     # expires in 24h, logged with a device fingerprint
jarvis access status           # FULL ACCESS: granted | not granted
jarvis access log              # append-only, tamper-evident ledger
jarvis access revoke --all     # take off the glasses - instant
```

Even with full access, every device install asks again for the specific target at the moment of install. **No autonomous self-propagation**: a scan sees devices and installs nothing; nothing installs except in response to your explicit command. This is test-enforced.

## Privacy

Local-first: license, memories, health samples, reminders, voice transcription and conversations are stored on your device. Only your AI-provider traffic leaves the machine, using your own key. Diagnostics bundles are built locally and fully redacted (no keys, no message bodies unless you explicitly pass `--include-conversations`); crash reports are opt-in and never leave the machine; the offline bundle contains the public key only — never private material.

## Health disclaimer

The Oracle is an informational heuristic against your own recorded baseline. It is not medical advice, not a diagnosis, and not a medical device.

## Releases

<!-- RELEASES:BEGIN -->
- **3.29.0** - jarvis_ai-3.29.0-py3-none-any.whl, UMBRA.exe (see `dist/SHA256SUMS`)
<!-- RELEASES:END -->

## Support

Troubleshooting, log locations, diagnostics bundles, and the support/refund policy: [SUPPORT.md](SUPPORT.md). Legal: [PRIVACY.md](PRIVACY.md) · [REFUND.md](REFUND.md).

## License

Proprietary — see [LICENSE](LICENSE) (freemium EULA: LITE free for personal use; PRO per-key). Third-party attributions: [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
