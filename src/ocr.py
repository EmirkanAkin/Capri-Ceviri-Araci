"""
Capri — Ekran Çevirisi (OCR)
================================
Windows'un yerleşik OCR motoru (Windows.Media.Ocr) ile ekrandan metin okur.
Ek model gerektirmez; küçük bir alanı ~5-15 ms'de tanır.

- `capture()` / `capture_monitor()` : mss ile hızlı ekran görüntüsü (BGRA)
- `recognize()`                    : BGRA görüntüden satır/paragraf çıkarır
- `RegionWatcher`                  : sabitlenmiş alanı izler, değişince yeniden okur
- `HotkeyManager`                  : sistem geneli kısayollar (RegisterHotKey)
- `prepare_overlay_window()`       : pencereyi ekran yakalamadan gizler, köşeleri yuvarlar
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import io
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_local = threading.local()


# ═══════════════════════════════════════════════════════════════════════════════
# Ekran yakalama
# ═══════════════════════════════════════════════════════════════════════════════

def _sct():
    """mss örneği iş parçacığına özeldir (mss thread-safe değildir)."""
    sct = getattr(_local, "sct", None)
    if sct is None:
        import mss
        sct = _local.sct = (getattr(mss, "MSS", None) or mss.mss)()
    return sct


@dataclass
class Shot:
    bgra: bytes
    width: int
    height: int
    left: int = 0
    top: int = 0

    def crop(self, x0: int, y0: int, x1: int, y1: int) -> "Shot":
        from PIL import Image
        img = Image.frombuffer("RGBA", (self.width, self.height), self.bgra, "raw", "RGBA", 0, 1)
        part = img.crop((x0, y0, x1, y1))
        return Shot(part.tobytes(), part.width, part.height, self.left + x0, self.top + y0)

    def to_jpeg(self, quality: int = 80, max_width: int = 0) -> bytes:
        from PIL import Image
        img = Image.frombuffer("RGBA", (self.width, self.height), self.bgra, "raw", "BGRA", 0, 1).convert("RGB")
        if max_width and img.width > max_width:
            img = img.resize((max_width, int(img.height * max_width / img.width)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    def signature(self) -> bytes:
        """Değişiklik algılama için küçük gri tonlamalı parmak izi."""
        from PIL import Image
        img = Image.frombuffer("RGBA", (self.width, self.height), self.bgra, "raw", "BGRA", 0, 1)
        width = 160
        return img.convert("L").resize((width, max(12, int(width * self.height / max(1, self.width)))), Image.BOX).tobytes()


def monitor_rect(index: int = 1) -> Dict[str, int]:
    monitors = _sct().monitors
    return dict(monitors[index if index < len(monitors) else 1])


def capture(left: int, top: int, width: int, height: int) -> Shot:
    raw = _sct().grab({"left": left, "top": top, "width": max(1, width), "height": max(1, height)})
    return Shot(bytes(raw.bgra), raw.width, raw.height, left, top)


def capture_monitor(index: int = 1) -> Shot:
    m = monitor_rect(index)
    return capture(m["left"], m["top"], m["width"], m["height"])


def signature_diff(a: Optional[bytes], b: Optional[bytes]) -> float:
    """Belirgin biçimde (>24 gri ton) değişen piksellerin yüzdesi; küçük yazı değişimlerini de yakalar."""
    if not a or not b or len(a) != len(b):
        return 100.0
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > 24)
    return changed * 100.0 / len(a)


# ═══════════════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OcrLine:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class OcrResult:
    lines: List[OcrLine] = field(default_factory=list)
    ms: float = 0.0
    language: str = ""

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs())

    def paragraphs(self) -> List[str]:
        """Dikey boşluğa göre satırları paragraflara birleştirir (diyalog kutuları tek paragraf olur)."""
        if not self.lines:
            return []
        lines = sorted(self.lines, key=lambda l: (round(l.y / max(4.0, l.h * 0.6)), l.x))
        paras: List[List[OcrLine]] = [[lines[0]]]
        for prev, cur in zip(lines, lines[1:]):
            gap = cur.y - (prev.y + prev.h)
            same_size = abs(cur.h - prev.h) < max(prev.h, cur.h) * 0.2
            # Konuşmacı adı gibi kısa etiketler ("Elena", "Captain Rex") diyalogdan ayrı tutulur
            label = len(prev.text.split()) <= 3 and not prev.text.rstrip().endswith((".", ",", "!", "?", "…", ":", ";", "-"))
            if gap > max(prev.h, cur.h) * 0.9 or not same_size or (label and len(paras[-1]) == 1):
                paras.append([cur])
            else:
                paras[-1].append(cur)
        out = []
        for group in paras:
            text = " ".join(l.text.strip() for l in group).replace(" - ", "-").strip()
            if text:
                out.append(text)
        return out


class OcrEngineWrapper:
    def __init__(self):
        self._engines: Dict[str, object] = {}
        self._lock = threading.Lock()

    @staticmethod
    def available() -> Tuple[bool, str]:
        try:
            from winrt.windows.media.ocr import OcrEngine
            langs = [l.language_tag for l in OcrEngine.available_recognizer_languages]
            if not langs:
                return False, "Windows'ta OCR dil paketi yüklü değil (Ayarlar > Dil > dil ekle)."
            return True, ", ".join(langs)
        except Exception as exc:  # winrt paketi yok
            return False, f"Windows OCR kullanılamıyor: {exc}"

    def languages(self) -> List[str]:
        from winrt.windows.media.ocr import OcrEngine
        return [l.language_tag for l in OcrEngine.available_recognizer_languages]

    def _engine(self, source_lang: str):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        key = source_lang or "auto"
        with self._lock:
            engine = self._engines.get(key)
            if engine is None:
                match = next((t for t in self.languages() if source_lang and t.lower().startswith(source_lang.lower())), None)
                engine = OcrEngine.try_create_from_language(Language(match)) if match else None
                engine = engine or OcrEngine.try_create_from_user_profile_languages()
                self._engines[key] = engine
            return engine

    def recognize(self, shot: Shot, source_lang: str = "en") -> OcrResult:
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        started = time.perf_counter()
        scale = 1.0
        bgra, width, height = shot.bgra, shot.width, shot.height
        # Küçük yazılar büyütülünce çok daha iyi tanınır
        if height < 120 or width < 240:
            from PIL import Image
            scale = 2.0 if height >= 40 else 3.0
            img = Image.frombuffer("RGBA", (width, height), bgra, "raw", "RGBA", 0, 1)
            img = img.resize((int(width * scale), int(height * scale)), Image.BICUBIC)
            bgra, width, height = img.tobytes(), img.width, img.height
        engine = self._engine(source_lang)

        async def run():
            writer = DataWriter()
            writer.write_bytes(bgra)
            bitmap = SoftwareBitmap.create_copy_from_buffer(
                writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED)
            return await engine.recognize_async(bitmap)

        result = asyncio.run(run())
        lines = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            xs = [w.bounding_rect.x for w in words]
            ys = [w.bounding_rect.y for w in words]
            x2 = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
            y2 = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
            lines.append(OcrLine(line.text, min(xs) / scale, min(ys) / scale, (x2 - min(xs)) / scale, (y2 - min(ys)) / scale))
        lines = _drop_cut_lines(lines, shot.height)
        return OcrResult(lines, (time.perf_counter() - started) * 1000, engine.recognizer_language.language_tag)


def _drop_cut_lines(lines: List[OcrLine], height: float) -> List[OcrLine]:
    """
    Seçim kenarında yarısı kesilmiş satırları ve harf oranı çok düşük gürültüyü atar
    (ör. alanın altında arka plandaki başka bir yazının üst yarısı).
    """
    if not lines:
        return lines
    heights = sorted(l.h for l in lines)
    median = heights[len(heights) // 2]
    kept = []
    for line in lines:
        letters = sum(ch.isalpha() for ch in line.text)
        if letters < 2 or letters / max(1, len(line.text.replace(" ", ""))) < 0.5:
            continue
        touches_edge = line.y <= 2 or line.y + line.h >= height - 2
        if touches_edge and len(lines) > 1 and line.h < median * 0.75:
            continue
        kept.append(line)
    return kept


OCR = OcrEngineWrapper()


# ═══════════════════════════════════════════════════════════════════════════════
# Sabitlenmiş alan izleyici
# ═══════════════════════════════════════════════════════════════════════════════

CHANGE_THRESHOLD = 0.02  # değişen piksel yüzdesi (OCR ucuz: ~5 ms; aynı metin yeniden çevrilmez)
MAX_UNSTABLE_FRAMES = 3   # hareketli arka planda en fazla bu kadar kare beklenir


class RegionWatcher:
    """
    Ekranın bir bölgesini düzenli aralıkla yakalar; görüntü değişip sabitlenince
    OCR yapar ve metin değiştiyse `on_text(text, ocr_ms)` çağırır.
    """

    def __init__(self, rect: Tuple[int, int, int, int], source_lang: str,
                 on_text: Callable[[str, float], None], on_state: Callable[[str], None] = lambda s: None,
                 interval: float = 0.35):
        self.rect = rect
        self.source_lang = source_lang
        self.on_text = on_text
        self.on_state = on_state
        self.interval = max(0.15, interval)
        self.paused = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ocr-watch")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def _loop(self) -> None:
        last_sig: Optional[bytes] = None
        pending_sig: Optional[bytes] = None
        last_text = ""
        unstable = 0
        left, top, width, height = self.rect
        while not self._stop.is_set():
            if self.paused:
                time.sleep(0.2)
                continue
            try:
                shot = capture(left, top, width, height)
                sig = shot.signature()
                changed = signature_diff(sig, last_sig) > CHANGE_THRESHOLD
                if changed:
                    # Metin yazılırken (daktilo efekti) ekran sabitlenene kadar bekle; hareketli
                    # arka planda (video, animasyon) sabitlenmezse birkaç kare sonra yine de oku.
                    stable = pending_sig is not None and signature_diff(sig, pending_sig) <= CHANGE_THRESHOLD
                    unstable = unstable + 1 if pending_sig is not None else 0
                    if stable or unstable >= MAX_UNSTABLE_FRAMES:
                        result = OCR.recognize(shot, self.source_lang)
                        text = result.text.strip()
                        last_sig, pending_sig, unstable = sig, None, 0
                        if text and text != last_text:
                            last_text = text
                            self.on_text(text, result.ms)
                        elif not text:
                            self.on_state("empty")
                    else:
                        pending_sig = sig
            except Exception as exc:
                self.on_state(f"error:{exc}")
                time.sleep(1.0)
            self._stop.wait(self.interval)


# ═══════════════════════════════════════════════════════════════════════════════
# Sistem geneli kısayollar
# ═══════════════════════════════════════════════════════════════════════════════

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_APP_RELOAD = 0x8001
_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def parse_hotkey(text: str) -> Optional[Tuple[int, int]]:
    """'Ctrl+Shift+T' → (modifiers, virtual-key)."""
    if not text:
        return None
    mods, vk = 0, None
    for part in [p.strip().lower() for p in text.split("+") if p.strip()]:
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])
        elif part in ("space", "boşluk"):
            vk = 0x20
        elif part in ("`", "tilde"):
            vk = 0xC0
    if vk is None or not mods and not (0x70 <= vk <= 0x87):
        return None
    return mods, vk


class HotkeyManager:
    """RegisterHotKey tabanlı kısayollar; kendi mesaj döngüsü iş parçacığında çalışır."""

    def __init__(self, on_error: Callable[[str, str], None] = lambda name, key: None):
        self._bindings: Dict[str, Tuple[str, Callable[[], None]]] = {}
        self._on_error = on_error
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self.registered: Dict[str, bool] = {}

    def set(self, bindings: Dict[str, Tuple[str, Callable[[], None]]]) -> None:
        with self._lock:
            self._bindings = dict(bindings)
        if not self._thread_id:
            threading.Thread(target=self._loop, daemon=True, name="hotkeys").start()
            self._ready.wait(2)
        else:
            _user32.PostThreadMessageW(self._thread_id, WM_APP_RELOAD, 0, 0)

    def _register_all(self, ids: Dict[int, Callable[[], None]]) -> None:
        for hk_id in list(ids):
            _user32.UnregisterHotKey(None, hk_id)
        ids.clear()
        self.registered = {}
        with self._lock:
            bindings = dict(self._bindings)
        for index, (name, (combo, callback)) in enumerate(bindings.items(), start=1):
            parsed = parse_hotkey(combo)
            ok = bool(parsed) and bool(_user32.RegisterHotKey(None, index, parsed[0] | MOD_NOREPEAT, parsed[1]))
            self.registered[name] = ok
            if ok:
                ids[index] = callback
            elif combo:
                self._on_error(name, combo)

    def _loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ids: Dict[int, Callable[[], None]] = {}
        msg = wt.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # mesaj kuyruğunu oluştur
        self._register_all(ids)
        self._ready.set()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                threading.Thread(target=ids[msg.wParam], daemon=True).start()
            elif msg.message == WM_APP_RELOAD:
                self._register_all(ids)


# ═══════════════════════════════════════════════════════════════════════════════
# Pencere yardımcıları
# ═══════════════════════════════════════════════════════════════════════════════

WDA_EXCLUDEFROMCAPTURE = 0x11
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def find_window(title: str) -> int:
    return int(_user32.FindWindowW(None, title) or 0) if _user32 else 0


def set_window_icon(title: str, ico_path) -> bool:
    """Pencerenin başlık/görev çubuğu simgesini .ico dosyasından ayarlar (kaynak koddan çalışırken python simgesi yerine)."""
    hwnd = find_window(title)
    if not hwnd or not Path(ico_path).exists():
        return False
    load = _user32.LoadImageW
    load.restype = wt.HANDLE
    load.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
    send = _user32.SendMessageW
    send.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    for which, size in ((1, 256), (0, 32)):  # ICON_BIG, ICON_SMALL
        icon = load(None, str(ico_path), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if icon:
            send(wt.HWND(hwnd), 0x0080, which, icon)  # WM_SETICON
    return True


def own_window(title: str = "Capri") -> int:
    """Bu sürece ait ana pencere (aynı adlı başka Capri penceresi karışmaz)."""
    import os
    found: List[int] = []

    def callback(hwnd, _):
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            text = ctypes.create_unicode_buffer(64)
            _user32.GetWindowTextW(hwnd, text, 64)
            if text.value == title and _user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    _user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(callback), 0)
    return found[0] if found else 0


def attention(title: str = "Capri") -> bool:
    """Capri arka plandaysa görev çubuğu düğmesini yanıp söndürür ve sistem sesi çalar (Windows bildirimi gibi)."""
    hwnd = own_window(title)
    if not hwnd or _user32.GetForegroundWindow() == hwnd:
        return False

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("hwnd", wt.HWND), ("dwFlags", wt.DWORD), ("uCount", wt.UINT), ("dwTimeout", wt.DWORD)]

    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 0, 0)   # FLASHW_ALL | FLASHW_TIMERNOFG
    _user32.FlashWindowEx(ctypes.byref(info))
    _user32.MessageBeep(0x40)   # MB_ICONASTERISK
    return True


def prepare_overlay_window(title: str, exclude_from_capture: bool = True, rounded: bool = True) -> bool:
    """Kendi OCR pencerelerimiz ekran yakalamada görünmez → kendi yazımızı okumayız."""
    hwnd = find_window(title)
    if not hwnd:
        return False
    if exclude_from_capture:
        _user32.SetWindowDisplayAffinity(wt.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE)
    if rounded:
        pref = ctypes.c_int(DWMWCP_ROUND)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                                                       ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass
    return True


def cursor_pos() -> Tuple[int, int]:
    pt = wt.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
