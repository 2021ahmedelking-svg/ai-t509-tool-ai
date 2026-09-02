# -*- coding: utf-8 -*-
"""
ui/app.py
~~~~~~~~~
Main application window — the single ``App`` class.

Responsibilities
----------------
* Window setup and DPI awareness
* Header bar (logo, device status pill, refresh button)
* Tab navigation (New Method / Old Method / Manual / About)
* Log panel with live output, progress bar, stop button
* Flash confirmation dialog + background flash worker
* Auto USB detection + watchdog
"""

from __future__ import annotations
import ctypes
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from core.config import (
    APP_NAME, APP_VERSION, APP_DATE,
    BASE_DIR, BIN_DIR,
    PRODUCT_IMG_PATH, SYSTEM_EXT_IMG_PATH,
    STEPS_NEW, LABELS_NEW,
    STEPS_CLASSIC, LABELS_CLASSIC,
    T, F, M,
)
from core.fastboot import (
    run_fb,
    fastboot_available,
    device_connected_fastboot,
    get_device_model,
    kill_current,
)
from core.adb import (
    adb_available,
    get_device_state,
    sideload,
    parse_sideload_percent,
    kill_current as kill_adb_current,
)
from core.updater import start_update_check, show_updater_if_needed
from ui.widgets   import RBtn, StepRow, RCard, StopButton, load_image

try:
    import customtkinter as ctk
    _CTK = True
except ImportError:
    _CTK = False

_FF = "Segoe UI Variable Display"
_FM = "Arial"  # Changed from JetBrains Mono to support Unicode/Arabic paths

_AppBase = ctk.CTk if _CTK else tk.Tk


def _fmt_size_gb(path: str) -> str:
    """
    ترجع حجم الملف بالجيجابايت بصيغة نظيفة (مثال: '2.14 GB').
    بتاخد أقل رقم عشري لازم عشان الحجم يفضل واضح ومفهوم:
    - لو >= 1 GB: رقمين عشريين (مثال: 2.14 GB)
    - لو أقل من 1 GB: 3 أرقام عشرية عشان الملفات الصغيرة متبقاش 0.00 GB
    """
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        return "— GB"
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{gb:.3f} GB"


def _fmt_size_smart(path: str) -> str:
    """
    ترجع حجم الملف بوحدة مناسبة تلقائيًا: MB للملفات الصغيرة (زي حزم
    sideload)، وGB للملفات الكبيرة، عشان الحجم يفضل واضح ومفهوم
    بدل ما يظهر '0.000 GB'.
    """
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        return "—"
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = size_bytes / (1024 ** 2)
    return f"{mb:.1f} MB"


# ══════════════════════════════════════════════════════════════════════════════
class App(_AppBase):
    """SM-T509 Flash Tool — main window."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  V{APP_VERSION}  —  {APP_DATE}")

        # State
        self._gsi                = tk.StringVar()
        self._q: queue.Queue     = queue.Queue()
        self._busy               = False
        self._stop               = False
        self._watchdog_alerted   = False
        self._watchdog_suppress  = False
        self._ui_locked          = False
        self._quick_cells: list  = []

        self.withdraw()          # Hide window until icon is ready
        self._setup_window()
        self._load_images()
        self._load_icon()        # Load icon path immediately
        self._build()
        self._poll()
        self._apply_icon_win32() # Apply icon before showing window
        self.deiconify()         # Now show the window

        self.after(50, self._start_post_init)



    def _start_post_init(self) -> None:
        threading.Thread(target=self._detect_device, daemon=True).start()
        self._start_watchdog()
        self._start_auto_detect()
        # Auto-updater — start immediately, show dialog once result is ready
        start_update_check()
        self.after(1500, lambda: show_updater_if_needed(self))

    # ── Window setup ─────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.configure(bg=T["bg"])
        self.minsize(1024, 680)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.resizable(True, True)

        def _maximize() -> None:
            try:
                self.state("zoomed")
            except tk.TclError:
                try:
                    self.attributes("-zoomed", True)
                except Exception:
                    pass
        self.after(50, _maximize)

        try:
            self.attributes("-toolwindow", False)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Ahmed.SMT509.FlashTool.1"
            )
        except Exception:
            pass

        self._set_titlebar_dark()
        for delay in (50, 200, 500, 1000, 2000):
            self.after(delay, self._apply_icon_win32)
        self.bind("<FocusIn>", lambda _e: self._apply_icon_win32())
        self.after(500, self._patch_popups)

    def _set_titlebar_dark(self) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4
            )
        except Exception:
            pass

    def _load_icon(self) -> None:
        mei = getattr(sys, "_MEIPASS", "") or ""
        candidates = [
            os.path.join(mei,      "icon.ico"),
            os.path.join(mei,      "logo.ico"),
            os.path.join(BASE_DIR, "icon.ico"),
            os.path.join(BASE_DIR, "logo.ico"),
            os.path.join(BIN_DIR,  "icon.ico"),
            os.path.join(BIN_DIR,  "logo.ico"),
        ]
        self._icon_path: Optional[str] = next(
            (p for p in candidates if os.path.isfile(p)), None
        )

    def _apply_icon_win32(self) -> None:
        p = getattr(self, "_icon_path", None)
        if not p or sys.platform != "win32":
            return
        try:
            WM_SETICON = 0x0080; ICON_SMALL = 0; ICON_BIG = 1
            IMAGE_ICON = 1;      LR_LOADFROMFILE = 0x10
            u32 = ctypes.windll.user32
            hSm = u32.LoadImageW(0, p, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            hBg = u32.LoadImageW(0, p, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            hHg = u32.LoadImageW(0, p, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
            hwnd = u32.GetParent(self.winfo_id()) or self.winfo_id()
            if hwnd and hBg:
                u32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hSm or hBg)
                u32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,   hHg or hBg)
                self._hicon_sm = hSm
                self._hicon_bg = hBg
                self._hicon_hg = hHg
                return
        except Exception:
            pass
        try:
            from PIL import Image, ImageTk
            img    = Image.open(p)
            photos = []
            for sz in (16, 32, 48, 64, 128):
                try:
                    im = img.copy()
                    im.thumbnail((sz, sz), Image.LANCZOS)
                    photos.append(ImageTk.PhotoImage(im))
                except Exception:
                    pass
            if photos:
                self.iconphoto(True, *photos)
                self._icon_refs = photos
        except Exception:
            pass

    def _apply_icon_to_popup(self, wid: int) -> None:
        p = getattr(self, "_icon_path", None)
        if not p or sys.platform != "win32":
            return
        try:
            WM_SETICON = 0x0080; ICON_SMALL = 0; ICON_BIG = 1
            IMAGE_ICON = 1;      LR_LOADFROMFILE = 0x10
            u32 = ctypes.windll.user32
            hSm = getattr(self, "_hicon_sm", None) or \
                  u32.LoadImageW(0, p, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            hBg = getattr(self, "_hicon_bg", None) or \
                  u32.LoadImageW(0, p, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if hBg:
                u32.SendMessageW(wid, WM_SETICON, ICON_SMALL, hSm or hBg)
                u32.SendMessageW(wid, WM_SETICON, ICON_BIG,   hBg)
        except Exception:
            pass

    def _patch_popups(self) -> None:
        if sys.platform != "win32" or not getattr(self, "_icon_path", None):
            return
        try:
            u32  = ctypes.windll.user32
            k32  = ctypes.windll.kernel32
            pid  = k32.GetCurrentProcessId()
            seen = getattr(self, "_popup_seen", set())

            def _cb(hwnd, _):
                if hwnd in seen:
                    return True
                wp = ctypes.c_ulong(0)
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
                if wp.value != pid:
                    return True
                cls = ctypes.create_unicode_buffer(64)
                u32.GetClassNameW(hwnd, cls, 64)
                if cls.value in ("#32770", "TkTopLevel", "TkChild"):
                    seen.add(hwnd)
                    self._apply_icon_to_popup(hwnd)
                return True

            PROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                      ctypes.c_void_p, ctypes.c_void_p)
            u32.EnumWindows(PROC(_cb), 0)
            self._popup_seen = seen
        except Exception:
            pass
        self.after(300, self._patch_popups)

    # ── Asset loading ─────────────────────────────────────────────────────────
    def _load_images(self) -> None:
        specs = {
            "new":      ("new.png",      24),
            "old":      ("old.png",      24),
            "manual":   ("manual.png",   24),
            "start":    ("start.png",    22),
            "stop":     ("stop.png",     22),
            "refresh":  ("refresh.png",  22),
            "browse":   ("browse.png",   22),
            "gsi":      ("gsi.png",      22),
            "telegram": ("telegram.png", 20),
        }
        self._img: dict = {
            key: load_image(fname, sz)
            for key, (fname, sz) in specs.items()
        }

    # ── Main layout ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self._build_header()
        tk.Frame(self, bg=T["border"], height=1).pack(fill="x")

        body = (ctk.CTkFrame(self, fg_color=T["bg"], corner_radius=0)
                if _CTK else tk.Frame(self, bg=T["bg"]))
        body.pack(fill="both", expand=True)

        # Right log panel
        self._log_sep = tk.Frame(body, bg=T["border"], width=1)
        self._log_sep.pack(side="right", fill="y")
        self._f_log = (ctk.CTkFrame(body, fg_color=T["bg2"], corner_radius=0)
                       if _CTK else tk.Frame(body, bg=T["bg2"]))
        self._f_log.pack(side="right", fill="both", expand=False)
        self._f_log.pack_propagate(False)
        self._build_log()

        # Left content
        self._f_left = (ctk.CTkFrame(body, fg_color=T["bg"], corner_radius=0)
                        if _CTK else tk.Frame(body, bg=T["bg"]))
        self._f_left.pack(side="left", fill="both", expand=True)
        self._build_tabs()

        self.bind("<Configure>", self._on_resize)
        self.after(100, self._on_resize)
        self.after(200, self._apply_stop_icon)

    def _apply_stop_icon(self) -> None:
        try:
            ico = self._img.get("stop")
            if ico:
                self._log_stop_btn.set_icon(ico)
            else:
                self._log_stop_btn.redraw()
        except Exception:
            pass

    # ── Header bar ────────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        hdr = tk.Frame(self, bg=T["bg2"])
        hdr.pack(fill="x", side="top")
        tk.Frame(hdr, bg=T["accent"], height=3).pack(fill="x")

        hi = tk.Frame(hdr, bg=T["bg2"])
        hi.pack(fill="x", padx=28, pady=14)

        # Left — logo + title
        lf = tk.Frame(hi, bg=T["bg2"])
        lf.pack(side="left")
        self._hdr_logo = load_image("logo.ico", 88) or load_image("icon.ico", 88)
        if self._hdr_logo:
            tk.Label(lf, image=self._hdr_logo, bg=T["bg2"]).pack(
                side="left", padx=(0, 14)
            )
        else:
            tk.Label(lf, text="⚡", font=(_FF, 28, "bold"),
                     fg=T["accent"], bg=T["bg2"]).pack(side="left", padx=(0, 14))

        tt = tk.Frame(lf, bg=T["bg2"])
        tt.pack(side="left")
        tk.Label(tt, text=f"{APP_NAME}",
                 font=F(20, True), fg=T["fg"], bg=T["bg2"]).pack(anchor="w")
        tk.Label(tt,
                 text="Galaxy Tab A7 (SM-T509)  ·  GSI Flasher  ·  By: Ahmed AbdelRazek",
                 font=F(9), fg=T["fg2"], bg=T["bg2"]).pack(anchor="w", pady=(2, 0))

        # Right — refresh + device pill
        rf = tk.Frame(hi, bg=T["bg2"])
        rf.pack(side="right")

        pill = (ctk.CTkFrame(rf, fg_color=T["bg4"], corner_radius=16,
                             border_width=1, border_color=T["border2"])
                if _CTK
                else tk.Frame(rf, bg=T["bg4"],
                              highlightthickness=1,
                              highlightbackground=T["border2"]))
        pill.pack(side="right", ipadx=4, ipady=2)
        self._dev_dot = tk.Label(pill, text="●", font=F(10),
                                 bg=T["bg4"], fg=T["fg3"], padx=8, pady=7)
        self._dev_dot.pack(side="left", padx=(8, 0))
        self._dev_lbl = tk.Label(pill, text="Checking…", font=F(10),
                                 bg=T["bg4"], fg=T["fg2"])
        self._dev_lbl.pack(side="left", padx=(2, 16), pady=7)

        self._hdr_ref_btn = RBtn(
            rf, "Refresh", self._refresh_device,
            bg=T["bg3"], fg=T["fg2"], hover_bg=T["bg5"],
            width=116, height=42, radius=16,
            font=F(10), icon=self._img.get("refresh"),
        )
        self._hdr_ref_btn.pack(side="right", padx=(0, 14))

    # ── Log panel ─────────────────────────────────────────────────────────────
    def _build_log(self) -> None:
        panel = self._f_log

        # Bottom — stop button + progress bar
        tk.Frame(panel, bg=T["border"], height=1).pack(side="bottom", fill="x")
        pw = tk.Frame(panel, bg=T["bg2"])
        pw.pack(side="bottom", fill="x")

        self._log_stop_btn = StopButton(pw, 80, 38, self._do_stop)
        self._log_stop_btn.pack(side="right", padx=(4, 8), pady=7)
        self._log_stop_btn.enable(False)

        self._cbar = tk.Canvas(pw, height=38, bg=T["bg2"],
                               highlightthickness=0, bd=0)
        self._cbar.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=7)
        self._cbar.bind("<Configure>", lambda _e: self._draw_cbar())
        self._cbar_pct        = 0.0
        self._cbar_label      = ""
        self._cbar_state      = "idle"
        self._cbar_target_pct = 0.0
        self._cbar_anim_id    = None
        self._cbar_frozen     = False
        self._cbar_shimmer_x  = 0          # Windows-style shimmer position

        # Top — log header
        hdr = tk.Frame(panel, bg=T["bg2"])
        hdr.pack(side="top", fill="x")
        tk.Label(hdr, text="LIVE LOG", font=F(9, True),
                 fg=T["accent"], bg=T["bg2"],
                 padx=8, pady=9).pack(side="left")

        self._log_hdr_btns: list = []
        for lbl, fn in [("Clear", "_clear_log"),
                        ("Copy",  "_copy_log"),
                        ("Save",  "_save_log")]:
            b = tk.Label(hdr, text=lbl, font=F(8), bg=T["bg2"],
                         fg=T["fg3"], padx=10, pady=9, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda _e, f=fn: getattr(self, f)())
            b.bind("<Enter>",    lambda _e, w=b: w.config(fg=T["accent"]))
            b.bind("<Leave>",    lambda _e, w=b: w.config(fg=T["fg3"]))
            self._log_hdr_btns.append(b)
        tk.Frame(panel, bg=T["border"], height=1).pack(side="top", fill="x")

        # USB / PORT info rows
        def _info_row(label: str, color: str):
            row = tk.Frame(panel, bg=T["bg2"])
            row.pack(side="top", fill="x")
            tk.Label(row, text=f"  {label}", font=F(8, True),
                     fg=T["fg2"], bg=T["bg2"],
                     width=6, anchor="w", padx=6).pack(side="left", pady=5)
            tk.Frame(row, bg=T["border"], width=1).pack(
                side="left", fill="y", pady=3
            )
            var = tk.StringVar(value="—")
            lbl_w = tk.Label(row, textvariable=var,
                             font=M(8), fg=T["fg3"],
                             bg=T["bg2"], anchor="w", padx=8)
            lbl_w.pack(side="left", fill="x", expand=True)
            return var, lbl_w

        self._usb_var,  self._usb_lbl  = _info_row("USB",   T["purple"])
        tk.Frame(panel, bg=T["border"], height=1).pack(side="top", fill="x")
        self._port_var, self._port_lbl = _info_row("COM", T["purple"])
        tk.Frame(panel, bg=T["border"], height=1).pack(side="top", fill="x")

        # Log text widget
        wrap = (ctk.CTkFrame(panel, fg_color=T["log_bg"], corner_radius=14)
                if _CTK else tk.Frame(panel, bg=T["log_bg"]))
        wrap.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        if _CTK:
            sb = ctk.CTkScrollbar(wrap, orientation="vertical",
                                  fg_color=T["bg2"],
                                  button_color=T["border2"],
                                  button_hover_color=T["accent"])
            sb.pack(side="right", fill="y")
        else:
            sb = ttk.Scrollbar(wrap, orient="vertical")
            sb.pack(side="right", fill="y")

        self._log_w = tk.Text(
            wrap, font=("Arial", 9), bg=T["log_bg"], fg=T["c_dim"],
            bd=0, highlightthickness=0, wrap="word",
            padx=10, pady=8, relief="flat", state="disabled",
            yscrollcommand=sb.set, spacing1=2, spacing3=2,
        )
        self._log_w.pack(fill="both", expand=True)
        if _CTK:
            sb.configure(command=self._log_w.yview)
        else:
            sb.config(command=self._log_w.yview)

        for tag, col in [
            ("ok",   T["c_ok"]),  ("err",  T["c_err"]),
            ("warn", T["c_warn"]),("dim",  T["c_dim"]),
            ("head", T["c_head"]),("info", T["c_info"]),
        ]:
            self._log_w.tag_config(tag, foreground=col)

        self._log_ctx = tk.Menu(
            self._log_w, tearoff=0,
            bg=T["bg3"], fg=T["fg"],
            activebackground=T["accent"], activeforeground=T["bg"],
            bd=0, relief="flat", font=F(9),
        )
        self._log_ctx.add_command(label="Copy selected", command=self._ctx_copy_sel)
        self._log_ctx.add_command(label="Copy all",      command=self._copy_log)
        self._log_ctx.add_separator()
        self._log_ctx.add_command(label="Clear log",     command=self._clear_log)
        self._log_w.bind("<Button-3>", self._show_log_ctx)

    # ── Progress bar (canvas) ─────────────────────────────────────────────────
    def _draw_cbar(self) -> None:
        try:
            c = self._cbar
            c.delete("all")
            W = c.winfo_width()
            H = c.winfo_height()
            if W < 10 or H < 10:
                return
            r   = H // 2
            pct = max(0.0, min(100.0, self._cbar_pct))

            # Track background
            self._rrect(c, 0, 0, W, H, r, fill=T["bg4"], outline="")

            if pct > 0:
                fw  = max(2 * r, int(W * pct / 100))
                col = {"done": T["grn"], "error": T["red"]}.get(
                    self._cbar_state, T["accent_d"]
                )
                fw = min(fw, W)
                self._rrect(c, 0, 0, fw, H, r, fill=col, outline="")

                # Windows-style shimmer stripe when running
                if self._cbar_state == "running" and fw > 20:
                    sx = getattr(self, "_cbar_shimmer_x", 0) % (fw + 80) - 40
                    sw = 36      # stripe width
                    # Clipping: only draw inside the filled region
                    x1s = max(0,  sx)
                    x2s = min(fw, sx + sw)
                    if x2s > x1s:
                        # Semi-transparent white stripe using stipple
                        c.create_rectangle(
                            x1s, 2, x2s, H - 2,
                            fill="#ffffff", stipple="gray25", outline=""
                        )

            # Label text
            if self._cbar_state == "done":
                txt, tc = "✓  Flash Complete!", "#ffffff"
            elif self._cbar_state == "error":
                txt = f"✗  {self._cbar_label}" if self._cbar_label else "✗  Error"
                tc  = "#ffffff"
            elif self._cbar_state == "idle":
                txt, tc = "Ready", T["fg3"]
            else:
                pct_s = f"{int(pct)}%"
                txt   = f"{self._cbar_label or 'Working…'}  {pct_s}"
                tc    = "#ffffff" if pct > 15 else T["fg2"]
            c.create_text(W // 2, H // 2, text=txt,
                          font=F(10, True), fill=tc, anchor="center")
        except Exception:
            pass

    def _start_cbar_anim(self) -> None:
        if self._cbar_anim_id:
            return
        def _tick() -> None:
            if self._cbar_state != "running":
                self._cbar_anim_id = None
                self._draw_cbar()
                return
            # Advance fill percentage smoothly
            if self._cbar_pct < self._cbar_target_pct:
                self._cbar_pct = min(self._cbar_pct + 0.8, self._cbar_target_pct)
            # Advance shimmer position — Windows file-copy speed
            self._cbar_shimmer_x = getattr(self, "_cbar_shimmer_x", 0) + 8
            self._draw_cbar()
            self._cbar_anim_id = self.after(40, _tick)   # ~25 fps
        self._cbar_anim_id = self.after(40, _tick)

    def _stop_cbar_anim(self) -> None:
        if self._cbar_anim_id:
            try:
                self.after_cancel(self._cbar_anim_id)
            except Exception:
                pass
            self._cbar_anim_id = None

    @staticmethod
    def _rrect(canvas, x1, y1, x2, y2, r, **kw) -> None:
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
               x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
               x1, y2, x1, y2-r, x1, y1+r, x1, y1, x1+r, y1]
        canvas.create_polygon(pts, smooth=True, **kw)

    def _set_progress(self, pct: float, label: str = "",
                      state: Optional[str] = None) -> None:
        if self._cbar_frozen and state not in ("idle", "running", "error", "done"):
            return
        self._cbar_target_pct = float(pct)
        if label:
            self._cbar_label = label
        if state:
            self._cbar_state = state
        elif pct >= 100:
            self._cbar_state = "done"
        elif pct > 0:
            self._cbar_state = "running"
        if self._cbar_state in ("done", "error"):
            self._cbar_frozen = True
            self._stop_cbar_anim()
            self._cbar_pct = float(pct)
        elif self._cbar_state == "running":
            self._cbar_frozen = False
            self._start_cbar_anim()
        else:
            self._cbar_frozen = False
            self._stop_cbar_anim()
        self._draw_cbar()

    def _reset_progress(self) -> None:
        self._cbar_frozen     = False
        self._cbar_pct        = 0.0
        self._cbar_target_pct = 0.0
        self._cbar_label      = ""
        self._cbar_state      = "idle"
        self._stop_cbar_anim()
        self._draw_cbar()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def _build_tabs(self) -> None:
        tab_wrap = tk.Frame(self._f_left, bg=T["bg2"])
        tab_wrap.pack(fill="x")
        tk.Frame(tab_wrap, bg=T["border"], height=1).pack(fill="x", side="bottom")

        tab_bar = tk.Frame(tab_wrap, bg=T["bg2"])
        tab_bar.pack(fill="x", expand=True)
        for i in range(4):
            tab_bar.columnconfigure(i, weight=1, uniform="tab")

        self._tab_val  = tk.StringVar(value="new")
        self._tab_btns: dict = {}
        tab_defs = [
            ("new",    "New Method",               self._img.get("new")),
            ("old",    "Old Method",               self._img.get("old")),
            ("manual", "Manual",                   self._img.get("manual")),
            ("about",  "About",                    None),
        ]
        for col_i, (val, lbl, ico) in enumerate(tab_defs):
            # Canvas-based tab with rounded top corners
            tc = tk.Canvas(tab_bar, height=58, bg=T["bg2"],
                           highlightthickness=0, bd=0, cursor="hand2")
            tc.grid(row=0, column=col_i, sticky="nsew")

            # Draw rounded tab shape
            def _draw_tab_bg(c=tc, v=val):
                c.delete("tab_bg")
                W = c.winfo_width() or 120
                H = c.winfo_height() or 46
                active = (self._tab_val.get() == v)
                bg = T["bg"] if active else T["bg2"]
                r = 12
                pts = [r,0, W-r,0, W,0, W,r, W,H, 0,H, 0,r, 0,0, r,0]
                c.create_polygon(pts, smooth=True, fill=bg, outline="", tags="tab_bg")

            tc.bind("<Configure>", lambda _e, d=_draw_tab_bg: d())
            tc.after(20, _draw_tab_bg)

            # Inner frame on canvas
            inner = tk.Frame(tc, bg=T["bg2"], cursor="hand2")
            tc.create_window(0, 0, window=inner, anchor="nw", tags="inner_win")

            def _place_inner(event=None, c=tc, f=inner):
                W = c.winfo_width() or 120
                H = c.winfo_height() or 46
                f.config(width=W, height=H)
                c.coords("inner_win", 0, 0)
                c.itemconfig("inner_win", width=W, height=H)

            tc.bind("<Configure>", lambda e, d=_draw_tab_bg, p=_place_inner: (d(), p(e)))

            # Content inside inner
            content = tk.Frame(inner, bg=T["bg2"])
            content.place(relx=0.5, rely=0.5, anchor="center")

            ico_lbl = None
            if ico:
                ico_lbl = tk.Label(content, image=ico, bg=T["bg2"], cursor="hand2")
                ico_lbl.pack(side="left", padx=(0, 5))

            base_sz = 10
            tl = tk.Label(content, text=lbl, font=F(base_sz),
                          bg=T["bg2"], fg=T["fg3"], cursor="hand2")
            tl.pack(side="left")
            # Store icon label ref for color updates
            if ico_lbl:
                ico_lbl._tab_val = val

            ind = tk.Canvas(tc, height=3, bg=T["bg2"],
                            highlightthickness=0, bd=0)
            ind.place(relx=0, rely=1.0, anchor="sw", relwidth=1.0, y=-1)

            tf = inner  # keep tf alias for _tab_switch compat
            self._tab_btns[val] = (tf, content, ind, tl)
            self._tab_canvases = getattr(self, "_tab_canvases", {})
            self._tab_canvases[val] = (tc, _draw_tab_bg)

            targets = [tc, inner, content, tl] + ([ico_lbl] if ico_lbl else [])
            for w in targets:
                w.bind("<Button-1>", lambda _e, v=val: self._tab_switch(v))
                w.bind("<Enter>",    lambda _e, v=val: self._tab_hover(v, True))
                w.bind("<Leave>",    lambda _e, v=val: self._tab_hover(v, False))

        self._tab_pages: dict = {
            val: tk.Frame(self._f_left, bg=T["bg"])
            for val, _, _ in tab_defs
        }

        # Build all pages now (fast enough, fixes lazy-load AttributeError)
        self._build_page_new()
        self._build_page_old()
        self._build_page_manual()
        self._build_page_about()
        self._tab_switch("new")

    def _tab_hover(self, val: str, enter: bool) -> None:
        if self._tab_val.get() == val:
            return
        tf, inner, ind, tl = self._tab_btns[val]
        col = T["bg3"] if enter else T["bg2"]
        for w in (tf, inner, tl):
            try: w.config(bg=col)
            except Exception: pass
        try: ind.config(bg=col)
        except Exception: pass
        cdict = getattr(self, "_tab_canvases", {})
        if val in cdict:
            tc, draw_fn = cdict[val]
            tc.config(bg=col)
            draw_fn()

    @staticmethod
    def _draw_tab_ind(c: tk.Canvas, active: bool) -> None:
        try:
            c.delete("all")
            if not active:
                try:
                    c.config(bg=c.master.cget("bg"))
                except Exception:
                    pass
                return
            W  = c.winfo_width() or 80
            # Full-width accent line like the screenshot
            H  = 3
            r  = 1
            c.create_rectangle(0, 0, W, H, fill=T["accent"], outline="")
            c.bind("<Configure>",
                   lambda _e, _c=c, _a=active: App._draw_tab_ind(_c, _a))
        except Exception:
            pass

    def _tab_switch(self, val: str) -> None:
        if getattr(self, "_ui_locked", False):
            return
        self._tab_val.set(val)
        for v, (tf, inner, ind, tl) in self._tab_btns.items():
            active = (v == val)
            bg_tab = T["bg"] if active else T["bg2"]
            for w in (tf, inner, tl):
                try: w.config(bg=bg_tab)
                except Exception: pass
            try: ind.config(bg=bg_tab)
            except Exception: pass
            base_sz = 10
            tl.config(
                fg   = T["fg"] if active else T["fg3"],
                font = F(base_sz, True) if active else F(base_sz),
            )
            # Also update canvas bg for active tab
            if v in (getattr(self, "_tab_canvases", {})):
                tc2, _ = self._tab_canvases[v]
                for _w in tc2.winfo_children():
                    try: _w.config(bg=bg_tab)
                    except Exception: pass
            self.after(10, lambda c=ind, a=active: App._draw_tab_ind(c, a))
            # Redraw rounded canvas tab
            cdict = getattr(self, "_tab_canvases", {})
            if v in cdict:
                tc, draw_fn = cdict[v]
                tc.config(bg=bg_tab)
                self.after(10, draw_fn)
        for v, p in self._tab_pages.items():
            if v == val:
                p.pack(fill="both", expand=True)
            else:
                p.pack_forget()

    # ── GSI flash page (shared by New/Old method) ─────────────────────────────
    def _build_gsi_page(self, page_key: str, steps: list,
                        labels: list, method: str) -> None:
        p = self._tab_pages[page_key]
        for row_i, weight in [(0, 0), (1, 1), (2, 0), (3, 0)]:
            p.rowconfigure(row_i, weight=weight)
        p.columnconfigure(0, weight=1)

        PAD = 20
        method_name = "New Method" if method == "new" else "Old Method"
        # Row 0: header
        th = tk.Frame(p, bg=T["bg"])
        th.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(14, 6))
        ttf = tk.Frame(th, bg=T["bg"])
        ttf.pack(side="left")
        tk.Label(ttf, text=f"Flash GSI  —  {method_name}",
                 font=F(16, True), fg=T["fg"], bg=T["bg"]).pack(anchor="w")

        # Row 1: FILES + STEPS columns
        cols = tk.Frame(p, bg=T["bg"])
        cols.grid(row=1, column=0, sticky="nsew", padx=PAD)
        cols.rowconfigure(0, weight=1)
        cols.columnconfigure(0, weight=2)
        cols.columnconfigure(1, weight=3)

        # Files card
        fc = (ctk.CTkFrame(cols, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(cols, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        fc.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        fh = tk.Frame(fc, bg=T["bg2"])
        fh.pack(fill="x")
        tk.Label(fh, text="FILES", font=F(9, True), fg=T["accent"],
                 bg=T["bg2"], padx=10, pady=9).pack(side="left")
        tk.Frame(fc, bg=T["border"], height=1).pack(fill="x")

        gpill = (ctk.CTkFrame(fc, fg_color=T["bg4"], corner_radius=16,
                          border_width=1, border_color=T["border"])
         if _CTK else tk.Frame(fc, bg=T["bg4"],
                               highlightthickness=1, highlightbackground=T["border"]))
        gpill.pack(fill="x", padx=12, pady=(14, 4))
        gri = (ctk.CTkFrame(gpill, fg_color=T["bg4"], corner_radius=0)
               if _CTK else tk.Frame(gpill, bg=T["bg4"]))
        gri.pack(fill="x", padx=10, pady=8)
        _gri_bg = T["bg4"]
        if self._img.get("gsi"):
            tk.Label(gri, image=self._img["gsi"], bg=_gri_bg).pack(
                side="left", padx=(0, 8)
            )
        tk.Label(gri, text="GSI File", font=F(10, True),
                 bg=_gri_bg, fg=T["fg"]).pack(side="left")

        if page_key == "new":
            self._gsi_lbl = tk.Label(fc, text="No file selected", font=("Arial", 10), bg=T["bg3"], fg=T["fg3"],
                                     wraplength=220, justify="left")
            self._gsi_lbl.pack(anchor="w", padx=14, pady=(4, 6))
        else:
            self._gsi_lbl2 = tk.Label(fc, text="No file selected", font=("Arial", 10), bg=T["bg3"], fg=T["fg3"],
                                      wraplength=220, justify="left")
            self._gsi_lbl2.pack(anchor="w", padx=14, pady=(4, 6))

        br_row = tk.Frame(fc, bg=T["bg3"])
        br_row.pack(fill="x", padx=12, pady=(2, 14))
        browse_btn = RBtn(
            br_row,
            "Browse GSI",
            self._browse if page_key == "new" else self._browse2,
            bg=T["bg4"], fg=T["fg"], hover_bg=T["bg5"],
            width=164, height=38, radius=14,
            font=F(10, True), icon=self._img.get("browse"),
        )
        browse_btn.pack(anchor="w")
        if page_key == "new":
            self._browse_btn  = browse_btn
        else:
            self._browse_btn2 = browse_btn

        # Steps card
        sc = (ctk.CTkFrame(cols, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(cols, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        sc.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        sh = tk.Frame(sc, bg=T["bg2"])
        sh.pack(fill="x")
        tk.Label(sh, text="FLASH STEPS", font=F(9, True), fg=T["purple"],
                 bg=T["bg2"], padx=10, pady=9).pack(side="left")
        tk.Frame(sc, bg=T["border"], height=1).pack(fill="x")

        s_canvas = tk.Canvas(sc, bg=T["bg3"], highlightthickness=0, bd=0)
        s_canvas.pack(fill="both", expand=True)
        s_vsb   = ttk.Scrollbar(sc, orient="vertical", command=s_canvas.yview)
        s_body  = tk.Frame(s_canvas, bg=T["bg3"])
        sb_win  = s_canvas.create_window((0, 0), window=s_body, anchor="nw")

        def _s_inner(e):
            s_canvas.configure(scrollregion=s_canvas.bbox("all"))
            bb = s_canvas.bbox("all")
            if bb and bb[3] > s_canvas.winfo_height():
                s_vsb.pack(side="right", fill="y")
            else:
                s_vsb.pack_forget()

        def _s_outer(e):
            s_canvas.itemconfig(sb_win, width=e.width)

        s_body.bind("<Configure>",  _s_inner)
        s_canvas.bind("<Configure>", _s_outer)
        s_canvas.bind("<MouseWheel>",
                      lambda e: s_canvas.yview_scroll(-1*(e.delta//120), "units"))

        n      = len(steps)
        s_pady = 3 if n >= 7 else 5
        s_font = F(8) if n >= 7 else F(10)
        for num, name, _ in steps:
            sr = tk.Frame(s_body, bg=T["bg3"])
            sr.pack(fill="x", padx=10, pady=s_pady)
            bc = tk.Canvas(sr, width=20, height=20, bg=T["bg3"],
                           highlightthickness=0, bd=0)
            bc.pack(side="left", padx=(0, 8))
            bc.create_oval(1, 1, 19, 19, fill=T["bg4"],
                           outline=T["border2"], width=1)
            bc.create_text(10, 10, text=str(num), font=M(7), fill=T["fg2"])
            tk.Label(sr, text=name, font=s_font,
                     bg=T["bg3"], fg=T["fg2"]).pack(side="left", pady=2)
        tk.Frame(s_body, bg=T["bg3"], height=6).pack()

        # Row 2: progress
        pc = (ctk.CTkFrame(p, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(p, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        pc.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(8, 0))

        phr = tk.Frame(pc, bg=T["bg2"])
        phr.pack(fill="x")
        tk.Label(phr, text="PROGRESS", font=F(9, True), fg=T["org"],
                 bg=T["bg2"], padx=10, pady=8).pack(side="left")
        tk.Frame(pc, bg=T["border"], height=1).pack(fill="x")

        if page_key == "new":
            self._steprow = StepRow(pc, steps, labels)
            self._steprow.pack(fill="x", pady=(8, 8), padx=10)
        else:
            self._steprow2 = StepRow(pc, steps, labels)
            self._steprow2.pack(fill="x", pady=(8, 8), padx=10)

        # Row 3: action buttons
        act = tk.Frame(p, bg=T["bg"])
        act.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(10, 16))
        if page_key == "new":
            self._flash_btn = RBtn(
                act, "Start Flash",
                lambda: self._confirm_flash("new"),
                bg=T["accent_d"], fg="#ffffff", hover_bg=T["accent_dh"],
                width=176, height=44, radius=16,
                font=F(11, True), icon=self._img.get("start"),
            )
            self._flash_btn.pack(side="left")
        else:
            self._flash_btn2 = RBtn(
                act, "Start Flash",
                lambda: self._confirm_flash("classic"),
                bg=T["accent_d"], fg="#ffffff", hover_bg=T["accent_dh"],
                width=176, height=44, radius=16,
                font=F(11, True), icon=self._img.get("start"),
            )
            self._flash_btn2.pack(side="left")

    def _build_page_new(self)  -> None: self._build_gsi_page("new",    STEPS_NEW,     LABELS_NEW,     "new")
    def _build_page_old(self)  -> None: self._build_gsi_page("old",    STEPS_CLASSIC, LABELS_CLASSIC, "classic")

    # ── Manual tab ────────────────────────────────────────────────────────────
    def _build_page_manual(self) -> None:
        p = self._tab_pages["manual"]
        for r, w in [(0,0),(1,0),(2,0),(3,0),(4,1)]: p.rowconfigure(r, weight=w)
        p.columnconfigure(0, weight=1)
        PAD = 20

        th = tk.Frame(p, bg=T["bg"])
        th.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(14, 8))
        ttf = tk.Frame(th, bg=T["bg"])
        ttf.pack(side="left")
        tk.Label(ttf, text="Manual Commands",
                 font=F(16, True), fg=T["fg"], bg=T["bg"]).pack(anchor="w")
        tk.Label(ttf, text="Run fastboot commands directly",
                 font=F(9), fg=T["fg3"], bg=T["bg"]).pack(anchor="w", pady=(3,0))

        qc = (ctk.CTkFrame(p, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(p, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        qc.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0,8))

        qh = tk.Frame(qc, bg=T["bg2"])
        qh.grid(row=0, column=0, sticky="ew")
        qc.columnconfigure(0, weight=1)
        tk.Label(qh, text="QUICK COMMANDS", font=F(9, True), fg=T["accent"],
                 bg=T["bg2"], padx=10, pady=8).pack(side="left")
        tk.Frame(qc, bg=T["border"], height=1).grid(row=0, column=0, sticky="sew")

        CMDS = [
            ("Reboot System",     "reboot"),
            ("Reboot Recovery",   "reboot recovery"),
            ("Reboot Bootloader", "reboot bootloader"),
            ("Reboot Fastboot",   "reboot fastboot"),
            ("List Devices",      "devices"),
            ("Flash product.img", "flash product product.img"),
            ("Erase system",      "erase system"),
            ("Erase userdata",    "erase userdata"),
            ("Erase cache",       "erase cache"),
        ]
        gf = tk.Frame(qc, bg=T["bg3"])
        gf.grid(row=1, column=0, sticky="ew", padx=8, pady=6)
        for ri in range(3): gf.rowconfigure(ri, weight=0, minsize=50)
        for ci in range(3): gf.columnconfigure(ci, weight=1)

        def _cell(parent, lbl, cmd, row_i, col_i):
            c = tk.Canvas(parent, highlightthickness=0, bd=0,
                          bg=T["bg3"], cursor="hand2", height=50)
            c.grid(row=row_i, column=col_i, sticky="ew", padx=3, pady=3)
            self._quick_cells.append((c, c))

            def _draw(hover=False):
                c.delete("all")
                W = c.winfo_width(); H = c.winfo_height()
                if W < 4 or H < 4: return
                r2  = 8
                bg2 = T["bg5"] if hover else T["bg4"]
                bdr = T["accent"] if hover else T["border"]
                fg2 = T["accent"] if hover else T["fg2"]
                pts = [r2,1, W-r2,1, W-1,1, W-1,r2, W-1,H-r2,
                       W-1,H-1, W-r2,H-1, r2,H-1, 1,H-1,
                       1,H-r2, 1,r2, 1,1, r2,1]
                c.create_polygon(pts, smooth=True, fill=bg2, outline=bdr, width=1)
                c.create_text(W//2, H//2, text=lbl, font=F(7),
                              fill=fg2, anchor="center")

            c.bind("<Configure>", lambda _e, d=_draw: d())
            c.bind("<Enter>",  lambda _e, d=_draw: d(True)
                   if not getattr(self, "_ui_locked", False) else None)
            c.bind("<Leave>",  lambda _e, d=_draw: d(False))
            c.bind("<Button-1>", lambda _e, cs=cmd: self._quick(cs))
            c.after(30, _draw)

        for i, (lbl, cmd) in enumerate(CMDS):
            r, ci = divmod(i, 3)
            _cell(gf, lbl, cmd, r, ci)

        cc = (ctk.CTkFrame(p, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(p, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        cc.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0,8))

        ch = tk.Frame(cc, bg=T["bg2"])
        ch.pack(fill="x")
        tk.Label(ch, text="CUSTOM COMMAND", font=F(9, True), fg=T["purple"],
                 bg=T["bg2"], padx=10, pady=8).pack(side="left")
        tk.Frame(cc, bg=T["border"], height=1).pack(fill="x")

        cmd_row = tk.Frame(cc, bg=T["bg3"])
        cmd_row.pack(fill="x", padx=14, pady=12)
        tk.Label(cmd_row, text="fastboot", font=M(10),
                 bg=T["bg3"], fg=T["fg2"], padx=4).pack(side="left")
        if _CTK:
            self._cmd_e = ctk.CTkEntry(
                cmd_row,
                font=ctk.CTkFont(family=_FM, size=13),
                fg_color=T["bg4"], text_color=T["fg"],
                border_color=T["border"], border_width=1,
                corner_radius=14, placeholder_text="command args…",
            )
            self._cmd_e.pack(side="left", fill="x", expand=True, padx=10, ipady=5)
        else:
            self._cmd_e = tk.Entry(
                cmd_row, font=M(11), bg=T["bg4"], fg=T["fg"],
                insertbackground=T["accent"], relief="flat", bd=0,
                highlightthickness=1, highlightbackground=T["border"],
            )
            self._cmd_e.pack(side="left", fill="x", expand=True, padx=10, ipady=9)
            self._cmd_e.bind("<FocusIn>",
                lambda _e: self._cmd_e.config(highlightbackground=T["accent"]))
            self._cmd_e.bind("<FocusOut>",
                lambda _e: self._cmd_e.config(highlightbackground=T["border"]))
        self._cmd_e.bind("<Return>", lambda _e: self._run_manual())
        RBtn(cmd_row, "Run", self._run_manual,
             bg=T["accent"], fg=T["bg"], hover_bg=T["accent_h"],
             width=80, height=38, radius=14,
             font=F(10, True)).pack(side="left")
        self._man_out = tk.Text(self)   # hidden dummy

        # ── ADB Sideload card ────────────────────────────────────────────────
        sc = (ctk.CTkFrame(p, fg_color=T["bg3"], corner_radius=14,
                           border_width=1, border_color=T["border"])
              if _CTK
              else tk.Frame(p, bg=T["bg3"], highlightthickness=1,
                            highlightbackground=T["border"]))
        sc.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(0,16))
        tk.Frame(p, bg=T["bg"]).grid(row=4, column=0, sticky="nsew")

        sh = tk.Frame(sc, bg=T["bg2"])
        sh.pack(fill="x")
        tk.Label(sh, text="ADB SIDELOAD", font=F(9, True), fg=T["grn"],
                 bg=T["bg2"], padx=10, pady=8).pack(side="left")
        tk.Frame(sc, bg=T["border"], height=1).pack(fill="x")

        sc_body = tk.Frame(sc, bg=T["bg3"])
        sc_body.pack(fill="x", padx=14, pady=12)

        # File select
        file_row = tk.Frame(sc_body, bg=T["bg3"])
        file_row.pack(fill="x", pady=(0, 12))
        self._sideload_browse_btn = RBtn(
            file_row, "Browse ZIP", self._browse_sideload,
            bg=T["bg4"], fg=T["fg2"], hover_bg=T["bg5"],
            width=140, height=42, radius=16, font=F(10),
            icon=self._img.get("browse"),
        )
        self._sideload_browse_btn.pack(side="left")
        self._sideload_lbl = tk.Label(
            file_row, text="No package selected", font=F(9),
            fg=T["fg3"], bg=T["bg3"], padx=10, anchor="w",
        )
        self._sideload_lbl.pack(side="left", fill="x", expand=True)

        # Start button
        act_row = tk.Frame(sc_body, bg=T["bg3"])
        act_row.pack(fill="x")
        self._sideload_btn = RBtn(
            act_row, "Start Sideload", self._start_sideload,
            bg=T["accent_d"], fg="#ffffff", hover_bg=T["accent_dh"],
            width=200, height=46, radius=16, font=F(11, True),
            icon=self._img.get("start"),
        )
        self._sideload_btn.pack(side="left")

    # ── About tab ─────────────────────────────────────────────────────────────
    def _build_page_about(self) -> None:
        p = self._tab_pages["about"]
        p.rowconfigure(0, weight=1)
        p.columnconfigure(0, weight=1)

        root = tk.Frame(p, bg=T["bg"])
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)

        PAD = 22

        def _card(parent, row, col, padl=0, padr=0, padt=0, padb=0):
            rc = RCard(parent, radius=16, bg=T["bg3"], border=T["border"])
            rc._frame.grid(row=row, column=col, sticky="nsew",
                   padx=((PAD+padl, PAD//2+padr) if col == 0
                         else (PAD//2+padl, PAD+padr)),
                   pady=(padt, padb))
            # Return the inner frame so existing pack() calls work
            return rc.inner

        def _card_hdr(card, color, title):
            h = tk.Frame(card, bg=T["bg3"])
            h.pack(fill="x")
            tk.Label(h, text=f"  {title}", font=F(9, True), fg=color,
                     bg=T["bg3"], padx=10, pady=9).pack(side="left")
            tk.Frame(card, bg=T["border"], height=1).pack(fill="x")

        def _scrollable(parent):
            outer = tk.Frame(parent, bg=T["bg3"])
            outer.pack(fill="both", expand=True)
            outer.rowconfigure(0, weight=1)
            outer.columnconfigure(0, weight=1)
            canvas = tk.Canvas(outer, bg=T["bg3"], highlightthickness=0, bd=0)
            canvas.grid(row=0, column=0, sticky="nsew")
            vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=lambda f, l: (
                vsb.grid(row=0, column=1, sticky="ns") if float(l) < 1.0
                else vsb.grid_remove()) or canvas.configure(yscrollcommand=vsb.set))
            inner = tk.Frame(canvas, bg=T["bg3"])
            wid   = canvas.create_window((0, 0), window=inner, anchor="nw")
            inner.bind("<Configure>",
                       lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>",
                        lambda e: canvas.itemconfig(wid, width=e.width))
            canvas.bind("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
            return inner

        def _link_btn(parent, icon, label, url, accent):
            H = 42
            c = tk.Canvas(parent, height=H, bg=T["bg3"],
                          highlightthickness=0, bd=0)
            c.pack(fill="x", padx=12, pady=3)
            def _draw(hover=False):
                c.delete("all")
                W = c.winfo_width() or 400
                r = 9
                bg  = T["bg5"] if hover else T["bg4"]
                bdr = accent   if hover else T["border"]
                pts = [r,1, W-r,1, W-1,1, W-1,r, W-1,H-r,
                       W-1,H-1, W-r,H-1, r,H-1, 1,H-1,
                       1,H-r, 1,r, 1,1, r,1]
                c.create_polygon(pts, smooth=True, fill=bg, outline=bdr, width=1)
                c.create_rectangle(7, 10, 10, H-10,
                                   fill=accent, outline="", width=0)
                x = 22
                if icon:
                    c.create_image(x+11, H//2, image=icon, anchor="center")
                    x += 30
                c.create_text(x+2, H//2, text=label, font=F(9),
                              fill=T["fg"] if hover else T["fg2"], anchor="w")
                c.create_text(W-16, H//2, text="›",
                              font=(_FF, 15, "bold"),
                              fill=accent if hover else T["fg3"],
                              anchor="center")
            c.bind("<Configure>", lambda _e: _draw())
            c.bind("<Enter>",     lambda _e: _draw(True))
            c.bind("<Leave>",     lambda _e: _draw(False))
            c.bind("<Button-1>",  lambda _e: webbrowser.open(url))
            c.config(cursor="hand2")
            c.after(30, _draw)

        # Hero card
        _hero_rc = RCard(root, radius=16, bg=T["bg3"], border=T["border"])
        _hero_rc._frame.grid(row=0, column=0, columnspan=2,
                  sticky="ew", padx=PAD, pady=(PAD, PAD//2))
        hero = _hero_rc.inner
        hi = tk.Frame(hero, bg=T["bg3"])
        hi.pack(fill="x", padx=24, pady=18)

        lf = tk.Frame(hi, bg=T["bg3"], width=80)
        lf.pack(side="left", fill="y")
        lf.pack_propagate(False)
        logo = load_image("logo.ico", 60) or load_image("icon.ico", 60)
        if logo:
            ll = tk.Label(lf, image=logo, bg=T["bg3"])
            ll.image = logo
            ll.place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(lf, text="⚡", font=(_FF, 36, "bold"),
                     fg=T["accent"], bg=T["bg3"]).place(
                relx=0.5, rely=0.5, anchor="center"
            )
        tk.Frame(hi, bg=T["border"], width=1).pack(
            side="left", fill="y", padx=(0, 18), pady=4
        )
        inf = tk.Frame(hi, bg=T["bg3"])
        inf.pack(side="left", fill="both", expand=True)
        tk.Label(inf, text=APP_NAME,
                 font=F(18, True), fg=T["fg"], bg=T["bg3"]).pack(anchor="w")
        vr = tk.Frame(inf, bg=T["bg3"])
        vr.pack(anchor="w", pady=(6, 10))
        tk.Label(vr, text=f" V{APP_VERSION} ",
                 font=F(10, True), fg=T["bg3"], bg=T["accent"],
                 padx=6, pady=2).pack(side="left")
        tk.Label(vr, text="Samsung Galaxy Tab A7 (SM-T509)",
                 font=F(10), fg=T["fg2"], bg=T["bg3"],
                 padx=8).pack(side="left")
        tk.Frame(inf, bg=T["border"], height=1).pack(fill="x", pady=(0, 8))
        for ico_t, lbl_t, val_t in [
            ("◈", "By",      "Ahmed AbdelRazek"),
            ("▣", "Device",  "SM-T509"),
            ("◉", "Version", f"V{APP_VERSION}  ({APP_DATE})"),
        ]:
            sr = tk.Frame(inf, bg=T["bg3"])
            sr.pack(anchor="w", pady=2)
            tk.Label(sr, text=ico_t, font=F(11), bg=T["bg3"], fg="#e0e0e0").pack(
                side="left", padx=(0, 8)
            )
            tk.Label(sr, text=lbl_t, font=F(10), fg=T["fg3"],
                     bg=T["bg3"], width=8, anchor="w").pack(side="left")
            tk.Label(sr, text=val_t, font=F(10, True),
                     fg=T["fg"], bg=T["bg3"]).pack(side="left")

        # Links card
        lc = _card(root, 1, 0, padr=5, padt=PAD//2, padb=PAD)
        _card_hdr(lc, T["accent"], "LINKS & COMMUNITY")
        lb = _scrollable(lc)
        tk.Frame(lb, bg=T["bg3"], height=4).pack()
        tg = self._img.get("telegram")
        for lbl, url in [
            ("Ahmed AbdelRazek", "https://t.me/ahmed_884"),
            ("SM-T509 Channel",                    "https://t.me/gta4lvex"),
            ("SM-T509 Group",                      "https://t.me/gta4lve"),
            ("Group Owner  (DevCatowa)",            "https://t.me/DevCatowa"),
        ]:
            _link_btn(lb, tg, lbl, url, T["accent"])

        tk.Frame(lb, bg=T["bg3"], height=10).pack()

        # Useful links card
        uc = _card(root, 1, 1, padl=5, padt=PAD//2, padb=PAD)
        _card_hdr(uc, T["accent"], "USEFUL LINKS")
        ub = _scrollable(uc)
        tk.Frame(ub, bg=T["bg3"], height=4).pack()

        # Simple clean action buttons
        def _simple_btn(parent, label, cmd):
            # Rounded button using Canvas
            BG_N  = T["bg4"]
            BG_H  = T["bg5"]
            WRAP  = tk.Frame(parent, bg=T["bg3"])
            WRAP.pack(fill="x", padx=12, pady=3)
            c = tk.Canvas(WRAP, height=44, highlightthickness=0, bd=0,
                          bg=T["bg3"], cursor="hand2")
            c.pack(fill="x")

            lw_var = [None]
            ar_var = [None]
            hover  = [False]

            def _redraw(h=False):
                c.delete("all")
                W = c.winfo_width() or 200
                H = c.winfo_height() or 44
                bg = BG_H if h else BG_N
                r  = 10
                pts = [r,0, W-r,0, W,0, W,r, W,H-r, W,H,
                       W-r,H, r,H, 0,H, 0,H-r, 0,r, 0,0, r,0]
                c.create_polygon(pts, smooth=True, fill=bg, outline="")
                fg_txt  = T["accent"] if h else T["fg2"]
                fg_arr  = T["accent"] if h else T["fg3"]
                c.create_text(14+8, H//2, text=label, font=F(10),
                              fill=fg_txt, anchor="w")
                c.create_text(W-14, H//2, text="›", font=F(12, True),
                              fill=fg_arr, anchor="e")

            c.bind("<Configure>", lambda _e: _redraw(hover[0]))
            c.bind("<Enter>",     lambda _e: (_redraw(True),  hover.__setitem__(0, True)))
            c.bind("<Leave>",     lambda _e: (_redraw(False), hover.__setitem__(0, False)))
            c.bind("<Button-1>",  lambda _e: cmd())
            c.after(20, lambda: _redraw(False))

        _simple_btn(ub, "📦  Required Files",  self._show_required_files_dialog)
        _simple_btn(ub, "📋  Flash Guide",      self._show_guide_dialog)
        tk.Frame(ub, bg=T["bg3"], height=6).pack()
        for lbl, url in [
            ("GSI Files",   "https://t.me/GsiGraveyard"),
            ("Channel",     "https://t.me/gta4lvex"),
            ("Group",       "https://t.me/gta4lve"),
        ]:
            _link_btn(ub, tg, lbl, url, T["accent"])
        tk.Frame(ub, bg=T["bg3"], height=10).pack()

    # ── Flash Guide dialog ────────────────────────────────────────────────────
    def _show_guide_dialog(self) -> None:
        """Show the full flash guide in a styled modal dialog."""
        BG     = T["bg"]
        BG2    = T["bg2"]
        BG3    = T["bg3"]
        BG4    = T["bg4"]
        ACC    = T["accent"]
        ORG    = T["org"]
        PUR    = T["purple"]
        FG     = T["fg"]
        FG2    = T["fg2"]
        FG3    = T["fg3"]
        GRN    = T["grn"]
        BRD    = T["border"]

        d = tk.Toplevel(self)
        d.title("Flash Guide  —  SM-T509")
        d.configure(bg=BG)
        d.resizable(False, False)
        d.grab_set()
        d.protocol("WM_DELETE_WINDOW", d.destroy)
        d.update_idletasks()
        W, H = 580, 620
        sx, sy = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{W}x{H}+{(sx-W)//2}+{(sy-H)//2}")
        try:
            import ctypes as _ct
            hwnd = _ct.windll.user32.GetParent(d.winfo_id())
            _ct.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, _ct.byref(_ct.c_int(1)), 4)
        except Exception:
            pass

        # Accent bar
        tk.Frame(d, bg=ACC, height=4).pack(fill="x")

        # Header
        hf = tk.Frame(d, bg=BG2)
        hf.pack(fill="x")
        tk.Label(hf, text="📋  Full Flash Guide", font=F(13, True),
                 fg=ACC, bg=BG2, pady=12, padx=8).pack(side="left")
        tk.Frame(d, bg=BRD, height=1).pack(fill="x")

        # Scrollable body
        outer = tk.Frame(d, bg=BG)
        outer.pack(fill="both", expand=True, padx=0, pady=0)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        wid   = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        def _scroll(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")

        canvas.bind("<MouseWheel>", _scroll)
        inner.bind("<MouseWheel>", _scroll)

        
        d.bind("<Up>",    lambda e: canvas.yview_scroll(-1, "units"))
        d.bind("<Down>",  lambda e: canvas.yview_scroll(1, "units"))
        d.bind("<Prior>", lambda e: canvas.yview_scroll(-5, "units"))
        d.bind("<Next>",  lambda e: canvas.yview_scroll(5, "units"))

        
        def _bind_mousewheel(widget):
            try:
                widget.bind("<MouseWheel>", _scroll)
            except Exception:
                pass
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        inner.bind("<Map>", lambda _e: d.after(150, lambda: _bind_mousewheel(inner)))

        PAD = 20

        def _section(title, color, items, notes=None):
            """Render one guide section card."""
            card = (ctk.CTkFrame(inner, fg_color=BG3, corner_radius=14,
                     border_width=1, border_color=BRD)
        if _CTK else tk.Frame(inner, bg=BG3,
                              highlightthickness=1, highlightbackground=BRD))
            card.pack(fill="x", padx=PAD, pady=(8, 0))
            # Card header
            ch = tk.Frame(card, bg=BG2)
            ch.pack(fill="x")
            tk.Label(ch, text=f"  {title}", font=F(10, True),
                     fg=color, bg=BG2, pady=8, padx=6).pack(side="left")
            tk.Frame(card, bg=BRD, height=1).pack(fill="x")
            # Steps
            for i, item in enumerate(items, 1):
                row = tk.Frame(card, bg=BG3)
                row.pack(fill="x", padx=14, pady=(6 if i == 1 else 2, 2 if i < len(items) else 8))
                # Step number badge
                bc = tk.Canvas(row, width=22, height=22, bg=BG3, highlightthickness=0)
                bc.pack(side="left", padx=(0, 10))
                bc.create_oval(1, 1, 21, 21, fill=BG4, outline=color, width=1)
                bc.create_text(11, 11, text=str(i), font=M(7), fill=color)
                tk.Label(row, text=item, font=F(9), bg=BG3, fg=FG2,
                         justify="left", wraplength=460, anchor="w").pack(
                    side="left", fill="x", expand=True)
            if notes:
                tk.Frame(card, bg=BRD, height=1).pack(fill="x", padx=14)
                tk.Label(card, text=notes, font=F(8), bg=BG3,
                         fg=FG3, justify="left", wraplength=500,
                         padx=14, pady=6).pack(anchor="w")

        def _divider(text="", color=FG3):
            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", padx=PAD, pady=(12, 4))
            tk.Frame(row, bg=color, height=1).pack(side="left", fill="x",
                                                    expand=True)
            if text:
                tk.Label(row, text=f"  {text}  ", font=F(8), fg=color, bg=BG).pack(side="left")
                tk.Frame(row, bg=color, height=1).pack(side="left", fill="x", expand=True)

        tk.Frame(inner, bg=BG, height=6).pack()

        _section("Flash recovery.tar & disabled_vbmeta.tar", ACC, [
            "Flash recovery.tar  →  AP",
            "Flash disabled_vbmeta.tar  →  CSC",
            "Then reboot to Recovery",
        ])

        _divider(color=BRD)

        _section("Reboot to Fastboot & flash with this tool", ACC, [
            "Reboot  →  fastboot",
            "Use this tool to flash your GSI",
        ])

        _divider(color=BRD)

        _section("From Recovery — Final steps", ACC, [
            "Flash Fix_Encryption.zip",
            "Wipe  →  Format Data  →  type  yes",
            "Reboot system",
        ])

        # Links section
        tk.Frame(inner, bg=BG, height=8).pack()
        lcard = (ctk.CTkFrame(inner, fg_color=BG3, corner_radius=14,
                      border_width=1, border_color=BRD)
         if _CTK else tk.Frame(inner, bg=BG3,
                               highlightthickness=1, highlightbackground=BRD))
        lcard.pack(fill="x", padx=PAD, pady=(0, 16))
        lh = tk.Frame(lcard, bg=BG2)
        lh.pack(fill="x")
        tk.Label(lh, text="🔗  Required Download Links", font=F(10, True),
                 fg=ACC, bg=BG2, pady=8, padx=6).pack(side="left")
        tk.Frame(lcard, bg=BRD, height=1).pack(fill="x")

        LINKS = [
            ("TWRP Download",        "https://t.me/gta4lvex/23"),
            ("OFOX Download",        "https://t.me/gta4lvex/25"),
            ("disabled_vbmeta.tar",  "https://www.mediafire.com/file/jhto77dd4xoj7ll/disabled_vbmeta.tar/file"),
            ("Fix_Encryption.zip",   "https://t.me/gta4lvex/22"),
        ]
        for lbl, url in LINKS:
            rc_lr = RCard(lcard, radius=10, bg=BG4, border=BRD, fit_content=True)
            rc_lr.pack(fill="x", padx=14, pady=2)
            lr = rc_lr.inner
            lr.config(cursor="hand2")
            name_lbl = tk.Label(lr, text=lbl, font=F(9, True),
                                bg=BG4, fg=FG2, cursor="hand2", padx=10, pady=8)
            name_lbl.pack(side="left")
            arr = tk.Label(lr, text="›", font=F(11, True), bg=BG4, fg=FG3, padx=10)
            arr.pack(side="right")
            def _on_e(e, c=lr, n=name_lbl, a=arr):
                for w in (c, n, a): w.config(bg=T["bg5"])
                n.config(fg=ACC); a.config(fg=ACC)
            def _on_l(e, c=lr, n=name_lbl, a=arr):
                for w in (c, n, a): w.config(bg=BG4)
                n.config(fg=FG2); a.config(fg=FG3)
            for w in (lr, name_lbl, arr):
                w.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
                w.bind("<Enter>", _on_e)
                w.bind("<Leave>", _on_l)
        tk.Frame(lcard, bg=BG3, height=6).pack()

        # Close button
        close_row = tk.Frame(inner, bg=BG)
        close_row.pack(fill="x", padx=PAD, pady=(0, 20))
        cb = RBtn(close_row, "Close", d.destroy,
                  bg=BG3, fg=FG2, hover_bg=T["bg5"],
                  width=100, height=36, radius=14, font=F(9))
        cb.pack(side="right")

    # ── Required Files dialog ─────────────────────────────────────────────────
    def _show_required_files_dialog(self) -> None:
        """Show all required download links in a styled dialog."""
        BG   = T["bg"]
        BG2  = T["bg2"]
        BG3  = T["bg3"]
        BG4  = T["bg4"]
        ACC  = T["accent"]
        ORG  = T["org"]
        GRN  = T["grn"]
        PUR  = T["purple"]
        FG   = T["fg"]
        FG2  = T["fg2"]
        FG3  = T["fg3"]
        BRD  = T["border"]

        FILES = [
            ("TWRP Download",
             "https://t.me/gta4lvex/23",
             "Custom Recovery — TWRP", ACC),
            ("OFOX Download",
             "https://t.me/gta4lvex/25",
             "Custom Recovery — OrangeFox", ACC),
            ("disabled_vbmeta.tar",
             "https://www.mediafire.com/file/jhto77dd4xoj7ll/disabled_vbmeta.tar/file",
             "Required to disable verified boot", ACC),
            ("Fix_Encryption.zip",
             "https://t.me/gta4lvex/22",
             "Flash from recovery after GSI", ACC),
        ]

        d = tk.Toplevel(self)
        d.title("Required Files  —  SM-T509")
        d.configure(bg=BG)
        d.resizable(False, False)
        d.grab_set()
        d.protocol("WM_DELETE_WINDOW", d.destroy)
        d.update_idletasks()
        W, H = 520, 530
        sx, sy = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{W}x{H}+{(sx-W)//2}+{(sy-H)//2}")
        try:
            import ctypes as _ct
            hwnd = _ct.windll.user32.GetParent(d.winfo_id())
            _ct.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, _ct.byref(_ct.c_int(1)), 4)
        except Exception:
            pass

        tk.Frame(d, bg=ACC, height=3).pack(fill="x")

        hf = tk.Frame(d, bg=BG2)
        hf.pack(fill="x")
        tk.Label(hf, text="📦  Required Files", font=F(13, True),
                 fg=FG, bg=BG2, pady=12, padx=16).pack(side="left")
        tk.Frame(d, bg=BRD, height=1).pack(fill="x")

        body = tk.Frame(d, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        for lbl, url, desc, col in FILES:
            rc_card = RCard(body, radius=14, bg=BG4, border=BRD, fit_content=True)
            rc_card.pack(fill="x", pady=4)
            card  = rc_card._frame   # outer frame (for bg/bind)
            inner_frame = rc_card.inner  # rounded inner
            inner_frame.config(cursor="hand2")
            info = tk.Frame(inner_frame, bg=BG4, cursor="hand2")
            info.pack(side="left", fill="both", expand=True, padx=14, pady=10)
            name_lbl = tk.Label(info, text=lbl, font=F(10, True),
                                fg=FG, bg=BG4, cursor="hand2", anchor="w")
            name_lbl.pack(anchor="w")
            desc_lbl = tk.Label(info, text=desc, font=F(8),
                     fg=FG3, bg=BG4, anchor="w")
            desc_lbl.pack(anchor="w", pady=(2, 0))
            arr = tk.Label(inner_frame, text="\u203a", font=F(12, True), fg=FG3,
                           bg=BG4, padx=14, cursor="hand2")
            arr.pack(side="right")

            _all_widgets = (inner_frame, info, name_lbl, desc_lbl, arr)

            def _hover_on(c=inner_frame, nl=name_lbl, dl=desc_lbl, a=arr, inf=info):
                for w in (c, inf, nl, dl, a): w.config(bg=T["bg5"])
                nl.config(fg=ACC); a.config(fg=ACC)

            def _hover_off(c=inner_frame, nl=name_lbl, dl=desc_lbl, a=arr, inf=info):
                def _check(c=c, nl=nl, dl=dl, a=a, inf=inf):
                    try:
                        mx = c.winfo_pointerx() - c.winfo_rootx()
                        my = c.winfo_pointery() - c.winfo_rooty()
                        if mx < 0 or my < 0 or mx > c.winfo_width() or my > c.winfo_height():
                            for w in (c, inf, nl, dl, a): w.config(bg=BG4)
                            nl.config(fg=FG); a.config(fg=FG3)
                    except Exception:
                        pass
                c.after(10, _check)

            for w in _all_widgets:
                w.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
                w.bind("<Enter>",  lambda _e, ho=_hover_on:  ho())
                w.bind("<Leave>",  lambda _e, hf2=_hover_off: hf2())

        # Close
        close_row = tk.Frame(body, bg=BG)
        close_row.pack(fill="x", pady=(12, 0))
        cb = RBtn(close_row, "Close", d.destroy,
                  bg=BG3, fg=FG2, hover_bg=T["bg5"],
                  width=100, height=36, radius=14, font=F(9))
        cb.pack(side="right")

    # ── Resize ────────────────────────────────────────────────────────────────
    def _on_resize(self, event=None) -> None:
        try:
            total = self.winfo_width()
            if total < 200:
                return
            log_w = max(300, min(440, int(total * 0.24)))
            self._f_log.configure(width=log_w)
        except Exception:
            pass

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str, tag: str = "dim") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._q.put((f"[{ts}]  {msg}\n", tag))

    def _log_fb(self, line: str) -> None:
        body, status, timing = self._fmt_fb_line(line)
        if status is None:
            tag = ("err" if any(w in line.lower()
                                for w in ("error", "fail", "cannot", "failed"))
                   else "dim")
            self.log(f"  {line}", tag)
            return
        tag = "ok" if status == "OKAY" else "err"
        ts  = datetime.now().strftime("%H:%M:%S")
        self._q.put((f"[{ts}]    {body}  ", "dim"))
        suffix = f"{status} {timing}" if timing else status
        self._q.put((f"{suffix}\n", tag))

    def _poll(self) -> None:
        try:
            while True:
                msg, tag = self._q.get_nowait()
                self._log_w.config(state="normal")
                self._log_w.insert("end", msg, tag)
                self._log_w.see("end")
                self._log_w.config(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _clear_log(self) -> None:
        self._log_w.config(state="normal")
        self._log_w.delete("1.0", "end")
        self._log_w.config(state="disabled")
        self._reset_progress()

    def _show_log_ctx(self, event) -> None:
        try:
            try:
                self._log_w.get("sel.first", "sel.last")
                state = "normal"
            except tk.TclError:
                state = "disabled"
            self._log_ctx.entryconfig("Copy selected", state=state)
            self._log_ctx.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass
        finally:
            try:
                self._log_ctx.grab_release()
            except Exception:
                pass

    def _ctx_copy_sel(self) -> None:
        try:
            sel = self._log_w.get("sel.first", "sel.last")
            if sel:
                self.clipboard_clear()
                self.clipboard_append(sel)
                self.update()
        except tk.TclError:
            pass

    def _copy_log(self) -> None:
        text = self._log_w.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Empty", "Log is empty.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        for w in getattr(self, "_log_hdr_btns", []):
            if w.cget("text") == "Copy":
                w.config(text="Copied!", fg=T["grn"])
                self.after(1200, lambda _w=w: _w.config(text="Copy", fg=T["fg3"]))
                break

    def _save_log(self) -> None:
        content = self._log_w.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("Empty", "Log is empty.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialfile=f"flash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Saved", f"Saved:\n{path}")

    # ── Device detection ──────────────────────────────────────────────────────
    def _detect_device(self) -> None:
        rc, out, err = run_fb(["devices"])
        if "NOT_FOUND" in err or rc == -1:
            self.after(0, self._set_dev, "fastboot not found", T["red"])
            self.after(0, self._set_usb_port,
                       "fastboot.exe not found", "— N/A —")
            self.log("fastboot.exe not found — place it in the 'bin' folder", "err")
            return
        fb_lines = [l for l in out.split("\n")
                    if "fastboot" in l.lower() and l.strip()]
        if fb_lines:
            s     = fb_lines[0].split()[0]          # serial (for USB row)
            model = get_device_model(s)              # model  (for PORT/COM row)
            self.after(0, self._set_dev, f"{s}  (fastboot)", T["grn"])
            self.after(0, self._set_usb_port, f"Device {s}", model)
            self.log(f"Device: {s}  |  Model: {model}", "ok")
            return
        self.after(0, self._set_dev, "Device is not connected", T["red"])
        self.after(0, self._set_usb_port,
                   "— Not connected —", "— No fastboot device —")
        self.log("Device is not connected", "warn")

    def _set_usb_port(self, usb: str, port: str) -> None:
        try:
            self._usb_var.set(usb)
            self._port_var.set(port)
            ok = "Device" in usb and "Not" not in usb and "N/A" not in usb
            self._usb_lbl.config(fg=T["c_ok"] if ok else T["fg3"])
            self._port_lbl.config(
                fg=(T["c_ok"] if port and "No" not in port
                    and "Wait" not in port and "N/A" not in port
                    else T["fg3"])
            )
        except Exception:
            pass

    def _set_dev(self, text: str, color: str) -> None:
        self._dev_dot.config(fg=color)
        self._dev_lbl.config(text=text, fg=color)
        try:
            bc   = T["grn"] if color == T["grn"] else T["border2"]
            pill = self._dev_dot.master
            if _CTK:
                pill.configure(border_color=bc)
            else:
                pill.config(highlightbackground=bc)
        except Exception:
            pass

    def _refresh_device(self) -> None:
        self._set_dev("Checking…", T["fg3"])
        threading.Thread(target=self._detect_device, daemon=True).start()

    def _start_auto_detect(self) -> None:
        self._last_dev_state = None

        def _check():
            if self._busy or self._watchdog_suppress:
                return
            try:
                rc, out, err = run_fb(["devices"])
                if rc == -1:
                    return
                fb_lines  = [l for l in out.split("\n")
                             if "fastboot" in l.lower() and l.strip()]
                connected = bool(fb_lines)
                serial    = fb_lines[0].split()[0] if fb_lines else None
                if connected == self._last_dev_state:
                    return
                prev = self._last_dev_state
                self._last_dev_state = connected
                if connected:
                    model = get_device_model(serial)
                    self.after(0, self._set_dev,
                               f"{serial}  (fastboot)", T["grn"])
                    self.after(0, self._set_usb_port,
                               f"Device {serial}", model)
                    self.log(f"Device connected: {serial}  |  Model: {model}", "ok")
                else:
                    self.after(0, self._set_dev,
                               "Device is not connected", T["red"])
                    self.after(0, self._set_usb_port,
                               "— Not connected —", "— No fastboot device —")
                    if prev is True:
                        self.log("Device disconnected", "warn")
            except Exception:
                pass

        def _loop():
            while True:
                time.sleep(1.0)
                threading.Thread(target=_check, daemon=True).start()

        threading.Thread(target=_loop, daemon=True, name="auto-detect").start()

    def _start_watchdog(self) -> None:
        def _watch():
            while True:
                for _ in range(20):
                    time.sleep(0.2)
                if not self._busy:
                    self._watchdog_alerted = False
                    continue
                if self._watchdog_suppress:
                    continue
                if (not device_connected_fastboot()
                        and self._busy
                        and not self._watchdog_alerted):
                    self._watchdog_alerted = True
                    self.log("⚠ Device disconnected — flash stopped!", "err")
                    self._do_stop()
                    self.after(0, self._set_dev,
                               "Device is not connected", T["red"])
                    self.after(0, messagebox.showerror,
                               "Device disconnected",
                               "⚠  Device is not connected.\n\nFlash operation stopped.")

        threading.Thread(target=_watch, daemon=True, name="fb-watchdog").start()

    # ── Browse ────────────────────────────────────────────────────────────────
    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select GSI File",
            filetypes=[("IMG files", "*.img"), ("All files", "*.*")],
        )
        if path:
            size_str = _fmt_size_gb(path)
            self._gsi.set(path)
            self._gsi_lbl.config(
                text=f"✓  {os.path.basename(path)}  ({size_str})",
                fg=T["c_ok"],
            )
            self.log(f"GSI: {path}", "ok")

    def _browse2(self) -> None:
        path = filedialog.askopenfilename(
            title="Select GSI File",
            filetypes=[("IMG files", "*.img"), ("All files", "*.*")],
        )
        if path:
            size_str = _fmt_size_gb(path)
            self._gsi.set(path)
            self._gsi_lbl2.config(
                text=f"✓  {os.path.basename(path)}  ({size_str})",
                fg=T["c_ok"],
            )
            self.log(f"GSI: {path}", "ok")

    # ── UI lock / unlock ──────────────────────────────────────────────────────
    def _lock_ui(self) -> None:
        for attr in ("_flash_btn", "_flash_btn2", "_browse_btn", "_browse_btn2",
                     "_sideload_btn", "_sideload_browse_btn"):
            b = getattr(self, attr, None)
            if b:
                b.enable(False)
        b = getattr(self, "_log_stop_btn", None)
        if b:
            b.enable(True)
        self._ui_locked = True
        try:
            for _v, (tf, inner, _ind, tl) in self._tab_btns.items():
                for w in (tf, inner, tl):
                    w.config(cursor="arrow")
        except Exception:
            pass
        try:
            for cell, cl in self._quick_cells:
                cell.config(cursor="arrow")
                cl.config(cursor="arrow")
        except Exception:
            pass
        try:
            (self._cmd_e.configure if _CTK else self._cmd_e.config)(state="disabled")
        except Exception:
            pass

    def _unlock_ui(self) -> None:
        for attr in ("_flash_btn", "_flash_btn2", "_browse_btn", "_browse_btn2",
                     "_sideload_btn", "_sideload_browse_btn"):
            b = getattr(self, attr, None)
            if b:
                b.enable(True)
        b = getattr(self, "_log_stop_btn", None)
        if b:
            b.enable(False)
        self._ui_locked = False
        try:
            for _v, (tf, inner, _ind, tl) in self._tab_btns.items():
                for w in (tf, inner, tl):
                    w.config(cursor="hand2")
        except Exception:
            pass
        try:
            for cell, cl in self._quick_cells:
                cell.config(cursor="hand2")
                cl.config(cursor="hand2")
        except Exception:
            pass
        try:
            (self._cmd_e.configure if _CTK else self._cmd_e.config)(state="normal")
        except Exception:
            pass

    # ── Flash confirm ─────────────────────────────────────────────────────────
    def _confirm_flash(self, method: str) -> None:
        if self._busy:
            return
        if not fastboot_available():
            messagebox.showerror(
                "fastboot Not Found",
                f"fastboot.exe not found.\n\nPlace it in:\n  {os.path.join(BASE_DIR, 'bin')}\n\n"
                "Download: https://developer.android.com/tools/releases/platform-tools",
            )
            return
        gsi = self._gsi.get().strip()
        if not gsi:
            messagebox.showerror("Missing GSI", "Select a GSI file first.")
            return
        if not os.path.exists(gsi):
            messagebox.showerror("File Not Found", f"GSI not found:\n{gsi}")
            return
        if not os.path.exists(PRODUCT_IMG_PATH):
            messagebox.showerror(
                "Missing product.img",
                f"product.img not found.\n\nExpected:\n  {PRODUCT_IMG_PATH}",
            )
            return
        gsi_size = _fmt_size_gb(gsi)
        label   = "New (5 steps)" if method == "new" else "Classic (7 steps)"
        if not messagebox.askyesno(
            "Confirm Flash",
            f"Method: {label}\n\n"
            f"  GSI:  {os.path.basename(gsi)}  ({gsi_size})\n\n"
            "⚠  This will ERASE ALL DATA.\n\nContinue?",
        ):
            return
        self._stop = False
        self._busy = True
        threading.Thread(
            target=self._do_flash, args=(gsi, method), daemon=True
        ).start()

    # ── Flash worker ──────────────────────────────────────────────────────────
    @staticmethod
    def _fmt_fb_line(line: str):
        m = re.search(r'\s+(OKAY|FAILED)\s*(\[.*?\])?\s*$', line)
        if not m:
            return line, None, None
        body   = line[:m.start()].rstrip()
        status = m.group(1)
        timing = ""
        raw    = (m.group(2) or "").strip()
        if raw:
            tm = re.search(r'([\d.]+)s', raw)
            if tm:
                timing = f"[ {float(tm.group(1)):.1f}s]"
        return body, status, timing

    def _do_flash(self, gsi: str, method: str) -> None:
        steps      = STEPS_NEW     if method == "new" else STEPS_CLASSIC
        sb         = self._steprow if method == "new" else self._steprow2
        prod_img   = PRODUCT_IMG_PATH
        sysext_img = SYSTEM_EXT_IMG_PATH

        self.after(0, self._lock_ui)
        self.after(0, sb.reset)
        self.after(0, self._reset_progress)
        self.after(0, lambda: self._set_progress(0, "Waiting for device…", "running"))
        self.log(f"── Flash [{method.upper()}] ──", "head")

        self._watchdog_suppress = True
        rc, out, err = run_fb(["devices"])
        self._watchdog_suppress = False
        if rc == -1:
            self._fail("fastboot not found.\n\nPlace fastboot.exe in the 'bin' folder.", sb)
            return
        lines = [l for l in out.split("\n") if l.strip()]
        if not any("fastboot" in l.lower() for l in lines):
            self.log("Device is not connected", "err")
            self._busy = False
            self.after(0, self._unlock_ui)
            self.after(0, lambda: self._set_progress(0, "No device", "error"))
            self.after(0, messagebox.showerror,
                       "Device is not connected",
                       "⚠  Device is not connected.\n\n"
                       "Please:\n  1. Connect your device via USB\n"
                       "  2. Boot into Fastboot Mode\n"
                       "  3. Press Refresh and try again")
            return
        serial = lines[0].split()[0]
        self.log(f"✓ Device: {serial}", "ok")

        total = len(steps)
        for i, (num, name, args) in enumerate(steps):
            if self._stop:
                self._abort(sb)
                return
            pct_start = int(i / total * 100)
            pct_end   = int((i + 1) / total * 100)
            self.after(0, lambda p=pct_start, n=f"Step {num}/{total}  —  {name}":
                       self._set_progress(p, n, "running"))
            self.after(0, sb.set_step, i, "run")
            self.after(0, lambda p=pct_start, n=f"Step {num}/{total}  —  {name}":
                       sb.set_progress(p, n))
            self.log(f"[{num}/{total}]  {name}…")

            if args is None:
                fb_args = ["--disable-verity", "--disable-verification",
                           "flash", "system", gsi]
                timeout = 900
            elif args == "product":
                fb_args = ["flash", "product", prod_img]
                timeout = 300
            elif args == "system_ext":
                fb_args = ["flash", "system_ext", sysext_img]
                timeout = 300
            else:
                fb_args = list(args)
                timeout = 120

            self._watchdog_suppress = True

            if args is None:
                _gsi_kb = max(1, os.path.getsize(gsi) // 1024)
                _sent   = [0]
                _written = [0]
                _last   = [0]

                def _cb(line,
                        _self=self, _ps=pct_start, _pe=pct_end,
                        _tot_kb=_gsi_kb, _sa=_sent, _wa=_written,
                        _lk=_last, _name=name, _num=num, _total=total):
                    _self._log_fb(line)
                    low = line.lower()
                    if "sending" in low and "kb" in low:
                        try:
                            kb = int(line.split("(")[-1].split("kb")[0].strip().replace(",", ""))
                            _lk[0] = kb
                            _sa[0] += kb
                            ratio = min((_sa[0] + _wa[0]) / (2 * _tot_kb), 1.0)
                            p = _ps + ratio * (_pe - _ps)
                            _self.after(0, lambda _p=p,
                                        _n=f"Step {_num}/{_total}  —  {_name}":
                                        _self._set_progress(_p, _n, "running"))
                        except Exception:
                            pass
                    elif "writing" in low:
                        try:
                            _wa[0] += _lk[0]
                            ratio = min((_sa[0] + _wa[0]) / (2 * _tot_kb), 1.0)
                            p = _ps + ratio * (_pe - _ps)
                            _self.after(0, lambda _p=p,
                                        _n=f"Step {_num}/{_total}  —  {_name}":
                                        _self._set_progress(_p, _n, "running"))
                        except Exception:
                            pass
            else:
                def _cb(line, _self=self):
                    _self._log_fb(line)

            rc, out, err = run_fb(fb_args, timeout, line_cb=_cb)
            self._watchdog_suppress = False

            combined = (out + "\n" + err).strip()
            if rc == -1:
                self.after(0, sb.set_step, i, "err")
                self._fail("fastboot not found.", sb)
                return
            if rc == -2:
                self.after(0, sb.set_step, i, "err")
                self._fail(f"Step {num} timed out after {timeout}s.", sb)
                return
            if rc != 0:
                self.after(0, sb.set_step, i, "err")
                if ("max-download-size" in combined.lower()
                        or "sendbuffer" in combined.lower()):
                    self._fail(
                        f"GSI flash failed — device rejected transfer.\n\n"
                        "• GSI may be too large for device RAM buffer\n"
                        "• Use a USB 3.0 data cable directly on motherboard port\n\n"
                        f"Error:\n{combined[:300]}", sb,
                    )
                else:
                    self._fail(
                        f"Step {num} failed (exit {rc})\n\n{combined[:400]}", sb
                    )
                return

            self.after(0, sb.set_step, i, "ok")
            self.after(0, lambda p=pct_end, n=f"Step {num}/{total}  —  {name}":
                       self._set_progress(p, n, "running"))
            self.after(0, lambda p=pct_end, n=f"Step {num}/{total}  —  {name}":
                       sb.set_progress(p, n))
            self.log("  ✓ Done", "ok")

        self.after(0, lambda: self._set_progress(100, "Complete!", "done"))
        self.after(0, lambda: sb.set_progress(100, "Complete!"))
        self._busy = False
        self.after(0, self._unlock_ui)
        self.log("── Flash complete! ──", "ok")
        self.after(0, messagebox.showinfo, "Flash Complete!",
                   "✓  Flash completed successfully!\n"
                   "─────────────────────────────\n"
                   "Next steps in recovery:\n\n"
                   "  • Flash Fix_Encryption.zip\n"
                   "  • Wipe  >  Format Data  >  yes\n"
                   "  • Reboot system\n"
                   "─────────────────────────────\n\n"
                   "📎 Required files are available in the\n"
                   "   [ About ] tab in this tool.")

    def _fail(self, msg: str, sb=None) -> None:
        self._busy = False
        self.after(0, self._unlock_ui)
        self.after(0, lambda: self._set_progress(0, "Failed", "error"))
        self.log(f"FAILED: {msg}", "err")
        self.after(0, messagebox.showerror, "Failed", f"Flash failed.\n\n{msg}")

    def _abort(self, sb=None) -> None:
        self._busy = False
        self.after(0, self._unlock_ui)
        self.after(0, lambda: self._set_progress(0, "Stopped", "idle"))
        self.log("Aborted.", "warn")

    def _do_stop(self) -> None:
        self._stop = True
        kill_current()
        kill_adb_current()
        self.after(0, lambda: self._set_progress(
            self._cbar_target_pct, "Stopped", "error"
        ))
        self.log("⛔ Stopped.", "err")
        self._busy = False
        self.after(100, self._unlock_ui)

    # ── Manual commands ───────────────────────────────────────────────────────
    def _quick(self, cmd: str) -> None:
        if getattr(self, "_ui_locked", False):
            return
        if not device_connected_fastboot():
            self.log("No device connected — command blocked", "err")
            messagebox.showwarning(
                "No Device",
                "No fastboot device connected.\n\nPlease connect your device first.",
            )
            return
        self.log(f"fastboot {cmd}")
        threading.Thread(
            target=self._exec, args=(cmd.split(),), daemon=True
        ).start()

    def _run_manual(self) -> None:
        cmd = (self._cmd_e.get() if not _CTK else self._cmd_e.get()).strip()
        if cmd:
            (self._cmd_e.delete if not _CTK else self._cmd_e.delete)(0, "end")
        if not cmd:
            return
        self._quick(cmd)

    def _exec(self, args: list) -> None:
        rc, out, err = run_fb(args, 30)
        res = (out + "\n" + err).strip() or "(no output)"
        for line in res.splitlines():
            if line.strip():
                self.log(f"  {line}", "ok" if rc == 0 else "err")

    # ── ADB Sideload ──────────────────────────────────────────────────────────
    def _browse_sideload(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Sideload Package (.zip)",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if path:
            self._sideload_zip = path
            size_str = _fmt_size_smart(path)
            self._sideload_lbl.config(
                text=f"✓  {os.path.basename(path)}  ({size_str})",
                fg=T["c_ok"],
            )
            self.log(f"Sideload package: {path}", "ok")

    def _start_sideload(self) -> None:
        if self._busy:
            return
        if not adb_available():
            messagebox.showerror(
                "adb Not Found",
                f"adb.exe not found.\n\nPlace it in:\n  {BASE_DIR}",
            )
            return
        zip_path = getattr(self, "_sideload_zip", "").strip() if isinstance(
            getattr(self, "_sideload_zip", ""), str) else ""
        if not zip_path:
            messagebox.showerror("Missing Package", "Select a .zip file first.")
            return
        if not os.path.exists(zip_path):
            messagebox.showerror("File Not Found", f"Package not found:\n{zip_path}")
            return
        self._stop = False
        self._busy = True
        threading.Thread(
            target=self._do_sideload, args=(zip_path,), daemon=True
        ).start()

    def _do_sideload(self, zip_path: str) -> None:
        self.after(0, self._lock_ui)
        self.after(0, self._reset_progress)
        self.after(0, lambda: self._set_progress(0, "Checking device…", "running"))
        self.log("── ADB Sideload ──", "head")

        self._watchdog_suppress = True
        state = get_device_state()
        self._watchdog_suppress = False

        if state == "no_adb":
            self._sideload_fail("adb.exe not found.\n\nPlace adb.exe in the tool folder.")
            return
        if state == "none":
            self._sideload_fail(
                "No device detected over ADB.\n\n"
                "Please:\n  1. Boot into Recovery\n"
                "  2. Choose 'Apply update from ADB'\n"
                "  3. Try again"
            )
            return
        if state != "sideload":
            self._sideload_fail(
                f"Device state is '{state}', not 'sideload'.\n\n"
                "In Recovery, choose:\n"
                "  'Apply update' → 'Apply from ADB'\n\n"
                "so the device shows 'sideload' before starting."
            )
            return

        self.log(f"✓ Device ready ({state})", "ok")
        self.log(f"Pushing: {os.path.basename(zip_path)}  ({_fmt_size_smart(zip_path)})")

        def _cb(line, _self=self) -> None:
            _self._log_fb(line)
            pct = parse_sideload_percent(line)
            if pct is not None:
                _self.after(0, lambda p=pct:
                            _self._set_progress(p, "Sideloading…", "running"))

        rc, out, err = sideload(zip_path, line_cb=_cb)

        if self._stop:
            self._sideload_abort()
            return

        combined = (out + "\n" + err).strip()
        if rc == -1:
            self._sideload_fail("adb.exe not found.")
            return
        if rc == -2:
            self._sideload_fail("Sideload timed out — the transfer took too long.")
            return
        if rc != 0:
            self._sideload_fail(f"Sideload failed (exit {rc})\n\n{combined[:400]}")
            return

        self.after(0, lambda: self._set_progress(100, "Complete!", "done"))
        self._busy = False
        self.after(0, self._unlock_ui)
        self.log("── Sideload complete! ──", "ok")
        self.after(0, messagebox.showinfo, "Sideload Complete!",
                   "✓  Package installed successfully via ADB Sideload!")

    def _sideload_fail(self, msg: str) -> None:
        self._busy = False
        self.after(0, self._unlock_ui)
        self.after(0, lambda: self._set_progress(0, "Failed", "error"))
        self.log(f"SIDELOAD FAILED: {msg}", "err")
        self.after(0, messagebox.showerror, "Sideload Failed", msg)

    def _sideload_abort(self) -> None:
        self._busy = False
        self.after(0, self._unlock_ui)
        self.after(0, lambda: self._set_progress(0, "Stopped", "idle"))
        self.log("Sideload aborted.", "warn")
