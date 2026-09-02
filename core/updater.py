# -*- coding: utf-8 -*-
"""
core/updater.py
~~~~~~~~~~~~~~~
Background update checker + in-app updater dialog.

Usage
-----
    from core.updater import start_update_check, show_updater_if_needed

    # Call at startup (non-blocking):
    start_update_check()

    # Call after UI is ready (e.g. app.after(3000, ...)):
    show_updater_if_needed(parent_window)

version.txt format (two lines)
-------------------------------
    1.1
    https://github.com/.../SM-T509-Flash-Tool-V1.1.exe
"""

from __future__ import annotations
import os
import sys
import threading
import tkinter as tk
import urllib.request
import webbrowser
from typing import Optional

from .config import APP_VERSION, VERSION_URL, BASE_DIR, BIN_DIR, T, F


# ── Internal state ────────────────────────────────────────────────────────────
# None  = still checking
# False = up to date  /  no internet
# (version_str, download_url)  = update available
_result: "None | bool | tuple[str, str]" = None
_lock   = threading.Lock()


# ── Background fetch ──────────────────────────────────────────────────────────
def _parse_version(v: str) -> tuple:
    """
    Convert any version string to a comparable tuple.
    Strategy:
      1. Strip leading 'v' or 'V'.
      2. Split on any non-alphanumeric separator (. - _ space).
      3. Numeric segments become ints; suffix strings kept as-is.
    Examples:
      '1.1'       -> (1, 1)
      'v1.1_r3'   -> (1, 1, 'r', 3)
      '2.0-beta1' -> (2, 0, 'beta', 1)
    Ensures any tag suffix (r3, rc2, beta) is still detected as newer
    than a plain version with no suffix.
    """
    import re
    try:
        v = v.strip().lstrip("vV")
        parts = re.split(r"[.\-_\s]+", v)
        result: list = []
        for p in parts:
            if not p:
                continue
            # split each segment into alternating alpha/digit chunks
            for chunk in re.findall(r"\d+|[A-Za-z]+", p):
                result.append(int(chunk) if chunk.isdigit() else chunk)
        return tuple(result) if result else (0,)
    except Exception:
        return (0,)


def _fetch() -> None:
    global _result
    try:
        import time as _time
        # Cache-busting timestamp — forces GitHub CDN to bypass its cache
        # so a freshly published version.txt is detected immediately.
        cache_bust = f"?ts={int(_time.time())}"
        req = urllib.request.Request(
            VERSION_URL + cache_bust,
            headers={
                "User-Agent":    f"SM-T509-Flash-Tool/{APP_VERSION}",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma":        "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")

        lines  = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        latest = lines[0] if lines else ""
        dl_url = lines[1] if len(lines) > 1 else ""

        current_t = _parse_version(APP_VERSION)
        latest_t  = _parse_version(latest)

        with _lock:
            if latest_t > current_t and dl_url:
                _result = (latest, dl_url)
            else:
                _result = False

    except Exception:
        with _lock:
            _result = False   # no internet — run silently


def start_update_check() -> None:
    """Kick off the background version check. Call once at startup."""
    t = threading.Thread(target=_fetch, daemon=True, name="update-check")
    t.start()


def show_updater_if_needed(parent: tk.Misc, _retries: int = 0) -> None:
    """
    Check for an update result exactly once at startup.
    Retries only while the background fetch is still in progress,
    up to a hard cap of ~10 seconds total — then gives up silently.
    Never re-schedules after the initial startup window closes.
    """
    _MAX_RETRIES = 12          # 12 x 800 ms = ~10 s max wait
    _RETRY_MS   = 800

    with _lock:
        result = _result

    if result is None:                          # fetch still running
        if _retries < _MAX_RETRIES:
            parent.after(
                _RETRY_MS,
                lambda: show_updater_if_needed(parent, _retries + 1),
            )
        # else: timeout — give up silently, never bother the user again
    elif result is False:                       # up to date or offline
        pass
    else:                                       # (version, url) — show once
        latest_ver, dl_url = result
        _UpdaterDialog(parent, latest_ver, dl_url)


# ── Updater dialog ────────────────────────────────────────────────────────────
class _UpdaterDialog:
    """
    Modal dialog that downloads the new EXE, replaces the current binary
    via a temporary BAT script, and restarts the application.
    """

    _W, _H = 480, 330
    _BG     = "#1c1c22"
    _ACCENT = "#00D8CC"
    _ACCENT_D = "#00897D"
    _ACCENT_H = "#00A89A"
    _FG     = "#EAEAF5"
    _FG2    = "#9090b0"
    _FG3    = "#5a5a7a"
    _CARD   = "#2b2b38"

    def __init__(self, parent: tk.Misc, latest_ver: str, dl_url: str) -> None:
        self._parent     = parent
        self._latest_ver = latest_ver
        self._dl_url     = dl_url
        self._busy       = False

        self._build()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build(self) -> None:
        p = tk.Toplevel(self._parent)
        p.title("Update Available — SM-T509 Flash Tool")
        p.configure(bg=self._BG)
        p.resizable(False, False)
        p.grab_set()
        p.protocol("WM_DELETE_WINDOW", self._close_app)

        p.update_idletasks()
        sx = p.winfo_screenwidth()
        sy = p.winfo_screenheight()
        p.geometry(
            f"{self._W}x{self._H}+{(sx - self._W)//2}+{(sy - self._H)//2}"
        )
        self._apply_dark_titlebar(p)
        self._popup = p

        # accent bar
        tk.Frame(p, bg=self._ACCENT, height=4).pack(fill="x", side="top")

        body = tk.Frame(p, bg=self._BG, padx=32, pady=22)
        body.pack(fill="both", expand=True)

        self._build_header(body)

        tk.Frame(body, bg=T["border"], height=1).pack(fill="x", pady=(0, 14))

        # status label
        self._status_var = tk.StringVar(
            value="Ready to update."
        )
        tk.Label(
            body, textvariable=self._status_var,
            bg=self._BG, fg=self._FG2,
            font=F(10), justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 12))

        self._build_progress(body)
        self._build_buttons(body)

    def _build_header(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=self._BG)
        row.pack(fill="x", pady=(0, 14))

        # icon — try next to exe first, then inside bundle (_MEIPASS)
        _img_path = os.path.join(BASE_DIR, "download.png")
        if not os.path.isfile(_img_path):
            _img_path = os.path.join(BIN_DIR, "download.png")
        self._icon_img = None  # keep reference alive
        try:
            from PIL import Image, ImageTk
            pil_img = Image.open(_img_path).resize((44, 44), Image.LANCZOS)
            self._icon_img = ImageTk.PhotoImage(pil_img)
            tk.Label(row, image=self._icon_img,
                     bg=self._BG).pack(side="left", padx=(0, 14))
        except Exception:
            # fallback: plain canvas circle with arrow if PIL missing or image absent
            ic = tk.Canvas(row, width=44, height=44,
                           bg=self._BG, highlightthickness=0)
            ic.pack(side="left", padx=(0, 14))
            ic.create_oval(2, 2, 42, 42, fill="#00332f",
                           outline=self._ACCENT, width=2)
            ic.create_text(23, 23, text="↑", fill=self._ACCENT,
                           font=("Segoe UI Variable Display", 20, "bold"))

        col = tk.Frame(row, bg=self._BG)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text="New Version Available!",
                 bg=self._BG, fg=self._FG,
                 font=F(13, bold=True)).pack(anchor="w")
        tk.Label(col,
                 text=f"v{APP_VERSION}  →  v{self._latest_ver}",
                 bg=self._BG, fg=self._FG2,
                 font=F(10)).pack(anchor="w", pady=(2, 0))

    def _build_progress(self, parent: tk.Frame) -> None:
        bar_bg = tk.Frame(parent, bg=self._CARD, height=8)
        bar_bg.pack(fill="x", pady=(0, 4))
        bar_bg.pack_propagate(False)

        self._bar_fill = tk.Frame(bar_bg, bg=self._ACCENT, height=8, width=0)
        self._bar_fill.place(x=0, y=0, relheight=1)
        self._bar_bg = bar_bg

        self._pct_lbl = tk.Label(
            parent, text="", bg=self._BG, fg=self._FG3, font=F(9)
        )
        self._pct_lbl.pack(anchor="e", pady=(0, 16))

    def _build_buttons(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=self._BG)
        row.pack(fill="x")

        # primary action canvas-button
        self._btn_c = tk.Canvas(row, width=170, height=38,
                                bg=self._BG, highlightthickness=0,
                                cursor="hand2")
        self._btn_c.pack(side="left")
        self._draw_btn(self._ACCENT_D)
        self._btn_c.bind("<Enter>",    lambda _e: self._draw_btn(self._ACCENT_H))
        self._btn_c.bind("<Leave>",    lambda _e: self._draw_btn(self._ACCENT_D))
        self._btn_c.bind("<Button-1>", lambda _e: self._start_download())

    # ── Download + replace ────────────────────────────────────────────────────
    def _close_app(self) -> None:
        """Close the update dialog and the entire application."""
        try:
            self._parent.destroy()
        except Exception:
            pass
        os._exit(0)

    def _start_download(self) -> None:
        if self._busy:
            return
        self._busy = True

        # lock UI
        self._btn_c.unbind("<Button-1>")
        self._btn_c.unbind("<Enter>")
        self._btn_c.unbind("<Leave>")
        self._draw_btn("#3a3a52")
        self._popup.protocol("WM_DELETE_WINDOW", lambda: None)

        threading.Thread(target=self._download_worker,
                         daemon=True, name="updater-dl").start()

    def _download_worker(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                current_exe = os.path.abspath(sys.executable)
            else:
                current_exe = os.path.abspath(sys.argv[0])

            exe_dir  = os.path.dirname(current_exe)
            # New exe keeps its own versioned name from the URL
            new_name = self._dl_url.split("/")[-1].split("?")[0]  # strip any query string
            new_path = os.path.join(exe_dir, new_name)
            bat_path = os.path.join(exe_dir, "_updater.bat")

            self._set_progress(0, "Connecting to Server...")

            req = urllib.request.Request(
                self._dl_url,
                headers={"User-Agent": f"SM-T509-Flash-Tool/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total      = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(new_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 90
                            self._set_progress(
                                pct,
                                f"Downloading...  "
                                f"{downloaded/1_048_576:.1f} MB"
                                f" / {total/1_048_576:.1f} MB",
                            )
                        else:
                            self._set_progress(
                                50,
                                f"Downloading...  {downloaded/1_048_576:.1f} MB",
                            )

            self._set_progress(95, "Preparing update...")

            # BAT: wait for old exe to exit → delete it → launch new versioned exe
            bat = (
                "@echo off\n"
                "timeout /t 2 /nobreak >nul\n"
                f'del /f /q "{current_exe}" >nul 2>&1\n'
                f'start "" "{new_path}"\n'
                'del "%~f0"\n'
            )
            with open(bat_path, "w", encoding="ascii") as f:
                f.write(bat)

            self._set_progress(100, "Restarting...")
            self._popup.after(600, lambda: self._launch_bat(bat_path))

        except Exception as exc:
            self._set_progress(0, f"Error: {exc}")
            self._popup.after(
                0,
                lambda: self._popup.protocol("WM_DELETE_WINDOW",
                                             self._popup.destroy),
            )
            self._busy = False

    @staticmethod
    def _launch_bat(bat_path: str) -> None:
        import subprocess as sp
        sp.Popen(bat_path, shell=True, creationflags=0x08000000)
        os._exit(0)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _set_progress(self, pct: float, msg: str) -> None:
        def _update() -> None:
            self._bar_bg.update_idletasks()
            w = self._bar_bg.winfo_width() or 416
            self._bar_fill.place(
                x=0, y=0, relheight=1, width=int(w * pct / 100)
            )
            self._pct_lbl.config(text=f"{pct:.0f}%")
            self._status_var.set(msg)
        self._popup.after(0, _update)

    def _draw_btn(self, fill: str) -> None:
        c = self._btn_c
        c.delete("all")
        W, H, r = 170, 38, 8
        # rounded rectangle using arcs + lines
        c.create_arc(1, 1, 1+r*2, 1+r*2, start=90,  extent=90,  fill=fill, outline=fill)
        c.create_arc(W-1-r*2, 1, W-1, 1+r*2, start=0,   extent=90,  fill=fill, outline=fill)
        c.create_arc(1, H-1-r*2, 1+r*2, H-1, start=180, extent=90,  fill=fill, outline=fill)
        c.create_arc(W-1-r*2, H-1-r*2, W-1, H-1, start=270, extent=90,  fill=fill, outline=fill)
        c.create_rectangle(1+r, 1,   W-1-r, H-1,   fill=fill, outline=fill)
        c.create_rectangle(1,   1+r, W-1,   H-1-r, fill=fill, outline=fill)
        # border outline arcs
        c.create_arc(1, 1, 1+r*2, 1+r*2, start=90,  extent=90,  style="arc", outline=self._ACCENT, width=1)
        c.create_arc(W-1-r*2, 1, W-1, 1+r*2, start=0,   extent=90,  style="arc", outline=self._ACCENT, width=1)
        c.create_arc(1, H-1-r*2, 1+r*2, H-1, start=180, extent=90,  style="arc", outline=self._ACCENT, width=1)
        c.create_arc(W-1-r*2, H-1-r*2, W-1, H-1, start=270, extent=90,  style="arc", outline=self._ACCENT, width=1)
        c.create_line(1+r, 1,   W-1-r, 1,   fill=self._ACCENT, width=1)
        c.create_line(1+r, H-1, W-1-r, H-1, fill=self._ACCENT, width=1)
        c.create_line(1,   1+r, 1,     H-1-r, fill=self._ACCENT, width=1)
        c.create_line(W-1, 1+r, W-1,   H-1-r, fill=self._ACCENT, width=1)
        c.create_text(W//2, H//2, text="Update Now",
                      fill=self._FG,
                      font=("Segoe UI Variable Display", 10, "bold"))

    @staticmethod
    def _apply_dark_titlebar(window: tk.Toplevel) -> None:
        try:
            import ctypes as _ct
            hwnd = _ct.windll.user32.GetParent(window.winfo_id())
            _ct.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, _ct.byref(_ct.c_int(1)), 4
            )
        except Exception:
            pass
