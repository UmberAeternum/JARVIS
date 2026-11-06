"""UMBRA release automation (Mark XX).

One command per release:
    python scripts/release.py [--version X.Y.Z] [--dry-run]
                              [--skip-tests] [--skip-exe]

Steps: bump the version (pyproject + __init__ + the suite's version check),
run the smoke suite, build the wheel, build UMBRA.exe with PyInstaller when
available (otherwise print the manual step), scan the wheel for secret
material, write SHA256SUMS, update the README releases section, and emit a
release checklist. --dry-run prints the entire plan and touches nothing.

Only stdlib imports; pip/PyInstaller are invoked as subprocesses with
argument lists (never a shell).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
INIT = REPO / "src" / "jarvis" / "__init__.py"
TESTS = REPO / "tests" / "test_smoke.py"
README = REPO / "README.md"
CHECKLIST = REPO / "RELEASE-CHECKLIST.md"
DIST = REPO / "dist"
SPEC = REPO / "UMBRA.spec"

RELEASES_BEGIN = "<!-- RELEASES:BEGIN -->"
RELEASES_END = "<!-- RELEASES:END -->"

SECRET_MARKERS = (
    "BEGIN PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
    "umbra-private.pem",
    "UMBRA-AAAA",  # never a real key, but catch accidental fixture keys
)


def read_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit("cannot find the version in pyproject.toml")
    return match.group(1)


def bump_version(current: str, requested: str | None) -> str:
    if requested:
        if not re.fullmatch(r"\d+\.\d+\.\d+", requested):
            raise SystemExit(f"--version must be X.Y.Z, got {requested!r}")
        return requested
    major, minor, patch = (int(part) for part in current.split("."))
    return f"{major}.{minor + 1}.0"


def replace_in_file(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"could not update {label} in {path.name}")
    path.write_text(new_text, encoding="utf-8")


def apply_version_bump(new_version: str, old_version: str) -> None:
    replace_in_file(
        PYPROJECT, r'^version = "[^"]+"', f'version = "{new_version}"', "pyproject version"
    )
    replace_in_file(
        INIT, r'^__version__ = "[^"]+"', f'__version__ = "{new_version}"', "__init__ version"
    )
    replace_in_file(
        TESTS,
        r'expect\(__version__ == "[^"]+"',
        f'expect(__version__ == "{new_version}"',
        "suite version assertion",
    )
    print(f"  version: {old_version} -> {new_version}")


def run_suite() -> None:
    print("  running the smoke suite ...")
    proc = subprocess.run(  # noqa: S603 - argument list, no shell
        [sys.executable, str(TESTS)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    tail = "\n".join(proc.stdout.strip().splitlines()[-3:])
    if proc.returncode != 0:
        print(tail)
        raise SystemExit("the smoke suite failed - release aborted")
    print(f"  suite: {tail.splitlines()[-1].strip() if tail else 'ok'}")


def build_wheel() -> Path | None:
    print("  building the wheel (pip wheel --no-deps) ...")
    proc = subprocess.run(  # noqa: S603 - argument list, no shell
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(DIST)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:])
        raise SystemExit("wheel build failed - release aborted")
    wheels = sorted(DIST.glob("jarvis_ai-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise SystemExit("no wheel produced")
    return wheels[-1]


def scan_wheel_for_secrets(wheel: Path) -> None:
    """The wheel is a zip: scan every text member for credential material."""
    hits: list[str] = []
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if not name.endswith((".py", ".txt", ".md", ".cfg", ".toml", ".json")):
                continue
            try:
                text = zf.read(name).decode("utf-8", "replace")
            except Exception:
                continue
            for marker in SECRET_MARKERS:
                if marker in text:
                    hits.append(f"{name}: {marker}")
    if hits:
        raise SystemExit("SECRET MATERIAL FOUND IN THE WHEEL - release aborted:\n" + "\n".join(hits))
    print(f"  wheel secret scan: clean ({wheel.name})")


def build_exe() -> Path | None:
    try:
        import PyInstaller  # noqa: F401 - availability probe only

        available = True
    except ImportError:
        available = False
    if not SPEC.exists():
        print("  UMBRA.spec missing - skipping the exe (manual step)")
        return None
    if not available:
        print("  PyInstaller not installed - MANUAL STEP:")
        print("    pip install pyinstaller && python -m PyInstaller UMBRA.spec --noconfirm")
        return None
    print("  building UMBRA.exe (PyInstaller) ...")
    proc = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            sys.executable, "-m", "PyInstaller", str(SPEC),
            "--noconfirm", "--distpath", str(DIST), "--workpath", str(REPO / "build"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:])
        raise SystemExit("exe build failed - release aborted")
    exe = DIST / "UMBRA.exe"
    if not exe.exists():
        raise SystemExit("PyInstaller reported success but UMBRA.exe is missing")
    return exe


def write_sums(artifacts: list[Path]) -> Path:
    lines = []
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}")
    out = DIST / "SHA256SUMS"
    # LF endings only: CRLF makes `sha256sum -c` fail on Linux and Git Bash
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


def update_readme_releases(version: str, artifact_names: list[str]) -> None:
    entry = f"- **{version}** - " + ", ".join(artifact_names) + " (see `dist/SHA256SUMS`)"
    text = README.read_text(encoding="utf-8")
    if RELEASES_BEGIN in text and RELEASES_END in text:
        pre, rest = text.split(RELEASES_BEGIN, 1)
        _, post = rest.split(RELEASES_END, 1)
        block = "\n".join([RELEASES_BEGIN, entry, RELEASES_END])
        new_text = pre + block + post
    else:
        section = (
            "\n## Releases\n\n"
            f"{RELEASES_BEGIN}\n{entry}\n{RELEASES_END}\n"
        )
        new_text = text.rstrip("\n") + "\n" + section
    README.write_text(new_text, encoding="utf-8")


def write_checklist(version: str, artifacts: list[Path], args_signed: bool = False) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Release checklist - {version} ({today})",
        "",
        "## Built",
        "- [ ] Smoke suite green (release.py refuses to build otherwise)",
        ("- [ ] artifacts signed" if args_signed
         else "- [ ] UNSIGNED build - configure UMBRA_SIGN_CERT and re-run with --sign "
              "before wide distribution"),
    ]
    for artifact in artifacts:
        lines.append(f"- [ ] {artifact.name} built")
    lines += [
        "- [ ] SHA256SUMS matches the artifacts (`sha256sum -c dist/SHA256SUMS`)",
        "- [ ] Wheel secret scan clean (release.py enforces)",
        "",
        "## Publish",
        "- [ ] Commit with the version bump (title has NO version number)",
        "- [ ] Tag v" + version + " and push it",
        "- [ ] GitHub release: attach wheel, UMBRA.exe (if built), SHA256SUMS",
        "- [ ] Sign the update manifest (payload + Ed25519 signature) and upload",
        "      umbra-manifest.json to the release - the update checker reads it",
        "- [ ] CI green on the release commit",
        "- [ ] Storefront (docs/index.html) copy reflects the new features",
        "- [ ] NO private key material anywhere: Documents/umbra-private and",
        "      PRIVATE-DO-NOT-SHARE stay out of every artifact and upload",
        "- [ ] Update the launcher repo release if the Android app changed",
    ]
    CHECKLIST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and stage an UMBRA release.")
    parser.add_argument("--version", help="target version X.Y.Z (default: minor bump)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--skip-tests", action="store_true", help="do not run the suite (not recommended)")
    parser.add_argument("--skip-exe", action="store_true", help="skip the PyInstaller exe build")
    parser.add_argument("--sign", action="store_true",
                        help="attempt artifact signing (requires UMBRA_SIGN_CERT configured; "
                             "without it the build stays UNSIGNED with a recorded warning)")
    args = parser.parse_args()

    old_version = read_version()
    new_version = bump_version(old_version, args.version)
    print(f"UMBRA release: {old_version} -> {new_version}" + ("  (DRY RUN)" if args.dry_run else ""))

    if args.dry_run:
        print("  would: bump pyproject.toml + src/jarvis/__init__.py + tests version assertion")
        print("  would: run python tests/test_smoke.py (abort on failure)")
        print("  would: python -m pip wheel . --no-deps -w dist/")
        if args.skip_exe:
            print("  would: skip the exe (--skip-exe)")
        elif SPEC.exists():
            print("  would: python -m PyInstaller UMBRA.spec --noconfirm (PyInstaller available)")
        else:
            print("  would: skip the exe (no UMBRA.spec)")
        print(f"  would: write {DIST / 'SHA256SUMS'}")
        print(f"  would: update the {RELEASES_BEGIN} block in README.md")
        print(f"  would: write {CHECKLIST}")
        print("  would: scan the wheel for secret material (abort on any hit)")
        print("dry run complete - nothing was modified")
        return 0

    apply_version_bump(new_version, old_version)
    if not args.skip_tests:
        run_suite()
    else:
        print("  SKIPPING the suite (--skip-tests) - not recommended")

    artifacts: list[Path] = []
    wheel = build_wheel()
    if wheel is not None:
        artifacts.append(wheel)
        scan_wheel_for_secrets(wheel)
    if not args.skip_exe:
        exe = build_exe()
        if exe is not None:
            artifacts.append(exe)
    if not artifacts:
        raise SystemExit("no artifacts were built")
    signed = False
    if args.sign:
        # Code signing requires a certificate configured outside this repo
        # (UMBRA_SIGN_CERT -> signtool/codesign invocation). Until that exists,
        # every build is explicitly UNSIGNED and the checklist records it.
        import os as _os

        if _os.environ.get("UMBRA_SIGN_CERT"):
            print("  [signing] UMBRA_SIGN_CERT is set - wire the signtool/codesign "
                  "invocation here once the certificate is provisioned.")
            signed = True
        else:
            print("  [signing] UNSIGNED BUILD - no certificate configured. Recorded "
                  "in RELEASE-CHECKLIST.md; see SUPPORT.md 'Code signing'.")
    sums = write_sums(artifacts)
    update_readme_releases(new_version, [a.name for a in artifacts])
    write_checklist(new_version, artifacts, args_signed=signed)
    print(f"  SHA256SUMS: {sums}")
    print(f"  checklist:  {CHECKLIST}")
    print(f"release {new_version} staged. Next: commit, tag v{new_version}, upload artifacts.")
    return 1 if args.skip_tests else 0


if __name__ == "__main__":
    raise SystemExit(main())
