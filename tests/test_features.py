"""
Özellik testleri: bulut çevirisi, iptal/devam, paralel Gemini,
çeviri editörü, inceleme raporu, sözlük editörü, JSON çevirici ve yama paylaşımı.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import app_modern
import providers
from test_app import fake_ollama, make_bridge, make_rpgmaker_game, run_sync  # noqa: F401 (fixture)


def notices(bridge):
    return [d for e, d in bridge._ui.events if e == "notify"]


def map_lines(game):
    return json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"]


class _FakeCloud(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "text" in body:  # DeepL
            out = {"translations": [{"text": "TR " + t} for t in body["text"]]}
        else:  # OpenAI
            items = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
            out = {"choices": [{"message": {"content": json.dumps({"translations": [f"TR {x}" for x in items]})}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_cloud(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeCloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(providers, "OPENAI_URL", base + "/openai")
    monkeypatch.setattr(providers, "DEEPL_URLS", {"free": base + "/deepl", "pro": base + "/deepl"})
    yield base
    server.shutdown()


def test_cloud_model_without_key_is_reported(tmp_path, monkeypatch):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="deepl")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(deepl_key=""))
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    assert any("API anahtarı yok" in n["text"] for n in notices(bridge))
    assert map_lines(game)[1]["parameters"][0].startswith("Welcome")


def test_cloud_translation_keeps_tags_and_caches(tmp_path, fake_cloud):
    cfg = providers.ProviderConfig(openai_key="k", deepl_key="k:fx")
    for provider in ("openai", "deepl"):
        cache, failed = {}, set()
        path = tmp_path / f"{provider}.json"
        providers.translate_with_cloud(provider, ["Hello {0}", "Open the [door]"], cache, path, cfg,
                                       log=lambda s: None, failed_out=failed)
        assert cache["Hello {0}"] == "TR Hello {0}" and not failed
        assert json.loads(path.read_text(encoding="utf-8"))["Open the [door]"] == "TR Open the [door]"
    assert providers.placeholders_valid("Hi {0} \\C[1]", "Selam \\C[1] {0}")
    assert not providers.placeholders_valid("Hi {0}", "Selam")


def test_rpgmaker_end_to_end_with_openai(tmp_path, monkeypatch, fake_cloud):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="openai")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(openai_key="k"))
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    assert map_lines(game)[2]["parameters"][0] == "TR The king is waiting for you."


def test_cancel_keeps_progress_and_marks_paused(tmp_path, monkeypatch, fake_cloud):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="openai")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(openai_key="k"))
    bridge._select_game(str(game))
    original_progress = bridge._progress

    def progress_then_cancel(done, total):
        bridge._cancel.set()  # ilk parti bitince kullanıcı "Durdur"a bastı
        original_progress(done, total)

    bridge._progress = progress_then_cancel
    run_sync(bridge, "translate")
    assert bridge._library.get(game)["status"] == "paused"
    assert json.loads(bridge._cache_path().read_text(encoding="utf-8")), "iptalde çeviriler önbellekte kalmalı"
    assert any(n["title"] == "Çeviri durduruldu" for n in notices(bridge))
    assert map_lines(game)[2]["parameters"][0] == "The king is waiting for you.", "iptalde oyuna yarım yazılmamalı"


def test_gemini_parallel_workers_use_all_keys(tmp_path, monkeypatch):
    import engine_renpy
    used = []

    class Resp:
        def __init__(self, items):
            text = json.dumps([f"TR {x}" for x in items])
            self.data = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.data

    def fake_urlopen(req, timeout=0):
        used.append(req.headers.get("X-goog-api-key"))
        prompt = json.loads(req.data)["contents"][0]["parts"][0]["text"]
        return Resp(json.loads(prompt[prompt.index("\n[") + 1:]))

    monkeypatch.setattr(engine_renpy.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(engine_renpy, "load_gemini_api_keys", lambda: ["key-a", "key-b", "key-c"])
    monkeypatch.setattr(engine_renpy.time, "sleep", lambda s: None)
    missing = [f"Line number {i}" for i in range(400)]
    cache = {}
    engine_renpy.translate_with_gemini(missing, cache, tmp_path / "g.json", "key-a", log=lambda s: None)
    assert all(cache[m] == f"TR {m}" for m in missing)
    assert set(used) == {"key-a", "key-b", "key-c"}


def test_editor_save_and_apply_rpgmaker(tmp_path, monkeypatch, fake_ollama):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    src = "The king is waiting for you."
    data = bridge.editor_load("ollama", query="king")
    assert data["total"] == 1 and data["items"][0]["tr"] == f"TR({src})"
    assert not bridge.editor_save("ollama", {src: "Kral bekliyor {0}"})["ok"], "fazla etiket reddedilmeli"
    assert bridge.editor_save("ollama", {src: "Kral seni bekliyor."})["ok"]
    run_sync(bridge, "editor_apply", "ollama")
    lines = map_lines(game)
    assert lines[2]["parameters"][0] == "Kral seni bekliyor."
    assert lines[1]["parameters"][0] == "TR(Welcome to our village, traveler.)"


def test_review_report_lists_failed_lines(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    cache_path = bridge._cache_path()
    app_modern._write_json(cache_path, {"Good line": "İyi satır"})
    bridge._record_review(cache_path, {"Broken line"})
    data = bridge.editor_load("gemini", only_review=True)
    assert [i["src"] for i in data["items"]] == ["Broken line"]
    assert bridge.editor_sources()[0]["review"] == 1
    bridge.editor_save("gemini", {"Broken line": "Bozuk satır"})
    assert bridge.editor_sources()[0]["review"] == 0


def test_glossary_roundtrip_keeps_meta(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(app_modern, "GLOSSARY_DIR", tmp_path)
    (tmp_path / "glossary_nsfw.json").write_text(json.dumps({"_aciklama": "not", "a": "b"}), encoding="utf-8")
    assert bridge.glossary_load("nsfw") == [["a", "b"]]
    assert bridge.glossary_save("nsfw", [["x", "y"], ["", "boş"]])["count"] == 1
    assert json.loads((tmp_path / "glossary_nsfw.json").read_text(encoding="utf-8")) == {"_aciklama": "not", "x": "y"}


def test_json_translator_page(tmp_path, monkeypatch, fake_ollama):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    src = tmp_path / "ui_strings.json"
    src.write_text(json.dumps({"menu": {"start": "Start the adventure", "quit": "Quit game"}, "id": "btn_01"}), encoding="utf-8")
    run_sync(bridge, "json_translate", str(src), "")
    out = json.loads((tmp_path / "ui_strings_tr.json").read_text(encoding="utf-8"))
    assert out["menu"]["start"] == "TR(Start the adventure)"
    assert json.loads(src.read_text(encoding="utf-8"))["menu"]["start"] == "Start the adventure"


def test_patch_export_import(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    app_modern._write_json(bridge._cache_path(), {"Hello": "Merhaba"})
    target = tmp_path / "demo.capripatch"

    class Win:
        def create_file_dialog(self, kind, **kw):
            return str(target) if kw.get("save_filename") else [str(target)]

    bridge._window = Win()
    assert bridge.export_patch() == str(target)
    app_modern._write_json(bridge._cache_path(), {})
    assert bridge.import_patch() is True
    assert json.loads(bridge._cache_path().read_text(encoding="utf-8")) == {"Hello": "Merhaba"}


def test_open_project_does_not_reanalyze(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "analyze")
    calls = []
    monkeypatch.setattr(bridge, "_run_task", lambda *a: calls.append(a) or True)
    assert bridge.analyze() is True and not calls, "analiz sonucu varken tekrar analiz edilmemeli"
    bridge.analyze(True)
    assert len(calls) == 1
