"""Safety gate: denylist for commands, URL rule, output truncation.

The gate lives here, in code - not in the prompt. The model cannot disable it;
it can only be overridden by the human answering a confirmation question.

The structural defense for command execution is shell_tool.py's argument-list
execution (shell=False): no shell ever parses model-generated text, which
removes entire bypass classes (quoting tricks, expansion, pipes). The denylist
below is the second layer: anything matching it is confirm-gated, covering
dangers that exist even without a shell (dangerous executables, inline-code
interpreters, downloader chains).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener
from urllib.request import HTTPRedirectHandler

# (pattern, reason) - matched case-insensitively against the full command line.
DENYLIST: list[tuple[str, str]] = [
    (r"\bshutdown\b", "shuts down the machine"),
    (r"\brestart-computer\b", "restarts the machine"),
    (r"\bformat\s+[a-z]:", "formats a drive"),
    (r"\bdiskpart\b", "raw disk partitioning"),
    (r"\bdd\s+if=", "raw disk write"),
    (r"\bmkfs", "filesystem format"),
    (r"\brm\s+[^|;&]*(-[a-z]*[rf]\b|--recursive|--force)", "recursive/forced delete"),
    (r"\bdel\s+/[fs]\b", "forced/recursive delete"),
    (r"\berase\s+/[fs]\b", "forced/recursive delete"),
    (r"\brmdir\s+/s\b", "recursive delete"),
    (r"remove-item\s+[^|;&]*-recurse", "recursive delete (PowerShell)"),
    (r"\breg\s+(add|delete|import|restore)\b", "registry modification"),
    (r"\bregedit\b", "registry editor"),
    (r"\bvssadmin\s+delete\b", "deletes shadow copies"),
    (r"\bcipher\s+/w\b", "secure free-space wipe"),
    (r"\bnet\s+user\s+.*/(add|delete)\b", "user account modification"),
    (r"(curl|wget|invoke-webrequest|iwr)\b[^|;&]*\|\s*(sh|bash|iex|powershell)\b",
     "downloads and pipes remote code straight into a shell"),
    # Encoding / download-and-run vectors (dangerous even without shell pipes)
    (r"\bcertutil\b.*(-urlcache|-decode)", "certutil download/decode payload vector"),
    (r"\bmshta\b", "mshta script execution"),
    (r"\bbitsadmin\s+/transfer\b", "bitsadmin download"),
    (r"powershell\b.*\s-(enc|ec|encodedcommand)\b", "encoded PowerShell command"),
    (r"\bbase64\s+(-d\b|-D\b|--decode\b)", "base64 decode in a command context"),
    # Inline-code interpreters can execute arbitrary logic from argv
    (r"powershell\b.*\s-(command|c)\s", "arbitrary PowerShell execution"),
    (r"\bpython[0-9.]*\s+-c\b", "inline Python execution"),
    (r"\bnode\s+(-e|--eval)\b", "inline JavaScript execution"),
]


def check_command(command: str) -> tuple[bool, str]:
    """Return (is_dangerous, reason) for a command line."""
    for pattern, reason in DENYLIST:
        if re.search(pattern, command, re.IGNORECASE):
            return True, reason
    return False, ""


# ------------------------------------------------------------------- URLs
# Rule: only http/https; for URLs the model or remote content can influence,
# local/loopback/private/reserved hosts are rejected (SSRF defense). The one
# sanctioned exception is a user-configured local brain (Ollama/LM Studio),
# where localhost is the feature - call sites pass allow_local=True explicitly.

_LOCAL_NAME_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".invalid",  # RFC 2606 reserved TLDs can never be legitimate public targets
    ".test",
    ".example",
)


def check_url(url: str, allow_local: bool = False) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "unparseable URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme must be http/https, got {parsed.scheme!r}"
    host = parsed.hostname
    if not host:
        return False, "missing host"
    if allow_local:
        return True, ""
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(_LOCAL_NAME_SUFFIXES):
        return False, "local/internal hosts are not allowed"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True, ""  # a regular domain name
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_reserved
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return False, "private/reserved IP hosts are not allowed"
    return True, ""


def _ip_allowed(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_local: bool) -> bool:
    if allow_local:
        return True  # sanctioned local endpoints (user-configured local brains)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_reserved
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    )


class _NoRedirects(HTTPRedirectHandler):
    """Refuse redirects: a 3xx from these endpoints is unexpected, not followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def guarded_fetch_json(url: str, allow_local: bool = False, timeout: float = 3.0):
    """Fetch JSON with full boundary checks: scheme, host, resolved IPs, redirects.

    Implements the SSRF rule end to end: protocol allow-list, hostname check,
    DNS resolution verified against the IP boundary (anti DNS-rebinding), and
    redirect refusal. Raises ValueError on any violation.
    """
    ok, reason = check_url(url, allow_local=allow_local)
    if not ok:
        raise ValueError(f"URL rejected: {reason}")
    host = urlparse(url).hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not _ip_allowed(addr, allow_local):
            raise ValueError(f"host {host!r} resolves to a forbidden address ({addr})")
    request = Request(url, headers={"User-Agent": "jarvis"})
    with build_opener(_NoRedirects).open(request, timeout=timeout) as resp:  # noqa: S310 - guarded above
        if getattr(resp, "status", 200) != 200:
            raise ValueError(f"unexpected status {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def guarded_fetch_bytes(
    url: str, max_bytes: int, allow_local: bool = False, timeout: float = 120.0
) -> tuple[bytes | None, str]:
    """Fetch raw bytes with the full SSRF rule applied. No file I/O here.

    Scheme + host + resolved-IP verification (anti DNS-rebinding), redirect
    refusal, hard size cap. Returns (data, "") or (None, reason).
    """
    ok, reason = check_url(url, allow_local=allow_local)
    if not ok:
        return None, f"URL rejected: {reason}"
    host = urlparse(url).hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return None, f"cannot resolve host {host!r}: {exc}"
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not _ip_allowed(addr, allow_local):
            return None, f"host {host!r} resolves to a forbidden address ({addr})"
    request = Request(url, headers={"User-Agent": "jarvis"})
    try:
        with build_opener(_NoRedirects).open(request, timeout=timeout) as resp:  # noqa: S310 - validated above
            if getattr(resp, "status", 200) != 200:
                return None, f"unexpected status {resp.status}"
            data = b""
            total = 0
            while chunk := resp.read(1 << 20):
                total += len(chunk)
                if total > max_bytes:
                    return None, f"download exceeded the {max_bytes:,} byte cap"
                data += chunk
            return data, ""
    except OSError as exc:
        return None, f"download failed: {exc}"


def truncate_output(text: str, limit: int = 8000) -> str:
    """Keep tool outputs from flooding the model's context window."""
    if len(text) <= limit:
        return text
    hidden = len(text) - limit
    return text[:limit] + f"\n... [output truncated - {hidden} characters hidden]"
