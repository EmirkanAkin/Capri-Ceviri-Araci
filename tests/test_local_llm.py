"""Dahili yerel modeller (llama.cpp, Ollama'sız): katalog, doğrulamalı indirme, sunucu yaşam döngüsü, motor bağlantıları."""
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

import app_modern
import engine_renpy
import local_llm
import providers
from test_app import make_bridge, make_rpgmaker_game, run_sync  # noqa: F401

FAKE = Path(__file__).with_name("fake_llama_server.py")


# ── Katalog ──────────────────────────────────────────────────────────────────
def test_catalog_is_pinned_and_verifiable():
    for spec in local_llm.CATALOG:
        assert re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) and re.fullmatch(r"[0-9a-f]{40}", spec["rev"]), spec["id"]
        assert spec["file"].endswith(".gguf") and spec["size"] > 1_000_000_000 and spec["family"] in ("translategemma", "milmmt")
        assert spec["tier"] in ("light", "heavy") and spec["vram_gb"] and spec["ram_gb"] and spec["speed"], "ölçülen hız yazılı"
    for runtime in local_llm.RUNTIMES.values():
        assert all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in runtime["files"])
    assert set(local_llm.RUNTIMES) == {"vulkan"}, "Vulkan her ekran kartında çalışır; CUDA'nın hız farkı %10 (ölçüldü)"
    assert local_llm.recommend(12)["model"] == "translategemma-12b" and local_llm.recommend(8)["model"] == "translategemma-4b"
    assert local_llm.recommend(None)["model"] == "translategemma-4b"


# ── İndirme ──────────────────────────────────────────────────────────────────
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(data: bytes):
    return lambda request, timeout: _Resp(data)


def test_download_verifies_size_and_sha256(tmp_path):
    data = b"gguf" * 1000
    good = hashlib.sha256(data).hexdigest()
    target = tmp_path / "m.gguf"
    seen = []
    local_llm._download("https://example.invalid/m.gguf", target, len(data), good, lambda d, t: seen.append(d), None, _opener(data))
    assert target.read_bytes() == data and seen[-1] == len(data)
    bad = tmp_path / "bad.gguf"
    with pytest.raises(ValueError, match="doğrulanamadı"):
        local_llm._download("https://example.invalid/m.gguf", bad, len(data), "0" * 64, None, None, _opener(data))
    assert not bad.exists() and not list(tmp_path.glob("*.part")), "bozuk dosya bırakılmaz"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(local_llm.DownloadCancelled):
        local_llm._download("https://example.invalid/m.gguf", tmp_path / "c.gguf", len(data), good, None, cancel, _opener(data))
    assert not list(tmp_path.glob("c.gguf*"))


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_runtime_install_extracts_safely(tmp_path, monkeypatch):
    monkeypatch.setattr(local_llm, "tools_dir", lambda: tmp_path / "tools")
    good = _zip({"llama-server.exe": b"MZ", "ggml.dll": b"x"})
    spec = {"label": "t", "files": [{"name": "rt.zip", "size": len(good), "sha256": hashlib.sha256(good).hexdigest()}]}
    monkeypatch.setitem(local_llm.RUNTIMES, "vulkan", spec)
    path = local_llm.install_runtime("vulkan", opener=_opener(good), log=lambda s: None)
    assert (path / "llama-server.exe").is_file() and local_llm.installed_runtimes() == ["vulkan"]
    evil = _zip({"../../kacis.txt": b"x", "llama-server.exe": b"MZ"})
    monkeypatch.setitem(local_llm.RUNTIMES, "vulkan", {"label": "t", "files": [
        {"name": "rt.zip", "size": len(evil), "sha256": hashlib.sha256(evil).hexdigest()}]})
    with pytest.raises(ValueError, match="Güvensiz"):
        local_llm.install_runtime("vulkan", opener=_opener(evil), log=lambda s: None)
    assert not (tmp_path / "kacis.txt").exists() and not list((tmp_path / "tools").glob(".*tmp"))


# ── Sunucu (llama-server taklidiyle) ─────────────────────────────────────────
@pytest.fixture
def fake_runtime(tmp_path, monkeypatch):
    tools, models = tmp_path / "tools", tmp_path / "models"
    (tools / f"{local_llm.LLAMA_VERSION}-vulkan").mkdir(parents=True)
    (tools / f"{local_llm.LLAMA_VERSION}-vulkan" / "llama-server.exe").write_bytes(b"MZ")
    models.mkdir()
    monkeypatch.setattr(local_llm, "tools_dir", lambda: tools)
    monkeypatch.setattr(local_llm, "models_dir", lambda: models)
    monkeypatch.setattr(local_llm, "model_installed", lambda model_id: model_id in local_llm.BY_ID)
    server = local_llm.LlamaServer()
    server.log_file = tmp_path / "server.log"
    monkeypatch.setattr(local_llm, "SERVER", server)
    launched = []
    real_popen = subprocess.Popen

    def popen(args, **kw):
        launched.append(args)
        port = args[args.index("--port") + 1]
        extra = ["--crash"] if "--crash" in args else []
        return real_popen([sys.executable, str(FAKE), "--port", port, *extra], **kw)

    monkeypatch.setattr(local_llm.subprocess, "Popen", popen)
    yield server, launched
    server.stop()


def test_server_starts_on_demand_reuses_and_switches_models(fake_runtime):
    server, launched = fake_runtime
    assert local_llm.translate_one("translategemma-4b", "Hello.\nBye.", "en", "tr", log=lambda s: None) == "TR(Hello.)\nTR(Bye.)"
    assert local_llm.translate_one("translategemma-4b", "Again.", "en", "tr", log=lambda s: None) == "TR(Again.)"
    assert len(launched) == 1, "aynı modelle sunucu yeniden açılmaz"
    args = launched[0]
    assert args[args.index("--host") + 1] == "127.0.0.1" and "--fit" in args and "--no-webui" in args
    assert local_llm.translate_one("milmmt-4b", "Hi.", "en", "tr", log=lambda s: None) == "TR(Hi.)"
    assert len(launched) == 2 and server.model_id == "milmmt-4b", "başka model istenince yeniden açılır"
    server.stop()
    assert not server.running()


def test_server_crash_is_reported_with_log(fake_runtime, monkeypatch):
    server, _ = fake_runtime
    server.extra_args = ["--crash"]
    with pytest.raises(RuntimeError, match="failed to load model"):
        server.ensure("translategemma-4b", log=lambda s: None, timeout=20)
    assert server.model_id is None


def test_idle_server_stops_itself(fake_runtime, monkeypatch):
    server, _ = fake_runtime
    monkeypatch.setattr(local_llm, "IDLE_SECONDS", 0)
    server.ensure("translategemma-4b", log=lambda s: None)
    server.last_used = 0
    for _ in range(80):
        if not server.running():
            break
        time.sleep(0.25)
    assert not server.running(), "kullanılmayan sunucu ekran kartı belleğini bırakır"


def test_missing_runtime_or_model_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(local_llm, "tools_dir", lambda: tmp_path / "yok")
    with pytest.raises(RuntimeError, match="llama.cpp"):
        local_llm.LlamaServer().ensure("translategemma-4b", log=lambda s: None)


# ── Uygulama ve motorlar ─────────────────────────────────────────────────────
def _fake_translate(calls):
    def fake(model_id, text, source, target, temperature=0.1, timeout=600, log=print):
        calls.append(model_id)
        return "\n".join(f"TR({line})" for line in text.split("\n"))
    return fake


def test_rpgmaker_game_translates_with_builtin_model(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local_llm, "translate_one", _fake_translate(calls))
    monkeypatch.setattr(local_llm, "server_exe", lambda flavor=None: Path("llama-server.exe"))
    monkeypatch.setattr(local_llm, "model_installed", lambda model_id: True)
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="local", local_model="translategemma-12b")
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    run_sync(bridge, "translate")
    lines = json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"]
    assert lines[1]["parameters"][0] == "TR(Welcome to our village, traveler.)"
    assert set(calls) == {"translategemma-12b"}


def test_renpy_unity_unreal_route_to_builtin_model(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local_llm, "translate_one", _fake_translate(calls))
    tl = tmp_path / "tl" / "Turkish"
    tl.mkdir(parents=True)
    script = tl / "s.rpy"
    script.write_text('translate Turkish a_1:\n\n    # e "Hello, [mc]!"\n    e ""\n', encoding="utf-8")
    assert engine_renpy.translate_templates(tl, tmp_path, tmp_path / "c.json", None, log=lambda s: None,
                                            model_kind="local", ollama_model="translategemma-4b") == 1
    assert 'e "TR(Hello, [mc]!)"' in script.read_text(encoding="utf-8")
    import engine_unity
    import engine_unreal
    out = engine_unity.translate_texts_unity(["Start Game"], tmp_path / "u.json", model_kind="local",
                                             ollama_model="translategemma-4b", log=lambda s: None)
    assert out["Start Game"] == "TR(Start Game)"
    out = engine_unreal.translate_texts_unreal(["The vault is sealed."], tmp_path / "r.json", model_kind="local",
                                               ollama_model="translategemma-4b", log=lambda s: None)
    assert out["The vault is sealed."] == "TR(The vault is sealed.)"


def test_screen_translation_prefers_milmmt_and_readiness_check(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local_llm, "translate_one", _fake_translate(calls))
    installed = {"translategemma-4b"}
    monkeypatch.setattr(local_llm, "model_installed", lambda model_id: model_id in installed)
    bridge = make_bridge(tmp_path, monkeypatch, model="local")
    assert bridge._local_model_id() == "translategemma-4b" and bridge._local_model_id(ocr=True) == "translategemma-4b"
    installed.add("milmmt-4b")
    assert bridge._local_model_id(ocr=True) == "milmmt-4b", "ekran çevirisinde tek satır modeli"
    ok, text, _ms = providers.translate_single_text("Hi.", "local", "tr", "en", local_model="milmmt-4b")
    assert ok and text == "TR(Hi.)" and calls[-1] == "milmmt-4b"
    monkeypatch.setattr(local_llm, "server_exe", lambda flavor=None: None)
    with pytest.raises(app_modern.UserError, match="Ollama gerekmez"):
        bridge._check_model_ready("rpgmaker")
    assert bridge._quality_provider() == "gemini" if providers.load_provider_config().gemini_keys else True


def test_download_task_installs_runtime_then_model(tmp_path, monkeypatch):
    done = []
    monkeypatch.setattr(local_llm, "server_exe", lambda flavor=None: Path("x") if "runtime" in done else None)
    monkeypatch.setattr(local_llm, "install_runtime", lambda flavor, progress, cancel, log: done.append("runtime") or progress(1, 2))
    monkeypatch.setattr(local_llm, "install_model", lambda mid, progress, cancel, log: done.append(mid) or progress(2, 2))
    monkeypatch.setattr(local_llm, "model_installed", lambda model_id: model_id in done)
    bridge = make_bridge(tmp_path, monkeypatch)
    run_sync(bridge, "download_local_model", "translategemma-4b")
    assert done == ["runtime", "translategemma-4b"] and bridge._settings["local_model"] == "translategemma-4b"
    assert any(e[0] == "models" for e in bridge._ui.events), "arayüz yeni durumu alır"
    state = bridge.local_models()
    assert {m["id"]: m["installed"] for m in state["models"]}["translategemma-4b"]


def test_app_update_keeps_downloaded_models():
    import updater
    assert {"models_llm", "tools"} <= set(updater.PROTECTED), "güncelleme indirilen modelleri silmez"


def test_recommendation_does_not_wait_for_background_gpu_detection(tmp_path, monkeypatch):
    import gpu_runtime
    monkeypatch.setattr(gpu_runtime, "nvidia_info", lambda: {"name": "RTX 5070", "memory": "12 GB"})
    monkeypatch.setattr(local_llm, "model_installed", lambda model_id: False)
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._gpu = {"name": "Algılanıyor…", "detail": "", "cuda": False}
    state = bridge.local_models()
    assert state["vram_gb"] == 12.0 and state["recommended"]["model"] == "translategemma-12b"
    assert [m["id"] for m in state["models"] if m["recommended"]] == ["translategemma-12b"]


def test_nested_wrapper_folders_are_detected(tmp_path):
    from test_app import make_rpgmaker_game
    deep = tmp_path / "Game_v1.1.3_Windows" / "Game v1.1.3 Windows" / "PC"
    make_rpgmaker_game(deep)
    (tmp_path / "Game_v1.1.3_Windows" / "Game v1.1.3 Windows" / "Readme.txt").write_text("x")
    kind, info = app_modern.detect_any_game_type(str(tmp_path / "Game_v1.1.3_Windows"))
    assert kind == "rpgmaker", "iki kat içteki oyun bulunur (oyun iki kat iç klasörde)"
    busy = tmp_path / "Library"
    for i in range(8):
        (busy / f"klasor{i}" / "alt").mkdir(parents=True)
    make_rpgmaker_game(busy / "klasor0" / "alt" / "Oyun")
    assert app_modern.detect_any_game_type(str(busy))[0] is None, "kalabalık klasörlerde derin tarama yapılmaz"
