"""
Tek pencere kuralı: aynı Capri kurulumu ikinci kez açılınca yeni pencere açılmaz, açık olan öne gelir.

Kilit kurulum klasörüne özeldir (farklı klasörlerdeki Capri kopyaları birbirini engellemez). Açık olan sürecin
numarası veri klasörüne yazılır; ikinci açılış o sürecin "Capri" penceresini bulup öne getirir.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
from pathlib import Path

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
_handle = None


def mutex_name(app_dir: Path) -> str:
    digest = hashlib.sha1(str(Path(app_dir).resolve()).casefold().encode("utf-8")).hexdigest()[:16]
    return f"Local\\Capri.{digest}"


def acquire(app_dir: Path, data_dir: Path) -> bool:
    """Kilidi alır; başka bir Capri bu klasörden zaten açıksa False. Windows dışında hep True."""
    global _handle
    if os.name != "nt" or os.environ.get("CAPRI_MULTI"):
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wt.HANDLE
    _handle = kernel32.CreateMutexW(None, False, mutex_name(app_dir))
    if not _handle:
        return True                         # kilit oluşturulamadıysa açılışı engelleme
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "instance.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass
    return True


def _windows_of(pid: int) -> list[int]:
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 64)
            if title.value == "Capri":
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def focus_existing(data_dir: Path) -> bool:
    """Açık olan Capri penceresini simge durumundan çıkarıp öne getirir."""
    try:
        pid = int(json.loads((data_dir / "instance.json").read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    windows = _windows_of(pid)
    if not windows:
        return False
    user32 = ctypes.windll.user32
    hwnd = windows[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True
