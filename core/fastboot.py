# -*- coding: utf-8 -*-
"""
core/fastboot.py
~~~~~~~~~~~~~~~~
Thin wrapper around fastboot.exe — runs commands, streams output line by line,
and detects connected devices.

Also reads the device MODEL (not serial) for the COM/USB info panel,
while keeping the raw serial visible where needed.
"""

from __future__ import annotations
import os
import subprocess
import sys
import threading
from typing import Callable, Optional

from .config import BASE_DIR, BIN_DIR


def _to_short_path(path: str) -> str:
    """Convert a Unicode path to its Windows short (8.3) path to avoid encoding issues."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.kernel32.GetShortPathNameW(path, buf, 512)
        return buf.value if buf.value else path
    except Exception:
        return path


def _fb_path() -> Optional[str]:
    mei = getattr(sys, "_MEIPASS", None) or ""
    for d in (mei, BIN_DIR, BASE_DIR, os.getcwd()):
        if not d:
            continue
        p = os.path.join(d, "fastboot.exe")
        if os.path.isfile(p):
            return p
    return None


def fastboot_available() -> bool:
    return _fb_path() is not None


_current_proc: Optional[subprocess.Popen] = None
_proc_lock    = threading.Lock()


def kill_current() -> None:
    with _proc_lock:
        p = _current_proc
    if p:
        try:
            p.kill()
        except Exception:
            pass


def run_fb(
    args: list,
    timeout: int = 30,
    line_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, str, str]:
    global _current_proc

    exe = _fb_path()
    if not exe:
        return -1, "", "NOT_FOUND"

    # Convert any file paths to short (8.3) paths to handle non-ASCII/Arabic folder names
    def _safe_arg(a: str) -> str:
        s = str(a)
        if os.path.exists(s):
            return _to_short_path(s)
        return s
    cmd = [_to_short_path(exe)] + [_safe_arg(a) for a in args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        with _proc_lock:
            _current_proc = proc

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _read_stream(stream, store, cb=None):
            for raw in stream:
                line = raw.decode(errors="replace").rstrip()
                store.append(line)
                if cb:
                    cb(line)
            stream.close()

        t_out = threading.Thread(
            target=_read_stream, args=(proc.stdout, stdout_lines, line_cb), daemon=True
        )
        t_err = threading.Thread(
            target=_read_stream, args=(proc.stderr, stderr_lines, line_cb), daemon=True
        )
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            t_out.join(2)
            t_err.join(2)
            with _proc_lock:
                _current_proc = None
            return -2, "\n".join(stdout_lines), "\n".join(stderr_lines)

        t_out.join(5)
        t_err.join(5)
        with _proc_lock:
            _current_proc = None

        return proc.returncode, "\n".join(stdout_lines), "\n".join(stderr_lines)

    except Exception as exc:
        with _proc_lock:
            _current_proc = None
        return -1, "", str(exc)


def device_connected_fastboot() -> bool:
    rc, out, err = run_fb(["devices"], timeout=5)
    if rc == -1:
        return False
    return any("fastboot" in l.lower() for l in out.splitlines() if l.strip())


def get_device_model(serial: str) -> str:
    """
    Query the device MODEL string (e.g. 'SM-T509') via fastboot getvar.
    Falls back to the serial if the model cannot be determined.
    """
    rc, out, err = run_fb(["getvar", "product"], timeout=6)
    combined = (out + "\n" + err).lower()
    for line in (out + "\n" + err).splitlines():
        stripped = line.strip()
        if "product:" in stripped.lower():
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                model = parts[1].strip()
                if model:
                    return model.upper()
    # Try 'model' variable
    rc2, out2, err2 = run_fb(["getvar", "model"], timeout=6)
    for line in (out2 + "\n" + err2).splitlines():
        stripped = line.strip()
        if "model:" in stripped.lower():
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                model = parts[1].strip()
                if model:
                    return model.upper()
    return serial   # fallback
