# -*- coding: utf-8 -*-
"""
core/config.py
~~~~~~~~~~~~~~
Application-wide constants: version, paths, theme tokens,
typography helpers, and flash-step definitions.
"""

from __future__ import annotations
import os
import sys

# ── Identity ──────────────────────────────────────────────────────────────────
APP_NAME    = "SM-T509 Flash Tool"
APP_VERSION = "1.2"
APP_DATE    = "29-8-2026"
APP_AUTHOR  = "Ahmed AbdelRazek"
APP_GROUP   = "DevCatowa"

# ── Runtime paths ─────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _MEI     = getattr(sys, "_MEIPASS", None)
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BIN_DIR  = _MEI if _MEI else BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(BASE_DIR)
    BIN_DIR  = BASE_DIR

PRODUCT_IMG_PATH    = os.path.join(BIN_DIR, "product.img")
SYSTEM_EXT_IMG_PATH = os.path.join(BIN_DIR, "system_ext.img")

# ── Update endpoints ──────────────────────────────────────────────────────────
GITHUB_USER  = "ahlawy8880"
GITHUB_REPO  = "SM-T509-FlashTool"
VERSION_URL  = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    "/main/version.txt"
)

# ── Theme — dark-only, warm charcoal palette ──────────────────────────────────
T: dict[str, str] = {
    "bg":       "#1c1c22",
    "bg2":      "#23232c",
    "bg3":      "#2b2b38",
    "bg4":      "#32324a",
    "bg5":      "#3e3e58",
    "bg_steps": "#2f2f42",
    "border":   "#3a3a52",
    "border2":  "#4a4a6a",
    "accent":   "#00D8CC",
    "accent_h": "#00F0E2",
    "accent_d": "#00897D",
    "accent_dh":"#00A89A",
    "grn":      "#22D36A",
    "grn_h":    "#3AEBA0",
    "red":      "#FF4560",
    "red_h":    "#FF7080",
    "org":      "#FF8C42",
    "org_h":    "#FFA870",
    "purple":   "#A78BFF",
    "fg":       "#EAEAF5",
    "fg2":      "#9090b0",
    "fg3":      "#5a5a7a",
    "log_bg":   "#1e1e28",
    "c_ok":     "#22D36A",
    "c_info":   "#5B9FFF",
    "c_warn":   "#FFD060",
    "c_err":    "#FF4560",
    "c_head":   "#00D8CC",
    "c_dim":    "#c8d0dc",
}

# ── Typography ────────────────────────────────────────────────────────────────
_FF = "Segoe UI Variable Display"
_FM = "Arial"  # Unicode-safe

def F(size: int = 11, bold: bool = False) -> tuple:
    s = size + 2
    return (_FF, s, "bold") if bold else (_FF, s)

def M(size: int = 10) -> tuple:
    return (_FM, size + 1)

# ── Flash step definitions ────────────────────────────────────────────────────
STEPS_NEW: list[tuple] = [
    (1, "Flash product",    "product"),
    (2, "Flash system_ext", "system_ext"),
    (3, "Erase system",     ["erase", "system"]),
    (4, "Flash GSI",        None),
    (5, "Reboot recovery",  ["reboot", "recovery"]),
]
LABELS_NEW: list[str] = ["Product", "Sys_ext", "System", "GSI", "Reboot"]

STEPS_CLASSIC: list[tuple] = [
    (1, "Erase metadata",  ["erase", "metadata"]),
    (2, "Erase cache",     ["erase", "cache"]),
    (3, "Erase system",    ["erase", "system"]),
    (4, "Flash product",   "product"),
    (5, "Flash GSI",       None),
    (6, "Erase userdata",  ["erase", "userdata"]),
    (7, "Reboot recovery", ["reboot", "recovery"]),
]
LABELS_CLASSIC: list[str] = ["Meta", "Cache", "System", "Product", "GSI", "Data", "Reboot"]
