# -*- coding: utf-8 -*-
"""
core/security.py
~~~~~~~~~~~~~~~~
Professional multi-layer anti-debug, anti-tamper, anti-reverse-engineering protection.
Call ``run_security_checks()`` once at startup — before any UI is created.
"""

from __future__ import annotations
import ctypes
import ctypes.wintypes
import hashlib
import hmac
import logging
import math
import os
import struct
import subprocess
import sys
import threading
import time

log = logging.getLogger("flash_tool.security")


# ── Known analysis / reverse engineering tool process names ───────────────────
_HOSTILE_PROCS: frozenset[str] = frozenset({
    "ollydbg.exe","x64dbg.exe","x32dbg.exe","windbg.exe",
    "ntsd.exe","cdb.exe","kd.exe","gdb.exe","immunity debugger.exe",
    "ida.exe","ida64.exe","idaq.exe","idaq64.exe","idaw.exe","idaw64.exe",
    "idat.exe","idat64.exe","idag.exe","idag64.exe","idaw32.exe",
    "binary_ninja.exe","binaryninja.exe","cutter.exe","rizin.exe",
    "radare2.exe","r2.exe","ghidra.exe",
    "dnspy.exe","dnspyex.exe","dotpeek.exe","ilspy.exe",
    "de4dot.exe","reflexil.exe","justdecompile.exe","telerik.justdecompile.exe",
    "jetbrains.dotpeek.exe",
    "scylla.exe","scylla_x64.exe","scylla_x86.exe","protection_id.exe",
    "lordpe.exe","petools.exe","peid.exe","exeinfope.exe",
    "die.exe","detect-it-easy.exe",
    "processhacker.exe","processhacker2.exe","procmon.exe","procmon64.exe",
    "procexp.exe","procexp64.exe","procexp64a.exe","process monitor.exe",
    "apimonitor.exe","apimonitor-x86.exe","apimonitor-x64.exe",
    "spy++.exe","spyxx.exe","spyxx_amd64.exe",
    "wireshark.exe","tshark.exe","fiddler.exe","fiddlereverywhere.exe",
    "charles.exe","burpsuite.exe","mitmproxy.exe","httpanalyzer.exe",
    "httpdebugger.exe","proxifier.exe",
    "hxd.exe","010editor.exe","hexworkshop.exe","uedit64.exe","ultraedit.exe",
    "sandboxiedcomlaunch.exe","sandboxierpcss.exe",
    "cuckoo.exe","sbiectrl.exe",
    "regshot.exe","autoruns.exe","autorunsc.exe","tcpview.exe",
    "filemon.exe","regmon.exe","depends.exe","dependencywalker.exe",
    "resource hacker.exe","reshack.exe","pe-bear.exe","pestudio.exe",
})

# ── Secret HMAC key (obfuscated via XOR) ─────────────────────────────────────
_RAW  = b'\x41\x68\x6d\x65\x64\x38\x38\x34\x53\x4d\x54\x35\x30\x39'
_MASK = b'\x1f\x0a\x19\x12\x05\x5a\x4b\x52\x3d\x2a\x36\x53\x4e\x58'
_HMAC_KEY = bytes(a ^ b for a, b in zip(_RAW, _MASK))


def _terminate(reason: str = "unknown") -> None:
    log.error(f"SECURITY TERMINATE triggered — reason: {reason}")
    try:
        import gc
        gc.collect()
        for mod in list(sys.modules.values()):
            try:
                del mod
            except Exception:
                pass
    except Exception:
        pass
    try:
        ctypes.memset(ctypes.cast(id(sys.argv), ctypes.c_void_p), 0, 64)
    except Exception:
        pass
    os._exit(1)


def _check_debugger_present() -> None:
    log.debug("Layer 1a: IsDebuggerPresent")
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            _terminate("IsDebuggerPresent")
    except Exception as e:
        log.debug(f"Layer 1a exception: {e}")


def _check_remote_debugger() -> None:
    log.debug("Layer 1b: CheckRemoteDebuggerPresent")
    try:
        h      = ctypes.windll.kernel32.GetCurrentProcess()
        result = ctypes.c_bool(False)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(h, ctypes.byref(result))
        if result.value:
            _terminate("CheckRemoteDebuggerPresent")
    except Exception as e:
        log.debug(f"Layer 1b exception: {e}")


def _check_nt_debug_port() -> None:
    log.debug("Layer 2a: NtQueryInformationProcess DebugPort")
    try:
        buf = ctypes.c_ulong(0)
        h   = ctypes.windll.kernel32.GetCurrentProcess()
        ret = ctypes.windll.ntdll.NtQueryInformationProcess(
            h, 7, ctypes.byref(buf), ctypes.sizeof(buf), None
        )
        if ret == 0 and buf.value != 0:
            _terminate("NtDebugPort != 0")
    except Exception as e:
        log.debug(f"Layer 2a exception: {e}")


def _check_nt_global_flag() -> None:
    log.debug("Layer 2b: NtGlobalFlag")
    try:
        buf = ctypes.c_ulong(0)
        h   = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.ntdll.NtQueryInformationProcess(
            h, 31, ctypes.byref(buf), ctypes.sizeof(buf), None
        )
        log.debug(f"Layer 2b: NtGlobalFlag value = {buf.value}")
        if buf.value == 1:  # 0=no debugger, 1=debugger present (ProcessDebugFlags)
            _terminate("NtGlobalFlag == 0")
    except Exception as e:
        log.debug(f"Layer 2b exception: {e}")


def _check_hardware_breakpoints() -> None:
    log.debug("Layer 3: Hardware breakpoints")
    try:
        class _CTX64(ctypes.Structure):
            _fields_ = [
                ("ContextFlags", ctypes.c_ulong),
                ("_pad",         ctypes.c_ubyte * 104),
                ("Dr0",          ctypes.c_ulonglong),
                ("Dr1",          ctypes.c_ulonglong),
                ("Dr2",          ctypes.c_ulonglong),
                ("Dr3",          ctypes.c_ulonglong),
                ("Dr6",          ctypes.c_ulonglong),
                ("Dr7",          ctypes.c_ulonglong),
            ]
        ctx = _CTX64()
        ctx.ContextFlags = 0x00010010
        if ctypes.windll.kernel32.GetThreadContext(
            ctypes.windll.kernel32.GetCurrentThread(), ctypes.byref(ctx)
        ):
            log.debug(f"Layer 3: Dr0={ctx.Dr0} Dr1={ctx.Dr1} Dr2={ctx.Dr2} Dr3={ctx.Dr3}")
            if ctx.Dr0 or ctx.Dr1 or ctx.Dr2 or ctx.Dr3:
                _terminate("Hardware breakpoints detected")
    except Exception as e:
        log.debug(f"Layer 3 exception: {e}")


def _check_heap_flags() -> None:
    log.debug("Layer 4: Heap flags / PEB")
    try:
        k32    = ctypes.windll.kernel32
        is64   = struct.calcsize("P") == 8
        pbi    = ctypes.create_string_buffer(48)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        proc_h = k32.GetCurrentProcess()
        if is64:
            ctypes.windll.ntdll.NtQueryInformationProcess(
                proc_h, 0, ctypes.byref(pbi), 48, None
            )
            peb_addr = struct.unpack_from("<Q", pbi.raw, 8)[0]
            log.debug(f"Layer 4: PEB addr = {hex(peb_addr)}")
            if peb_addr:
                ng_flag = ctypes.c_ulong(0)
                if ctypes.windll.kernel32.ReadProcessMemory(
                    proc_h,
                    ctypes.c_void_p(peb_addr + 0xBC),
                    ctypes.byref(ng_flag),
                    4, None
                ):
                    log.debug(f"Layer 4: PEB NtGlobalFlag = {hex(ng_flag.value)}")
                    if ng_flag.value & 0x70:
                        _terminate(f"PEB heap flags set: {hex(ng_flag.value)}")
    except Exception as e:
        log.debug(f"Layer 4 exception: {e}")


def _check_timing() -> None:
    log.debug("Layer 5: Timing check")
    try:
        t0 = time.perf_counter()
        x = 0
        for i in range(600_000):
            x ^= i * 0x6b + (i >> 3)
        elapsed = time.perf_counter() - t0
        log.debug(f"Layer 5: loop elapsed = {elapsed:.3f}s")
        if elapsed > 8.0:
            _terminate(f"Timing check 1 failed: {elapsed:.2f}s > 8.0s")
        t1 = time.perf_counter()
        _ = math.factorial(2000)
        elapsed2 = time.perf_counter() - t1
        log.debug(f"Layer 5: factorial elapsed = {elapsed2:.3f}s")
        if elapsed2 > 5.0:
            _terminate(f"Timing check 2 failed: {elapsed2:.2f}s > 5.0s")
    except Exception as e:
        log.debug(f"Layer 5 exception: {e}")


def _check_process_list() -> None:
    log.debug("Layer 6: Process list scan")
    try:
        raw = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"],
            creationflags=0x08000000,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode(errors="ignore").lower()
        for name in _HOSTILE_PROCS:
            if name in raw:
                _terminate(f"Hostile process detected: {name}")
        log.debug("Layer 6: No hostile processes found")
    except Exception as e:
        log.debug(f"Layer 6 exception: {e}")


def _check_parent_process() -> None:
    log.debug("Layer 7: Parent process check")
    try:
        SAFE_PARENTS = {
            "explorer.exe","cmd.exe","powershell.exe",
            "conhost.exe","python.exe","pythonw.exe","svchost.exe",
        }
        pid_self = os.getpid()
        raw = subprocess.check_output(
            ["wmic","process","where",f"ProcessId={pid_self}","get","ParentProcessId"],
            creationflags=0x08000000, stderr=subprocess.DEVNULL, timeout=5,
        ).decode(errors="ignore")
        lines = [l.strip() for l in raw.splitlines() if l.strip().isdigit()]
        if not lines:
            log.debug("Layer 7: Could not get parent PID")
            return
        ppid = int(lines[0])
        parent_raw = subprocess.check_output(
            ["wmic","process","where",f"ProcessId={ppid}","get","Name"],
            creationflags=0x08000000, stderr=subprocess.DEVNULL, timeout=5,
        ).decode(errors="ignore").lower()
        parent_name = [l.strip() for l in parent_raw.splitlines()
                       if l.strip() and "name" not in l.lower()]
        if parent_name:
            pn = parent_name[0]
            log.debug(f"Layer 7: Parent process = {pn}")
            if pn in _HOSTILE_PROCS:
                _terminate(f"Parent is hostile: {pn}")
        else:
            log.debug("Layer 7: Could not determine parent name")
    except Exception as e:
        log.debug(f"Layer 7 exception: {e}")


def _check_bundle_integrity() -> None:
    log.debug("Layer 8: Bundle integrity")
    try:
        if getattr(sys, "frozen", False):
            mei = getattr(sys, "_MEIPASS", None)
            if not mei or not os.path.isdir(mei):
                _terminate("_MEIPASS missing or invalid")
            for required in ("adb.exe", "fastboot.exe"):
                p = os.path.join(mei, required)
                if not os.path.isfile(p):
                    _terminate(f"Missing required file: {required}")
        log.debug("Layer 8: OK (source mode or bundle intact)")
    except Exception as e:
        log.debug(f"Layer 8 exception: {e}")


def _check_pe_header() -> None:
    log.debug("Layer 9: PE header check")
    try:
        if not getattr(sys, "frozen", False):
            log.debug("Layer 9: Skipped (not frozen)")
            return
        exe = os.path.abspath(sys.executable)
        if not os.path.isfile(exe):
            _terminate("Executable not found")
        with open(exe, "rb") as f:
            header = f.read(2)
        if header != b"MZ":
            _terminate(f"Bad MZ header: {header!r}")
        log.debug("Layer 9: MZ header OK")
    except Exception as e:
        log.debug(f"Layer 9 exception: {e}")


def _check_api_hooks() -> None:
    log.debug("Layer 10: API hook check")
    try:
        k32  = ctypes.windll.kernel32
        addr = ctypes.cast(k32.IsDebuggerPresent, ctypes.c_void_p).value
        if addr:
            buf = (ctypes.c_ubyte * 4)()
            ctypes.memmove(buf, addr, 4)
            log.debug(f"Layer 10: IsDebuggerPresent first bytes = {list(buf)}")
            if buf[0] == 0xE9 or (buf[0] == 0xFF and buf[1] == 0x25):
                _terminate(f"API hook detected on IsDebuggerPresent: {list(buf)}")
    except Exception as e:
        log.debug(f"Layer 10 exception: {e}")


# ── Layer 11: HMAC self-integrity token ───────────────────────────────────────
_INTEGRITY_TOKEN: bytes | None = None

def _generate_integrity_token() -> None:
    global _INTEGRITY_TOKEN
    log.debug("Layer 11: Generating integrity token")
    try:
        data = f"{sys.executable}{os.getpid()}{time.time():.0f}".encode()
        _INTEGRITY_TOKEN = hmac.new(_HMAC_KEY, data, hashlib.sha256).digest()
        log.debug("Layer 11: Token generated OK")
    except Exception as e:
        log.debug(f"Layer 11 exception: {e}")

def _verify_integrity_token() -> None:
    try:
        if _INTEGRITY_TOKEN is None:
            _terminate("Integrity token is None")
        if len(_INTEGRITY_TOKEN) != 32:
            _terminate(f"Integrity token bad length: {len(_INTEGRITY_TOKEN)}")
    except Exception as e:
        log.debug(f"Token verify exception: {e}")


def _start_watchdog() -> None:
    _scan_interval   = [5]
    _proc_scan_count = [0]

    def _loop() -> None:
        while True:
            time.sleep(_scan_interval[0])
            _check_debugger_present()
            _check_remote_debugger()
            _check_nt_debug_port()
            _check_hardware_breakpoints()
            _verify_integrity_token()
            _proc_scan_count[0] += 1
            if _proc_scan_count[0] >= 3:
                _proc_scan_count[0] = 0
                _check_process_list()

    t = threading.Thread(target=_loop, daemon=True, name="sec-watchdog")
    t.start()


def run_security_checks() -> None:
    if sys.platform != "win32":
        log.info("Security: non-Windows, skipping all checks.")
        return

    log.info("Security: starting all layers...")
    _check_debugger_present()
    log.info("Security: L1a passed")
    _check_remote_debugger()
    log.info("Security: L1b passed")
    _check_nt_debug_port()
    log.info("Security: L2a passed")
    _check_nt_global_flag()
    log.info("Security: L2b passed")
    _check_hardware_breakpoints()
    log.info("Security: L3 passed")
    _check_heap_flags()
    log.info("Security: L4 passed")
    _check_timing()
    log.info("Security: L5 passed")
    _check_process_list()
    log.info("Security: L6 passed")
    _check_parent_process()
    log.info("Security: L7 passed")
    _check_bundle_integrity()
    log.info("Security: L8 passed")
    _check_pe_header()
    log.info("Security: L9 passed")
    _check_api_hooks()
    log.info("Security: L10 passed")
    _generate_integrity_token()
    log.info("Security: L11 passed — all checks done")
    _start_watchdog()
    log.info("Security: watchdog started")
