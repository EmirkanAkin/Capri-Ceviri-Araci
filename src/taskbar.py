"""
Görev çubuğu ilerlemesi: Capri'nin görev çubuğu simgesinde çevirinin ilerlemesini gösterir (Windows ITaskbarList3).

COM nesnesi kendi iş parçacığında (STA) yaşar; çağrılar kuyruğa atılır, böylece çeviri iş parçacığı hiç beklemez ve
COM'un iş parçacığı kuralları çiğnenmez. Aynı değeri tekrar göndermez (yüzde değişmedikçe sessiz kalır).
Windows dışında ya da COM kullanılamıyorsa her şey sessizce hiçbir şey yapmaz.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes as wt
from typing import Callable, Optional

NONE, INDETERMINATE, NORMAL, ERROR, PAUSED = 0x0, 0x1, 0x2, 0x4, 0x8
_SCALE = 1000            # değer binde bir hassasiyetle gönderilir
_CLSID = "{56FDF344-FD6D-11d0-958A-006097C9A090}"   # CLSID_TaskbarList
_IID = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"     # IID_ITaskbarList3
_HR_INIT, _SET_VALUE, _SET_STATE, _RELEASE = 3, 9, 10, 2   # sanal tablo sıraları
_Thread, _Timer = threading.Thread, threading.Timer   # testler threading.Thread'i geçici değiştirse de etkilenmez


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    guid = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
    return guid


class _TaskbarList:
    """ITaskbarList3 üzerinde ham sanal tablo çağrıları (comtypes gerekmez)."""

    def __init__(self):
        self.ptr = ctypes.c_void_p()
        ole32 = ctypes.windll.ole32
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID)), None, 1, ctypes.byref(_guid(_IID)), ctypes.byref(self.ptr))
        if hr != 0 or not self.ptr:
            raise OSError(f"TaskbarList oluşturulamadı (0x{hr & 0xFFFFFFFF:08X})")
        self._call(_HR_INIT, [])

    def _call(self, index: int, args: list, argtypes: tuple = ()) -> int:
        vtable = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return proto(vtable[index])(self.ptr, *args)

    def set_value(self, hwnd: int, done: int, total: int) -> int:
        return self._call(_SET_VALUE, [hwnd, done, total], (wt.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong))

    def set_state(self, hwnd: int, flags: int) -> int:
        return self._call(_SET_STATE, [hwnd, flags], (wt.HWND, ctypes.c_int))

    def release(self) -> None:
        if self.ptr:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[_RELEASE])(self.ptr)
            self.ptr = ctypes.c_void_p()


class TaskbarProgress:
    """
    Görev çubuğu simgesinin ilerleme göstergesi.
    find_window: pencere tutamacını döndürür (pencere henüz yoksa 0; bulunana kadar her çağrıda yeniden denenir).
    """

    def __init__(self, find_window: Callable[[], int]):
        self._find_window = find_window
        self._hwnd = 0
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._last: tuple = (NONE, -1)
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self.available = sys.platform == "win32"
        self.results: list = []     # testler için son HRESULT'lar

    # ── Genel API ──
    def value(self, done: float, total: float) -> None:
        """Belirli ilerleme (yeşil çubuk)."""
        if total <= 0:
            return
        self._send(NORMAL, max(0, min(_SCALE, int(done * _SCALE / total))))

    def busy(self) -> None:
        """Süresi belli olmayan iş (kayan çubuk)."""
        self._send(INDETERMINATE, -1)

    def paused(self, clear_after: float = 6.0) -> None:
        """Durduruldu: sarı çubuk, bir süre sonra kaybolur."""
        self._send(PAUSED, max(self._last[1], _SCALE // 100), clear_after)

    def error(self, clear_after: float = 10.0) -> None:
        """Hata: takıldığı yerde kırmızı çubuk (ilerleme yoksa dolu), bir süre sonra kaybolur."""
        self._send(ERROR, self._last[1] if self._last[1] > 0 else _SCALE, clear_after)

    def clear(self) -> None:
        self._send(NONE, -1)

    def close(self) -> None:
        self.clear()
        self._queue.put(None)

    # ── İç işleyiş ──
    def _send(self, state: int, value: int, clear_after: float = 0.0) -> None:
        if not self.available:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if (state, value) == self._last:
                return
            self._last = (state, value)
            if self._thread is None:
                self._thread = _Thread(target=self._worker, daemon=True, name="taskbar")
                self._thread.start()
            self._queue.put((state, value))
            if clear_after > 0:
                self._timer = _Timer(clear_after, self._expire, args=((state, value),))
                self._timer.daemon = True
                self._timer.start()

    def _expire(self, shown: tuple) -> None:
        if self._last == shown:     # arada yeni bir iş başladıysa dokunma
            self.clear()

    def _window(self) -> int:
        if not self._hwnd or not ctypes.windll.user32.IsWindow(self._hwnd):
            try:
                self._hwnd = int(self._find_window() or 0)
            except Exception:
                self._hwnd = 0
        return self._hwnd

    def _worker(self) -> None:
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
            taskbar = _TaskbarList()
        except Exception:
            self.available = False
            return
        try:
            stop = False
            while not stop:
                item = self._queue.get()
                stop = item is None
                while not self._queue.empty():          # birikmişse yalnızca en sonuncusu önemli
                    nxt = self._queue.get()
                    if nxt is None:
                        stop = True
                    else:
                        item = nxt
                if item is None:
                    break
                hwnd = self._window()
                if not hwnd:
                    continue
                state, value = item
                try:
                    results = [taskbar.set_state(hwnd, state)]
                    if state in (NORMAL, ERROR, PAUSED) and value >= 0:
                        results.append(taskbar.set_value(hwnd, value, _SCALE))
                    self.results = results
                except Exception:
                    pass
        finally:
            taskbar.release()
            ctypes.windll.ole32.CoUninitialize()
