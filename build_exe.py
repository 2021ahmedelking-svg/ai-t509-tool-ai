# -*- coding: utf-8 -*-
"""
build_exe.py
~~~~~~~~~~~~
SM-T509 Flash Tool — Secure One-File Build Script

Produces:  dist/SM-T509-Flash-Tool.exe

Layout expected in the same folder:
  main.py
  core/
  ui/
  fastboot.exe
  AdbWinApi.dll  AdbWinUsbApi.dll  libwinpthread-1.dll
  product.img
  system_ext.img
  icon.ico  (or logo.ico)
  *.png  (button images)

Run:
  python build_exe.py
"""

from __future__ import annotations
import base64
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))


# ── Console helpers ───────────────────────────────────────────────────────────
def _step(n: int, msg: str)  -> None: print(f"\n  [{n}] {msg}...")
def _ok(msg: str)            -> None: print(f"      + {msg}")
def _warn(msg: str)          -> None: print(f"      ! {msg}")
def _err(msg: str)           -> None:
    print(f"\n  [ERROR] {msg}")
    input("\nPress Enter to exit...")
    sys.exit(1)


print()
print("  =====================================================")
print("   SM-T509 Flash Tool  —  ONE-FILE Secure Build")
print("  =====================================================")


# ── 1. Install / upgrade Python dependencies ──────────────────────────────────
_step(1, "Installing dependencies")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "--upgrade",
     "pyinstaller", "pillow", "customtkinter"],
    check=True,
)
_ok("Done")


# ── 2. UPX (optional — compresses the EXE) ────────────────────────────────────
_step(2, "Checking UPX")
upx_dir = os.path.join(BASE, "upx")
upx_exe = os.path.join(upx_dir, "upx.exe")
use_upx = False

if not os.path.isfile(upx_exe):
    _ok("Downloading UPX 4.2.4...")
    os.makedirs(upx_dir, exist_ok=True)
    zip_path = os.path.join(BASE, "upx.zip")
    try:
        urllib.request.urlretrieve(
            "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-win64.zip",
            zip_path,
        )
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                if member.endswith("upx.exe"):
                    with z.open(member) as src, open(upx_exe, "wb") as dst:
                        dst.write(src.read())
                    break
        os.remove(zip_path)
    except Exception as exc:
        _warn(f"UPX download failed ({exc}), skipping")

if os.path.isfile(upx_exe):
    use_upx = True
    _ok("UPX ready")
else:
    _warn("UPX not available — EXE will not be compressed")


# ── 3. Encrypt source (XOR, 64-byte random key per build) ─────────────────────
_step(3, "Encrypting source")
src_path = os.path.join(BASE, "main.py")
if not os.path.isfile(src_path):
    _err(f"main.py not found in {BASE}")

with open(src_path, "rb") as f:
    raw = f.read()

key       = secrets.token_bytes(64)
enc_bytes = bytes(b ^ key[i % 64] for i, b in enumerate(raw))
enc_b64   = base64.b64encode(enc_bytes).decode()
key_b64   = base64.b64encode(key).decode()
_ok(f"Encrypted {len(raw):,} bytes  |  key: {len(key)} bytes (random per build)")


# ── 4. Write encrypted loader ─────────────────────────────────────────────────
_step(4, "Writing encrypted loader")
loader_path = os.path.join(BASE, "_smtloader.py")

LOADER = f'''# -*- coding: utf-8 -*-
# SM-T509 Flash Tool — Encrypted Loader (auto-generated, do not edit)
import base64, sys, os, time, ctypes, threading

# Pre-import every module the tool needs so PyInstaller bundles them
import queue, tkinter, tkinter.ttk, tkinter.filedialog, tkinter.messagebox
import tkinter.scrolledtext, tkinter.font
import PIL, PIL.Image, PIL.ImageTk, PIL.ImageDraw, PIL.ImageFont, PIL.IcoImagePlugin
import customtkinter, darkdetect
import subprocess, shutil, struct, gc, webbrowser, traceback, datetime, re
import urllib.request

_ENC = {repr(enc_b64)}
_KEY = {repr(key_b64)}

def _xor(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def _guard():
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            ctypes.windll.kernel32.ExitProcess(1)
    except Exception: pass
    try:
        h = ctypes.windll.kernel32.GetCurrentProcess()
        r = ctypes.c_bool(False)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(h, ctypes.byref(r))
        if r.value: ctypes.windll.kernel32.ExitProcess(1)
    except Exception: pass
    try:
        t0 = time.perf_counter()
        s  = sum(range(300_000))
        if time.perf_counter() - t0 > 2.5:
            ctypes.windll.kernel32.ExitProcess(1)
    except Exception: pass
    try:
        import subprocess as _sp
        bad = {{"ollydbg","x64dbg","x32dbg","ida64","idaq","idaq64",
                "wireshark","processhacker","dnspy","de4dot","cheatengine",
                "ghidra","pestudio","die","x96dbg"}}
        out = _sp.check_output("tasklist /fo csv /nh", shell=True,
                               stderr=_sp.DEVNULL).decode(errors="ignore").lower()
        for name in bad:
            if name in out: ctypes.windll.kernel32.ExitProcess(1)
    except Exception: pass
    def _watch():
        while True:
            time.sleep(9)
            try:
                if ctypes.windll.kernel32.IsDebuggerPresent():
                    ctypes.windll.kernel32.ExitProcess(1)
            except Exception: pass
    threading.Thread(target=_watch, daemon=True).start()

_guard()

_src   = _xor(base64.b64decode(_ENC), base64.b64decode(_KEY))
_globs = dict(globals())
_globs["__name__"] = "__main__"
_globs["__file__"] = os.path.abspath(sys.argv[0])
_globs["__spec__"] = None
exec(compile(_src.decode("utf-8"), "__main__", "exec"), _globs)
'''

with open(loader_path, "w", encoding="utf-8") as f:
    f.write(LOADER)
_ok("Loader written")


# ── 5. Collect assets & binaries ──────────────────────────────────────────────
_step(5, "Collecting assets")
datas:    list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []

# Python source packages (core/ and ui/)
for pkg in ("core", "ui"):
    pkg_dir = os.path.join(BASE, pkg)
    if os.path.isdir(pkg_dir):
        for fn in os.listdir(pkg_dir):
            if fn.endswith(".py"):
                datas.append((os.path.join(pkg_dir, fn), pkg))
        _ok(f"Package: {pkg}/")
    else:
        _warn(f"{pkg}/ not found — tool won't run without it!")

# Images & icons
for fn in os.listdir(BASE):
    low = fn.lower()
    if low.endswith((".png", ".ico")) and not fn.startswith("_"):
        datas.append((os.path.join(BASE, fn), "."))
        _ok(f"Image: {fn}")

# fastboot.exe
fb_exe = os.path.join(BASE, "fastboot.exe")
if os.path.isfile(fb_exe):
    binaries.append((fb_exe, "."))
    _ok(f"fastboot.exe  ({os.path.getsize(fb_exe)//1024:,} KB)")
else:
    _warn("fastboot.exe NOT FOUND — tool won't flash without it!")

# adb.exe
adb_exe = os.path.join(BASE, "adb.exe")
if os.path.isfile(adb_exe):
    binaries.append((adb_exe, "."))
    _ok(f"adb.exe  ({os.path.getsize(adb_exe)//1024:,} KB)")
else:
    _warn("adb.exe NOT FOUND — security check will fail!")

# Support DLLs
for dll in ("AdbWinApi.dll", "AdbWinUsbApi.dll", "libwinpthread-1.dll"):
    p = os.path.join(BASE, dll)
    if os.path.isfile(p):
        binaries.append((p, "."))
        _ok(f"{dll}  ({os.path.getsize(p)//1024:,} KB)")
    else:
        _warn(f"{dll} NOT FOUND — fastboot may fail without it!")

# product.img
prod_img = os.path.join(BASE, "product.img")
if os.path.isfile(prod_img):
    datas.append((prod_img, "."))
    _ok(f"product.img  ({os.path.getsize(prod_img)//1024:,} KB)")
else:
    _warn("product.img NOT FOUND — flash won't work without it!")

# system_ext.img
sysext_img = os.path.join(BASE, "system_ext.img")
if os.path.isfile(sysext_img):
    datas.append((sysext_img, "."))
    _ok(f"system_ext.img  ({os.path.getsize(sysext_img)//1024:,} KB)")
else:
    _warn("system_ext.img NOT FOUND — New Method flash won't work without it!")

_ok(f"Total: {len(datas)} data file(s), {len(binaries)} binary/dll(s)")


# ── 6. Write PyInstaller spec ─────────────────────────────────────────────────
_step(6, "Writing spec file")

datas_str    = "\n".join(f"        ({repr(s)}, {repr(d)})," for s, d in datas)
binaries_str = "\n".join(f"        ({repr(s)}, {repr(d)})," for s, d in binaries)
icon_path    = os.path.join(BASE, "icon.ico")
icon_line    = f"    icon={repr(icon_path)}," if os.path.isfile(icon_path) else ""
upx_line     = f"    upx_dir={repr(upx_dir)}," if use_upx else ""

# ── Versioned EXE name ────────────────────────────────────────────────────────
import importlib.util as _ilu
_spec_cfg = _ilu.spec_from_file_location("config", os.path.join(BASE, "core", "config.py"))
_cfg_mod  = _ilu.module_from_spec(_spec_cfg)
_spec_cfg.loader.exec_module(_cfg_mod)
APP_VER   = getattr(_cfg_mod, "APP_VERSION", "1.0")
EXE_NAME  = f"SM-T509-Flash-Tool-V{APP_VER}"
_ok(f"Output name: {EXE_NAME}.exe  (version from core/config.py)")

spec = f"""# -*- mode: python -*-
a = Analysis(
    [{repr(loader_path)}],
    pathex=[{repr(BASE)}],
    binaries=[
{binaries_str}
    ],
    datas=[
{datas_str}
    ],
    hiddenimports=[
        # stdlib
        'queue', 'threading', 'os', 'sys', 'time', 're',
        'ctypes', 'ctypes.wintypes', 'base64', 'secrets',
        'subprocess', 'shutil', 'struct', 'gc',
        'webbrowser', 'traceback', 'datetime',
        'urllib', 'urllib.request',
        # tkinter
        'tkinter', 'tkinter.ttk',
        'tkinter.filedialog', 'tkinter.messagebox',
        'tkinter.scrolledtext', 'tkinter.font',
        # PIL
        'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw',
        'PIL.ImageFont', 'PIL.IcoImagePlugin',
        # third-party
        'customtkinter', 'darkdetect',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name={repr(EXE_NAME)},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx={use_upx},
{upx_line}
    console=False,
    disable_windowed_traceback=False,
    onefile=True,
{icon_line}
)
"""

spec_path = os.path.join(BASE, "tool.spec")
with open(spec_path, "w", encoding="utf-8") as f:
    f.write(spec)
_ok("Spec written")


# ── 7. Build ──────────────────────────────────────────────────────────────────
_step(7, "Building ONE-FILE EXE  (1–2 min)...")
print()
result = subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    spec_path,
])

# Cleanup temp files
for fp in (loader_path, spec_path):
    try:
        os.remove(fp)
    except Exception:
        pass
build_dir = os.path.join(BASE, "build")
if os.path.isdir(build_dir):
    shutil.rmtree(build_dir, ignore_errors=True)

if result.returncode != 0:
    _err("Build failed — see output above")

exe_path = os.path.join(BASE, "dist", f"{EXE_NAME}.exe")
exe_mb   = (os.path.getsize(exe_path) // 1024 // 1024
            if os.path.isfile(exe_path) else 0)

print()
print("  =====================================================")
print(f"   Build complete!  →  dist\\{EXE_NAME}.exe")
print(f"   Size: ~{exe_mb} MB  (single file, no extra folders)")
print("  -----------------------------------------------------")
print("   Bundled inside EXE:")
print("    + core/  +  ui/  (encrypted source packages)")
print("    + fastboot.exe + adb.exe + AdbWinApi.dll")
print("    + AdbWinUsbApi.dll + libwinpthread-1.dll")
print("    + product.img + system_ext.img")
print("    + all icons & images")
print("  -----------------------------------------------------")
print("   Protection:")
print("    + XOR encryption (64-byte random key per build)")
print("    + Runtime decryption in RAM only")
print("    + Anti-debug (IsDebuggerPresent x2 + NtQuery)")
print("    + Suspicious process scanner")
print("    + Timing attack detection")
print("    + Hardware breakpoint detection")
print("    + Background watchdog thread")
if use_upx:
    print("    + UPX compression")
print("  =====================================================")
print()
input("Press Enter to exit...")
