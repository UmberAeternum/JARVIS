# J.A.R.V.I.S.

[![CI](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml/badge.svg)](https://github.com/UmberAeternum/JARVIS/actions/workflows/ci.yml)

**Just A Rather Very Intelligent System** — a personal AI assistant for your PC. It hears you, sees your screen, remembers what you tell it, runs your programs, manages files, opens apps, searches the web, and answers out loud — with a safety gate between the model and your machine at every step.

Works with a **cloud brain** (Z.AI GLM, OpenAI, Google Gemini, or any OpenAI-compatible API) or a **local brain** (Ollama / LM Studio) — and can chain both: a cloud primary with a local fallback that takes over automatically when you're offline or rate-limited.

**Companion project:** [jarvis-launcher](https://github.com/UmberAeternum/jarvis-launcher) — the same brain as an Android home-screen replacement: sci-fi HUD, pulsing AI core, inline chat, hold-to-talk.

## Features

| Tool | What it does |
|---|---|
| `run_command` | Runs programs with arguments directly (no shell parser involved, 30 s timeout, captured output) — dangerous programs require your confirmation |
| `open_app` | Launches apps by name or path |
| `read_file` / `write_file` / `list_dir` | File access, scoped to your machine; writes outside the workspace ask first |
| `web_search` | Keyless DuckDuckGo search |
| `system_status` | CPU / RAM / disk / battery |
| `clipboard_read` | Reads the clipboard — only when you explicitly ask, and always marked as untrusted data |
| **Dry-run mode** | `--dry-run` / `/dryrun`: tools print their exact payload and would-be impact; nothing executes |
| **Fallback brain** | Optional second brain takes over when the primary is offline or rate-limited |
| **Keychain storage** | Optional OS-keychain credential storage (`pip install jarvis-ai[secure]`) — no plaintext keys on disk |
| **Voice (Mark II)** | Push-to-talk mic capture → local transcription → spoken replies via offline TTS — audio never leaves your machine |
| **Vision (Mark III)** | `/look` one-shot screenshots, `/live` screen sharing (a fresh capture with every turn), and `jarvis watch` ambient observation — all through a vision-capable model |
| **Memory** | Persistent second brain in SQLite: `memory_save` / `memory_search` / `memory_recent` — facts survive across sessions, stored locally |
| **Streaming** | Replies render token-by-token as they generate |
| **Wake word** | `jarvis wake`: hands-free — say "Jarvis", speak a command, get a spoken answer (local Vosk detection) |
| **Screen control** | Opt-in `screen_click` / `screen_type` / `screen_press` / `screen_scroll` — every action confirm-gated, pyautogui failsafe armed |
| **Health (Mark V)** | The Oracle: HR/HRV samples from wearable CSV exports, screened against your own 30-day baseline with sigma-level risk bands — local, honest, not a diagnosis |
| **Avatar (Mark VI)** | `jarvis face` — a local web face with lip-synced spoken replies; bring your own VRM model for full 3D |
| **Portal (Mark VII)** | `jarvis portal` — a WebXR room for headsets and phones: JARVIS chat panel floating in your space, a kanban wall you cycle by pinch/trigger, your GLB models on a desk |

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/UmberAeternum/JARVIS.git
cd JARVIS
pip install .
# everything: keychain storage + voice (Mark II) + vision (Mark III)
pip install ".[all]"
```

## First run

```
jarvis
```

> If `jarvis` is not recognized, your Python `Scripts` directory is not on
> PATH — run `python -m jarvis` instead (or add the Scripts folder to PATH).

The setup wizard walks you through the brain:

1. **Cloud** — pick a provider, paste your API key (input is hidden), and the key is validated with a live call before anything is saved.
2. **Local** — the wizard auto-probes Ollama (port 11434) and LM Studio (port 1234), lists your chat-capable models, and hides embedding/audio models automatically.
3. **Fallback** — optionally configure a second brain; if the primary is offline or rate-limited, JARVIS switches to it for the session and tells you.
4. **Keychain** — if the `keyring` extra is installed, the wizard offers to store keys in the OS keychain instead of a JSON file.

Your API key is stored **only on your machine** (`%APPDATA%\jarvis\config.json` on Windows). It is never sent anywhere except to the provider you chose, and it is never committed to this repository. You can also set the `JARVIS_API_KEY` environment variable to override the stored key.

Re-run the wizard any time with `/setup`.

## Using JARVIS

```
you> what's my CPU usage?
you> open notepad
you> search the web for the latest ollama models
you> /look what error is on my screen?     # screenshot -> vision answer
you> /live                                 # share your screen every turn
you> remember that my deploy server is 10.0.0.5
you> /tools                                # list all 12 tools
you> /voice          /tts                  # toggle mic / spoken replies
you> /dryrun         /publish
you> /clear          /exit
```

Launch modes: `jarvis --voice` (push-to-talk), `jarvis --live` (screen sharing), `jarvis --dry-run` (tools plan, never execute), `jarvis watch --interval 30` (ambient observation), `jarvis wake` (hands-free — say "Jarvis").

## Voice mode (Mark II)

```bash
pip install ".[voice]"     # vosk STT + sounddevice + numpy + pyttsx3 (any CPython)
jarvis --voice
```

- **Press Enter on an empty line to speak** (or keep typing — text always works). The mic records up to 10 s, silence is trimmed, and speech is transcribed **locally**.
- **Two STT backends, best available wins:** faster-whisper (best accuracy, multilingual) when wheels exist for your Python (≤ 3.13 — install `.[voice-whisper]`), otherwise **Vosk** (works on any CPython, including 3.15; the small English model ~40 MB downloads once into the config directory).
- **Replies are spoken aloud** via offline SAPI TTS. `/tts` toggles speech, `/voice` toggles the mic.
- **Private by design:** recording and transcription run entirely on your machine; no audio is uploaded.
- Diagnose your setup with `python tests/voice_probe.py` (records one utterance, transcribes it, speaks a confirmation).
- Without the `[voice]` extra, JARVIS runs as pure text chat and says exactly what is missing if you try `/voice`.

## Vision mode (Mark III)

```bash
pip install ".[vision]"    # mss + pillow
jarvis --live              # screen sharing: a screenshot with every turn
```

Three ways for JARVIS to see, all through your configured provider's vision-capable model (set `vision.model` in the config if your primary model is text-only):

| Mode | Command | What happens |
|---|---|---|
| **Screenshot** | `/look what error is on my screen?` | One-shot capture → vision answer |
| **Live screen sharing** | `/live` (or `--live`) | A fresh screenshot travels with **every** turn — JARVIS sees your screen as you converse |
| **Ambient watch** | `jarvis watch --interval 30` | Background loop: only when the screen meaningfully changes does JARVIS look, summarize, and (if TTS is on) speak |

- **Privacy:** unlike voice STT (fully local), vision frames are uploaded to your cloud provider to be described. `/live` prints this notice when enabled; watch mode prints it at startup.
- Captures are downscaled to 1280 px wide and JPEG-compressed before upload to keep token costs sane; watch mode only spends tokens on changed screens.
- Vision is read-only by default. With screen control enabled (below), JARVIS can act on what it sees — always with your confirmation.

## Screen control (opt-in)

The eyes can be given hands: with `pyautogui` installed (`pip install jarvis-ai[control]`) and `"screen_control": true` set in the `vision` section of `%APPDATA%\jarvis\config.json`, JARVIS gains `screen_click`, `screen_type`, `screen_press` and `screen_scroll`. Every action requires you to approve that exact action at the prompt, coordinates are validated, and pyautogui's failsafe (slam the mouse into a screen corner) aborts automation instantly. Combined with `/look`, the loop is: JARVIS sees the screen, proposes an action, you approve, it verifies the result visually.

## Memory (the second brain)

JARVIS persists durable facts about you in `%APPDATA%\jarvis\memory.db` (SQLite, local-only): say "remember that my deploy server is X" and it survives restarts. `/tools` lists the memory commands; forgetting anything requires your confirmation.

## Hands-free wake word

```bash
jarvis wake
```

Say **"Jarvis"** — the local wake-word detector (Vosk streaming, no cloud) cues with *"wake word detected"*, captures your command until you pause, runs it through the full agent (tools included), and speaks the answer. Ctrl+C to stand down.

## Health — the Oracle (Mark V)

```bash
jarvis health
```

Feed it heart-rate data from your wearable (CSV export from Garmin Connect, Oura, or any file with a timestamp + value column — or just say *"log my HRV at 48"*), and the Oracle screens it against **your own** rolling 30-day baseline:

```
HEALTH SIGNAL: ELEVATED - consider rest and hydration; watch for symptoms
HRV: recent 35.0 vs 30-day baseline 51.2 (std 1.9, n=27) -> z=-2.68 [HIGH] suppressed
Screening heuristic against your own baseline - not a medical diagnosis.
```

- Suppressed HRV and elevated resting HR are known statistical precursors of respiratory illness by roughly one to two days — so the signal can appear **before** you feel sick. That is a screening heuristic with sigma values attached, never a diagnosis or a certainty.
- Data lives in `%APPDATA%\jarvis\health.db`, local only. In-chat: `health_log`, `health_import`, `health_check`, `health_trend`.



## Avatar — the face (Mark VI)

```bash
jarvis face
```

Opens a local page (`127.0.0.1` only, never exposed to your network): a **procedural HUD face** — blinking eyes, a mouth that moves while the reply is spoken, waveform ring while talking — plus a full chat panel. Replies are spoken by your browser's TTS, and the mouth is driven by the utterance's real boundary events.

- **Bring your own 3D model:** drop any `avatar.vrm` (export one from free VRoid Studio) into `%APPDATA%\jarvis\` and press MODE → the page loads it through three-vrm as a full 3D character with idle sway, blinking, and viseme-driven mouth. No licensed character ships with this software — like your key, the model is yours.
- Conversation-only by design: the avatar is the face; tools stay at the terminal where their confirmations live.

## Portal — the XR room (Mark VII)

```bash
jarvis portal
```

Opens a **WebXR room** served by your PC: JARVIS as a floating chat panel in your space, a **kanban wall** on your wall (select a card with trigger or pinch to cycle it across the board), and a desk for your own GLB models (drop `.glb` files into the `models` folder of the config directory).

- Works in a **headset browser** (immersive-vr with DOM-overlay text input, hand-tracking pinch), in **AR on your phone**, and as a **2D fallback** in any desktop browser
- Text entry in-headset rides the DOM Overlay (Quest Browser supports it)
- **Security:** the portal is the one component bound to your **LAN** — a headset is a separate device and cannot reach `127.0.0.1`. Exposure is gated by a random per-session token (printed with the URL when you start it), the server stops with Ctrl+C, and it never runs unless you start it
- The XR rendering can only be judged in a headset — HTTP contract, storage, and gating are all covered by the test suite

## Security model

- **Bring your own key.** No API key ships with this software — anyone who hardcodes a shared key into a public repo gets it drained within hours.
- **Keys stay local.** Stored per-user in the OS config directory; never in the repo, never echoed to the console.
- **Dangerous commands are gated.** A denylist (`format`, `shutdown`, `reg add`, `rm -rf`-style deletes, …) triggers an interactive confirmation before anything runs. The gate lives in code, not in the prompt.
- **Untrusted context is labelled.** Clipboard and web content is wrapped as data, never treated as instructions — mitigating prompt injection.
- **Command execution is argument-list only.** No shell ever parses model-generated text, which removes quoting/expansion/pipe bypass classes; inline-code interpreters (`powershell -Command`, `python -c`) are confirm-gated.
- **Outbound URLs are guarded.** Every HTTP fetch validates the scheme, the hostname, and the resolved IP addresses (anti DNS-rebinding), and refuses redirects — local endpoints are allowed only where a local brain is the explicit feature.

## Publishing to GitHub

Run `/publish` inside JARVIS: it detects git and the GitHub CLI, guides you through `gh auth login` if needed, and creates + pushes the repo in one confirmed step (`gh repo create <name> --source . --push`). Manual instructions are printed whenever a prerequisite is missing.

## Development

```bash
python tests/test_smoke.py   # offline smoke suite, 39 checks
```

CI (`.github/workflows/ci.yml`) runs the 39-check suite on Windows and Ubuntu across Python 3.10–3.14.

## Project structure

```
src/jarvis/
├── cli.py            # entry point: wizard → chat loop, /look /live /voice /tts
├── wizard.py         # onboarding: provider menu, key validation, keychain, save
├── config.py         # schema v4 (brains, voice, vision) + auto-migration
├── brain.py          # provider-agnostic client, failover chain, streaming
├── agent.py          # turn loop: model → tools → results → answer (multimodal)
├── tools.py          # tool registry with JSON schemas + opt-in groups
├── shell_tool.py     # run_command: direct program execution, denylist + gate
├── memory.py         # persistent second brain (SQLite, local-only)
├── screen_tools.py   # opt-in click/type/press/scroll (confirm-gated)
├── voice.py          # Mark II: push-to-talk STT (whisper/vosk) + offline TTS
├── vision.py         # Mark III: capture, change detection, vision messages
├── watch.py          # ambient screen observation loop
├── publish.py        # guided GitHub publishing (gh)
├── safety.py         # denylist, URL guard, confirmation gate, truncation
└── system_prompt.py  # the JARVIS master prompt (persona + tool contract)
```

## Roadmap

- [x] Voice loop (push-to-talk STT + offline TTS)
- [x] Vision: screenshots, live screen sharing, ambient watch
- [x] Screen control (click/typing automation, confirm-gated)
- [x] Persistent local memory ("second brain" search)
- [x] Streaming responses
- [x] Hands-free wake word
- [x] Health: HR/HRV screening against your own baseline (the Oracle)
- [x] Portal: WebXR room for headsets (chat panel, kanban wall, desk models)
- [ ] Multi-monitor vision, clipboard paste for non-ASCII typing, wake-word tuning UI

## License

MIT — see [LICENSE](LICENSE).
