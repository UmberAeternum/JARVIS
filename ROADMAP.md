# UMBRA — ROADMAP (the single numbering)

_This file is the one source of truth for what "done" means. Every mark maps
to shipped commits; every open phase has an exit gate. Do not renumber: new
work appends._

## Definition of done (fixed, applies to every phase)

1. Code + tests, tests written against the CONTROL first (a reach feature
   without its control-test is not done).
2. Smoke suite green (`python tests/test_smoke.py`), CI green including the
   gitleaks secret-scan.
3. Independent verification: the gate commands run on the live machine and
   their outputs quoted.
4. Docs touched: this file's phase table + the affected user docs.

## Canonical mapping (prompt numbering ↔ shipped history)

The XXVI–XXXI prompt re-ordered marks relative to the shipped history. The
shipped chain is canonical; prompt numbers map as follows:

| Prompt mark | Topic | Shipped as | Commits |
|---|---|---|---|
| XXVI living presence | wake, ambient, personality | Mark XXVIII | `d88b5ce` |
| XXVII voice + HUD | voice profile, HUD, intro | Mark XXIX | `5443556` |
| XXVIII app injection | API, overlay, scaffolds | Mark XXVI | `cd8aa49` |
| XXIX device injection | scan/install/bundle | Mark XXVII | `32064e6` |
| XXX docs + release | README, storefront | Mark XXX | `f9168c4`+`4e8aaf4` (v3.17.0) |
| XXXI GA hardening | EDITH + armor | Mark XXXI | `0c372b1` (EDITH) · `6ced59c`+`ac42345` (GA) · `d540991` (v3.19.0) |

## Phases and exit gates

| Phase | Goal | Exit gate | Status |
|---|---|---|---|
| 0. Freeze + audit | This file; independent audit of the EDITH work | Audit 9/9 PASS; mapping table committed | **DONE** |
| 1. Policy spine | Central `authorize()`, tiered grants, `jarvis access verify` | Every gated command default-denies; per-tier expiry; tamper detected | **this phase** |
| 2. JARVIS quality | Eval suite (20–30 scenarios), prompt-injection defenses on fetched content, `jarvis doctor`, multi-provider abstraction | Evals run on every model swap | open |
| 3. EDITH hardening | Pairing handshake, least-privilege tool scopes, red-team pass | "scan with no command = zero installs" + all bypass attempts fail | open |
| 4. GA | Code signing, signed updates, payment→key pipeline, license hardening, PRIVACY/REFUND | Clean-machine install, update round-trip, secret scan green | **partially done** (updates/license/legal/hygiene shipped in XXXI; signing + clean-VM install open) |
| 5. Polish | HUD, voice, branding, docs site | Demo video recorded end to end | open |

## Grant tiers (SETTLED — Phase 1 design)

One "full" switch was too coarse. Reach is granted per tier, each expiring
independently:

| Tier | Unlocks | Typical holder |
|---|---|---|
| `observe` | read-only status surfaces (API /health, access log) | dashboards |
| `assist` | API chat + tools, overlay attachment | the user's own editor/browser extensions |
| `act` | PRO tools reachable through the API (screen control etc., still tier-gated by license) | power users, explicitly requested |
| `install` | `jarvis inject install` execution | the host machine doing a deliberate deploy |

- `jarvis access grant --full` grants **all** tiers — the rare case, kept for
  compatibility.
- `jarvis access grant --tiers assist,install [--window-hours N]` grants
  exactly the named tiers, each expiring N hours out (default 24).
- The typed confirmation phrase is required for every grant, whatever the
  tier. Config can change the window length; it can never create a grant.

## Pairing design (SETTLED — Phase 3 scope)

Target-side consent for devices that already run UMBRA:

1. On the target: `jarvis pair` prints a 6-digit one-time code + fingerprint,
   valid 5 minutes, single use.
2. On the host: `jarvis inject install --pair 123456 ...` — the code is
   verified by running `jarvis pair --verify <code>` on the target through
   the same ssh/adb session; a mismatch aborts before any file is pushed.
3. First-ever install has nothing to pair with yet — it still authenticates
   through SSH keys / adb (documented nuance; pairing governs reach to
   already-instrumented devices, which is where a worm would spread).

Implemented in Phase 3. This section is the design of record.

## Working method

- Tests first: the failing control-test is written before the capability.
- Independent verification at every gate: agent summaries are claims; run
  the suite and the gate commands yourself (or via a separate auditor).

## Phases 11-20 run (spec of 2026-11-10, autonomous)

Continues from v3.29.0. Gates per phase: smoke suite, `jarvis eval compare`
(no regression), `jarvis access verify`, commit + tag `phase-N`.

| Phase | Goal | Status |
|---|---|---|
| 11. Orb HUD, avatar, boot sequence | Token-gated display-only HUD (127.0.0.1:8776): particle orb with the six state colors, status ring, live action log, devices, captions, boot line with honorific, minimal/hud/scanline themes, reduced-motion/high-contrast/keyboard a11y. Global kill switch (`jarvis stop`, HUD KILL button, agent `should_stop` probe between tool calls). 1 new smoke check, 2 new eval scenarios (hud category) | **DONE** (96/96 smoke · 33/33 eval · no regressions · ledger OK) |
| 12. Voice upgrade | Streaming STT/TTS provider abstraction (`voice_stream.py`): local-first (Vosk partials), cloud opt-in twice + endpoint SSRF gate + sensitive-text refusal for cloud TTS; live HUD captions, listening indicator, sentence-chunked speech with barge-in, wake loop with wake-word stripping, measured latency budget (fake-clock tested). `jarvis wake --stream`, `jarvis stop` halts capture. 1 new smoke check, 1 new eval scenario (voice category) | **DONE** (97/97 smoke · 34/34 eval · no regressions · ledger OK) |
| 13. Hand gestures | opt-in, local hand tracking; fist = kill switch; gestures can never confirm high-consequence actions | open |
| 14. Browser/app control | action DSL through authorize(), MONEY stop-before-final-step | open |
| 15. Messaging/email | draft-only, per-message confirmation | open |
| 16. Website builder | original templates, clone-brand refusal, publish gate | open |
| 17. Reel/video assistant | ffmpeg non-destructive pipeline | open |
| 18. Phone companion + devices | PWA upgrade, device grants, scoped tokens | open |
| 19. Productivity core | tasks/calendar/notes/automations under HIGH-CONSEQUENCE rules | open |
| 20. Verify and release | red-team pass 2, fresh-clone CI, docs, release dry-run | open |
- Red-team pass per phase: try to bypass the new controls via config, env
  var, API, and restart. Any success is a bug fixed in the same phase.
