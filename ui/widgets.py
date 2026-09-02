# -*- coding: utf-8 -*-
"""
ui/widgets.py
~~~~~~~~~~~~~
Reusable UI components used throughout the application.

Components
----------
RBtn       — Rounded action button (CTk-accelerated when available)
StepRow    — Horizontal flash-step progress strip
RCard      — Rounded card container
StopButton — Dedicated stop/cancel button
load_image — Utility to load PNG/ICO from bundled assets
"""

from __future__ import annotations
import os
import sys
import tkinter as tk
from typing import Callable, Optional

from core.config import T, F, M, BASE_DIR, BIN_DIR

try:
    import customtkinter as ctk
    _CTK = True
except ImportError:
    _CTK = False


# ── Asset loader ──────────────────────────────────────────────────────────────
def load_image(fname: str, size: int = 22) -> Optional[tk.PhotoImage]:
    """
    Locate *fname* in the bundled assets and return a PhotoImage.
    Search order: _MEIPASS → BIN_DIR → BASE_DIR.
    Returns None if the file is not found or cannot be loaded.
    """
    mei = getattr(sys, "_MEIPASS", "") or ""
    candidates = [
        os.path.join(mei,      fname),
        os.path.join(BIN_DIR,  fname),
        os.path.join(BASE_DIR, fname),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            from PIL import Image, ImageTk
            img = Image.open(path).convert("RGBA").resize(
                (size, size), Image.LANCZOS
            )
            return ImageTk.PhotoImage(img)
        except Exception:
            try:
                return tk.PhotoImage(file=path)
            except Exception:
                pass
    return None


# ── RBtn ──────────────────────────────────────────────────────────────────────
class RBtn:
    """
    Rounded action button.

    Uses ``CTkButton`` when *customtkinter* is available; falls back to a
    canvas-drawn rounded rectangle otherwise.  The public interface is
    identical in both cases.
    """

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable,
        *,
        bg:       str = "#2a2a2a",
        fg:       str = "#d8d8d8",
        hover_bg: Optional[str] = None,
        width:    int   = 160,
        height:   int   = 48,
        radius:   int   = 12,
        font:     tuple = ("Segoe UI", 10, "bold"),
        icon:     Optional[tk.PhotoImage] = None,
        enabled:  bool  = True,
    ) -> None:
        self._enabled  = enabled
        self._command  = command
        self._bg       = bg
        self._hover_bg = hover_bg or bg
        self._fg       = fg
        self._font     = font
        self._text     = text
        self._width    = width
        self._height   = height
        self._radius   = radius
        self._icon     = icon

        if _CTK:
            self._use_ctk = True
            font_obj = ctk.CTkFont(
                family=font[0], size=font[1],
                weight="bold" if len(font) > 2 and font[2] == "bold" else "normal",
            )
            self._widget = ctk.CTkButton(
                parent,
                text=text,
                command=command if enabled else (lambda: None),
                fg_color=bg,
                hover_color=hover_bg or bg,
                text_color=fg,
                corner_radius=radius,
                font=font_obj,
                width=width,
                height=height,
                image=icon,
                compound="left",
                state="normal" if enabled else "disabled",
                border_width=1,
                border_color=T["border"],
            )
            self._cmd_orig = command
        else:
            self._use_ctk = False
            try:
                pbg = parent.cget("bg")
            except Exception:
                pbg = T["bg"]
            self._frame = tk.Frame(parent, bg=pbg, width=width, height=height)
            self._frame.pack_propagate(False)
            self._canvas = tk.Canvas(
                self._frame, width=width, height=height,
                highlightthickness=0, bd=0, bg=pbg,
            )
            self._canvas.pack(fill="both", expand=True)
            self._canvas.bind("<Map>",      lambda _e: self._draw(self._bg))
            self._canvas.bind("<Enter>",    lambda _e: self._draw(self._hover_bg) if self._enabled else None)
            self._canvas.bind("<Leave>",    lambda _e: self._draw(self._bg))
            self._canvas.bind("<Button-1>", lambda _e: self._command() if self._enabled else None)
            self._canvas.configure(cursor="hand2" if enabled else "arrow")

    # ── Layout delegation ──────────────────────────────────────────────────────
    def pack(self, **kw) -> None:
        (self._widget if self._use_ctk else self._frame).pack(**kw)

    def grid(self, **kw) -> None:
        (self._widget if self._use_ctk else self._frame).grid(**kw)

    def place(self, **kw) -> None:
        (self._widget if self._use_ctk else self._frame).place(**kw)

    def pack_forget(self) -> None:
        (self._widget if self._use_ctk else self._frame).pack_forget()

    def grid_forget(self) -> None:
        (self._widget if self._use_ctk else self._frame).grid_forget()

    def config(self, **kw) -> None:
        if not self._use_ctk:
            self._frame.config(**kw)

    def cget(self, key: str) -> str:
        return "" if self._use_ctk else self._frame.cget(key)

    # ── State ─────────────────────────────────────────────────────────────────
    def enable(self, value: bool = True) -> None:
        self._enabled = value
        if self._use_ctk:
            self._widget.configure(
                state="normal" if value else "disabled",
                command=self._cmd_orig if value else (lambda: None),
            )
        else:
            self._canvas.configure(cursor="hand2" if value else "arrow")
            self._draw(self._bg)

    def set_icon(self, image: tk.PhotoImage) -> None:
        self._icon = image
        if self._use_ctk:
            try:
                self._widget.configure(image=image)
            except Exception:
                pass
        else:
            self._draw(self._bg)

    # ── Canvas rendering ──────────────────────────────────────────────────────
    def _draw(self, fill: str) -> None:
        c = self._canvas
        c.delete("all")
        w, h, r = self._width, self._height, self._radius
        fc = fill if self._enabled else T["bg4"]
        tc = self._fg if self._enabled else T["fg3"]
        pts = [r,0, w-r,0, w,0, w,r, w,h-r, w,h, w-r,h,
               r,h, 0,h, 0,h-r, 0,r, 0,0, r,0]
        c.create_polygon(pts, smooth=True, fill=fc,
                         outline=T["border"], width=1)
        import tkinter.font as tkfont
        try:
            tw = tkfont.Font(font=self._font).measure(self._text)
        except Exception:
            tw = len(self._text) * 8

        if self._icon:
            try:
                iw = self._icon.width()
            except Exception:
                iw = 20
            gap   = 8
            total = iw + gap + tw
            ix    = (w - total) // 2
            c.create_image(ix + iw // 2, h // 2,
                           image=self._icon, anchor="center")
            c.create_text(ix + iw + gap, h // 2,
                          text=self._text, fill=tc,
                          font=self._font, anchor="w")
        else:
            c.create_text(w // 2, h // 2, text=self._text,
                          fill=tc, font=self._font, anchor="center")


# ── StepRow ───────────────────────────────────────────────────────────────────
class StepRow(tk.Frame):
    """
    Horizontal row of numbered step cells with a progress bar underneath.

    States per cell: ``"idle"`` | ``"run"`` | ``"ok"`` | ``"err"``
    """

    _STATE_COLORS: dict[str, tuple[str, str, str, str]] = {
        #          bg           border        number        label
        "idle": (T["bg_steps"], T["border2"], T["fg3"],    T["fg2"]),
        "run":  ("#0a1f1e",     T["accent"],  T["accent"], T["fg"]),
        "ok":   ("#051a0e",     T["grn"],     T["grn"],    T["grn"]),
        "err":  ("#1a0508",     T["red"],     T["red"],    T["red"]),
    }

    def __init__(
        self,
        parent: tk.Misc,
        steps: list[tuple],
        labels: list[str],
        **kw,
    ) -> None:
        super().__init__(parent, bg=T["bg3"], **kw)
        self._n      = len(steps)
        self._states = ["idle"] * self._n
        self._cells: list[tuple] = []

        self._build_cells(steps, labels)
        self._build_bar()

        self._label = tk.Label(self, text="Ready",
                               font=F(9), bg=T["bg3"], fg=T["fg2"])
        self._label.pack(anchor="w", padx=10, pady=(0, 4))

    def _build_cells(self, steps: list[tuple], labels: list[str]) -> None:
        row = tk.Frame(self, bg=T["bg3"])
        row.pack(fill="x", padx=6, pady=6)

        for i, (num, _, _) in enumerate(steps):
            if i > 0:
                tk.Frame(row, bg=T["border"], width=1).pack(
                    side="left", fill="y", pady=6
                )
            wrap = tk.Frame(row, bg=T["bg3"])
            wrap.pack(side="left", fill="both", expand=True, padx=3)
            cell = tk.Canvas(wrap, width=60, height=64,
                             bg=T["bg3"], highlightthickness=0, bd=0)
            cell.pack(fill="both", expand=True)

            def _draw(c=cell, idx=i, n=num, lbl=labels[i]) -> None:
                c.delete("all")
                W = c.winfo_width() or 60
                H = c.winfo_height() or 64
                cbg, ctop, cnb, ctxt = self._STATE_COLORS.get(
                    self._states[idx],
                    self._STATE_COLORS["idle"],
                )
                r   = 8
                pts = [r,1, W-r,1, W-1,1, W-1,r, W-1,H-1, W-1,H-1,
                       W-r,H-1, r,H-1, 1,H-1, 1,H-1, 1,r, 1,1, r,1]
                c.create_polygon(pts, smooth=True,
                                 fill=cbg, outline=ctop, width=2)
                c.create_text(W // 2, H // 3,
                              text=str(n), font=M(10),
                              fill=cnb, anchor="center")
                c.create_text(W // 2, H * 2 // 3 + 4,
                              text=lbl, font=F(8, True),
                              fill=ctxt, anchor="center")

            cell.bind("<Configure>", lambda _e, d=_draw: d())
            cell.after(30, _draw)
            self._cells.append((cell, _draw, num, labels[i]))

    def _build_bar(self) -> None:
        self._bar_canvas = tk.Canvas(self, height=8, bg=T["bg3"],
                                     highlightthickness=0, bd=0)
        self._bar_canvas.pack(fill="x", padx=10, pady=(2, 4))
        self._bar_pct = 0.0

        def _redraw(event=None) -> None:
            c = self._bar_canvas
            c.delete("all")
            W = c.winfo_width()
            H = c.winfo_height()
            if W < 4 or H < 4:
                return
            r    = H // 2
            pts  = [r,0, W-r,0, W,0, W,r, W,H-r, W,H,
                    W-r,H, r,H, 0,H, 0,H-r, 0,r, 0,0, r,0]
            c.create_polygon(pts, smooth=True, fill=T["bg4"], outline="")
            fw = max(2 * r, int(W * self._bar_pct))
            if fw > 0:
                fw   = min(fw, W)
                fpts = [r,0, fw-r,0, fw,0, fw,r, fw,H-r, fw,H,
                        fw-r,H, r,H, 0,H, 0,H-r, 0,r, 0,0, r,0]
                c.create_polygon(fpts, smooth=True,
                                 fill=T["accent"], outline="")

        self._bar_canvas.bind("<Configure>", _redraw)
        self._redraw_bar = _redraw

    # ── Public API ─────────────────────────────────────────────────────────────
    def set_step(self, index: int, state: str) -> None:
        self._states[index] = state
        _cell, draw_fn, _num, _lbl = self._cells[index]
        draw_fn()

    def set_progress(self, pct: float, text: str = "") -> None:
        self._bar_pct = max(0.0, min(1.0, pct / 100))
        self._redraw_bar()
        if text:
            self._label.config(text=text)

    def reset(self) -> None:
        for i in range(self._n):
            self._states[i] = "idle"
            _, draw_fn, _, _ = self._cells[i]
            draw_fn()
        self._bar_pct = 0.0
        self._redraw_bar()
        self._label.config(text="Ready")


# ── RCard ─────────────────────────────────────────────────────────────────────
class RCard:
    """
    Rounded card container — a tk.Frame with a canvas-drawn rounded border.
    Use ``card.inner`` as the parent for child widgets.
    """

    def __init__(
        self,
        parent: tk.Misc,
        radius: int = 12,
        bg: Optional[str] = None,
        border: Optional[str] = None,
        fit_content: bool = False,
        **kw,
    ) -> None:
        self._bg  = bg     or T["bg3"]
        self._bdr = border or T["border"]
        self._r   = radius
        # fit_content=True: طول الكارت بيتحدد حسب محتواه الفعلي (مثالي لعناصر
        # القوائم زي "Required Files" و روابط "Flash Guide")، بدل ما ياخد
        # الطول الافتراضي لـ Canvas (200px) اللي بيخلي الكارت فاضي وضخم.
        # السلوك الافتراضي (fit_content=False) فضل زي ما هو تماماً عشان أي
        # كارت تاني في الأداة (زي كروت الداشبورد الرئيسية) ميتأثرش.
        self._fit = fit_content
        self._resizing = False
        try:
            pbg = parent.cget("bg")
        except Exception:
            pbg = T["bg"]
        self._frame  = tk.Frame(parent, bg=pbg, **kw)
        self._canvas = tk.Canvas(self._frame, highlightthickness=0,
                                 bd=0, bg=pbg)
        self._canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=self._bg)
        self._canvas.create_window(0, 0, window=self.inner,
                                   anchor="nw", tags="win")
        self._canvas.bind("<Configure>", self._on_resize)
        if self._fit:
            self.inner.bind("<Configure>", self._on_resize)

    def pack(self, **kw) -> None:  self._frame.pack(**kw)
    def grid(self, **kw) -> None:  self._frame.grid(**kw)
    def place(self, **kw) -> None: self._frame.place(**kw)

    def _on_resize(self, event=None) -> None:
        # حارس ضد إعادة الدخول: في وضع fit_content، تغيير عرض/طول inner أو
        # canvas بيولّد Configure جديد يرجع يستدعي الدالة دي تاني، فلازم
        # نمنع أي استدعاء متداخل عشان مايحصلش RecursionError.
        if self._resizing:
            return
        self._resizing = True
        try:
            W = self._canvas.winfo_width()
            H = self._canvas.winfo_height()
            if W < 4:
                return
            if self._fit:
                # نثبت العرض بس ونسيب الطول يتحدد من غير الفريم الداخلي نفسه
                self.inner.config(width=W - 2)
                self.inner.update_idletasks()
                H = max(self.inner.winfo_reqheight() + 2, 4)
                if self._canvas.winfo_height() != H:
                    self._canvas.configure(height=H)
            if H < 4:
                return
            self._redraw_bg(W, H)
        finally:
            self._resizing = False

    def _redraw_bg(self, W: int, H: int) -> None:
        self._canvas.delete("bg")
        r   = self._r
        pts = [r,1, W-r,1, W-1,1, W-1,r, W-1,H-r, W-1,H-1,
               W-r,H-1, r,H-1, 1,H-1, 1,H-r, 1,r, 1,1, r,1]
        self._canvas.create_polygon(pts, smooth=True,
                                    fill=self._bg, outline=self._bdr,
                                    width=1, tags="bg")
        self._canvas.tag_lower("bg")
        self._canvas.itemconfig("win", width=W - 2, height=H - 2)
        self._canvas.coords("win", 1, 1)
        if not self._fit:
            self.inner.config(width=W - 2, height=H - 2)


# ── StopButton ────────────────────────────────────────────────────────────────
class StopButton:
    """
    Dedicated stop / cancel button rendered on a canvas.
    Call ``enable(True)`` to arm it, ``enable(False)`` to dim it.
    """

    def __init__(
        self,
        parent: tk.Misc,
        width: int,
        height: int,
        command: Callable,
    ) -> None:
        try:
            pbg = parent.cget("bg")
        except Exception:
            pbg = T["bg2"]
        self._w       = width
        self._h       = height
        self._cmd     = command
        self._enabled = False
        self._icon    = None
        self._hover   = False

        self._frame = tk.Frame(parent, bg=pbg, width=width, height=height)
        self._frame.pack_propagate(False)
        self._canvas = tk.Canvas(self._frame, width=width, height=height,
                                 highlightthickness=0, bd=0, bg=pbg)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Map>",       lambda _e: self.redraw())
        self._canvas.bind("<Configure>", lambda _e: self.redraw())
        self._canvas.bind("<Enter>",     lambda _e: self._on_enter())
        self._canvas.bind("<Leave>",     lambda _e: self._on_leave())
        self._canvas.bind("<Button-1>",  lambda _e: self._on_click())
        self._canvas.configure(cursor="arrow")

    def pack(self, **kw) -> None:  self._frame.pack(**kw)
    def grid(self, **kw) -> None:  self._frame.grid(**kw)
    def place(self, **kw) -> None: self._frame.place(**kw)

    def enable(self, value: bool = True) -> None:
        self._enabled = value
        self._hover   = False
        self._canvas.configure(cursor="hand2" if value else "arrow")
        self.redraw()

    def set_icon(self, icon: tk.PhotoImage) -> None:
        self._icon = icon
        self.redraw()

    def redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        W = c.winfo_width()  or self._w
        H = c.winfo_height() or self._h
        r   = 8
        bg  = ("#3d0e1c" if self._hover else T["bg4"]) if self._enabled else T["bg4"]
        fg  = T["red"] if self._enabled else T["fg3"]
        bdr = (T["red"] if self._hover else "#5a1a2a") if self._enabled else T["border"]
        pts = [r,1, W-r,1, W-1,1, W-1,r, W-1,H-r, W-1,H-1,
               W-r,H-1, r,H-1, 1,H-1, 1,H-r, 1,r, 1,1, r,1]
        c.create_polygon(pts, smooth=True, fill=bg, outline=bdr, width=1)
        c.create_text(W // 2, H // 2, text="Stop",
                      fill=fg, font=F(9, True), anchor="center")

    def _on_enter(self) -> None:
        if self._enabled:
            self._hover = True
            self.redraw()

    def _on_leave(self) -> None:
        self._hover = False
        self.redraw()

    def _on_click(self) -> None:
        if self._enabled:
            self._cmd()
