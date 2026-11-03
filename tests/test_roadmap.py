"""
Yol haritası özellikleri: sürükle-bırak, çoklu monitör OCR, çok dilli yerel model,
kimlik bilgisi deposu, bağlamlı çeviri ve diğerleri.
"""
import json

import app_modern
from test_app import fake_ollama, make_bridge, make_rpgmaker_game, run_sync  # noqa: F401


# ── Sürükle-bırak ────────────────────────────────────────────────────────────
def test_open_dropped_folder_exe_and_invalid(tmp_path, monkeypatch):
    game = make_rpgmaker_game(tmp_path / "wrap" / "DropQuest")
    (game / "Game.exe").write_bytes(b"MZ")
    bridge = make_bridge(tmp_path, monkeypatch)
    analyzed = []
    monkeypatch.setattr(bridge, "analyze", lambda force=False: analyzed.append(1) or True)
    assert bridge.open_dropped(str(tmp_path / "wrap"))["title"] == "Demo Quest"  # sarmalayıcı klasör
    assert bridge.open_dropped(str(game / "Game.exe"))["engine"] == "rpgmaker"   # .exe → üst klasör
    assert bridge.open_dropped(str(tmp_path / "yok")) is None
    assert len(analyzed) == 2


def test_drop_event_emits_paths(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    handlers = {}

    class Events:
        def __getattr__(self, name):
            class Slot:
                def __iadd__(slot, handler):
                    handlers[name] = handler
                    return slot
            return Slot()

    class Doc:
        events = Events()

    class Dom:
        document = Doc()

    class Win:
        dom = Dom()

    bridge._window = Win()
    bridge._bind_drop()
    callback = handlers["drop"]._DOMEventHandler__callback
    callback({"dataTransfer": {"files": [{"name": "Game", "pywebviewFullPath": "C:\\Games\\Game"}]}})
    assert ("dropped", ["C:\\Games\\Game"]) in bridge._ui.events


# ── OCR çoklu monitör ────────────────────────────────────────────────────────
class _Win:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, a))


def test_ocr_uses_monitor_under_cursor_and_its_dpi(tmp_path, monkeypatch):
    import ocr
    bridge = make_bridge(tmp_path, monkeypatch)
    monitors = [
        {"phys": {"left": 0, "top": 0, "width": 2560, "height": 1440}, "x": 0, "y": 0, "w": 2560, "h": 1440, "scale": 1.0},
        {"phys": {"left": 2560, "top": 0, "width": 3840, "height": 2160}, "x": 2560, "y": 0, "w": 2560, "h": 1440, "scale": 1.5},
    ]
    monkeypatch.setattr(bridge, "_monitors", lambda: monitors)
    wins = {k: _Win() for k in ("select", "popup", "pin")}
    bridge.set_ocr_windows(wins, (2560, 1440), 1.0)
    grabbed = []
    monkeypatch.setattr(ocr, "cursor_pos", lambda: (4000, 500))  # ikinci monitör
    monkeypatch.setattr(ocr, "capture", lambda *a: grabbed.append(a) or ocr.Shot(b"\x00" * 16, 2, 2, a[0], a[1]))
    monkeypatch.setattr(ocr.OCR, "available", lambda: (True, "tr"))
    assert bridge.ocr_start("once")
    assert grabbed[0] == (2560, 0, 3840, 2160)
    assert ("move", (2560, 0)) in wins["select"].calls and ("resize", (2560, 1440)) in wins["select"].calls
    # İkinci monitördeki fiziksel (3000, 600) noktası → mantıksal 2560 + 440/1.5
    bridge._ocr_anchor["popup"] = (3000, 600, 900, 300)
    bridge._place("popup", 460, 150)
    move = [c for c in wins["popup"].calls if c[0] == "move"][-1][1]
    assert move == (2560 + int(441 / 1.5), int(601 / 1.5) + int(300 / 1.5) + 10)


# ── NLLB çok dilli + fp16 küçültülmüş model ──────────────────────────────────
def test_nllb_language_codes_and_switch():
    import engine_common
    eng = engine_common.TranslationEngine(model_dir=None, model_kind="nllb", source_lang="auto", target_lang="de")
    assert (eng.source_lang, eng.target_lang) == ("en", "de")

    class Tok:
        src_lang = None

        def convert_tokens_to_ids(self, token):
            return token

    eng._tokenizer = Tok()
    eng.set_languages("ja", "es")
    assert eng._tokenizer.src_lang == "jpn_Jpan" and eng._forced_bos == "spa_Latn"


def test_compact_model_status(tmp_path, monkeypatch):
    import providers
    m = tmp_path / "model_nllb"
    m.mkdir()
    for name, size in providers.NLLB_MODEL_FILES.items():
        if name != "pytorch_model.bin":
            (m / name).write_bytes(b"x" * size)
    with open(m / "model.safetensors", "wb") as f:
        f.truncate(providers.NLLB_MODEL_FILES["pytorch_model.bin"] // 2)
    monkeypatch.setattr(providers, "resolve_model_dir", lambda name: m)
    st = providers.get_offline_model_status("nllb")
    assert st["is_ready"] and st["compact"] and not st["missing_files"]


def test_bridge_allows_nllb_for_other_targets(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(app_modern.prov, "translate_single_text", lambda *a, **k: (True, "Hallo", 5))
    assert bridge.translate_text("Hello", "en", "de", "nllb")["ok"]
    assert not bridge.translate_text("Hello", "en", "de", "opus")["ok"]


# ── API anahtarları: Windows Kimlik Bilgisi Yöneticisi ───────────────────────
def test_plaintext_keys_migrate_to_credential_manager(tmp_path, monkeypatch):
    import providers
    import secrets_store
    if not secrets_store.available():
        return
    monkeypatch.setattr(secrets_store, "PREFIX", "CapriTest/")  # gerçek anahtarlara dokunma
    monkeypatch.setattr(providers, "CONFIG_FILE", tmp_path / "config_providers.json")
    monkeypatch.setattr(providers, "LEGACY_CONFIG_FILE", tmp_path / "eski_config.json")
    monkeypatch.setattr(providers, "GEMINI_LEGACY_FILE", tmp_path / "gemini_api_key.txt")
    monkeypatch.setattr(providers, "send_to_recycle_bin", lambda path: path.unlink() or True)
    for name in providers.SECRET_FIELDS:
        secrets_store.delete(name)
    try:
        providers.GEMINI_LEGACY_FILE.write_text("key-one\nkey-two\n", encoding="utf-8")
        providers.CONFIG_FILE.write_text(json.dumps({"openai_key": "sk-test", "active_provider": "openai"}), encoding="utf-8")
        cfg = providers.load_provider_config()
        assert cfg.gemini_keys == ["key-one", "key-two"] and cfg.openai_key == "sk-test"
        saved = json.loads(providers.CONFIG_FILE.read_text(encoding="utf-8"))
        assert saved["openai_key"] == "" and saved["gemini_keys"] == [] and saved["secrets"] == "windows-credential-manager"
        assert not providers.GEMINI_LEGACY_FILE.exists()
        again = providers.load_provider_config()
        assert again.gemini_keys == ["key-one", "key-two"] and again.active_provider == "openai"
    finally:
        for name in providers.SECRET_FIELDS:
            secrets_store.delete(name)


# ── Bağlamlı çeviri + oyuna özel sözlük ──────────────────────────────────────
def test_project_glossary_and_context_instruction(tmp_path, monkeypatch):
    game = make_rpgmaker_game(tmp_path / "game")
    (game / "www/data/Actors.json").write_text(json.dumps([None, {"name": "Elena", "nickname": "Kraliçe"}, {"name": "Marcus"}]), encoding="utf-8")
    bridge = make_bridge(tmp_path, monkeypatch, target="tr")
    bridge._select_game(str(game))
    res = bridge.project_scan_characters()
    assert res["ok"] and res["added"] == 3
    bridge.project_glossary_save([["Elena", "Elena"], ["Healing Potion", "Şifa İksiri"]], "siz", "Ortaçağ fantastik.")
    loaded = bridge.project_glossary_load()
    assert loaded["address"] == "siz" and ["Healing Potion", "Şifa İksiri"] in loaded["rows"]
    instr = bridge._extra_instruction()
    assert "'siz'" in instr and "Healing Potion → Şifa İksiri" in instr and "Ortaçağ fantastik." in instr
    assert bridge._glossary("glossary_rpgm.json").lookup("Healing Potion") == "Şifa İksiri"
    merged = json.loads(bridge._glossary_path().read_text(encoding="utf-8"))
    assert merged["Healing Potion"] == "Şifa İksiri" and "Save" in merged


def test_renpy_character_scan_reads_loose_and_rpa(tmp_path):
    import pickle
    import zlib
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text('define e = Character("Eileen", color="#c8ffc8")\ndefine m = Character(_("Mom"))\n', encoding="utf-8")
    payload = b'define l = Character("Lucy")\n'
    index = zlib.compress(pickle.dumps({"chars.rpy": [(51, len(payload))]}, protocol=2))
    with open(game / "archive.rpa", "wb") as f:
        offset = 51 + len(payload)
        f.write(f"RPA-3.0 {offset:016x} {0:08x}\n".encode().ljust(51, b" "))
        f.write(payload)
        f.write(index)
    assert app_modern.scan_renpy_characters(game) == ["Eileen", "Mom", "Lucy"]


def test_renpy_templates_keep_dialogue_order(tmp_path, monkeypatch):
    import engine_renpy
    tl = tmp_path / "tl"
    tl.mkdir()
    (tl / "a.rpy").write_text('translate Turkish a1:\n    # e "Zebra line."\n    e ""\n\ntranslate Turkish a2:\n    # e "Apple line."\n    e ""\n', encoding="utf-8")
    seen = {}

    def fake_gemini(missing, cache, cache_path, api_key, **kw):
        seen["order"], seen["extra"] = list(missing), kw.get("extra_instruction")
        cache.update({m: "TR " + m for m in missing})
        return len(missing)

    monkeypatch.setattr(engine_renpy, "translate_with_gemini", fake_gemini)
    monkeypatch.setattr(engine_renpy, "load_gemini_api_key", lambda: "k")
    engine_renpy.translate_templates(tl, tmp_path, tmp_path / "c.json", None, log=lambda s: None,
                                     model_kind="gemini", extra_instruction="Hitap: sen")
    assert seen["order"] == ["Zebra line.", "Apple line."] and seen["extra"] == "Hitap: sen"


# ── Ren'Py kalite editörü ────────────────────────────────────────────────────
def _quality_tl(tmp_path):
    tl = tmp_path / "tl"
    tl.mkdir()
    (tl / "s.rpy").write_text(
        'translate Turkish q1:\n\n    # e "I really missed you, my friend."\n    e "I really missed you, my friend."\n\n'
        'translate Turkish q2:\n\n    # e "{i}Where were you?{/i}"\n    e "{i}Where were you?{/i}"\n\n'
        'translate Turkish q3:\n\n    # e "Good morning."\n    e "Günaydın."\n', encoding="utf-8")
    return tl


def test_quality_editor_applies_only_valid_edits(tmp_path):
    import engine_renpy
    tl = _quality_tl(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"I really missed you, my friend.": "I really missed you, my friend."}), encoding="utf-8")
    calls = []

    def complete(system, user):
        items = json.loads(user)
        calls.append(len(items))
        out = []
        for item in items:
            if item["en"].startswith("I really"):
                out.append({"id": item["id"], "tr": "Seni gerçekten çok özledim dostum."})
            else:
                out.append({"id": item["id"], "tr": "Neredeydin?"})  # {i} etiketi düşmüş → reddedilmeli
        return json.dumps(out, ensure_ascii=False)

    res = engine_renpy.quality_edit_with_llm(tl, cache_path, complete, log=lambda s: None)
    text = (tl / "s.rpy").read_text(encoding="utf-8")
    assert res["edited"] == 1 and res["rejected"] == 1 and calls == [2]
    assert 'e "Seni gerçekten çok özledim dostum."' in text
    assert 'e "{i}Where were you?{/i}"' in text and 'e "Günaydın."' in text
    assert json.loads(cache_path.read_text(encoding="utf-8"))["I really missed you, my friend."].startswith("Seni")
    calls.clear()
    engine_renpy.quality_edit_with_llm(tl, cache_path, complete, log=lambda s: None)
    assert calls == [], "önbellekteki sonuçlar için modele tekrar gidilmemeli"


def test_quality_provider_selection(tmp_path, monkeypatch):
    import providers
    bridge = make_bridge(tmp_path, monkeypatch, model="deepl")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(gemini_keys=["k"]))
    assert bridge._quality_provider() == "gemini"
    bridge._settings["model"] = "ollama"
    assert bridge._quality_provider() == "ollama"


# ── BepInEx otomatik kurulum ─────────────────────────────────────────────────
def test_bepinex_asset_selection(monkeypatch):
    import bepinex_installer as bi
    releases = {
        "BepInEx/BepInEx": [
            {"tag_name": "v6.0.0-pre.2", "prerelease": True, "assets": [
                {"name": "BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip", "browser_download_url": "u6"}]},
            {"tag_name": "v5.4.23.6", "prerelease": False, "assets": [
                {"name": "BepInEx_win_x86_5.4.23.6.zip", "browser_download_url": "u5x86"},
                {"name": "BepInEx_win_x64_5.4.23.6.zip", "browser_download_url": "u5"}]},
        ],
        "bbepis/XUnity.AutoTranslator": [
            {"tag_name": "v5.6.3.1", "prerelease": False, "assets": [
                {"name": "XUnity.AutoTranslator-BepInEx-5.6.3.1.zip", "browser_download_url": "x5"},
                {"name": "XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.3.1.zip", "browser_download_url": "xi"}]},
        ],
    }
    monkeypatch.setattr(bi, "_releases", lambda repo: releases[repo])
    mono = bi.choose_assets("Mono", "x64")
    assert mono["bepinex"][1] == "u5" and mono["xunity"][1] == "x5"
    il2 = bi.choose_assets("IL2CPP", "x64")
    assert il2["bepinex"][1] == "u6" and il2["xunity"][1] == "xi"
    assert bi.choose_assets("Mono", "x86")["bepinex"][1] == "u5x86"


def test_bepinex_install_uninstall_roundtrip(tmp_path, monkeypatch):
    import io
    import zipfile
    import bepinex_installer as bi
    root = tmp_path / "Game"
    (root / "Game_Data" / "Managed").mkdir(parents=True)
    (root / "winhttp.dll").write_bytes(b"orijinal")

    def make_zip(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        path = tmp_path / f"{len(files)}_{abs(hash(tuple(files)))}.zip"
        path.write_bytes(buf.getvalue())
        return path

    zips = {"bepinex": make_zip({"winhttp.dll": b"yeni", "doorstop_config.ini": b"x", "BepInEx/core/BepInEx.dll": b"c",
                                 "../kacis.txt": b"zip-slip"}),
            "xunity": make_zip({"BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.Core.dll": b"p"})}
    monkeypatch.setattr(bi, "choose_assets", lambda runtime, arch: {k: (k, k, "v1") for k in zips})
    monkeypatch.setattr(bi, "_download", lambda name, url, log: zips[name])
    manifest = bi.install(root, log=lambda s: None)
    assert bi.is_installed(root) and (root / "winhttp.dll").read_bytes() == b"yeni"
    assert not (tmp_path / "kacis.txt").exists() and manifest["replaced"] == ["winhttp.dll"]
    bi.uninstall(root, log=lambda s: None)
    assert not (root / "BepInEx").exists() and (root / "winhttp.dll").read_bytes() == b"orijinal"
    assert not bi.is_installed(root)


# ── RPG Maker VX Ace / VX / XP (Ruby Marshal) ────────────────────────────────
def _vxace_game(root):
    import rgss_marshal as rm
    S, s = rm.Sym, (lambda t: rm.RString(t.encode(), ivars=[(rm.Sym(b"E"), True)]))

    def cmd(code, *params):
        return rm.RObject(S(b"RPG::EventCommand"), [(S(b"@code"), code), (S(b"@indent"), 0),
                                                    (S(b"@parameters"), rm.RArray(list(params)))])

    commands = rm.RArray([cmd(101, s(""), 0, 0, 2), cmd(401, s("Welcome, \\N[1]!")), cmd(102, rm.RArray([s("Yes"), s("No")]), 2),
                          cmd(402, 0, s("Yes")), cmd(355, s("p 'script'")), cmd(0)])
    page = rm.RObject(S(b"RPG::Event::Page"), [(S(b"@list"), commands), (S(b"@graphic"), rm.RUserDef(S(b"Table"), b"\x01\x00"))])
    event = rm.RObject(S(b"RPG::Event"), [(S(b"@name"), s("EV001")), (S(b"@pages"), rm.RArray([page]))])
    mapobj = rm.RObject(S(b"RPG::Map"), [(S(b"@display_name"), s("")), (S(b"@events"), rm.RHash([(1, event)]))])
    actor = rm.RObject(S(b"RPG::Actor"), [(S(b"@name"), s("Eric")), (S(b"@nickname"), s("The Brave")),
                                         (S(b"@character_name"), s("Actor1")), (S(b"@description"), s("A young hero."))])
    data = root / "Data"
    data.mkdir(parents=True)
    (data / "Map001.rvdata2").write_bytes(rm.dumps(mapobj))
    (data / "Actors.rvdata2").write_bytes(rm.dumps(rm.RArray([None, actor])))
    (root / "Game.exe").write_bytes(b"MZ")
    return data


def test_rgss_marshal_roundtrip_is_byte_exact(tmp_path):
    import rgss_marshal as rm
    data = _vxace_game(tmp_path / "g")
    for f in data.iterdir():
        raw = f.read_bytes()
        assert rm.dumps(rm.loads(raw)) == raw
    assert rm.loads(b"\x04\x08i\x02\xe8\x03") == 1000 and rm.dumps(-129) == b"\x04\x08i\xff\x7f" and rm.loads(rm.dumps(-257)) == -257


def test_vxace_extract_and_write_only_player_text(tmp_path):
    import engine_rpgmaker as er
    data = _vxace_game(tmp_path / "g")
    texts = {t.original: t.context for t in er.extract_texts_vxace(data, log=lambda s: None)}
    assert texts == {"Welcome, \\N[1]!": "dialogue", "Yes": "choice", "No": "choice",
                     "Eric": "database", "The Brave": "database", "A young hero.": "database"}
    er.write_translations_vxace(data, {"Welcome, \\N[1]!": "Hoş geldin, \\N[1]!", "Yes": "Evet", "A young hero.": "Genç bir kahraman."},
                                log=lambda s: None)
    after = {t.original for t in er.extract_texts_vxace(data, log=lambda s: None)}
    assert {"Hoş geldin, \\N[1]!", "Evet", "Genç bir kahraman.", "No"} <= after
    import rgss_marshal as rm
    actor = rm.loads((data / "Actors.rvdata2").read_bytes()).items[1]
    assert actor.get("@character_name").text == "Actor1", "dosya adı alanları çevrilmemeli"


def test_vxace_game_end_to_end(tmp_path, monkeypatch, fake_ollama):
    import providers
    import engine_rpgmaker as er
    root = tmp_path / "VXGame"
    data = _vxace_game(root)
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(root))
    assert bridge._game["type"] == "rpgmaker" and bridge._game["info"].engine_type == "vxace"
    run_sync(bridge, "analyze")
    assert bridge._game["analysis"]["unique"] == 6
    run_sync(bridge, "translate")
    after = {t.original for t in er.extract_texts_vxace(data, log=lambda s: None)}
    assert "TR(Welcome, \\N[1]!)" in after and "TR(Eric)" in after
    assert bridge.list_backups(), "çeviri öncesi .rvdata2 yedeği alınmalı"


# ── Güncelleme ───────────────────────────────────────────────────────────────
def test_updater_check_stage_and_script(tmp_path, monkeypatch):
    import threading
    import zipfile
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import updater
    pkg = tmp_path / "Capri-9.0.0.zip"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("Capri/Capri.exe", "MZ-9.0.0")
        zf.writestr("Capri/data/glossary.json", "{}")              # kullanıcı sözlüğü: atlanmalı
        zf.writestr("Capri/web/index.html", "<html></html>")
        zf.writestr("Capri/config_providers.json", "{}")          # kullanıcı verisi: atlanmalı
        zf.writestr("Capri/portable_cache/cache/x.json", "{}")    # kullanıcı verisi: atlanmalı
        zf.writestr("Capri/../kacis.txt", "x")                    # zip-slip: atlanmalı

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/releases/latest"):
                body = json.dumps({"tag_name": "v9.0.0", "html_url": "http://x/rel", "body": "Notlar",
                                   "assets": [{"name": pkg.name, "browser_download_url": f"{base}/pkg.zip"}]}).encode()
            else:
                body = pkg.read_bytes()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(updater, "API", base + "/repos/{repo}/releases/latest")
    monkeypatch.setattr(updater, "STAGING_DIR", tmp_path / "staging")
    try:
        info = updater.check("4.2.0", "kullanici/Capri")
        assert info["available"] and info["latest"] == "9.0.0" and info["asset"].endswith("pkg.zip")
        assert not updater.check("9.0.0", "kullanici/Capri")["available"]
        assert updater.check("1.0", "gecersiz depo")["error"]
        staged = updater.stage(info["asset"], info["latest"], log=lambda s: None)
        assert (staged / "Capri.exe").exists() and (staged / "web" / "index.html").exists()
        assert not (staged / "data").exists()
        assert not (staged / "config_providers.json").exists() and not (staged / "portable_cache").exists()
        assert not (tmp_path / "staging" / "kacis.txt").exists()
        script = updater.write_apply_script(staged, app_dir=tmp_path / "app", pid=1234).read_text(encoding="utf-8")
        assert "robocopy" in script and '"portable_cache"' in script and '"model_nllb"' in script and "1234" in script
        assert '"data"' in script and "Capri.pyw" in script   # kaynak koddan çalışırken yeniden açma komutu
    finally:
        server.shutdown()
    assert updater.parse_version("v4.10.0") > updater.parse_version("4.9.9")
