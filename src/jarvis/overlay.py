"""Mark XXVI - the overlay: UMBRA beside your other apps.

`jarvis overlay` opens a small always-on-top companion window (Tkinter,
stdlib) that shows live API status and the last reply, and accepts queries
which it sends to the local API (`jarvis serve --api`).

- `--attach <process-name>` best-effort finds the process (psutil, already a
  dependency) and tags sent messages with a context line - honest scope: the
  overlay observes nothing by itself.
- `--clickthrough` makes the window click-through on Windows (display-only:
  the input box will not receive clicks while active).
- Without Tkinter the overlay degrades to a console companion with the same
  behavior; `--no-ui` runs the logic headless (status once, clean exit) for
  tests and scripting.
"""

from __future__ import annotations

import http.client
import json
import threading

from . import api as api_mod
from . import config
from .api import ensure_token, load_token


def fetch_status(port: int, token: str) -> dict | None:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
        conn.request("GET", "/health", headers={"X-Jarvis-Token": token})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return data if resp.status == 200 else None
    except (OSError, ValueError):
        return None


def fetch_chat(port: int, token: str, text: str) -> dict:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        conn.request(
            "POST", "/chat",
            body=json.dumps({"text": text}),
            headers={"X-Jarvis-Token": token, "Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return data
    except (OSError, ValueError) as exc:
        return {"error": f"API offline - run jarvis serve --api ({exc})"}


def find_process(name_sub: str) -> str | None:
    """Best-effort process lookup via psutil (already a dependency)."""
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name"]):
            pname = (proc.info.get("name") or "").lower()
            if name_sub.lower() in pname:
                return f"{proc.info['name']} (pid {proc.info['pid']})"
    except Exception:
        return None
    return None


def run_overlay(
    console,
    attach_name: str | None = None,
    no_ui: bool = False,
    clickthrough: bool = False,
) -> int:
    token = ensure_token()
    # EDITH-protocol: cross-app attachment requires full access (Mark XXXI)
    if attach_name:
        from .access import require_full

        if not require_full("overlay --attach " + attach_name):
            console.print(
                "[red]Full access is not granted.[/] Cross-app attachment needs it:\n"
                "  [bold]jarvis access grant --full[/]"
            )
            return 1
    attach_desc = find_process(attach_name) if attach_name else None
    if no_ui:
        status = fetch_status(api_mod.DEFAULT_PORT, token)
        if status:
            console.print(
                f"[green]API online:[/] {status.get('model')} "
                f"(tier {status.get('tier')}, version {status.get('version')})"
                + (f" · attached: {attach_desc}" if attach_desc else "")
            )
        else:
            console.print(
                "[yellow]API offline[/] - start it with [bold]jarvis serve --api[/]"
                + (f" · attached: {attach_desc}" if attach_desc else "")
            )
        return 0
    try:
        import tkinter  # noqa: F401 - availability probe
    except ImportError:
        return _console_companion(console, token, attach_desc)
    return _tk_ui(token, attach_desc, clickthrough)


def _console_companion(console, token: str, attach_desc: str | None) -> int:
    console.print(
        "[yellow]Tkinter unavailable - console companion mode.[/] "
        "Type a message, Enter to send, Ctrl+C to exit."
    )
    while True:
        try:
            text = console.input("[bold cyan]you>[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]Overlay standing down, Sir.[/]")
            return 0
        if not text.strip():
            continue
        if attach_desc:
            text = f"[context: user is working in {attach_desc}]\n" + text
        data = fetch_chat(api_mod.DEFAULT_PORT, token, text)
        console.print(
            (data or {}).get("reply")
            or (data or {}).get("error")
            or "[yellow]no response[/]"
        )


def _apply_clickthrough(root) -> None:
    """Windows-only best effort: layered + transparent window style."""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x20 | 0x80000)
    except Exception:
        pass  # best effort on non-Windows or window-manager refusal


def _tk_ui(token: str, attach_desc: str | None, clickthrough: bool) -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("UMBRA")
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.88)
    except tk.TclError:
        pass
    root.geometry("400x480+60+60")
    root.configure(bg="#050A12")

    status = tk.Label(
        root, text="UMBRA · checking API...", fg="#7FA8B8", bg="#050A12",
        font=("Consolas", 9), anchor="w",
    )
    status.pack(fill="x", padx=8, pady=(8, 0))
    log = tk.Text(
        root, bg="#050A12", fg="#66F0FF", insertbackground="#66F0FF",
        font=("Consolas", 10), height=20, wrap="word", state="disabled",
        relief="flat",
    )
    log.pack(fill="both", expand=True, padx=8, pady=6)
    entry = tk.Entry(
        root, bg="#0E2233", fg="#66F0FF", insertbackground="#66F0FF",
        font=("Consolas", 11), relief="flat",
    )
    entry.pack(fill="x", padx=8, pady=(0, 8))

    if clickthrough:
        _apply_clickthrough(root)

    def append(text: str) -> None:
        log.config(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.config(state="disabled")

    def refresh_status() -> None:
        info = fetch_status(api_mod.DEFAULT_PORT, token)
        if info:
            status.config(text=f"UMBRA · {info.get('model')} · tier {info.get('tier')}")
        else:
            status.config(text="UMBRA · API offline (jarvis serve --api)")
        root.after(10000, refresh_status)

    def send(event=None) -> None:
        text = entry.get().strip()
        if not text:
            return
        entry.delete(0, "end")
        if attach_desc:
            text = f"[context: user is working in {attach_desc}]\n" + text
        append("YOU: " + text)

        def worker() -> None:
            data = fetch_chat(api_mod.DEFAULT_PORT, token, text)
            reply = (data or {}).get("reply") or (data or {}).get("error") or "(no response)"
            root.after(0, lambda: append("J: " + reply))

        threading.Thread(target=worker, daemon=True).start()

    entry.bind("<Return>", send)
    append("UMBRA overlay online, Sir.")
    refresh_status()
    root.mainloop()
    return 0
