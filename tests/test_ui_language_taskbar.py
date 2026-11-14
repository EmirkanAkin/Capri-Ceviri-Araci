"""Arayüz dilinin Python mesajlarını da kapsaması ve görev çubuğu ilerlemesi."""
import ast
import itertools
import os
import re
import time
from pathlib import Path

import pytest

import app_modern
from i18n_en import EN
from test_app import make_bridge, run_sync  # noqa: F401

SRC = Path(app_modern.__file__).parent


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kw: self.calls.append((name, *args))


def _task(bridge, fn):
    bridge.fake_task = lambda: bridge._run_task("Deneme", fn)
    run_sync(bridge, "fake_task")
    return [c[0] for c in bridge._taskbar.calls]


def test_taskbar_follows_task_lifecycle(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._taskbar = Recorder()

    def ok():
        bridge._stage("translate", "Çeviri")
        bridge._progress(5, 10)
    assert _task(bridge, ok) == ["busy", "busy", "value", "clear"]
    assert ("value", 5, 10) in bridge._taskbar.calls

    bridge._taskbar = Recorder()

    def cancelled():
        raise app_modern.TranslationCancelled()
    assert _task(bridge, cancelled) == ["busy", "paused"]

    bridge._taskbar = Recorder()

    def failed():
        raise RuntimeError("bozuk")
    assert _task(bridge, failed) == ["busy", "error"]


@pytest.mark.skipif(os.name != "nt", reason="Windows görev çubuğu")
def test_taskbar_progress_calls_windows_and_skips_repeats():
    import ctypes
    from ctypes import wintypes as wt
    import taskbar
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    hwnd = user32.CreateWindowExW(0, "STATIC", "capri-test", 0, 0, 0, 10, 10, None, None, None, None)   # gösterilmez
    assert hwnd
    try:
        bar = taskbar.TaskbarProgress(lambda: hwnd)
        bar.value(37, 100)
        for _ in range(50):
            if bar.results or not bar.available:
                break
            time.sleep(0.05)
        if not bar.available or not bar.results or (os.environ.get("CI") and bar.results != [0, 0]):
            pytest.skip("Bu makinede Windows görev çubuğu (Explorer) yok")
        assert bar.results == [0, 0], "SetProgressState + SetProgressValue S_OK döner"
        assert bar._last == (taskbar.NORMAL, 370)
        bar.value(37.01, 100)                    # aynı binde bir: yeniden gönderilmez
        assert bar._queue.qsize() == 0
        bar.error(clear_after=0.2)
        assert bar._last == (taskbar.ERROR, 370), "hata çubuğu takıldığı yerde kalır"
        time.sleep(0.6)
        assert bar._last == (taskbar.NONE, -1), "hata çubuğu bir süre sonra kaybolur"
        bar.close()
        bar._thread.join(2)
        assert not bar._thread.is_alive()
    finally:
        user32.DestroyWindow(hwnd)


def test_taskbar_without_window_is_silent():
    import taskbar
    bar = taskbar.TaskbarProgress(lambda: 0)
    bar.busy()
    bar.value(1, 2)
    bar.close()
    assert bar.results == []


def test_python_numbers_stay_turkish_and_cached_notes_do_not_depend_on_language(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, ui_language="en")
    bridge._ui_payload()
    assert app_modern._n(21529) == "21.529", "Python Türkçe yazar; sayıyı arayüz (i18n.js) dile göre biçimler"
    import i18n
    assert i18n.translate_text("2.575 satır oyuna yazıldı", EN) == "2,575 lines written to the game"
    assert i18n.translate_text("Sürüm 1.0.5", {"Sürüm {0}": "Version {0}"}) == "Version 1.0.5", "sürüm numarası sayı değildir"


def test_ocr_windows_receive_the_same_dictionary(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, ui_language="en")
    bridge._ui_payload()
    got = bridge.ui_dictionary()
    assert got["language"] == "en" and got["dict"]["Kopyala"] == "Copy"
    assert bridge._tr("Alan izleniyor…") == "Watching the area…"
    for page in ("ocr_pin.html", "ocr_popup.html", "ocr_select.html"):
        html = (SRC.parent / "web" / page).read_text(encoding="utf-8")
        assert '<script src="i18n.js"></script>' in html and "ui_dictionary" in html, page


# ── Python'dan ekrana giden her mesajın İngilizce karşılığı olmalı ────────────────────────────────────────────
UI_CALLS = {"_toast", "_notify", "_status", "_ask", "_notice", "UserError", "_task_failed"}
UI_KEYS = {"text", "title", "hint", "summary", "meta", "font", "engine_detail", "translation", "label"}
_TR = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(ve|bir|bu|ile|için|yok|var|değil|oyun|Oyun|satır|dosya|Uyumlu|Eksik)\b")


def _variants(node):
    """İfadenin ekranda alabileceği metin kalıpları; değişken kısımlar {n}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [[node.value]]
    if isinstance(node, ast.JoinedStr):
        return [[v.value if isinstance(v, ast.Constant) else None for v in node.values]]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _variants(node.left) or [[None]], _variants(node.right) or [[None]]
        return [a + b for a, b in itertools.islice(itertools.product(left, right), 8)]
    if isinstance(node, ast.IfExp):
        return ((_variants(node.body) or [[None]]) + (_variants(node.orelse) or [[None]]))[:8]
    return None


def _template(parts):
    out, n = [], 0
    for p in parts:
        if p is None:
            out.append("{%d}" % n)
            n += 1
        else:
            out.append(p)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _known(text, shapes):
    if text in shapes or not _TR.search(text):
        return True
    # " · " ile birleşen metin arayüzde (i18n.js) en uzun eşleşen parçalara bölünerek çevrilir
    parts = text.split(" · ")
    if len(parts) < 2:
        return False
    i = 0
    while i < len(parts):
        for j in range(len(parts), i, -1):
            if j - i < len(parts) and _known(" · ".join(parts[i:j]), shapes):
                i = j
                break
        else:
            return False
    return True


def _ui_strings(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        exprs = []
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in UI_CALLS:
                exprs += node.args[:2] + [k.value for k in node.keywords if k.arg in ("title", "text", "hint")]
        if isinstance(node, ast.Dict):
            exprs += [v for k, v in zip(node.keys, node.values)
                      if isinstance(k, ast.Constant) and k.value in UI_KEYS]
        for expr in exprs:
            for parts in _variants(expr) or []:
                text = _template(parts)
                if text and not re.fullmatch(r"(\{\d+\}\s*)+", text):
                    found.append((node.lineno, text))
    return found


def test_every_python_ui_message_has_an_english_translation():
    shapes = {re.sub(r"\s+", " ", re.sub(r"\{\d+\}", "{}", k)).strip() for k in EN}
    missing = []
    for lineno, text in _ui_strings(SRC / "app_modern.py") + [(0, t) for t in app_modern.WHATS_NEW]:
        shape = re.sub(r"\{\d+\}", "{}", text)
        if not _known(shape, shapes):
            missing.append(f"app_modern.py:{lineno}: {text}")
    assert not missing, "İngilizce sözlükte (i18n_en.py) karşılığı yok:\n" + "\n".join(sorted(set(missing)))


def test_notification_text_is_translated_like_the_interface():
    import i18n
    t = lambda s: i18n.translate_text(s, EN)  # noqa: E731
    assert t("HentaiKanojo · 2.575 satır oyuna yazıldı · 2 satır incelenmeli.") == \
        "HentaiKanojo · 2,575 lines written to the game · 2 lines need review.", "sayı İngilizce biçime geçer"
    assert t("Bulut · en hızlı · Hazır · 3 anahtar") == "Cloud · fastest · Ready · 3 keys", "kısa kalıp bütün satırı yutmaz"
    assert t("Analiz ediliyor…") == "Analyzing…"
    assert t("Bilinmeyen bir metin") == "Bilinmeyen bir metin"
    assert t("Çeviri tamamlandı") == "Translation completed"
