# Support — UMBRA

## First steps (fastest fixes)

| Symptom | Fix |
|---|---|
| "No brain configured yet" | Run `jarvis setup` (the wizard). Paste your provider API key — it is validated live and never echoed. |
| "The brain rejected the API key" | The key is wrong or expired. Re-run `jarvis setup`, or check `jarvis settings show` (keys are masked). |
| "Cannot reach the brain" | Cloud: check your connection. Local (Ollama): is it running? `ollama serve`, then pull a chat model (`ollama pull qwen2.5:7b`). |
| Voice input does nothing | The voice extra is not installed: `pip install "jarvis-ai[voice]"`. The reason is printed at startup. |
| PRO features refuse ("PRO feature" hint) | `jarvis license status`, then `jarvis license activate UMBRA-xxxx.yyyy`. |
| Lost your config | `jarvis settings show` still works; if the file is gone, `jarvis setup` rebuilds it. Memories and health data are kept. |

## Where your data lives (all local)

Base directory (Windows: `%APPDATA%\jarvis`; Linux: `~/.config/jarvis`):

| Item | Location |
|---|---|
| Settings / brain config | `config.json` (API key stored here, or in the OS keychain when enabled) |
| Logs (redacted) | `logs/app.log` |
| Crash reports (opt-in) | `crash-<timestamp>.txt` |
| Memories | `memory.db` |
| Conversations | `conversations.db` |
| Health samples | `health.db` |
| Reminders | `sentinel.json` |
| Watch rules | `watchtower.json` |
| Kanban board | `board.json` |
| License key | `license.key` |
| Additional profiles | `profiles/<name>/` (the active one is recorded in `profile`) |

Nothing in these files is uploaded anywhere. Only your own AI-provider traffic leaves the machine.

## Diagnostics bundle (attach this to any support request)

```bash
jarvis diagnostics bundle                 # default: no message bodies
jarvis diagnostics bundle --include-conversations   # only if asked to
```

The bundle is a zip written locally. It contains: version / OS / Python, your
license **tier** (never the license key), a **redacted** settings dump (API keys
masked), the tail of `logs/app.log` (redacted), and conversation **metadata**
(ids, titles, turn counts). Message bodies are only included when you pass
`--include-conversations`, and even then every line is scrubbed of key shapes,
license keys and email addresses. Attach the zip when contacting support.

## Crash reporting

Crash reports are **opt-in** and stay on your machine:

```bash
jarvis settings set diagnostics.crash_reports=true
```

After an unexpected error you will get a `crash-*.txt` path in the base
directory — include it (or run `jarvis diagnostics bundle`) when reporting.
Nothing is ever uploaded automatically.

## Health disclaimer

The Oracle (HR/HRV screening) is an informational heuristic computed against
your own recorded baseline. It is not medical advice, not a diagnosis, and not
a medical device. Do not use it to make medical decisions.

## Support & refunds

- **LITE (free):** community support via the repository issues
  (<https://github.com/UmberAeternum/JARVIS/issues>). Include a diagnostics
  bundle (never paste raw keys into an issue — the redacted bundle is safe).
- **PRO (licensed):** contact the publisher's sales/support channel you
  purchased from, with your diagnostics bundle attached. Your license key
  identifies your purchase — the support flow never needs your API keys.
- **Refunds:** handled per the terms of the EULA (`LICENSE`). Contact the
  publisher's support channel with your license key; the key itself verifies
  the purchase. Local data is never required for a refund and never leaves
  your machine.
