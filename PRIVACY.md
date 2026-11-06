# Privacy Policy — UMBRA

_Last updated: 2026-11-07. This policy describes the UMBRA software (the "Product"). The publisher is the entity identified in the EULA (`LICENSE`)._

## The short version

UMBRA is local-first. Your conversations, memories, health samples, reminders, license details and voice transcriptions stay on your device. The Product does not contain telemetry, analytics, or any background upload. Nothing is sent anywhere except:

1. **Your AI provider** — the chat text and any content (screenshots, files) you explicitly attach, sent to the provider *you* configure with *your own* API key; and
2. **The update checker** — a single HTTPS GET of a small signed manifest from the publisher's release server (report-only; disable with `jarvis settings set updates.check_on_start=false`).

## What is stored, and where

| Data | Location (Windows; Linux equivalent under `~/.config/jarvis`) |
|---|---|
| Brain config + API key | `%APPDATA%\jarvis\config.json` (or your OS keychain) |
| Conversations | `%APPDATA%\jarvis\conversations.db` |
| Memories | `%APPDATA%\jarvis\memory.db` |
| Health samples | `%APPDATA%\jarvis\health.db` |
| Reminders / watch rules / board | `%APPDATA%\jarvis\*.json` |
| License key | `%APPDATA%\jarvis\license.key` |
| Access ledger (reach log) | `%APPDATA%\jarvis\access-log.jsonl` |
| Crash reports (opt-in only) | `%APPDATA%\jarvis\crash-*.txt` |

Deleting these files deletes the data permanently. Uninstalling the Product does not automatically delete them.

## Crash reporting

Opt-in only (`jarvis settings set diagnostics.crash_reports=true`). Crash files are written locally and are **never uploaded automatically**. If you choose to send one, it has already been redacted of API keys, license keys and email addresses.

## Diagnostics bundles

Built locally on demand (`jarvis diagnostics bundle`), fully redacted, and only sent by you — manually, to the publisher's support channel.

## Children

The Product is not directed at children under 13 (or the equivalent minimum age in your jurisdiction).

## Your rights (GDPR / DPDP baseline)

The publisher processes no personal data on any server: all personal data the Product handles stays on your device under your control, which is the strongest form of data minimization. To exercise access, correction, deletion or portability of *your own* data, use the Product's own tools (`jarvis export`, `jarvis settings reset`, file deletion) — or contact the publisher's support channel, which will assist without requiring you to transmit data you do not wish to send.

## Changes

Material changes to this policy ship in the Product's release notes and update the date above.
