"""
Arayüz regresyon testi: web/index.html headless Edge'de, gerçek köprünün (CapriBridge) yanıtlarıyla açılır.
Bütün sayfalar gezilir; JavaScript hatası olmamalı, sağlayıcılar iki grupta olmalı ve arayüz İngilizce seçildiğinde
ekranda çevrilmemiş (Türkçe harfli) metin kalmamalı. Edge yoksa atlanır. Pencere açılmaz, genel girdi gönderilmez.
"""
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

import app_modern
from cdp_client import CDP
from i18n_en import EN
from test_app import make_bridge

ROOT = Path(__file__).resolve().parent.parent
EDGE = next((p for p in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")) if p.exists()), None)
pytestmark = pytest.mark.skipif(EDGE is None, reason="Microsoft Edge bulunamadı")

STUB = r"""
(() => {
  const REC = __REC__;
  window.__errs = [];
  window.addEventListener("error", (e) => __errs.push(String(e.message)));
  window.addEventListener("unhandledrejection", (e) => __errs.push(String(e.reason)));
  const api = new Proxy({}, { get: (_, name) => async (...args) =>
    (name in REC ? JSON.parse(JSON.stringify(REC[name])) : null) });
  window.pywebview = { api };
})();
"""

LEAKS = r"""
(() => {
  const SKIP = "textarea, input, code, pre, .cell-src, .cell-tr, .selectable, #logBox, #txOutput, [data-no-i18n], script, style, .demo";
  const out = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const el = n.parentElement;
    if (!el || el.closest(SKIP)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const t = n.textContent.replace(/\s+/g, " ").trim();
    if (/[çğıöşüÇĞİÖŞÜ]/.test(t)) out.add(t);
  }
  return [...out];
})()
"""

PAGES = ["studio", "library", "editor", "backups", "glossary", "json", "providers", "models", "translator", "ocr", "guide"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    import secrets_store
    monkeypatch.setattr(secrets_store, "PREFIX", "CapriTest/")      # kullanıcının gerçek anahtarları okunmaz
    bridge = make_bridge(tmp_path, monkeypatch)
    rec = {"get_state": bridge.get_state(), "model_status": bridge.model_status(), "ocr_status": bridge.ocr_status(),
           "glossary_load": bridge.glossary_load("general"), "list_backups": [], "editor_sources": []}
    port = _free_port()
    profile = tmp_path / "edge"
    proc = subprocess.Popen([str(EDGE), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--window-size=1440,900", "--no-first-run", "--disable-extensions", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(150):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                page = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.1)
        assert page, "Edge başlatılamadı"
        c = CDP(page["webSocketDebuggerUrl"])
        c.call("Page.enable")
        c.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        c.call("Page.addScriptToEvaluateOnNewDocument",
               {"source": STUB.replace("__REC__", json.dumps(rec, ensure_ascii=False, default=str))})
        c.call("Page.navigate", {"url": (ROOT / "web" / "index.html").as_uri()})
        for _ in range(150):
            if c.js("typeof S !== 'undefined' && !!S.state && !!S.ui"):
                break
            time.sleep(0.1)
        c.js("typeof stopDemo === 'function' && stopDemo()")
        yield c
    finally:
        try:
            c.call("Browser.close")
        except Exception:
            pass
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _visit_all(c) -> None:
    for page in PAGES:
        c.js(f"document.querySelector('[data-page=\"{page}\"]').click()")
        time.sleep(0.25)
        if page == "providers":
            for prov in c.js("[...document.querySelectorAll('[data-prov]')].map(e => e.dataset.prov)"):
                c.js(f"document.querySelector('[data-prov=\"{prov}\"]').click()")


def test_every_page_renders_without_javascript_errors(ui):
    _visit_all(ui)
    assert ui.js("__errs") == []
    ui.js("document.querySelector('[data-page=\"providers\"]').click()")
    assert ui.js("[...document.querySelectorAll('.prov-group')].map(e => e.textContent)") == ["Bulut", "Bilgisayarında"]
    assert "Ekran (OCR)" in ui.js("document.querySelector('#heroMeta') ? document.querySelector('#heroMeta').textContent : ''") \
        or ui.js("S.slides.length") > 0


def test_english_interface_leaves_no_turkish_text_on_screen(ui):
    ui.js(f"I18N.set('en', {json.dumps(EN, ensure_ascii=False)})")
    leaks = {}
    for page in PAGES:
        ui.js(f"document.querySelector('[data-page=\"{page}\"]').click()")
        time.sleep(0.3)
        for y in (0, 900, 1800, 2700):
            ui.js(f"document.querySelector('#scroll').scrollTop = {y}")
            time.sleep(0.05)
            for text in ui.js(LEAKS) or []:
                leaks.setdefault(text, page)
    assert not leaks, "İngilizce arayüzde çevrilmemiş metin: " + "; ".join(f"{p}: {t[:80]}" for t, p in leaks.items())
    assert ui.js("__errs") == []


def test_ctrl_s_saves_editor_changes(ui):
    ui.js("document.querySelector('[data-page=\"editor\"]').click()")
    time.sleep(0.3)
    ui.js("""window.__calls = []; call = async (name, ...args) => { __calls.push([name, ...args]); return {ok: true, msg: "ok"}; };
             S.editor = {model: "gemini", dirty: {"Hello": "Merhaba"}, items: [], offset: 0};
             document.querySelector('#editorBody').insertAdjacentHTML('beforeend', '<button id="edSave">Kaydet</button>');""")
    ui.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 's', ctrlKey: true, bubbles: true}))")
    time.sleep(0.3)
    assert ["editor_save", "gemini", {"Hello": "Merhaba"}] in ui.js("__calls")
    ui.js("__calls.length = 0; S.editor.dirty = {}")
    ui.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 's', ctrlKey: true, bubbles: true}))")
    time.sleep(0.2)
    assert not [c for c in ui.js("__calls") if c[0] == "editor_save"], "değişiklik yoksa kaydetmez"
