"""Phase 2A - the eval harness runner.

Usage (from the repo root):
    python tests/evals/harness.py run [--category X] [--live] [--write-baseline]
    python tests/evals/harness.py compare <baseline.json> <new.json>

Offline mode (default) replays scripted fixtures - deterministic, no
network, safe for CI. --live runs against the configured provider and
records replies WITHOUT scoring them (model judgment needs human review);
it is never used in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jarvis.evals import (  # noqa: E402
    compare_results,
    default_scenarios_dir,
    load_scenarios,
    run_scenarios,
    write_baseline,
)


def _print_table(results: dict) -> None:
    for entry in results["results"]:
        mark = "PASS" if entry["passed"] else ("KNOWN-FAIL" if entry["known_failure"] else "FAIL")
        latency = f" ({entry['latency_ms']} ms)" if entry.get("latency_ms") else ""
        print(f"[{mark}] {entry['id']} ({entry['category']}){latency}")
        for failure in entry.get("failures", []):
            print(f"       - {failure}")
        if entry.get("known_failure") and entry.get("reason"):
            print(f"       known: {entry['reason']}")
    print(f"\n{results['passed']}/{results['total']} passed, "
          f"{results['known_failures']} known failures, {results['failed']} failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the UMBRA eval baseline.")
    parser.add_argument("action", nargs="?", default="run", choices=["run", "compare"])
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--live", action="store_true",
                        help="run against the configured provider (never in CI; "
                             "replies are recorded but not scored)")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record the run as the new baseline")
    parser.add_argument("--out", help="write the raw run results to this file")
    parser.add_argument("compare_args", nargs="*",
                        help="compare: <baseline.json> <new.json>")
    args = parser.parse_args()

    if args.action == "compare":
        if len(args.compare_args) < 2:
            print("usage: harness.py compare <baseline.json> <new.json>")
            return 1
        baseline = json.loads(Path(args.compare_args[0]).read_text(encoding="utf-8"))
        current = json.loads(Path(args.compare_args[1]).read_text(encoding="utf-8"))
        report = compare_results(baseline, current)
        print(f"regressions: {report['regressions'] or '(none)'}")
        print(f"recovered:   {report['recovered'] or '(none)'}")
        print(f"still failing: {report['still_failing'] or '(none)'}")
        return 1 if report["regressions"] else 0

    scenarios_dir = default_scenarios_dir()
    if scenarios_dir is None:
        print("scenario directory not found - run from a repository checkout")
        return 1
    scenarios = load_scenarios(scenarios_dir, args.category)
    if not scenarios:
        print(f"no scenarios found in {scenarios_dir}")
        return 1

    if args.live:
        print("LIVE mode: the configured provider answers; replies are recorded "
              "but NOT scored (model judgment needs human review).")
        from jarvis import config as config_module

        cfg = config_module.Config.load()
        if cfg is None:
            print("no brain configured - run python -m jarvis first")
            return 1
        from jarvis.brain import make_brain_chain

        chain = make_brain_chain(cfg)
        print(f"brain: {cfg.brains.primary.provider} ({cfg.brains.primary.model})")
        for scenario in scenarios:
            print(f"  [{scenario['id']}] {scenario.get('title', '')}")
            try:
                response = chain.create_chat(
                    messages=[{"role": "user", "content": str(scenario.get("input", ""))}]
                )
                print(f"    reply: {(response.choices[0].message.content or '')[:200]}")
            except Exception as exc:
                print(f"    ERROR: {type(exc).__name__}: {exc}")
        print("live run complete - replies recorded above, no scores applied")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        results = run_scenarios(scenarios, Path(tmp))
    _print_table(results)

    if args.write_baseline:
        baseline = HERE / "baseline.json"
        write_baseline(baseline, results)
        print(f"baseline written: {baseline}")

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"raw results: {args.out}")

    return 1 if results["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
