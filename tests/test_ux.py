"""
Kullanıcı deneyimi ve performans: hata yolu, net durumlar, süre tahmini, kalıcı analiz, hızlı algılama.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import app_modern
from test_app import fake_ollama, make_bridge, make_rpgmaker_game, run_sync  # noqa: F401

SRC = Path(__file__).resolve().parent.parent / "src"


def events(bridge, name):
    return [d for e, d in bridge._ui.events if e == name]


# ── Hatanın kök nedeni: pywebview exe'de stdout'u cp1254 ile açıyor ──────────
def test_log_survives_stdout_that_cannot_encode(monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1254"))
    channel = app_modern.UiChannel()
    channel.log("• Çeviri başladı — Oyun · en → tr ✔ ⚠")   # eskiden UnicodeEncodeError


def test_harden_stdio_fills_missing_streams_before_webview():
    code = ("import sys; sys.stdout = sys.stderr = None; sys.path.insert(0, %r); import paths; paths.harden_stdio();"
            "assert sys.stdout.encoding.lower() == 'utf-8'; print('→ ✔ ⚠');"
            "import webview.http; assert sys.stdout.encoding.lower() == 'utf-8'" % str(SRC))
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


def test_notify_failure_cannot_leave_project_stuck(tmp_path, monkeypatch):
    """Hata yolundaki bildirim de düşse proje 'sürüyor'da kalmaz, işlem kilidi açılır."""
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_check_model_ready", lambda t: None)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))

    def boom(game, failed):
        raise PermissionError(13, "Erişim engellendi", "resources.assets")

    def bad_notify(*a, **k):
        raise UnicodeEncodeError("charmap", "→", 0, 1, "x")

    monkeypatch.setattr(bridge, "_translate_rpgmaker", boom)
    monkeypatch.setattr(bridge, "_notify", bad_notify)
    run_sync(bridge, "translate")
    item = bridge._library.get(bridge._game["root"])
    assert item["status"] == "error" and not bridge._busy
    assert item["last_error"]["title"] == "Oyun dosyalarına yazılamadı" and "kapat" in item["last_error"]["hint"]
    assert events(bridge, "task_error")[-1]["title"] == "Oyun dosyalarına yazılamadı"
    assert events(bridge, "busy")[-1] == {"busy": False}


@pytest.mark.parametrize("exc,title,page", [
    (RuntimeError("429 RESOURCE_EXHAUSTED"), "API kotası doldu", "providers"),
    (RuntimeError("API key not valid"), "API anahtarı kabul edilmedi", "providers"),
    (ConnectionError("reset"), "İnternet bağlantısı kurulamadı", None),
    (TimeoutError("timed out"), "Sunucu yanıt vermedi", None),
    (OSError(28, "No space left"), "Diskte yer kalmadı", None),
    (MemoryError(), "Bellek yetmedi", "models"),
    (ModuleNotFoundError("No module named 'torch'", name="torch"), "Yerel model ortamı eksik", "models"),
    (ModuleNotFoundError("No module named 'UnityPy.resources'", name="UnityPy.resources"), "Uygulamanın bir parçası eksik", None),
    (UnicodeEncodeError("charmap", "→", 0, 1, "x"), "Beklenmeyen bir hata oluştu", None),
])
def test_errors_are_described_in_plain_language(exc, title, page):
    from user_errors import describe_error
    info = describe_error(exc)
    assert info["title"] == title and info["hint"] and type(exc).__name__ in info["detail"]
    assert (info["action"] or {}).get("page") == page


def test_preflight_error_is_not_marked_as_failed_translation(tmp_path, monkeypatch):
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="openai")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig())
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "translate")
    assert bridge._library.get(bridge._game["root"]).get("status") != "error", "çeviri hiç başlamadı"
    assert "API anahtarı yok" in events(bridge, "task_error")[-1]["hint"]


def test_all_lines_failing_is_reported_as_failure(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_check_model_ready", lambda t: None)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))

    def nothing(game, failed):
        failed.update({"a", "b"})
        return 0

    monkeypatch.setattr(bridge, "_translate_rpgmaker", nothing)
    run_sync(bridge, "translate")
    assert bridge._library.get(bridge._game["root"])["status"] == "error"


# ── "Son işlem az önce" ve takılı kalan durum ────────────────────────────────
def test_cover_art_does_not_count_as_last_action(tmp_path):
    lib = app_modern.ProjectLibrary(tmp_path / "p.json")
    first = lib.upsert("C:/a", title="A")
    time.sleep(0.01)
    lib.upsert("C:/b", title="B")
    time.sleep(0.01)
    assert lib.upsert("C:/a", touch=False, appid="1")["updated"] == first["updated"]
    assert lib.list()[0]["title"] == "B", "kapak yüklenince sıralama değişmemeli"


def test_interrupted_translation_is_not_stuck_after_restart(tmp_path):
    path = tmp_path / "p.json"
    app_modern.ProjectLibrary(path).upsert("C:/a", status="translating")
    lib = app_modern.ProjectLibrary(path)
    lib.recover_interrupted()
    assert lib.get("C:/a")["status"] == "paused"


def test_cancel_records_where_it_stopped(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_check_model_ready", lambda t: None)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))

    def stops(game, failed):
        bridge._progress(0, 200)
        bridge._progress(50, 200)
        bridge._cancel.set()
        bridge._progress(60, 200)

    monkeypatch.setattr(bridge, "_translate_rpgmaker", stops)
    run_sync(bridge, "translate")
    item = bridge._library.get(bridge._game["root"])
    assert item["status"] == "paused" and item["paused_done"] == 50 and item["paused_total"] == 200 and item["last_action_at"]


def test_finished_translation_records_result_and_keeps_analysis(tmp_path, monkeypatch, fake_ollama):
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "analyze")
    run_sync(bridge, "translate")
    item = bridge._library.get(bridge._game["root"])
    assert item["status"] == "translated" and item["last_result"]["written"] > 0 and item["last_action"] == "Çeviri tamamlandı"
    assert bridge._game["analysis"]["estimate"]["pending"] == 0
    keys = [d["key"] for d in events(bridge, "stage")]
    assert keys == ["backup", "prepare", "translate", "write"], "adımlar sırayla bildirilmeli"
    first_lines = bridge._game["analysis"]["stats"]["unique"]
    bridge._select_game(str(tmp_path / "game"))
    run_sync(bridge, "analyze")
    assert bridge._game["analysis"]["stats"]["unique"] == first_lines, "çevrilmiş dosya yeniden 'kaynak' sayılmamalı"


def test_retranslation_restores_originals_first(tmp_path, monkeypatch, fake_ollama):
    import engine_rpgmaker as er
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    game = make_rpgmaker_game(tmp_path / "game")
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append(text) or True)
    run_sync(bridge, "translate")
    assert asked and "orijinal" in asked[0]
    texts = {t.original for t in er.extract_texts_mv_mz(game / "www" / "data", log=lambda s: None)}
    assert any(t.startswith("TR(") for t in texts) and not any(t.startswith("TR(TR(") for t in texts), "çift çeviri olmamalı"
    assert bridge._library.get(bridge._game["root"])["status"] == "translated"


def test_retranslation_can_be_declined(tmp_path, monkeypatch, fake_ollama):
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "translate")
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: False)
    run_sync(bridge, "translate")
    assert bridge._library.get(bridge._game["root"])["status"] == "translated", "vazgeçince durum değişmemeli"


# ── Süre tahmini ─────────────────────────────────────────────────────────────
def test_estimate_scales_with_text_and_workers(tmp_path):
    from progress import SpeedStore, estimate
    small = estimate("gemini", 5_000)["seconds"]
    assert estimate("gemini", 500_000)["seconds"] == pytest.approx(small * 100, rel=0.02), "metin büyüdükçe süre büyümeli"
    assert estimate("gemini", 500_000, workers=4)["seconds"] == pytest.approx(small * 25, rel=0.02)
    assert estimate("opus", 100_000, gpu=False)["seconds"] > estimate("opus", 100_000, gpu=True)["seconds"] * 5
    assert estimate("gemini", 2_000_000)["text"].endswith(("dk", "sa"))
    store = SpeedStore(tmp_path / "s.json")
    assert estimate("gemini", 1000, store=store)["basis"] == "prior"
    store.record("gemini", chars=10_000, seconds=100, workers=2)    # 50 karakter/sn/anahtar
    result = estimate("gemini", 1000, workers=2, store=SpeedStore(tmp_path / "s.json"))
    assert result["basis"] == "learned" and result["seconds"] == pytest.approx(10)
    store.record("gemini", chars=30_000, seconds=100, workers=2)    # hareketli ortalama: (50 + 150) / 2
    assert store.get("gemini") == pytest.approx(100)


def test_live_eta_uses_recent_speed_and_ignores_cached_jump():
    from progress import LiveEta
    now = [0.0]
    eta = LiveEta(clock=lambda: now[0])
    eta.start(1000)
    now[0] = 0.1
    eta.update(300)     # önbellekten anlık sıçrama
    assert eta.rate() is None
    assert eta.eta_seconds(fallback_per_item=0.5) == pytest.approx(350), "ilk parti bitene kadar ön tahmin"
    now[0] = 10.0
    eta.update(350)
    assert eta.rate() == pytest.approx(50 / 10.0)
    now[0] = 110.0
    eta.update(400)     # hız düştü: eski örnekler 90 sn penceresinden çıkar
    assert eta.rate() == pytest.approx(0.5)
    assert eta.eta_seconds() == pytest.approx(1200)
    assert eta.worked() == (100, 110.0)


def test_durations_read_naturally():
    from progress import format_duration, format_estimate, format_rate
    assert format_duration(50) == "50 sn" and format_duration(250) == "4 dk 10 sn" and format_duration(3900) == "1 sa 5 dk"
    assert format_estimate(4) == "birkaç saniye" and format_estimate(42) == "yaklaşık 40 sn"
    assert format_estimate(250) == "yaklaşık 4 dk" and format_estimate(4500) == "yaklaşık 1 sa 15 dk"
    assert format_rate(5.25) == "5,2 satır/sn" and format_rate(0.5) == "30 satır/dk" and format_rate(None) == ""


def test_progress_event_carries_live_numbers(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._eta_prior = 2.0
    bridge._progress(0, 100)
    payload = [d for e, d in bridge._ui.events if e == "progress"][-1]
    assert payload["eta_s"] == pytest.approx(200) and payload["unit"] == "satır" and payload["pct"] == 0


# ── Kalıcı analiz ve hızlı açılış ────────────────────────────────────────────
def test_analysis_panel_data_and_estimate(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "analyze")
    analysis = events(bridge, "analysis")[-1]
    stats, est = analysis["stats"], analysis["estimate"]
    assert stats["unique"] > 0 and stats["words"] >= stats["unique"] and stats["exact"] is True
    assert est["pending"] == stats["unique"] and est["cached"] == 0 and est["text"] and est["basis"] == "prior"
    uniques = bridge._game["uniques"]     # önbellekteki satırlar süreye girmez
    bridge._cache_path().parent.mkdir(parents=True, exist_ok=True)
    bridge._cache_path().write_text(json.dumps({u: "x" for u in uniques}), encoding="utf-8")
    est = bridge._estimate(bridge._game)
    assert est["pending"] == 0 and est["cached"] == len(uniques) and est["seconds"] == 0


def test_estimate_changes_with_engine(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    run_sync(bridge, "analyze")
    fast = bridge._estimate(bridge._game)["seconds"]
    bridge._settings["model"] = "ollama"
    assert bridge._estimate(bridge._game)["seconds"] > fast


def test_renpy_text_estimate_counts_dialogue(tmp_path):
    game = tmp_path / "game"
    (game / "tl" / "Turkish").mkdir(parents=True)
    (game / "script.rpy").write_text('label start:\n    e "Hello there, friend."\n    "A narrator line."\n    $ x = "code"\n    jump end\n', encoding="utf-8")
    (game / "tl" / "Turkish" / "script.rpy").write_text('    e "Merhaba arkadaşım."\n', encoding="utf-8")
    stats = app_modern.estimate_renpy_text(game)
    assert stats["unique"] == 2 and stats["exact"] is False and stats["chars"] == len("Hello there, friend.") + len("A narrator line.")


def test_analysis_is_restored_from_disk_until_game_changes(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    game = make_rpgmaker_game(tmp_path / "game")
    calls = []
    original = bridge._analyze_rpgmaker
    monkeypatch.setattr(bridge, "_analyze_rpgmaker", lambda g: calls.append(1) or original(g))
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    assert len(calls) == 1
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    assert len(calls) == 1, "değişmeyen oyun yeniden taranmamalı"
    assert bridge._game["uniques"] and bridge._game["analysis"]["estimate"]["pending"]
    (game / "www" / "data" / "Map001.json").write_text("{}", encoding="utf-8")
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    assert len(calls) == 2, "oyun dosyası değişince yeniden taranmalı"


def test_analysis_does_not_lock_the_app_and_switching_discards_old_result(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    first = make_rpgmaker_game(tmp_path / "one")
    second = make_rpgmaker_game(tmp_path / "two")
    bridge._select_game(str(first))
    original = bridge._analyze_rpgmaker

    def switch_midway(game):
        assert not bridge._busy, "analiz işlem kilidi tutmamalı"
        result = original(game)
        bridge._select_game(str(second))
        return result

    monkeypatch.setattr(bridge, "_analyze_rpgmaker", switch_midway)
    run_sync(bridge, "analyze")
    assert not events(bridge, "analysis"), "eski projenin sonucu ekrana gelmemeli"


def test_analysis_failure_is_explained(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))

    def boom(game):
        raise PermissionError(13, "Erişim engellendi")

    monkeypatch.setattr(bridge, "_analyze_rpgmaker", boom)
    run_sync(bridge, "analyze")
    error = events(bridge, "task_error")[-1]
    assert error["label"] == "Analiz" and error["title"] == "Oyun dosyalarına yazılamadı"
    assert events(bridge, "analyzing")[-1]["active"] is False


def test_unity_detection_does_not_parse_assets(tmp_path, monkeypatch):
    import engine_unity
    data = tmp_path / "Game" / "Game_Data"
    data.mkdir(parents=True)
    (data / "resources.assets").write_bytes(b"x")
    (tmp_path / "Game" / "Game.exe").write_bytes(b"MZ")

    def forbidden(*a):
        pytest.fail("algılama varlıkları yüklememeli")

    monkeypatch.setattr(engine_unity.UnityPy, "load", forbidden)
    info = engine_unity.detect_unity_game(tmp_path / "Game")
    assert info.game_title == "Game" and info.scanned is False


def test_unity_analysis_loads_assets_once_and_writes_nothing_to_game(tmp_path, monkeypatch):
    import engine_unity

    class Obj:
        def __init__(self, kind, data):
            self.type = type("T", (), {"name": kind})
            self._data = data

        def read(self):
            return self._data

    asset = type("A", (), {"m_Name": "english_text", "m_Script": "id\tvalue\nk1\tHello there\n"})
    font = type("F", (), {"m_Name": "Main", "m_FontData": b"TTF"})
    loads = []
    env = type("E", (), {"objects": [Obj("TextAsset", asset), Obj("Font", font)]})
    monkeypatch.setattr(engine_unity.UnityPy, "load", lambda *a: loads.append(a) or env)
    monkeypatch.setattr(engine_unity.FontChecker, "check_turkish_support",
                        lambda p: {"fully_supported": False, "missing_chars": ["ş"]})
    data = tmp_path / "Game" / "Game_Data"
    data.mkdir(parents=True)
    (data / "resources.assets").write_bytes(b"x")
    before = sorted(p.name for p in data.iterdir())
    info = engine_unity.detect_unity_game(tmp_path / "Game")
    texts = engine_unity.extract_texts_unity(info, log=lambda s: None)
    assert len(loads) == 1, "resources.assets tek kez yüklenmeli"
    assert [t.original for t in texts] == ["Hello there"]
    assert info.font_turkish_support is False and info.missing_font_chars == ["ş"]
    assert sorted(p.name for p in data.iterdir()) == before, "oyun klasörüne geçici dosya yazılmamalı"


def test_cache_files_are_compact(tmp_path):
    cache = app_modern.TranslationCache(tmp_path / "c.json")
    cache.load()
    cache.set("a", "b")
    cache.save()
    assert "\n" not in (tmp_path / "c.json").read_text(encoding="utf-8")


def test_art_is_served_from_local_address_not_base64(tmp_path, monkeypatch):
    import urllib.error
    import urllib.request
    import library
    from PIL import Image
    monkeypatch.setattr(library, "ART_DIR", tmp_path / "art")
    source = tmp_path / "poster.png"
    Image.new("RGB", (800, 1200), "red").save(source)
    url = library._art_url(source, "poster")
    assert url.startswith("http://127.0.0.1:") and url.endswith(".jpg") and "base64" not in url
    with urllib.request.urlopen(url) as response:
        assert response.headers["Content-Type"] == "image/jpeg" and response.read()[:2] == b"\xff\xd8"
    base = url.rsplit("/", 1)[0]
    for bad in ("/../poster.png", "/..%5Cposter.png", "/yok.jpg"):
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + bad)


def test_editor_search_does_not_reread_or_revalidate_everything(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    path = bridge._cache_path("gemini")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({f"line {i}": f"satır {i}" for i in range(2000)}), encoding="utf-8")
    checks, reads = [], []
    real_valid, real_read = app_modern.prov.placeholders_valid, app_modern._read_json

    def counting_valid(s, t):
        checks.append(s)
        return real_valid(s, t)

    def counting_read(p, d):
        reads.append(p)
        return real_read(p, d)

    monkeypatch.setattr(app_modern.prov, "placeholders_valid", counting_valid)
    monkeypatch.setattr(app_modern, "_read_json", counting_read)
    result = bridge.editor_load("gemini", "", False, 0, 80)
    assert result["total"] == 2000 and len(result["items"]) == 80
    assert len(checks) == 80, "yalnızca gösterilen satırlar doğrulanmalı"
    bridge.editor_load("gemini", "line 19", False, 0, 80)
    assert reads.count(path) == 1, "dosya değişmedikçe yeniden okunmamalı"


# ── Güncellemeden sonra eski arayüz açılmamalı ───────────────────────────────
def test_web_cache_is_cleared_when_ui_changes(tmp_path):
    web, storage = tmp_path / "web", tmp_path / "webview"
    web.mkdir()
    (web / "index.html").write_text("eski", encoding="utf-8")
    cache = storage / "EBWebView" / "Default" / "Cache"
    local = storage / "EBWebView" / "Default" / "Local Storage"
    cache.mkdir(parents=True)
    local.mkdir(parents=True)
    assert app_modern.refresh_web_cache(web, storage, "1.0.0") is True and not cache.exists()
    assert local.exists(), "yerel veriler (ör. çeviri geçmişi) korunmalı"
    cache.mkdir()
    assert app_modern.refresh_web_cache(web, storage, "1.0.0") is False and cache.exists(), "değişiklik yoksa önbellek kalmalı"
    assert app_modern.refresh_web_cache(web, storage, "1.0.1") is True and not cache.exists(), "sürüm değişince temizlenmeli"
    cache.mkdir()
    (web / "index.html").write_text("yeni içerik", encoding="utf-8")
    assert app_modern.refresh_web_cache(web, storage, "1.0.1") is True and not cache.exists(), "dosya değişince temizlenmeli"


# ── Unity: StreamingAssets ve BepInEx ────────────────────────────────────────
def _unity_game(root, runtime_il2cpp=False, tsv=True):
    data = root / "Game_Data"
    (data / "StreamingAssets").mkdir(parents=True)
    (data / "boot.config").write_text("x", encoding="utf-8")
    (root / "Game.exe").write_bytes(b"MZ")
    if runtime_il2cpp:
        (root / "GameAssembly.dll").write_bytes(b"x")
    if tsv:
        (data / "StreamingAssets" / "lang.tsv").write_bytes("k1\tOpen the gate\r\nk2\t  Hello there \tnote\r\nk3\t123\r\n".encode("utf-8"))
    return data / "StreamingAssets" / "lang.tsv"


def _unity_bridge(tmp_path, monkeypatch, fake_ollama):
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    return bridge


def test_streaming_assets_are_written_and_backed_up(tmp_path, monkeypatch, fake_ollama):
    bridge = _unity_bridge(tmp_path, monkeypatch, fake_ollama)
    path = _unity_game(tmp_path / "Game")
    original = path.read_bytes()
    bridge._select_game(str(tmp_path / "Game"))
    run_sync(bridge, "translate")
    text = path.read_bytes().decode("utf-8")
    assert text == "k1\tTR(Open the gate)\r\nk2\t  TR(Hello there) \tnote\r\nk3\t123\r\n", "yalnızca metin sütunu değişmeli"
    item = bridge._library.get(bridge._game["root"])
    assert item["status"] == "translated" and item["last_result"]["written"] == 2
    backups = bridge.list_backups()
    assert backups and backups[0]["files"] == 1, "5 GB'lık varlık değil, değişen dosya yedeklenmeli"
    bridge._restore_originals(bridge._game)
    assert path.read_bytes() == original


def test_il2cpp_declining_bepinex_still_writes_open_files(tmp_path, monkeypatch, fake_ollama):
    bridge = _unity_bridge(tmp_path, monkeypatch, fake_ollama)
    path = _unity_game(tmp_path / "Game", runtime_il2cpp=True)
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append(title) or False)
    bridge._select_game(str(tmp_path / "Game"))
    run_sync(bridge, "translate")
    assert asked == ["BepInEx köprüsü"] and "TR(Open the gate)" in path.read_text(encoding="utf-8")
    assert bridge._library.get(bridge._game["root"])["status"] == "translated"


def test_declining_bepinex_with_no_open_text_is_not_reported_as_done(tmp_path, monkeypatch, fake_ollama):
    bridge = _unity_bridge(tmp_path, monkeypatch, fake_ollama)
    _unity_game(tmp_path / "Game", runtime_il2cpp=True, tsv=False)
    calls = []
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: False)
    monkeypatch.setattr(app_modern.engine_unity if hasattr(app_modern, "engine_unity") else __import__("engine_unity"),
                        "translate_texts_unity", lambda **k: calls.append(1) or {})
    bridge._select_game(str(tmp_path / "Game"))
    run_sync(bridge, "translate")
    assert not calls, "izin verilmezse API harcanmamalı"
    assert bridge._library.get(bridge._game["root"]).get("status") != "translated"
    assert not [n for n in events(bridge, "notify") if n["title"] == "Çeviri tamamlandı"]
    assert "BepInEx olmadan" in events(bridge, "task_error")[-1]["hint"]


def test_nothing_written_is_not_called_complete(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_check_model_ready", lambda t: None)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    monkeypatch.setattr(bridge, "_translate_rpgmaker", lambda game, failed: 0)
    run_sync(bridge, "translate")
    assert bridge._library.get(bridge._game["root"])["status"] == "error"
    assert "yazılacak satır bulunamadı" in events(bridge, "task_error")[-1]["hint"]


# ── Otomatik oyun bulma ──────────────────────────────────────────────────────
def test_scanner_finds_games_skips_known_and_changes_nothing(tmp_path, monkeypatch):
    import game_scanner
    games = tmp_path / "Oyunlar"
    make_rpgmaker_game(games / "RpgOyun")
    make_rpgmaker_game(games / "Kayitli")
    _unity_game(games / "UnityOyun")
    (games / "BosKlasor").mkdir()
    (games / "Steamworks Shared").mkdir()
    before = sorted(str(p) for p in games.rglob("*"))
    found = game_scanner.scan(app_modern.detect_any_game_type, app_modern.game_root_of, app_modern.game_title_of,
                              [games, tmp_path / "yok"], [], [str(games / "Kayitli")])
    assert {g["engine"] for g in found} == {"rpgmaker", "unity"} and len(found) == 2
    assert sorted(str(p) for p in games.rglob("*")) == before, "tarama salt okunur olmalı"


def test_scan_sources_reads_steam_epic_and_custom(tmp_path, monkeypatch):
    import game_scanner
    manifests = tmp_path / "m"
    manifests.mkdir()
    (manifests / "a.item").write_text(json.dumps({"InstallLocation": "D:/Epic/Oyun"}), encoding="utf-8")
    (manifests / "bozuk.item").write_text("{", encoding="utf-8")
    assert game_scanner.epic_games(manifests) == [Path("D:/Epic/Oyun")]
    monkeypatch.setattr(game_scanner, "steam_folders", lambda: [Path("S:/steamapps/common")])
    monkeypatch.setattr(game_scanner, "epic_games", lambda: [Path("D:/Epic/Oyun")])
    monkeypatch.setattr(game_scanner, "gog_games", lambda: [])
    parents, direct = game_scanner.scan_sources(["E:/Benim"], drives=[Path("C:/")])
    assert {Path("S:/steamapps/common"), Path("C:/Games"), Path("C:/Oyunlar"), Path("E:/Benim")} <= set(parents)
    assert direct == [Path("D:/Epic/Oyun")]


def test_scan_bridge_add_dismiss_and_notify_once(tmp_path, monkeypatch):
    import game_scanner
    games = tmp_path / "Oyunlar"
    make_rpgmaker_game(games / "Bir")
    _unity_game(games / "Iki")
    monkeypatch.setattr(game_scanner, "scan_sources", lambda extra: ([games], []))
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._scan_found = []
    run_sync(bridge, "scan_games")
    found = bridge._scan_payload()["found"]
    assert len(found) == 2 and found[0]["engine_label"]
    assert len([n for n in events(bridge, "notify") if "yeni oyun" in n["title"]]) == 1
    run_sync(bridge, "scan_games")
    assert len([n for n in events(bridge, "notify") if "yeni oyun" in n["title"]]) == 1, "aynı oyunlar için tekrar bildirim yok"
    project = bridge.scan_add(found[0]["path"])
    assert project["title"] == found[0]["title"] and len(bridge._scan_payload()["found"]) == 1
    assert bridge.scan_dismiss(found[1]["path"])["found"] == []
    run_sync(bridge, "scan_games")
    assert bridge._scan_payload()["found"] == [], "gizlenen ve eklenen oyun yeniden önerilmemeli"


# ── Ren'Py çok dilli hedef ───────────────────────────────────────────────────
def test_renpy_language_names_are_valid():
    from languages import SUPPORTED_LANGUAGES, code_for_renpy_name, renpy_language_name
    assert renpy_language_name("tr") == "Turkish" and renpy_language_name("zh-CN") == "SimplifiedChinese"
    for code in SUPPORTED_LANGUAGES:
        name = renpy_language_name(code)
        assert name.isidentifier() and code_for_renpy_name(name) == code


def _renpy_game(root):
    game = root / "game"
    game.mkdir(parents=True)
    (root / "Oyun.exe").write_bytes(b"MZ")
    (game / "script.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")
    return game


@pytest.mark.parametrize("code,folder,native", [("de", "German", "Deutsch"), ("ru", "Russian", "Русский"), ("tr", "Turkish", "Türkçe")])
def test_renpy_support_file_uses_target_language(tmp_path, code, folder, native):
    import engine_renpy as er
    game = _renpy_game(tmp_path / "G")
    info = er.analyze_game(tmp_path / "G", log=lambda s: None, language=folder)
    assert info.tl_dir == game / "tl" / folder
    er.enable_turkish(info, True, log=lambda s: None)
    script = info.support_file.read_text(encoding="utf-8")
    assert f'config.default_language = "{folder}"' in script and f'Language("{folder}")' in script and native in script
    assert ("_renptr_char_map" in script) == (code == "tr"), "Türkçe akrabalık tablosu başka dile girmemeli"
    if code != "tr":
        assert "Turkish" not in script and "Türkçe" not in script


def test_switching_renpy_language_removes_old_autoload(tmp_path):
    import engine_renpy as er
    game = _renpy_game(tmp_path / "G")
    er.enable_turkish(er.analyze_game(tmp_path / "G", log=lambda s: None), True, log=lambda s: None)
    (game / "zz_turkish_autoload.rpyc").write_bytes(b"x")
    er.enable_turkish(er.analyze_game(tmp_path / "G", log=lambda s: None, language="German"), True, log=lambda s: None)
    names = {p.name for p in game.glob("zz_*")}
    assert names == {"zz_capri_german_autoload.rpy"}
    assert er.analyze_game(tmp_path / "G", log=lambda s: None).loose_rpy == 1, "destek betiği oyun betiği sayılmamalı"


def test_renpy_templates_get_target_language_and_no_turkish_tables(tmp_path, monkeypatch):
    import engine_renpy as er
    tl = tmp_path / "game" / "tl" / "German"
    tl.mkdir(parents=True)
    (tl / "script.rpy").write_text('translate German start_1:\n\n    # "Hello there"\n    ""\n', encoding="utf-8")
    seen = {}

    def fake(missing, cache, cache_path, api_key, log, progress, failed_out, extra_instruction, target_lang, source_lang):
        seen.update(target=target_lang, source=source_lang)
        cache.update({m: "Hallo" for m in missing})

    monkeypatch.setattr(er, "translate_with_gemini", fake)
    monkeypatch.setattr(er, "load_gemini_api_key", lambda: "k")
    assert er.translate_templates(tl, tmp_path, tmp_path / "c.json", None, log=lambda s: None, model_kind="gemini",
                                  target_lang="de", source_lang="en") == 1
    assert seen == {"target": "de", "source": "en"} and '"Hallo"' in (tl / "script.rpy").read_text(encoding="utf-8")


def test_font_check_uses_target_language_chars(tmp_path, monkeypatch):
    from engine_common import FontChecker
    monkeypatch.setattr(FontChecker, "_read_cmap", staticmethod(lambda p: {ord(c) for c in "äöüß"}))
    font = tmp_path / "f.ttf"
    font.write_bytes(b"x")
    assert FontChecker.check_turkish_support(font, "äöüß")["fully_supported"] is True
    assert FontChecker.check_turkish_support(font)["fully_supported"] is False


def test_ollama_prompt_follows_target_language():
    from engine_common import OllamaTranslationEngine
    assert "Türkçe" in OllamaTranslationEngine()._system_prompt()
    prompt = OllamaTranslationEngine(target_lang="de")._system_prompt()
    assert "German" in prompt and "§SEP§" in prompt


# ── Unreal IoStore ───────────────────────────────────────────────────────────
def test_retoc_listing_and_extraction(tmp_path, monkeypatch):
    import unreal_pak
    paks = tmp_path / "Paks"
    paks.mkdir()
    (paks / "a.utoc").write_bytes(b"x")
    calls = []

    def fake(args, aes_key="", timeout=600):
        calls.append((args, aes_key))
        if args[0] == "list":
            return ("pakchunk0                      " + "ab" * 12 + " ExportBundleData     ../../../G/Content/Map.uasset\n"
                    "pakchunk0                      " + "cd" * 12 + " ExternalFile         ../../../G/Content/Localization/Game/en/Game.locres\n"
                    "pakchunk0                      " + "ef" * 12 + " ExternalFile         ../../../G/Content/Localization/Game/fr/Game.locres\n")
        Path(args[3]).write_bytes(b"LOC")
        return ""

    monkeypatch.setattr(unreal_pak, "run_retoc", fake)
    found = unreal_pak.find_iostore_localization(paks, "en", "0xK")
    assert found == {paks / "a.utoc": [("cd" * 12, "G/Content/Localization/Game/en/Game.locres")]}
    files = unreal_pak.extract_iostore(found, tmp_path / "out", "0xK")
    assert [p.relative_to(tmp_path / "out").as_posix() for p in files] == ["G/Content/Localization/Game/en/Game.locres"]
    assert calls[-1] == (["get", str(paks / "a.utoc"), "cd" * 12, str(files[0].resolve())], "0xK")
    unsafe = {paks / "a.utoc": [("00" * 12, "../../kacis.locres")]}
    unreal_pak.extract_iostore(unsafe, tmp_path / "out2")
    assert not (tmp_path / "kacis.locres").exists(), "dışarı yazma engellenmeli"


def test_retoc_is_installed_only_after_consent(tmp_path, monkeypatch, fake_ollama):
    import providers
    import unreal_pak
    root = tmp_path / "UE"
    (root / "Engine").mkdir(parents=True)
    (root / "G" / "Binaries").mkdir(parents=True)
    paks = root / "G" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / "c.pak").write_bytes(b"P")
    (paks / "c.utoc").write_bytes(b"U")
    monkeypatch.setattr(unreal_pak, "TOOLS_DIR", tmp_path / "t")
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "repak.exe").write_bytes(b"MZ")
    monkeypatch.setattr(unreal_pak, "RETOC_DIR", tmp_path / "r")
    monkeypatch.setattr(unreal_pak, "run", lambda args, aes_key="", timeout=600: "")
    installed = []
    monkeypatch.setattr(unreal_pak, "install_retoc", lambda log=print: installed.append(1))
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append(text) or False)
    bridge._select_game(str(root))
    run_sync(bridge, "translate")
    assert asked and "retoc" in asked[0] and not installed, "izin verilmeden kurulmamalı"


# ── Güncelleme notları ve sürüm otomasyonu ───────────────────────────────────
def test_whats_new_is_short_and_in_state(tmp_path, monkeypatch):
    state = make_bridge(tmp_path, monkeypatch).get_state()
    assert state["whats_new"] and all(len(line) < 90 for line in state["whats_new"])
    assert state["version"] == app_modern.APP_VERSION


def _build_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_exe", SRC.parent / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_notes_are_short_plain_list():
    notes = _build_module().release_notes().splitlines()
    assert notes == [f"- {item}" for item in app_modern.WHATS_NEW] and len(notes) <= 10
    assert not any(mark in line for line in notes for mark in ("#", "**", "`"))


def test_update_notes_are_cleaned_for_display():
    import updater
    body = ("### Düzeltmeler\n- **Çeviri:** `→` hatası\n  (alt satır) düzeldi\n\n"
            "### Arayüz\n* [Bağlantı](http://x) metni\nDüz satır\n")
    assert updater.clean_notes(body) == ["Çeviri: → hatası (alt satır) düzeldi", "Bağlantı metni", "Düz satır"]
    assert len(updater.clean_notes("\n".join(f"- m{i}" for i in range(30)))) == 12
    assert updater.clean_notes("") == []


def test_signing_is_optional_and_uses_certificate(tmp_path, monkeypatch):
    build = _build_module()
    monkeypatch.delenv("CAPRI_SIGN_PFX", raising=False)
    assert build.sign(tmp_path / "Capri.exe") is False
    calls = []
    monkeypatch.setenv("CAPRI_SIGN_PFX", "c.pfx")
    monkeypatch.setenv("CAPRI_SIGN_PASSWORD", "gizli")
    monkeypatch.setattr(build, "find_signtool", lambda: "signtool")
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, check: calls.append(cmd))
    assert build.sign(tmp_path / "Capri.exe") is True
    assert calls[0][:2] == ["signtool", "sign"] and "c.pfx" in calls[0] and "/tr" in calls[0]


def test_workflows_are_valid_yaml():
    yaml = pytest.importorskip("yaml")
    folder = SRC.parent / ".github" / "workflows"
    release = yaml.safe_load((folder / "release.yml").read_text(encoding="utf-8"))
    test = yaml.safe_load((folder / "test.yml").read_text(encoding="utf-8"))
    assert release["permissions"] == {"contents": "write"} and test["jobs"]["test"]["runs-on"] == "windows-latest"
    assert any("--check-tag" in step.get("run", "") for step in release["jobs"]["release"]["steps"])


def test_folder_names_become_readable_titles(tmp_path):
    assert app_modern.readable_folder_name(Path("C:/G/Demo.Oyun.3/game")) == "Demo Oyun 3"
    assert app_modern.readable_folder_name(Path("C:/G/My_Cool.Game")) == "My Cool Game"
    assert app_modern.readable_folder_name(Path("C:/G/Dune Awakening")) == "Dune Awakening"


def test_folder_named_content_is_not_unreal(tmp_path):
    from engine_unreal import detect_unreal_game
    root = tmp_path / "Zomboid"
    (root / "steamapps" / "content").mkdir(parents=True)
    (root / "Zomboid.exe").write_bytes(b"MZ")
    assert detect_unreal_game(root) is None
    real = tmp_path / "Real"
    (real / "G" / "Content" / "Paks").mkdir(parents=True)
    (real / "G" / "Content" / "Paks" / "a.pak").write_bytes(b"P")
    assert detect_unreal_game(real).game_project_name == "G"


def test_second_instance_does_not_share_ui_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as first:
        first.bind(("127.0.0.1", 0))
        first.listen(1)
        busy = first.getsockname()[1]
        assert app_modern.free_ui_port(busy) != busy
    assert app_modern.free_ui_port(busy) == busy, "boşsa aynı port kullanılmalı (yerel veriler adrese bağlı)"


# ── Güncelleyici: konsolsuz, yarım kalmayan kurulum ──────────────────────────
def _staged(tmp_path, files):
    staged = tmp_path / "staged"
    for rel, data in files.items():
        (staged / rel).parent.mkdir(parents=True, exist_ok=True)
        (staged / rel).write_bytes(data)
    return staged


def test_install_staged_replaces_files_and_keeps_user_data(tmp_path):
    import updater
    app = tmp_path / "app"
    (app / "_internal").mkdir(parents=True)
    (app / "Capri.exe").write_bytes(b"old")
    (app / "_internal" / "a.dll").write_bytes(b"old")
    (app / "portable_cache").mkdir()
    (app / "portable_cache" / "settings.json").write_text("{}", encoding="utf-8")
    staged = _staged(tmp_path, {"Capri.exe": b"new", "_internal/a.dll": b"new", "_internal/b.dll": b"new",
                                "portable_cache/settings.json": b"EZME", "data/glossary.json": b"EZME"})
    assert updater.install_staged(staged, app, log=lambda s: None) == 3
    assert (app / "Capri.exe").read_bytes() == b"new" and (app / "_internal" / "b.dll").read_bytes() == b"new"
    assert (app / "portable_cache" / "settings.json").read_text(encoding="utf-8") == "{}" and not (app / "data").exists()
    assert not list(app.rglob("*.capri-*")), "geçici dosya kalmamalı"


def test_install_staged_rolls_back_when_a_file_stays_locked(tmp_path, monkeypatch):
    import os
    import updater
    app = tmp_path / "app"
    app.mkdir()
    (app / "Capri.exe").write_bytes(b"old-exe")
    (app / "z.dll").write_bytes(b"old-dll")
    staged = _staged(tmp_path, {"Capri.exe": b"new-exe", "z.dll": b"new-dll"})
    real_replace = os.replace

    def locked(src, dst):
        if str(src).endswith("z.dll"):
            raise PermissionError("kilitli")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", locked)
    monkeypatch.setattr(updater, "_retry", lambda action, seconds=15: action())
    with pytest.raises(PermissionError):
        updater.install_staged(staged, app, log=lambda s: None)
    monkeypatch.setattr(updater.os, "replace", real_replace)
    assert (app / "Capri.exe").read_bytes() == b"old-exe" and (app / "z.dll").read_bytes() == b"old-dll", "yarım güncelleme kalmamalı"
    assert not list(app.glob("*.capri-new"))


def test_update_result_is_reported_once_and_cleaned(tmp_path, monkeypatch):
    import updater
    monkeypatch.setattr(updater, "STAGING_DIR", tmp_path / "portable_cache" / "update")
    (tmp_path / "portable_cache" / "update" / "9.9.9").mkdir(parents=True)
    (tmp_path / "x.capri-old").write_bytes(b"x")
    (tmp_path / "portable_cache" / updater.RESULT_FILE).write_text('{"ok": true, "to": "9.9.9"}', encoding="utf-8")
    assert updater.take_result(tmp_path) == {"ok": True, "to": "9.9.9"}
    assert updater.take_result(tmp_path) is None
    assert not (tmp_path / "portable_cache" / "update").exists() and not (tmp_path / "x.capri-old").exists()


def test_apply_update_uses_helper_not_batch_file(tmp_path, monkeypatch):
    import subprocess
    import updater
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(app_modern, "FROZEN", True)
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / Path(sys.executable).name).write_bytes(b"MZ")
    monkeypatch.setattr(updater, "stage", lambda *a, **k: staged)
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw)))
    monkeypatch.setattr(bridge, "win_close", lambda: None)
    monkeypatch.setattr(app_modern.time, "sleep", lambda s: None)
    monkeypatch.setattr(app_modern.threading, "Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    bridge._update_info = {"available": True, "asset": "http://x/C.zip", "latest": "9.9.9"}
    run_sync(bridge, "apply_update")
    cmd, kw = launched[0]
    assert cmd[0].endswith(Path(sys.executable).name) and "--apply-update" in cmd and "cmd" not in Path(cmd[0]).name.lower()
    assert ("update_progress", {"installing": True}) in bridge._ui.events


# ── Gemini: zaman aşımı, kota ve hız ─────────────────────────────────────────
def _fake_gemini(monkeypatch, behaviour):
    import io
    import urllib.error
    import engine_renpy as er
    import providers
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        body = json.loads(req.data)
        items = json.loads(body["contents"][0]["parts"][0]["text"].split("liste:\n", 1)[1])
        model = req.full_url.split("/models/")[1].split(":")[0]
        calls.append((model, len(items), timeout, body["generationConfig"]))
        outcome = behaviour(model, len(calls))
        if isinstance(outcome, int):
            text = b"generateRequestsPerDay limit" if outcome == 4290 else b"{}"
            raise urllib.error.HTTPError(req.full_url, 429 if outcome == 4290 else outcome, "x", {}, io.BytesIO(text))
        reply = {"candidates": [{"content": {"parts": [{"text": json.dumps([f"TR {i}" for i in items])}]}}]}
        return Resp(json.dumps(reply).encode())

    monkeypatch.setattr(er.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(er, "load_gemini_api_keys", lambda: ["k1", "k2"])
    monkeypatch.setattr(er.time, "sleep", lambda s: None)
    monkeypatch.setattr(providers, "gemini_model_order", lambda *a: ["gemini-2.5-flash-lite", "gemini-2.5-flash"])
    monkeypatch.setattr(providers, "note_gemini_success", lambda m: None)
    monkeypatch.setattr(er, "_write_cache_file", lambda *a, **k: None)
    return er, calls


def test_gemini_uses_long_timeout_small_batches_and_parallel_requests(tmp_path, monkeypatch):
    er, calls = _fake_gemini(monkeypatch, lambda model, n: "ok")
    cache, progress = {}, []
    lines = [f"line {i}" for i in range(200)]
    er.translate_with_gemini(lines, cache, tmp_path / "c.json", "k1", log=lambda s: None,
                             progress=lambda d, t: progress.append(d))
    assert len(cache) == 200 and all(n <= er.GEMINI_BATCH for _m, n, _t, _c in calls)
    assert all(t >= 60 for _m, _n, t, _c in calls), "uzun parti erken kesilmemeli"
    assert progress[0] == 0 and progress[-1] == 200 and len(progress) >= 5, "ilerleme sık güncellenmeli"


def test_gemini_flash_runs_without_thinking(tmp_path, monkeypatch):
    er, calls = _fake_gemini(monkeypatch, lambda model, n: 429 if "lite" in model else "ok")
    er.translate_with_gemini(["a", "b"], {}, tmp_path / "c.json", "k1", log=lambda s: None)
    flash = [c for m, _n, _t, c in calls if m == "gemini-2.5-flash"]
    assert flash and flash[0]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_daily_quota_stops_with_clear_error(tmp_path, monkeypatch):
    import user_errors
    er, calls = _fake_gemini(monkeypatch, lambda model, n: 4290)
    with pytest.raises(er.GeminiQuotaExhausted) as raised:
        er.translate_with_gemini([f"l{i}" for i in range(100)], {}, tmp_path / "c.json", "k1", log=lambda s: None)
    assert user_errors.describe_error(raised.value)["title"] == "API kotası doldu"
    assert len(calls) < 40, "kota dolunca sonsuz denemeye girmemeli"


# ── Yol haritası: maliyet, sözlük, oyna, kalite, yazı tipi ───────────────────
def test_cost_estimate_for_paid_providers_only():
    from progress import estimate_cost
    assert estimate_cost("gemini", "", 100_000) is None and estimate_cost("opus", "", 100_000) is None
    assert estimate_cost("openai", "bilinmeyen-model", 100_000) is None
    mini = estimate_cost("openai", "gpt-4o-mini", 1_000_000)
    assert 0 < mini["usd"] < 1 and "$" in mini["text"]
    assert estimate_cost("anthropic", "claude-sonnet-4-5", 1_000_000)["usd"] > mini["usd"]
    assert estimate_cost("deepl", "", 1_000_000)["usd"] == pytest.approx(25)
    assert estimate_cost("openai", "gpt-4o-mini", 100)["text"] == "1 sentten az"


@pytest.mark.parametrize("name,content,expected", [
    ("s.json", '{"_aciklama": "x", "Save": "Kaydet", "Load": "Yükle"}', [["Save", "Kaydet"], ["Load", "Yükle"]]),
    ("s.json", '[["Save", "Kaydet"], ["bos", ""]]', [["Save", "Kaydet"]]),
    ("s.csv", "kaynak,çeviri\nSave,Kaydet\n\"Hi, you\",\"Selam, sen\"\n", [["Save", "Kaydet"], ["Hi, you", "Selam, sen"]]),
])
def test_glossary_files_are_parsed(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    assert app_modern.parse_glossary_file(path) == expected


def test_play_finds_the_game_executable(tmp_path, monkeypatch):
    import subprocess
    bridge = make_bridge(tmp_path, monkeypatch)
    game = make_rpgmaker_game(tmp_path / "game")
    (game / "Game.exe").write_bytes(b"MZ" * 100)
    (game / "unins000.exe").write_bytes(b"MZ" * 1000)
    bridge._select_game(str(game))
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw["cwd"])))
    assert bridge.play_game() is True and Path(started[0][0][0]).name == "Game.exe"


def test_quality_pairs_fix_only_flagged_lines_with_valid_edits():
    import engine_renpy as er
    sources = ["Open the gate.", "The storm came {b}fast{/b}.", "Good morning."]
    drafts = {"Open the gate.": "Open the gate.", "The storm came {b}fast{/b}.": "Fırtına {b}hızlı{/b} geldi.",
              "Good morning.": "Günaydın."}
    seen = {}

    def complete(system, user):
        seen["system"], seen["items"] = system, json.loads(user)
        return json.dumps([{"id": 0, "tr": "Kapıyı aç."}])

    edits = er.quality_edit_pairs(sources, drafts, complete, target_lang="de", log=lambda s: None)
    assert edits == {"Open the gate.": "Kapıyı aç."}
    assert [i["en"] for i in seen["items"]] == ["Open the gate."] and "German" in seen["system"]
    assert er.quality_system("tr") == er.QUALITY_SYSTEM_TR


def test_cjk_font_is_used_and_copied_for_renpy(tmp_path):
    import engine_renpy as er
    from engine_common import FontChecker
    game = tmp_path / "G" / "game"
    (game / "gui").mkdir(parents=True)
    (tmp_path / "G" / "Oyun.exe").write_bytes(b"MZ")
    (game / "script.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")
    (game / "gui" / "main.ttf").write_bytes(b"x")
    noto = tmp_path / "NotoSansJP-Regular.otf"
    noto.write_bytes(b"OTF")
    info = er.analyze_game(tmp_path / "G", log=lambda s: None, language="Japanese")
    info.tl_dir.mkdir(parents=True)
    original = FontChecker._read_cmap
    FontChecker._read_cmap = staticmethod(lambda p: set())
    try:
        er.enable_turkish(info, True, log=lambda s: None, fallback_font=noto)
    finally:
        FontChecker._read_cmap = original
    script = info.support_file.read_text(encoding="utf-8")
    assert "NotoSansJP-Regular.otf" in script and "DejaVu" not in script
    assert (game / "NotoSansJP-Regular.otf").exists() and (info.tl_dir / "main.ttf").read_bytes() == b"OTF"


def test_attention_flashes_only_when_in_background(monkeypatch):
    import ocr
    monkeypatch.setattr(ocr, "own_window", lambda title="Capri": 1234)
    flashed = []
    fake = type("U", (), {"GetForegroundWindow": staticmethod(lambda: 1234),
                          "FlashWindowEx": staticmethod(lambda info: flashed.append(1)),
                          "MessageBeep": staticmethod(lambda t: None)})
    monkeypatch.setattr(ocr, "_user32", fake)
    assert ocr.attention() is False and not flashed
    fake.GetForegroundWindow = staticmethod(lambda: 99)
    assert ocr.attention() is True and flashed
