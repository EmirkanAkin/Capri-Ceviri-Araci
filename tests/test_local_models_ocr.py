"""Yerel çeviri modelleri (TranslateGemma, MiLMMT), Latin dışı kaynak metinler, hazır arayüz sözlükleri ve gündüz
altyazısı okuma."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import app_modern
import engine_common
import providers
from test_app import _FakeOllama, fake_ollama, make_bridge, run_sync  # noqa: F401


# ── Ollama: çeviri modeli aileleri ───────────────────────────────────────────
def test_model_family_and_recommendation():
    assert engine_common.ollama_family("translategemma:12b") == "translategemma"
    assert engine_common.ollama_family("hf.co/mradermacher/MiLMMT-46-4B-v1.0-GGUF:Q4_K_M") == "milmmt"
    assert engine_common.ollama_family("qwen2.5:7b") == "chat"
    assert engine_common.recommended_ollama_model(16) == "translategemma:12b"
    assert engine_common.recommended_ollama_model(12) == engine_common.recommended_ollama_model(None) == "translategemma:4b",         "12 GB kartta 12B işlemciye taşar (ölçüldü)"
    assert engine_common.ollama_host("http://localhost:11434/") == "http://127.0.0.1:11434", "IPv6 gecikmesi yok"
    assert engine_common.ollama_context(40) == engine_common.ollama_context(900) == 4096, "num_ctx sabit: model yeniden yüklenmez"
    assert providers.ProviderConfig().ollama_model == "translategemma:4b", "varsayılan artık çeviri modeli"


def test_official_prompt_formats():
    tg = engine_common.translategemma_prompt("Hi.", "auto", "zh-CN")
    assert tg.startswith("You are a professional English (en) to Simplified Chinese (zh-Hans) translator.")
    assert tg.endswith("into Simplified Chinese:\n\n\nHi."), "metin üç satır sonundan sonra gelir (ollama.com/library/translategemma)"
    assert engine_common.milmmt_prompt("Hi.", "en", "tr") == "Translate this from English to Turkish:\nEnglish: Hi.\nTurkish:"


def test_model_does_not_add_spaces_inside_tags():
    from engine_common import tidy_mask_spacing
    assert tidy_mask_spacing("XPH000XIs this real?XPH001X", "XPH000X Gerçekten mi? XPH001X") == "XPH000XGerçekten mi?XPH001X"
    assert tidy_mask_spacing("Hey XPH000X, awake", "Hey XPH000X, uyandın") == "Hey XPH000X, uyandın"


def test_translategemma_translates_consecutive_lines_as_one_block(fake_ollama):
    _FakeOllama.requests.clear()
    engine = engine_common.OllamaTranslationEngine(model_name="translategemma:4b", host=fake_ollama, log=lambda s: None)
    out = engine.translate_batch(["Hello.", "Where is the castle?", "Run!"])
    assert out == {"Hello.": "TR(Hello.)", "Where is the castle?": "TR(Where is the castle?)", "Run!": "TR(Run!)"}
    assert _FakeOllama.requests == [("/api/chat", "translategemma:4b")], "üç satır tek istekte (bağlam)"


def test_translategemma_falls_back_to_single_lines_when_block_misaligns(monkeypatch):
    calls = []

    def fake(host, model, text, source, target, temperature=0.1, timeout=120):
        calls.append(text)
        return "tek satır döndü" if "\n" in text else f"TR({text})"

    monkeypatch.setattr(engine_common, "ollama_translate_one", fake)
    engine = engine_common.OllamaTranslationEngine(model_name="translategemma:4b", log=lambda s: None)
    assert engine._api_batch(["A one.", "B two."]) == ["TR(A one.)", "TR(B two.)"]
    assert calls == ["A one.\nB two.", "A one.", "B two."]


def test_milmmt_uses_raw_prompt_line_by_line(fake_ollama):
    _FakeOllama.requests.clear()
    model = "hf.co/mradermacher/MiLMMT-46-4B-v1.0-GGUF:Q4_K_M"
    engine = engine_common.OllamaTranslationEngine(model_name=model, host=fake_ollama, log=lambda s: None)
    assert engine.translate_batch(["Hello.", "Bye."]) == {"Hello.": "TR(Hello.)", "Bye.": "TR(Bye.)"}
    assert _FakeOllama.requests == [("/api/generate", model)] * 2


def test_screen_translation_with_ollama_uses_model_format(fake_ollama):
    cfg = providers.ProviderConfig(ollama_host=fake_ollama, ollama_model="translategemma:4b")
    ok, text, _ms = providers.translate_single_text("The door is locked.", "ollama", "tr", "en", cfg=cfg)
    assert ok and text == "TR(The door is locked.)"


def test_translation_models_cannot_be_quality_editors():
    cfg = providers.ProviderConfig(ollama_model="translategemma:4b")
    with pytest.raises(RuntimeError, match="yalnızca çeviri"):
        providers.llm_complete("ollama", "sys", "user", cfg)


class _Pull(BaseHTTPRequestHandler):
    installed = ["translategemma:4b"]

    def do_GET(self):
        self._send({"models": [{"name": n} for n in _Pull.installed]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.end_headers()
        for done in (0, 50, 100):
            self.wfile.write((json.dumps({"status": "pulling", "total": 100 << 20, "completed": done << 20}) + "\n").encode())
        _Pull.installed.append(body["model"])
        self.wfile.write(b'{"status": "success"}\n')

    def _send(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def test_ollama_models_lists_presets_and_pull_downloads_with_progress(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Pull)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        saved = {}
        cfg = providers.ProviderConfig(ollama_host=f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: cfg)
        monkeypatch.setattr(app_modern.prov, "save_provider_config", lambda c: saved.update(model=c.ollama_model))
        bridge = make_bridge(tmp_path, monkeypatch)
        bridge._gpu = {"vram_gb": 16.0}
        info = bridge.ollama_models()
        assert info["running"] and info["recommended"] == "translategemma:12b"
        state = {p["model"]: p["installed"] for p in info["presets"]}
        assert state["translategemma:4b"] and not state["translategemma:12b"]
        run_sync(bridge, "ollama_pull", "translategemma:12b")
        progress = [e[1] for e in bridge._ui.events if e[0] == "progress"]
        assert progress and progress[-1]["done"] == 100 and progress[-1]["total"] == 100
        assert saved["model"] == "translategemma:12b", "indirilen model seçilir"
    finally:
        server.shutdown()


# ── Latin dışı kaynak metinler atlanmaz ──────────────────────────────────────
def test_renpy_cjk_only_lines_are_sent_to_the_translator(tmp_path, fake_ollama):
    from engine_renpy import translate_templates
    tl = tmp_path / "tl" / "Turkish"
    tl.mkdir(parents=True)
    script = tl / "script.rpy"
    script.write_text('translate Turkish a_1:\n\n    # e "おはよう、先輩！"\n    e ""\n', encoding="utf-8")
    written = translate_templates(tl, tmp_path, tmp_path / "c.json", None, log=lambda s: None,
                                  model_kind="ollama", ollama_host=fake_ollama, source_lang="ja")
    assert written == 1 and 'e "TR(おはよう、先輩！)"' in script.read_text(encoding="utf-8")


def test_vxace_japanese_text_is_extracted(tmp_path):
    import rgss_marshal as rm
    import engine_rpgmaker as er
    S = rm.Sym
    s = lambda t: rm.RString(t.encode(), ivars=[(rm.Sym(b"E"), True)])  # noqa: E731
    actor = rm.RObject(S(b"RPG::Actor"), [(S(b"@name"), s("勇者")), (S(b"@nickname"), s("")),
                                         (S(b"@description"), s("村の若者。"))])
    data = tmp_path / "Data"
    data.mkdir()
    (data / "Actors.rvdata2").write_bytes(rm.dumps(rm.RArray([None, actor])))
    texts = {t.original for t in er.extract_texts_vxace(data, log=lambda s: None)}
    assert {"勇者", "村の若者。"} <= texts


# ── Hazır arayüz sözlükleri ──────────────────────────────────────────────────
def test_bundled_dictionary_is_used_and_user_entries_win(tmp_path):
    import i18n
    from i18n_en import EN
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    bundled.mkdir()
    full = {k: f"DE {v}" for k, v in EN.items()}
    (bundled / "de.json").write_text(json.dumps(full), encoding="utf-8")
    d = i18n.Dictionaries(user, bundled)
    assert d.get("de")["Kaydet"] == "DE Save" and d.missing("de") == 0, "anahtarsız kullanıcı da hazır dili kullanır"
    user.mkdir()
    (user / "de.json").write_text(json.dumps({"Kaydet": "Speichern"}), encoding="utf-8")
    assert d.get("de")["Kaydet"] == "Speichern"
    partial = dict(list(full.items())[:-3])
    (bundled / "fr.json").write_text(json.dumps(partial), encoding="utf-8")
    assert d.get("fr") is None and d.missing("fr") == 3, "yeni sürüm metinleri eksikse yalnızca onlar üretilir"
    result, failed = d.build("fr", lambda items: {x: f"FR {x}" for x in items})
    assert failed == 0 and len(result) == len(EN) and result["Kaydet"] == "DE Save"


def test_shipped_ui_dictionaries_are_complete_and_keep_placeholders():
    import i18n
    from i18n_en import EN
    from paths import RES_DIR
    folder = RES_DIR / "data" / "ui_lang"
    files = sorted(folder.glob("*.json"))
    assert files, "pakette hazır sözlük yok"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        bad = [k for k, v in data.items() if k in EN and not i18n.placeholders_ok(k, v)]
        assert not bad, f"{path.name}: yer tutucusu bozuk {bad[:3]}"
        assert len(set(EN) - set(data)) <= len(EN) * 0.05, f"{path.name}: eksik metin çok"


# ── Gündüz altyazısı ─────────────────────────────────────────────────────────
ocr_ok = __import__("ocr").OCR.available()[0]


@pytest.mark.skipif(not ocr_ok, reason="Windows OCR yok")
def test_outlined_subtitle_on_bright_sky_is_read():
    import difflib
    import ocr
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1280, 140
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        v = int(200 + 55 * y / h)
        d.line((0, y, w, y), fill=(v - 30, v - 10, v))
    text = "Lucia, get in the car. Now!"
    font = ImageFont.truetype("segoeuib.ttf", 38)
    d.text(((w - d.textlength(text, font=font)) / 2, 40), text, font=font, fill=(255, 214, 64),
           stroke_width=3, stroke_fill=(0, 0, 0))
    r, g, b = img.split()
    shot = ocr.Shot(Image.merge("RGBA", (b, g, r, Image.new("L", img.size, 255))).tobytes(), w, h)
    got = " ".join(line.text for line in ocr.OCR.recognize(shot, "en").lines)
    assert difflib.SequenceMatcher(None, text.lower(), got.lower()).ratio() > 0.85, got


def test_app_uses_shipped_dictionary_without_a_cloud_key(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, ui_language="de")
    monkeypatch.setattr(bridge, "_ui_translator", lambda code: None)     # bulut anahtarı yok
    payload = bridge._ui_payload()
    assert payload["pending"] is False, "hazır gelen dil için bulut anahtarı gerekmez"
    assert payload["dict"]["Kaydet"] and payload["dict"]["Kaydet"] != "Save"
