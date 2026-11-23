"""
Ekran çevirisini sesli okuma: çeviri pencereleri headless Edge'de açılır; Windows sesleri yerine sahte bir
speechSynthesis kullanılır (ses çıkmaz, pencere açılmaz, genel girdi gönderilmez).
"""
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from cdp_client import CDP
from test_ui_headless import EDGE, ROOT, _free_port

pytestmark = pytest.mark.skipif(EDGE is None, reason="Microsoft Edge bulunamadı")

STUB = r"""
(() => {
  window.__spoken = []; window.__settings = []; window.__errs = [];
  window.addEventListener("error", (e) => __errs.push(String(e.message)));
  const voices = __VOICES__;
  const synth = { getVoices: () => voices, speak: (u) => __spoken.push([u.text, u.lang]), cancel: () => {}, onvoiceschanged: null };
  Object.defineProperty(window, "speechSynthesis", { value: synth });
  window.SpeechSynthesisUtterance = function (text) { this.text = text; };
  const api = { ocr_resize: async () => null, ocr_hide: async () => null, ocr_pin_last: async () => null,
    ocr_pin_toggle: async () => null, ocr_pin_stop: async () => null, ui_dictionary: async () => null,
    update_settings: async (p) => { __settings.push(p); return p; } };
  window.pywebview = { api };
})();
"""


@pytest.fixture
def page(tmp_path):
    port = _free_port()
    profile = tmp_path / "edge"
    proc = subprocess.Popen([str(EDGE), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--no-first-run", "--disable-extensions", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    clients = []

    def open_page(name, voices):
        target = None
        for _ in range(150):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                target = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.1)
        assert target, "Edge başlatılamadı"
        c = CDP(target["webSocketDebuggerUrl"])
        clients.append(c)
        c.call("Page.enable")
        c.call("Page.addScriptToEvaluateOnNewDocument", {"source": STUB.replace("__VOICES__", json.dumps(voices))})
        c.call("Page.navigate", {"url": (ROOT / "web" / name).as_uri()})
        for _ in range(100):
            if c.js("!!window.CapriSpeech && (!!window.OCRPIN || !!window.OCRPOP)"):
                break
            time.sleep(0.05)
        return c

    try:
        yield open_page
    finally:
        for c in clients:
            try:
                c.call("Browser.close")
            except Exception:
                pass
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


VOICES = [{"name": "Microsoft Zira", "lang": "en-US", "localService": True},
          {"name": "Microsoft Emel Online (Natural)", "lang": "tr-TR", "localService": False},
          {"name": "Microsoft Tolga", "lang": "tr-TR", "localService": True}]


def test_pinned_translation_reads_each_new_line_once(page):
    c = page("ocr_pin.html", VOICES)
    c.js('OCRPIN.update({lang: "tr", speak: true, translation: "Alan izleniyor…", placeholder: true, state: "live"})')
    assert c.js("__spoken") == [], "yer tutucu metin okunmaz"
    c.js('OCRPIN.update({translation: "Merhaba.", state: "live"})')
    c.js('OCRPIN.update({translation: "Merhaba.", state: "live"})')
    c.js('OCRPIN.update({translation: "Hata metni", state: "error"})')
    c.js('OCRPIN.update({translation: "Nasılsın?", state: "live"})')
    assert c.js("__spoken") == [["Merhaba.", "tr-TR"], ["Nasılsın?", "tr-TR"]]
    c.js('document.querySelector("#speak").click()')
    assert c.js("__settings") == [{"ocr_speak": False}]
    c.js('OCRPIN.update({translation: "Sessiz.", state: "live"})')
    assert len(c.js("__spoken")) == 2, "kapatınca okumaz"
    assert c.js("__errs") == []


def test_popup_speaks_on_click_and_explains_a_missing_voice(page):
    c = page("ocr_popup.html", VOICES[:2])          # Türkçe yalnızca çevrimiçi ses: metni dışarı gönderir, kullanılmaz
    c.js('OCRPOP.show({state: "ok", translation: "Merhaba.", original: "Hello.", lang: "tr", meta: "OCR 20 ms"})')
    c.js('document.querySelector("#speak").click()')
    assert c.js("__spoken") == []
    assert "Windows sesi yok" in c.js('document.querySelector("#meta").textContent')
    c.js('OCRPOP.show({state: "ok", translation: "Hello again.", original: "x", lang: "en", speak: true})')
    assert c.js("__spoken") == [["Hello again.", "en-US"]], "ayar açıksa çeviri gelince okunur"
    assert c.js("__errs") == []
