"""
Köprü, optimizasyon ve uçtan uca testleri.

Hızlı testler her zaman çalışır. GPU / ağ / yerel oyun gerektirenler,
koşul sağlanmadığında otomatik atlanır (pytest -m "not slow" ile hepsi atlanır).
"""
import difflib
import json
import os
import random
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import app_modern
import backup_system
import engine_common
import providers
from engine_common import TranslationCache

APP_DIR = Path(__file__).resolve().parent.parent


# ── Bulanık önbellek: optimizasyon sonucu değiştirmemeli ─────────────────────
def _reference_fuzzy(data, key, threshold):
    if not data or not key:
        return None
    best, best_ratio, key_lower = None, 0.0, key.lower()
    if len(key) < 6:
        return data.get(key)
    for source, target in data.items():
        if not source or not target:
            continue
        ratio = difflib.SequenceMatcher(None, key_lower, source.lower()).ratio()
        if ratio > best_ratio and ratio >= threshold:
            best_ratio, best = ratio, target
    return best


def test_fuzzy_matches_reference_implementation():
    rng = random.Random(7)
    words = "the hero went to tavern and found an ancient crystal sword with magic power".split()
    data = {" ".join(rng.choice(words) for _ in range(rng.randint(2, 12))): f"tr{i}" for i in range(1500)}
    cache = TranslationCache(Path("unused.json"), data)
    keys = list(data)[:40] + [k + " now" for k in list(data)[40:80]] + ["completely different text here"]
    for threshold in (0.75, 0.85):
        for key in keys:
            assert cache.get_fuzzy(key, threshold) == _reference_fuzzy(data, key, threshold)


def test_translation_cache_shares_dict_and_preserves_file(tmp_path):
    path = tmp_path / "c.json"
    shared = {"Old line": "Eski satır"}
    cache = TranslationCache(path, shared)
    cache.set("New line", "Yeni satır")
    cache.save()
    assert shared["New line"] == "Yeni satır"  # çağıranın sözlüğüne yansır
    assert json.loads(path.read_text(encoding="utf-8")) == {"Old line": "Eski satır", "New line": "Yeni satır"}


# ── Önbellek adlandırma (eski çeviriler korunmalı) ───────────────────────────
def test_cache_path_compat_and_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(app_modern, "DATA_DIR", tmp_path)
    root = Path(r"C:\Games\Demo")
    base = engine_common.cache_file_for(root, tmp_path)
    assert app_modern.cache_path_for(root, "renpy", "gemini", "tr").name == f"{base.stem}_gemini.json"
    assert app_modern.cache_path_for(root, "renpy", "opus", "tr").name == f"{base.stem}.json"
    assert app_modern.cache_path_for(root, "rpgmaker", "nllb", "tr").name == f"{base.stem}_rpgm_nllb.json"
    legacy = base.parent / f"{base.stem}_unity_gemini.json.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"a": "b"}', encoding="utf-8")
    current = app_modern.cache_path_for(root, "unity", "gemini", "tr")
    assert current.name == f"{base.stem}_unity_gemini.json" and current.exists() and not legacy.exists()
    assert app_modern.cache_path_for(root, "unity", "gemini", "de").name.endswith("_unity_gemini_de.json")


# ── Yedek güvenliği ──────────────────────────────────────────────────────────
def test_zip_restore_blocks_path_traversal(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    archive = tmp_path / "b.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("data/ok.txt", "ok")
        zf.writestr("../evil.txt", "evil")
    entry = backup_system.BackupEntry(archive, "genel", "t", "t", 2, True, archive.stat().st_size)
    ok, count, _ = backup_system.restore_game_backup(entry, game, log=lambda s: None)
    assert ok and count == 1
    assert (game / "data" / "ok.txt").exists() and not (tmp_path / "evil.txt").exists()


def test_backup_roundtrip(tmp_path):
    root = tmp_path / "g"
    (root / "data").mkdir(parents=True)
    f = root / "data" / "Map001.json"
    f.write_text("orijinal", encoding="utf-8")
    backup_system.create_game_backup(root, "rpgmaker", [f], log=lambda s: None)
    f.write_text("çevrilmiş", encoding="utf-8")
    entry = backup_system.list_game_backups(root)[0]
    ok, count, _ = backup_system.restore_game_backup(entry, root, log=lambda s: None)
    assert ok and count == 1 and f.read_text(encoding="utf-8") == "orijinal"


# ── Sentetik RPG Maker MV oyunu ──────────────────────────────────────────────
def make_rpgmaker_game(root: Path) -> Path:
    data = root / "www" / "data"
    data.mkdir(parents=True)
    (data / "System.json").write_text(json.dumps({"gameTitle": "Demo Quest"}), encoding="utf-8")
    events = [None, {"pages": [{"list": [
        {"code": 101, "parameters": ["", 0, 0, 2, "Guard"]},
        {"code": 401, "parameters": ["Welcome to our village, traveler."]},
        {"code": 401, "parameters": ["The king is waiting for you."]},
        {"code": 0, "parameters": []},
    ]}]}]
    (data / "Map001.json").write_text(json.dumps({"events": events}), encoding="utf-8")
    (data / "MapInfos.json").write_text("[]", encoding="utf-8")
    return root


def test_detection_descends_into_wrapper_folder(tmp_path):
    make_rpgmaker_game(tmp_path / "wrapper" / "DemoQuest")
    kind, info = app_modern.detect_any_game_type(str(tmp_path / "wrapper"))
    assert kind == "rpgmaker"
    assert app_modern.game_title_of(kind, info, Path(info.root)) == "Demo Quest"


class FakeUi:
    def __init__(self):
        self.events = []

    def emit(self, event, payload=None):
        self.events.append((event, payload))

    def log(self, message):
        self.events.append(("log", str(message)))

    def progress(self, payload):
        self.events.append(("progress", payload))

    def clear_progress(self):
        pass


def make_bridge(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(app_modern, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_modern, "SETTINGS_FILE", tmp_path / "data" / "settings.json")
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(app_modern, "resolve_art", lambda *a, **k: {"appid": None, "name": None, "poster": None, "hero": None})
    bridge = app_modern.CapriBridge()
    bridge._ui = FakeUi()
    bridge._library = app_modern.ProjectLibrary(tmp_path / "data" / "projects.json")
    bridge._settings.update({"source": "en", "target": "tr", "backup": True, "nsfw": False, **settings})
    return bridge


def run_sync(bridge, method, *args):
    """_run_task iş parçacığını senkron çalıştırır."""
    started = []
    orig = threading.Thread

    class Inline:
        def __init__(self, target=None, daemon=None, name=None, **kw):
            self.target = target
            self.name = name

        def start(self):
            started.append(self.name)
            self.target()

    threading.Thread = Inline
    try:
        assert getattr(bridge, method)(*args) is True
    finally:
        threading.Thread = orig


def test_bridge_state_and_settings(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    state = bridge.get_state()
    assert state["version"] == app_modern.APP_VERSION
    assert {"gemini", "opus", "nllb", "ollama"} <= set(state["full_models"])
    assert bridge.update_settings({"target": "de", "bogus": 1})["target"] == "de"
    assert "bogus" not in bridge._settings


def test_ui_channel_batches_logs():
    channel = app_modern.UiChannel()
    calls = []

    class W:
        def run_js(self, script):
            calls.append(script)

    for i in range(500):
        channel._queue.put(("log", f"line {i}"))
    channel.progress({"done": 1, "total": 2})
    channel.window = W()
    time.sleep(0.35)
    assert 1 <= len(calls) <= 2
    payload = json.loads(calls[0][calls[0].index("(") + 1: -1])
    assert sum(len(ev["d"]) for ev in payload if ev["e"] == "log") == 500


# ── Ollama yolu (sahte sunucu ile) ───────────────────────────────────────────
class _FakeOllama(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = body["messages"][1]["content"].split("\n\n", 1)[1]
        parts = [p.strip() for p in text.split("§SEP§")]
        out = "\n§SEP§\n".join(f"TR({p})" for p in parts)
        data = json.dumps({"message": {"content": out}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_ollama():
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_renpy_translate_templates_ollama(tmp_path, fake_ollama):
    from engine_renpy import translate_templates
    tl = tmp_path / "tl" / "Turkish"
    tl.mkdir(parents=True)
    script = tl / "script.rpy"
    script.write_text(
        'translate Turkish start_1:\n\n    # e "Hello there, [mc]!"\n    e ""\n\n'
        'translate Turkish start_2:\n\n    # e "Where is the castle?"\n    e ""\n', encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    written = translate_templates(tl, APP_DIR / "model", cache_path, None, log=lambda s: None,
                                  model_kind="ollama", ollama_host=fake_ollama)
    out = script.read_text(encoding="utf-8")
    assert written == 2
    assert 'e "TR(Hello there, [mc]!)"' in out and 'e "TR(Where is the castle?)"' in out
    assert json.loads(cache_path.read_text(encoding="utf-8"))["Where is the castle?"] == "TR(Where is the castle?)"


def test_rpgmaker_end_to_end_with_fake_ollama(tmp_path, monkeypatch, fake_ollama):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    cfg = providers.ProviderConfig(ollama_host=fake_ollama)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: cfg)
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    run_sync(bridge, "translate")
    lines = json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"]
    assert lines[1]["parameters"][0] == "TR(Welcome to our village, traveler.)"
    assert bridge._library.get(game)["status"] == "translated"
    assert bridge.list_backups(), "çeviri öncesi yedek alınmalı"


# ── Unity önbellek hatası regresyonu (yerel model yerine sahte motor) ────────
def test_unity_offline_path_returns_new_translations(tmp_path, monkeypatch):
    import engine_unity

    class FakeEngine:
        def __init__(self, cache=None, **kw):
            self.cache = cache

        def translate_batch(self, sources, progress=None, tracker=None):
            out = {s: f"TR:{s}" for s in sources}
            for s, t in out.items():
                self.cache.set(s, t)
            self.cache.save()
            return out

    monkeypatch.setattr(engine_common, "TranslationEngine", FakeEngine)
    cache_path = tmp_path / "u.json"
    cache_path.write_text(json.dumps({"Old": "Eski"}), encoding="utf-8")
    result = engine_unity.translate_texts_unity(["Old", "New game"], cache_path, model_kind="opus", log=lambda s: None)
    assert result["New game"] == "TR:New game"
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["Old"] == "Eski" and saved["New game"] == "TR:New game"


# ── Yavaş / ortam gerektiren testler ─────────────────────────────────────────
def _cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.skipif(not providers.get_offline_model_status("opus")["is_ready"], reason="OPUS modeli yok")
def test_opus_preview_is_cached_between_calls():
    providers.release_offline_engines()
    ok1, text1, lat1 = providers.translate_single_text("Welcome to our tavern!", "opus", log=lambda s: None)
    ok2, text2, lat2 = providers.translate_single_text("The dragon is coming.", "opus", log=lambda s: None)
    assert ok1 and ok2 and text1 and text2
    assert lat2 < lat1, "ikinci önizleme modeli yeniden yüklememeli"
    providers.release_offline_engines()


@pytest.mark.slow
@pytest.mark.skipif(not (_cuda() and providers.get_offline_model_status("opus")["is_ready"]), reason="GPU/OPUS yok")
def test_rpgmaker_end_to_end_with_opus(tmp_path, monkeypatch):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="opus")
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    text = json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"][1]["parameters"][0]
    assert text and text != "Welcome to our village, traveler."


# Gerçek oyunlarda salt okunur algılama testi: CAPRI_REAL_GAMES="C:\Oyun1=unity;D:\Oyun2=renpy"
REAL_GAMES = [tuple(item.rsplit("=", 1)) for item in os.environ.get("CAPRI_REAL_GAMES", "").split(";") if "=" in item]     or [("", "atlandı")]


@pytest.mark.parametrize("path,expected", REAL_GAMES)
def test_real_game_detection_readonly(path, expected):
    if not path or not Path(path).is_dir():
        pytest.skip("CAPRI_REAL_GAMES tanımlı değil ya da oyun bu bilgisayarda yok")
    kind, _info = app_modern.detect_any_game_type(path)
    assert kind == expected


def test_web_assets_present():
    for name in ("index.html", "app.css", "app.js", "fonts/fonts.css"):
        assert (APP_DIR / "web" / name).is_file()
    html = (APP_DIR / "web" / "index.html").read_text(encoding="utf-8")
    assert "pywebview-drag-region" in html and "app.js" in html
