# -*- coding: utf-8 -*-
"""
SM-T509 Flash Tool
~~~~~~~~~~~~~~~~~~
Entry point — bootstraps security, DPI awareness, and launches the UI.

Run:   python main.py
Build: python build_exe.py
"""

import ctypes
import sys
import traceback
import tkinter
import logging
import os

# ── Logging: in-memory only, no file on disk ──────────────────────────────────
logging.basicConfig(
    stream=open(os.devnull, "w"),
    level=logging.CRITICAL,
)
log = logging.getLogger("flash_tool")
# ── Force CWD to script directory ────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_SCRIPT_DIR)

log.info("=== SM-T509 Flash Tool starting ===")
log.info(f"Python: {sys.version}")
log.info(f"Executable: {sys.executable}")
log.info(f"CWD fixed to: {os.getcwd()}")


def _set_dpi_aware() -> None:
    """Enable per-monitor DPI awareness (Windows only)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _global_exception_handler(exc_type, exc_value, exc_tb) -> None:
    """Show a crash dialog for any unhandled exception."""
    try:
        tkinter.messagebox.showerror(
            f"Crash — SM-T509 Flash Tool",
            f"An unexpected error occurred:\n\n{exc_value}",
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main() -> None:
    # 1. Security checks (anti-debug / anti-tamper)
    try:
        log.info("Running security checks...")
        from core.security import run_security_checks
        run_security_checks()
        log.info("Security checks passed.")
    except Exception:
        log.error("Security checks FAILED:\n" + traceback.format_exc())
        raise

    # 2. DPI awareness
    try:
        _set_dpi_aware()
        log.info("DPI awareness set.")
    except Exception:
        log.warning("DPI awareness failed (non-fatal):\n" + traceback.format_exc())

    # 3. Global exception hook
    sys.excepthook = _global_exception_handler

    # 4. Launch UI
    try:
        log.info("Importing UI...")
        from ui.app import App
        from core.config import APP_NAME, APP_VERSION
        log.info(f"Launching {APP_NAME} V{APP_VERSION}")

        app = App()
        app.log(f"{APP_NAME}  V{APP_VERSION}  —  Ready", "head")

        from core.fastboot import fastboot_available
        if not fastboot_available():
            log.warning("fastboot.exe not found")
            app.log("fastboot.exe not found — bundle may be corrupted", "err")

        log.info("Entering mainloop.")
        app.mainloop()

    except Exception:
        msg = traceback.format_exc()
        log.error("FATAL error on startup:\n" + msg)
        try:
            tkinter.messagebox.showerror(
                "Crash — SM-T509 Flash Tool",
                f"Fatal error on startup:\n\n{msg[:600]}",
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
