# -*- coding: utf-8 -*-
"""
core/adb.py
~~~~~~~~~~~
Thin wrapper around adb.exe — runs commands, streams output, detects
device state, and drives ADB Sideload with live progress parsing.

Mirrors the structure of core/fastboot.py so the two stay consistent.
"""

from __future__ import annotations
import os
import re
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


def _adb_path() -> Optional[str]:
    mei = getattr(sys, "_MEIPASS", None) or ""
    for d in (mei, BIN_DIR, BASE_DIR, os.getcwd()):
        if not d:
            continue
        p = os.path.join(d, "adb.exe")
        if os.path.isfile(p):
            return p
    return None


def adb_available() -> bool:
    return _adb_path() is not None


_current_proc: Optional[subprocess.Popen] = None
_proc_lock    = threading.Lock()


def kill_current() -> None:
    """Kill whatever adb process is currently running (e.g. an in-progress sideload)."""
    with _proc_lock:
        p = _current_proc
    if p:
        try:
            p.kill()
        except Exception:
            pass


def run_adb(
    args: list,
    timeout: int = 30,
    line_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, str, str]:
    """
    Run an adb command and stream its output line-by-line via ``line_cb``.

    adb sideload reports progress using carriage returns (\\r) instead of
    newlines to redraw the same line, so we split on either character —
    plain fastboot-style newline splitting would swallow that progress.
    """
    global _current_proc

    exe = _adb_path()
    if not exe:
        return -1, "", "NOT_FOUND"

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
            buf = bytearray()
            while True:
                chunk = stream.read(1)
                if not chunk:
                    break
                if chunk in (b"\n", b"\r"):
                    if buf:
                        line = bytes(buf).decode(errors="replace").strip()
                        buf.clear()
                        if line:
                            store.append(line)
                            if cb:
                                cb(line)
                else:
                    buf += chunk
            if buf:
                line = bytes(buf).decode(errors="replace").strip()
                if line:
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


def get_device_state() -> str:
    """
    Returns the adb device state, mirroring 'adb devices' output:
      'sideload'      — device is in recovery, waiting for a sideload push
      'device'        — normal adb session
      'recovery'      — in recovery but not yet in sideload mode
      'unauthorized'  — needs USB-debugging authorization on the device
      'offline'       — listed but not responding
      'none'          — nothing connected
      'no_adb'        — adb.exe not found
    """
    rc, out, _err = run_adb(["devices"], timeout=6)
    if rc == -1:
        return "no_adb"
    lines = [l for l in out.splitlines()
             if l.strip() and "List of devices" not in l]
    if not lines:
        return "none"
    parts = lines[0].split()
    if len(parts) >= 2:
        return parts[1].strip().lower()
    return "none"


_PCT_RE = re.compile(r"(\d{1,3})\s*%")


def parse_sideload_percent(line: str) -> Optional[int]:
    """
    Extract a 0-100 percentage from a sideload progress line, e.g.:
      "serving: 'update.zip'  (~45%)"
    Returns None if the line carries no percentage.
    """
    m = _PCT_RE.search(line)
    if not m:
        return None
    try:
        return max(0, min(100, int(m.group(1))))
    except ValueError:
        return None


def sideload(
    zip_path: str,
    line_cb: Optional[Callable[[str], None]] = None,
    timeout: int = 1800,
) -> tuple[int, str, str]:
    """
    Run 'adb sideload <zip_path>'. Default timeout is 30 minutes since large
    GSI/OTA zips can take a while over USB while the device is in recovery.
    """
    return run_adb(["sideload", zip_path], timeout=timeout, line_cb=line_cb)
