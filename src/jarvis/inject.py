"""Mark XXVII - device injection: one command installs UMBRA elsewhere.

`jarvis inject scan`     - sweep the LAN /24 on telling ports (22 ssh,
                           445 smb, 5555 adb, 8775 UMBRA API) and guess each
                           host's OS + install feasibility. Threaded TCP
                           connect is the stdlib-friendly sweep (ICMP needs
                           raw sockets/admin); no mDNS without a dependency.
`jarvis inject install`  - push the wheel/exe/installer to a target over
                           ssh/scp (windows, linux) or adb (android).
                           --dry-run prints the exact plan with ZERO network
                           calls; --yes is required for a real install.
`jarvis inject bundle`   - offline self-contained installer zip: wheel,
                           UMBRA.exe when available, generated installer
                           scripts, public key text, README. NO private keys,
                           NO secrets - the public key ships in the package
                           itself (licensing.PUBLIC_KEY_B64) and as a text
                           file.

Safety:
- Plans are pure data (argv lists); runner.py is the single execution point,
  argv-only, shell=False - no shell parser ever sees target or plan text.
- Remote ssh command strings are module constants; the target is validated
  against a strict [user@]host charset (letters, digits, dot, dash,
  underscore) before any plan exists.
- Passwords are never asked for or stored (SSH keys/agent only).
- root/admin targets are refused without --i-know.
- The private-key folder is never read, referenced, or pushed. Windows-over-
  WinRM is not implemented - the plan prints the exact manual command
  instead (noted assumption).
"""

from __future__ import annotations

import re
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

SCAN_PORTS = (22, 445, 5555, 8775)
SCAN_TIMEOUT_S = 0.15
SCAN_PORT_LABELS = {
    22: "ssh",
    445: "smb (likely windows)",
    5555: "adb",
    8775: "UMBRA API",
}

# strict target charset: [user@]host - the ONLY user data that reaches a
# remote command line, and only as the ssh login target argument.
_SAFE_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:@[A-Za-z0-9][A-Za-z0-9._-]*)?$")

# remote installer commands are constants - never assembled from user input
_WIN_INSTALL_CMD = "powershell -NoProfile -ExecutionPolicy Bypass -File umbra-install/install-umbra.ps1"
_LIN_INSTALL_CMD = "bash /tmp/install-umbra.sh"
_LIN_INSTALL_UNIT_CMD = "bash /tmp/install-umbra.sh --user-unit"


def validated_target(target: str) -> str:
    target = (target or "").strip()
    match = _SAFE_TARGET.fullmatch(target)
    if not match:
        raise SystemExit(
            f"invalid target {target!r} - use [user@]host or an IP "
            "(letters, digits, dot, dash, underscore only)"
        )
    return target


# ------------------------------------------------------------------- scan


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sweep_hosts(hosts: list[str], ports: list[int], timeout: float = SCAN_TIMEOUT_S) -> dict[str, list[int]]:
    """Probe (host, port) pairs concurrently; returns host -> open ports."""
    combos = [(host, port) for host in hosts for port in ports]
    with ThreadPoolExecutor(max_workers=128) as pool:
        futures = [pool.submit(_port_open, host, port, timeout) for host, port in combos]
    open_by_host: dict[str, list[int]] = {}
    for (host, port), future in zip(combos, futures):
        try:
            is_open = bool(future.result())
        except Exception:
            is_open = False
        if is_open:
            open_by_host.setdefault(host, []).append(port)
    return {host: sorted(ports_) for host, ports_ in open_by_host.items()}


def lan_subnet_hosts() -> list[str]:
    """The /24 around this machine's LAN address (portal.lan_address)."""
    from .portal import lan_address

    address = lan_address()
    parts = address.split(".")
    if len(parts) != 4:
        return []
    prefix = ".".join(parts[:3])
    return [f"{prefix}.{last}" for last in range(1, 255)]


def guess_os(open_ports: list[int]) -> str:
    has = set(open_ports)
    if 8775 in has:
        return "UMBRA API (already injected)"
    if 5555 in has and 22 not in has:
        return "android (adb)"
    if 22 in has and 445 in has:
        return "windows (ssh+smb) - install possible over ssh"
    if 22 in has:
        return "linux/unix (ssh) - install possible over ssh"
    if 445 in has:
        return "windows (smb only) - needs ssh or WinRM"
    return "unknown"


def run_scan(console, timeout: float = SCAN_TIMEOUT_S) -> int:
    console.print("[cyan]Sweeping the local /24 on ports 22/445/5555/8775...[/]")
    found = sweep_hosts(lan_subnet_hosts(), list(SCAN_PORTS), timeout)
    if not found:
        console.print("[yellow]No responsive hosts found.[/]")
        return 0
    for host in sorted(found):
        ports = found[host]
        labels = ", ".join(f"{p} ({SCAN_PORT_LABELS.get(p, '?')})" for p in ports)
        console.print(f"  [bold]{host}[/]  open: {labels}")
        console.print(f"      guess: {guess_os(ports)}")
    console.print(
        "[dim]Install with: jarvis inject install --target <ip> "
        "--os <windows|linux|android> --dry-run[/]"
    )
    return 0


# ---------------------------------------------------------------- install


def _wheel_name() -> str:
    from . import __version__

    return f"jarvis_ai-{__version__}-py3-none-any.whl"


def _root_guard(target: str, i_know: bool) -> None:
    user = target.split("@")[0].lower() if "@" in target else ""
    if user in ("root", "administrator", "admin") and not i_know:
        raise SystemExit(
            "refusing to install into an admin/root account without --i-know."
        )


def build_plan(os_name: str, target: str, apk: Path | None = None,
               systemd: bool = False) -> list[tuple[str, list[str]]]:
    """The exact execution plan, as data. Printed by --dry-run, executed by
    runner.execute_steps. The target is regex-validated before any argv
    exists; remote ssh commands are module constants."""
    safe = validated_target(target)
    wheel = _wheel_name()

    if os_name == "android":
        if apk is None:
            raise SystemExit("android install needs --apk <path to UMBRA-launcher-*.apk>")
        apk_arg = str(apk)
        return [
            ("verify a device is attached", ["adb", "devices"]),
            ("install the launcher APK", ["adb", "install", "-r", apk_arg]),
        ]

    if os_name == "windows":
        wheel_arg = f"dist/{wheel}"
        dest = f"{safe}:umbra-install/"
        return [
            (f"push wheel + exe + installer to {dest}",
             ["scp", wheel_arg, "dist/UMBRA.exe", "scripts/install-umbra.ps1", dest]),
            ("run the silent installer over ssh",
             ["ssh", safe, _WIN_INSTALL_CMD]),
        ]

    if os_name == "linux":
        wheel_arg = f"dist/{wheel}"
        dest = f"{safe}:/tmp/"
        remote = _LIN_INSTALL_UNIT_CMD if systemd else _LIN_INSTALL_CMD
        return [
            (f"push wheel + installer to {dest}",
             ["scp", wheel_arg, "scripts/install-umbra.sh", dest]),
            ("run the installer over ssh",
             ["ssh", safe, remote]),
        ]

    raise SystemExit(f"unsupported os {os_name!r} - use windows, linux or android")


def print_plan(console, steps: list[tuple[str, list[str]]]) -> None:
    for index, (description, argv) in enumerate(steps, start=1):
        console.print(f"  {index}. {description}")
        console.print(f"     [dim]{' '.join(argv)}[/]")


def run_install(console, os_name: str, target: str, apk: Path | None,
                systemd: bool, dry_run: bool, yes: bool, i_know: bool) -> int:
    _root_guard(target, i_know)
    steps = build_plan(os_name, target, apk=apk, systemd=systemd)
    if dry_run:
        # read-only planning: allowed without a grant (zero network, zero reach)
        console.print("[cyan]Dry run - the plan (zero network calls made):[/]")
        print_plan(console, steps)
        return 0
    if not yes:
        console.print("[yellow]A real install is about to run on the target.[/]")
        console.print("Review it first with [bold]--dry-run[/], then add [bold]--yes[/] to execute.")
        return 1

    # EDITH-protocol Phase 1 spine: real installs go through the authorize
    # chokepoint (install tier) + a per-target confirm
    from . import access

    allowed, reason = access.authorize("inject.install", target=target)
    if not allowed:
        console.print(
            f"[red]{reason}[/]\n"
            "Grant it interactively: [bold]jarvis access grant --full[/]"
        )
        return 1
    from rich.prompt import Confirm

    if not Confirm.ask(f"[yellow]Install UMBRA onto {target} right now?[/]", default=False):
        from .access import log_append

        log_append("install_aborted", "per-target confirmation declined: " + target)
        console.print("[dim]Aborted - no install.[/]")
        return 1

    from .runner import execute_steps

    code = execute_steps(steps, console)
    from .access import log_append

    log_append("install_done" if code == 0 else "install_failed", "target: " + target)
    if code == 0:
        console.print("[green]Injected, Sir. UMBRA now lives on the target.[/]")
    return code


# ----------------------------------------------------------------- bundle


INSTALL_PS1 = """# UMBRA silent installer (Windows) - generated by jarvis inject bundle.
$ErrorActionPreference = "Stop"
$dest = "$env:LOCALAPPDATA\\UMBRA"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "UMBRA.exe" $dest -Force
$wheel = Get-ChildItem -Filter "jarvis_ai-*.whl" | Select-Object -First 1
if ($wheel) { Copy-Item $wheel.FullName $dest -Force }
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:USERPROFILE\\Desktop\\UMBRA.lnk")
$lnk.TargetPath = "$dest\\UMBRA.exe"
$lnk.Save()
Write-Host "UMBRA installed to $dest - shortcut on the Desktop."
"""

INSTALL_SH = """#!/usr/bin/env bash
# UMBRA installer (Linux) - generated by jarvis inject bundle.
set -e
DEST="$HOME/.local/share/umbra"
BIN="$HOME/.local/bin"
mkdir -p "$DEST" "$BIN"
cp UMBRA.exe "$DEST/" 2>/dev/null || true
WHEEL=$(ls jarvis_ai-*.whl 2>/dev/null | head -n 1 || true)
if [ -n "$WHEEL" ]; then
  python3 -m pip install --user "$WHEEL"
fi
printf '#!/usr/bin/env bash\\nexec python3 -m jarvis "$@"\\n' > "$BIN/umbra"
chmod +x "$BIN/umbra"
if [ "${1:-}" = "--user-unit" ]; then
  mkdir -p "$HOME/.config/systemd/user"
  printf '[Unit]\\nDescription=UMBRA sentinel\\n[Service]\\nExecStart=%s -m jarvis sentinel\\n[Install]\\nWantedBy=default.target\\n' \\
    "$(command -v python3)" > "$HOME/.config/systemd/user/umbra-sentinel.service"
  systemctl --user daemon-reload
  echo "unit installed: systemctl --user enable --now umbra-sentinel"
fi
echo "UMBRA installed - run: $BIN/umbra"
"""

BUNDLE_README = """UMBRA offline install bundle
============================
Contents: the wheel (pip-installable), UMBRA.exe when built, installer
scripts for Windows/Linux, and the publisher's PUBLIC key (the PRO verifier
is embedded in the package itself).

Windows: powershell -ExecutionPolicy Bypass -File install-umbra.ps1
Linux:   bash install-umbra.sh          (add --user-unit for a sentinel unit)
Android: adb install -r UMBRA-launcher-*.apk   (APK ships separately)

First run starts the setup wizard: pick a brain, paste a key (or use a
local Ollama), done. Everything stays on the target machine.
"""


def locate_artifacts() -> tuple[Path | None, Path | None]:
    """Newest wheel + exe from dist/ (or UMBRA-PRODUCT as a fallback)."""
    wheels: list[Path] = []
    exe: Path | None = None
    for base in (Path("dist"),
                 Path.home() / "OneDrive" / "Documents" / "UMBRA-PRODUCT" / "windows"):
        if not base.is_dir():
            continue
        found = sorted(base.glob("jarvis_ai-*.whl"), key=lambda p: p.stat().st_mtime)
        if found:
            wheels.append(found[-1])
        candidate = base / "UMBRA.exe"
        if candidate.is_file():
            exe = candidate
    return (wheels[-1] if wheels else None, exe)


def build_bundle(out: Path, wheel: Path | None, exe: Path | None) -> Path:
    """Offline installer zip. Public key text comes from the package itself;
    this function never touches any private-key folder."""
    from . import __version__
    from .licensing import PUBLIC_KEY_B64

    out = out.with_suffix(".zip") if out.suffix != ".zip" else out
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        if wheel is not None:
            zf.write(wheel, wheel.name)
        if exe is not None:
            zf.write(exe, exe.name)
        zf.writestr("install-umbra.ps1", INSTALL_PS1)
        zf.writestr("install-umbra.sh", INSTALL_SH)
        zf.writestr("umbra-public-key.txt", PUBLIC_KEY_B64 + "\n")
        zf.writestr("README-INSTALL.txt", BUNDLE_README)
        zf.writestr("VERSION", __version__ + "\n")
    return out


def no_secrets_guard(bundle: Path) -> None:
    """Belt and braces: the bundle must never contain key material."""
    with zipfile.ZipFile(bundle) as zf:
        for name in zf.namelist():
            lowered = name.lower()
            if lowered.endswith((".pem", ".p12", ".pfx", ".key")):
                raise SystemExit("SECRET MATERIAL IN BUNDLE: " + name)
            if "private" in lowered:
                raise SystemExit("private material in bundle: " + name)


def run_inject(console, args: list[str]) -> int:
    sub = args[0] if args else ""
    if sub in ("", "--help", "-h"):
        console.print(
            "usage: jarvis inject scan\n"
            "       jarvis inject install --target <ip|host> --os <windows|linux|android>\n"
            "                         [--apk <file>] [--systemd] [--dry-run] [--yes] [--i-know]\n"
            "       jarvis inject bundle [--out <file>]\n"
            "One command installs UMBRA on another device. Passwords are never asked\n"
            "for or stored - SSH keys/agent only. Root/admin targets need --i-know."
        )
        return 0

    if sub == "scan":
        return run_scan(console)

    if sub == "install":
        rest = args[1:]
        target = _flag(rest, "--target")
        os_name = _flag(rest, "--os")
        if not target or not os_name:
            console.print(
                "usage: jarvis inject install --target <ip|host> "
                "--os <windows|linux|android> [...]"
            )
            return 1
        apk = None
        if "--apk" in rest:
            index = rest.index("--apk")
            if index + 1 < len(rest):
                apk = Path(rest[index + 1])
        return run_install(
            console, os_name, target, apk=apk,
            systemd="--systemd" in rest,
            dry_run="--dry-run" in rest,
            yes="--yes" in rest,
            i_know="--i-know" in rest,
        )

    if sub == "bundle":
        out = Path(_flag(args[1:], "--out") or "umbra-inject-bundle.zip")
        wheel, exe = locate_artifacts()
        if wheel is None:
            console.print("[yellow]No wheel in dist/ - building one first...[/]")
            from .runner import build_wheel_to_dist

            if not build_wheel_to_dist():
                console.print("[red]wheel build failed[/]")
                return 1
            wheel, exe = locate_artifacts()
        bundle = build_bundle(out, wheel, exe)
        no_secrets_guard(bundle)
        console.print("[green]Bundle written:[/] " + str(bundle))
        console.print("  wheel: " + (wheel.name if wheel else "(none)")
                      + " · exe: " + ("yes" if exe else "not built"))
        console.print(
            "[dim]No private keys, no secrets - the public key ships in the package.[/]"
        )
        return 0

    console.print("usage: jarvis inject scan | install | bundle (--help)")
    return 1


def _flag(args: list[str], flag: str) -> str | None:
    if flag in args:
        index = args.index(flag)
        if index + 1 < len(args):
            return args[index + 1]
    return None
