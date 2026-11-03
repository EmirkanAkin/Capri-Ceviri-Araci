"""
Ekran çevirisi (OCR), Gemini model zinciri, metin çevirici ve GPU optimizasyonu testleri.
"""
import json
import time

import pytest
from PIL import Image, ImageDraw, ImageFont

import app_modern
import ocr
import providers
from test_app import make_bridge


def text_shot(lines, size=(900, 260), font_size=28):
    img = Image.new("RGB", size, (18, 18, 22))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("segoeui.ttf", font_size)
    for y, line in lines:
        draw.text((24, y), line, fill=(240, 240, 240), font=font)
    r, g, b = img.split()
    bgra = Image.merge("RGBA", (b, g, r, Image.new("L", img.size, 255))).tobytes()
    return ocr.Shot(bgra, img.width, img.height)


ocr_ok = ocr.OCR.available()[0]


# ── Gemini: sabit model yerine tüm uygun modeller ────────────────────────────
def test_gemini_model_order_ranks_and_filters(monkeypatch):
    names = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-3.5-flash-lite",
             "gemma-4-31b-it", "gemini-3.8-flash-tts", "gemini-2.5-flash-image", "lyria-3.5"]
    ranked = sorted([n for n in names if not providers._GEMINI_EXCLUDE.search(n)], key=providers._gemini_rank)
    assert ranked[:2] == ["gemini-flash-lite-latest", "gemini-3.5-flash-lite"]
    assert ranked[-1] == "gemma-4-31b-it" and "gemini-3.8-flash-tts" not in ranked
    monkeypatch.setattr(providers, "gemini_models", lambda key="", refresh=False: ranked)
    order = providers.gemini_model_order("gemini-2.5-pro")
    assert order[0] == "gemini-2.5-pro" and order.count("gemini-2.5-pro") == 1
    assert providers.gemini_model_order("auto")[0] == "gemini-flash-lite-latest"


def test_gemini_preview_falls_back_to_next_model(monkeypatch):
    monkeypatch.setattr(providers, "gemini_model_order", lambda pref="auto", key="": ["dead-model", "good-model"])
    tried = []

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, json.dumps(body)

        def json(self):
            return self._body

    def fake_post(url, **kw):
        tried.append(url.split("/models/")[1].split(":")[0])
        if "dead-model" in url:
            return Resp(429, {"error": "quota"})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '["Merhaba"]'}]}}]})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    ok, text, _ = providers.translate_single_text("Hello", "gemini", cfg=providers.ProviderConfig(gemini_keys=["k"]))
    assert ok and text == "Merhaba" and tried == ["dead-model", "good-model"]


# ── OCR çekirdeği ────────────────────────────────────────────────────────────
@pytest.mark.skipif(not ocr_ok, reason="Windows OCR yok")
def test_ocr_reads_text_and_groups_paragraphs():
    shot = text_shot([(20, "Elena"), (70, "I never thought I would see you again after"),
                      (106, "everything that happened in the castle."), (200, "Save   Load   Quit")])
    result = ocr.OCR.recognize(shot, "en")
    paras = result.paragraphs()
    assert paras[0] == "Elena"
    assert "again after everything that happened" in paras[1]
    assert paras[-1].replace("  ", " ").startswith("Save Load")
    assert result.ms < 500


@pytest.mark.skipif(not ocr_ok, reason="Windows OCR yok")
def test_ocr_small_crop_is_upscaled():
    shot = text_shot([(10, "Quest complete!")], size=(400, 60), font_size=16)
    assert "Quest complete" in ocr.OCR.recognize(shot.crop(0, 0, 300, 50), "en").text


@pytest.mark.skipif(not ocr_ok, reason="Windows OCR yok")
def test_ocr_drops_line_cut_at_selection_edge():
    shot = text_shot([(20, "The door is locked."), (160, "Hidden text below the box")], size=(700, 240), font_size=30)
    cut = shot.crop(0, 0, 700, 178)  # ikinci satırın yalnızca üst kısmı alanda
    assert ocr.OCR.recognize(cut, "en").text == "The door is locked."


def test_hotkey_parsing():
    assert ocr.parse_hotkey("Ctrl+Shift+T") == (0x2 | 0x4, ord("T"))
    assert ocr.parse_hotkey("Alt+F2") == (0x1, 0x71)
    assert ocr.parse_hotkey("F9") == (0, 0x78)
    assert ocr.parse_hotkey("T") is None and ocr.parse_hotkey("") is None


def test_region_watcher_reports_only_changed_stable_text(monkeypatch):
    frames = [text_shot([(20, "First line of dialogue.")])] * 3 + [text_shot([(20, "Second line arrives now.")])] * 3
    frames += [frames[-1]] * 20
    it = iter(frames)
    monkeypatch.setattr(ocr, "capture", lambda *a: next(it))
    texts = []

    class FakeOCR:
        @staticmethod
        def recognize(shot, lang):
            return ocr.OcrResult([ocr.OcrLine("Second" if shot is frames[3] else "First", 0, 0, 10, 10)], 1.0, "tr")

    monkeypatch.setattr(ocr, "OCR", FakeOCR)
    watcher = ocr.RegionWatcher((0, 0, 10, 10), "en", lambda t, ms: texts.append(t), interval=0.15)
    watcher.interval = 0.01
    watcher.start()
    time.sleep(0.6)
    watcher.stop()
    assert texts == ["First", "Second"], "her yeni metin yalnızca bir kez bildirilmeli"


# ── Köprü: OCR akışı (sahte pencerelerle) ───────────────────────────────────
class FakeWindow:
    def __init__(self):
        self.js, self.visible, self.moves = [], False, []

    def evaluate_js(self, script):
        self.js.append(script)

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def move(self, x, y):
        self.moves.append((x, y))

    def resize(self, w, h):
        pass

    def minimize(self):
        pass

    def restore(self):
        pass


def payloads(win, prefix):
    return [json.loads(js[len(prefix) + 1:-1]) for js in win.js if js.startswith(prefix)]


@pytest.mark.skipif(not ocr_ok, reason="Windows OCR yok")
def test_bridge_ocr_select_translate_and_pin(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    windows = {k: FakeWindow() for k in ("select", "popup", "pin")}
    bridge.set_ocr_windows(windows, (1920, 1080), 1.0)
    calls = []

    def fake_translate(text, provider, **kw):
        calls.append(text)
        return True, "TR: " + text, 42

    monkeypatch.setattr(app_modern.prov, "translate_single_text", fake_translate)
    screen = text_shot([(40, "The door is locked.")], size=(1920, 1080), font_size=34)
    monkeypatch.setattr(ocr, "capture", lambda *a: screen)
    monkeypatch.setattr(ocr, "cursor_pos", lambda: (10, 10))
    monkeypatch.setattr(bridge, "_monitors", lambda: [{"phys": {"left": 0, "top": 0, "width": 1920, "height": 1080},
                                                       "x": 0, "y": 0, "w": 1920, "h": 1080, "scale": 1.0}])
    started = []
    monkeypatch.setattr(app_modern.threading, "Thread",
                        lambda target=None, args=(), daemon=None, name=None, **k: type("T", (), {"start": lambda self: (started.append(1), target(*args))})())

    assert bridge.ocr_start("once") is True
    assert windows["select"].visible and windows["select"].js[0].startswith("OCRSEL.open(")
    bridge.ocr_selected(0.0, 0.0, 0.4, 0.1)
    assert not windows["select"].visible and windows["popup"].visible
    states = payloads(windows["popup"], "OCRPOP.show")
    assert states[0]["state"] == "loading" and states[-1]["state"] == "ok"
    assert states[-1]["translation"] == "TR: The door is locked."
    # Aynı metin ikinci kez çevrilmez (önbellek)
    bridge.ocr_selected(0.0, 0.0, 0.4, 0.1)
    assert calls == ["The door is locked."]
    # Sabitle: izleyici başlar, pencere görünür
    monkeypatch.setattr(ocr, "RegionWatcher", lambda *a, **k: type("W", (), {"start": lambda s: None, "stop": lambda s: None, "running": True, "paused": False})())
    bridge.ocr_pin_last()
    assert windows["pin"].visible and not windows["popup"].visible
    bridge._pin_on_text("New subtitle line.", 5.0)
    assert payloads(windows["pin"], "OCRPIN.update")[-1]["translation"] == "TR: New subtitle line."
    bridge.ocr_pin_stop()
    assert not windows["pin"].visible


def test_translate_text_page(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    seen = {}

    def fake(text, provider_id, target_lang, source_lang, nsfw_mode, log, max_tokens):
        seen.update(provider=provider_id, target=target_lang, source=source_lang, max_tokens=max_tokens)
        return True, "Merhaba\nDünya", 10

    monkeypatch.setattr(app_modern.prov, "translate_single_text", fake)
    res = bridge.translate_text("Hello\nWorld", "auto", "tr", "deepl")
    assert res["ok"] and res["text"] == "Merhaba\nDünya" and seen["provider"] == "deepl" and seen["source"] == "auto"
    assert seen["max_tokens"] >= 2048
    assert not bridge.translate_text("Hello", "en", "de", "opus")["ok"], "OPUS yalnızca Türkçeye çevirir"


def test_hotkey_settings_reload(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    reloads = []
    bridge._hotkeys = object()
    monkeypatch.setattr(bridge, "_setup_hotkeys", lambda: reloads.append(1))
    bridge.update_settings({"ocr_hotkey": "Ctrl+Alt+Q"})
    bridge.update_settings({"ocr_hotkey": "Ctrl+Alt+Q"})
    assert reloads == [1] and bridge._settings["ocr_hotkey"] == "Ctrl+Alt+Q"


def _cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _cuda(), reason="CUDA yok")
def test_optimize_gpu_enables_tf32_and_reports(tmp_path, monkeypatch):
    import torch
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    res = bridge.optimize_gpu(preload=False, silent=True)
    assert res["ok"] and res["tflops"] > 1 and res["vram_total"] > 1
    assert torch.backends.cuda.matmul.allow_tf32 and torch.backends.cudnn.benchmark
