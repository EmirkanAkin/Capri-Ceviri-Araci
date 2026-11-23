"""
Godot 3 / 4: paket okuma, çeviri tabloları (OptimizedTranslation / PHashTranslation), sahne yazıları ve yama.
tests/data altındaki iki küçük paket, Capri'nin kendi deneme projesinden gerçek Godot 4.7.2 ve 3.6.3 ile dışa
aktarılmıştır. Yamanın gerçek motorda çalıştığı (Türkçe ve İngilizce sistem dilinde) elle doğrulandı; burada aynı
arama yolu (özet → kova → metin) Python'da izlenir.
"""
import json
import shutil
import struct
from pathlib import Path

import pytest

import app_modern
import engine_godot as eg
import godot_formats as gf
import providers
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401 (fixture)

DATA = Path(__file__).parent / "data"


def _game(tmp_path, fixture, name="Demo"):
    root = tmp_path / name
    root.mkdir()
    shutil.copy(DATA / fixture, root / "Demo.pck")
    (root / "Demo.exe").write_bytes(b"MZ" + bytes(100))
    return root


@pytest.mark.parametrize("fixture, version, engine", [("godot4_demo.pck", 4, (4, 7, 2)), ("godot3_demo.pck", 1, (3, 6, 3))])
def test_real_packs_and_translation_tables(fixture, version, engine):
    pck = gf.read_pck(DATA / fixture)
    assert pck.version == version and pck.engine == engine and not pck.encrypted
    settings = gf.read_project_binary(pck.read("project.binary"))
    key = "internationalization/locale/translations" if engine[0] == 4 else "locale/translations"
    assert settings[key] == ["res://text.en.translation", "res://text.de.translation"]
    res = gf.read_resource(pck.read("text.en.translation"))
    assert res.type == ("OptimizedTranslation" if engine[0] == 4 else "PHashTranslation") and res.writable
    table = gf.optimized_table(res)
    assert table.lookup("GREETING") == "Hello, %s!" and table.lookup("MENU_START") == "Start Game"
    assert table.lookup("MISSING") is None
    de = gf.optimized_table(gf.read_resource(pck.read("text.de.translation")))
    assert de.locale == "de" and de.lookup("GREETING") == "Hallo"


def test_rebuilt_table_keeps_keys_and_layout():
    pck = gf.read_pck(DATA / "godot4_demo.pck")
    res = gf.read_resource(pck.read("text.en.translation"))
    table = gf.optimized_table(res)
    repl = {at: {"Hello, %s!": "Merhaba, %s!", "Start Game": "Oyuna başla"}.get(msg) for at, msg in table.messages()}
    data = gf.write_optimized(res, table.rebuilt({k: v for k, v in repl.items() if v}))
    again = gf.read_resource(data)
    new = gf.optimized_table(again)
    assert new.lookup("GREETING") == "Merhaba, %s!" and new.lookup("MENU_START") == "Oyuna başla"
    assert new.lookup("QUOTE") == 'He said "wait".', "çevrilmeyen girdi özgün metniyle kalır"
    assert new.hash_table == table.hash_table and len(new.bucket_table) == len(table.bucket_table)
    assert data.endswith(b"RSRC") and [n for n, *_ in again.props] == [n for n, *_ in res.props]


def test_smaz_and_hash_match_godot():
    assert gf.ot_hash(0, b"") == 0x1000193
    assert gf.smaz_decompress(bytes([254]) + b"X" + bytes([255, 2]) + b"abc" + bytes([1])) == b"Xabcthe"


def test_patch_pack_roundtrip_v1_and_v2(tmp_path):
    files = {"a.txt": b"hello", "capri_tr/messages.json": "{\"Ok\": \"Tamam\"}".encode()}
    for version, engine in ((1, (3, 6, 3)), (2, (4, 7, 2))):
        path = tmp_path / f"p{version}.pck"
        gf.write_pck(path, files, engine, version=version)
        pck = gf.read_pck(path)
        assert pck.version == version and {n: pck.read(n) for n in pck.entries} == files


def test_embedded_pack_in_executable(tmp_path):
    inner = tmp_path / "inner.pck"
    gf.write_pck(inner, {"project.binary": b"ECFG" + struct.pack("<I", 0)}, (4, 2, 0))
    blob = inner.read_bytes()
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ" + bytes(5000) + blob + struct.pack("<Q", len(blob)) + gf.PCK_MAGIC)
    pck = gf.read_pck(exe)
    assert pck.start == 5002 and pck.read("project.binary").startswith(b"ECFG")


def test_scene_texts_binary_and_text():
    pck = gf.read_pck(DATA / "godot4_demo.pck")
    scene = next(n for n in pck.entries if n.endswith(".scn"))
    assert eg.scene_texts(pck.read(scene)) == ["Options"]
    text = ('[gd_scene format=2]\n[node name="A" type="Label"]\ntext = "Two\nlines \\"quoted\\""\n'
            'rect_size = Vector2( 1, 2 )\n[node name="B" type="Button"]\nhint_tooltip = "Tip"\ntext = "123"\n'
            '[sub_resource type="X" id=1]\ntext = "not a node"\n')
    assert eg.text_scene_texts(text) == ['Two\nlines "quoted"', "Tip"]


def test_po_messages():
    po = ('msgid ""\nmsgstr ""\n"Language: en\\n"\n\nmsgid "Start"\nmsgstr "Start game"\n\n'
          'msgctxt "menu"\nmsgid "Open"\nmsgstr "Open it"\n\nmsgid "Multi"\nmsgstr ""\n"line one "\n"line two"\n')
    assert eg._po_messages(po) == {"Start": "Start game", "Multi": "line one line two"}


def test_override_merge_keeps_other_settings():
    assert eg.merge_override("", "C:/G/capri_tr.gd") == '[autoload]\n\nCapriTr="*C:/G/capri_tr.gd"\n'
    current = '[display]\nwindow/size=1\n\n[autoload]\nModLoader="*res://m.gd"\nCapriTr="*C:/old.gd"\n'
    merged = eg.merge_override(current, "C:/G/capri_tr.gd")
    assert merged.count("CapriTr=") == 1 and 'ModLoader="*res://m.gd"' in merged and "window/size=1" in merged
    assert merged.index("[autoload]") < merged.index("CapriTr=")


@pytest.mark.parametrize("fixture, script_mark", [("godot4_demo.pck", "path_join"), ("godot3_demo.pck", "File.new()")])
def test_detect_extract_and_write_patch(tmp_path, fixture, script_mark):
    root = _game(tmp_path, fixture)
    info = eg.detect_godot(root)
    assert info and info.source_locale == "en" and not info.encrypted
    units = eg.extract_texts(info)
    assert {u.original for u in units} == {"Hello, %s!", "Start Game", "Options"} | (
        {'He said "wait".'} if "4" in fixture else set())
    assert {u.kind for u in units if u.original == "Options"} == {"ui"}
    original = (root / "Demo.pck").read_bytes()
    written = eg.write_translations(info, {"Hello, %s!": "Merhaba, %s!", "Start Game": "Oyuna başla", "Options": "Seçenekler"})
    assert written == 3
    assert (root / "Demo.pck").read_bytes() == original, "oyunun paketine dokunulmaz"
    patch = gf.read_pck(root / eg.PATCH_NAME)
    table = gf.optimized_table(gf.read_resource(patch.read("text.en.translation")))
    assert table.lookup("GREETING") == "Merhaba, %s!"
    assert json.loads(patch.read(eg.MESSAGES_PATH)) == {"Options": "Seçenekler"}
    script = (root / eg.SCRIPT_NAME).read_text(encoding="utf-8")
    assert script_mark in script and '"res://text.en.translation"' in script and 'LOCALE = "en"' in script.replace(":= ", "= ")
    override = (root / "override.cfg").read_text(encoding="utf-8")
    assert f'CapriTr="*{(root / eg.SCRIPT_NAME).resolve().as_posix()}"' in override
    assert eg.detect_godot(root).pck_path.name == "Demo.pck", "yama paketi oyun paketi sanılmaz"


def test_bridge_translates_and_restore_removes_patch(tmp_path, monkeypatch, fake_ollama):
    root = _game(tmp_path, "godot4_demo.pck")
    (root / "override.cfg").write_text("[display]\nwindow/size/width=800\n", encoding="utf-8")
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: True)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    assert bridge._select_game(str(root))["engine"] == "godot"
    run_sync(bridge, "analyze")
    assert bridge._game["analysis"]["unique"] == 4
    run_sync(bridge, "translate")
    patch = gf.read_pck(root / eg.PATCH_NAME)
    table = gf.optimized_table(gf.read_resource(patch.read("text.en.translation")))
    assert table.lookup("MENU_START") == "TR(Start Game)"
    assert "window/size/width=800" in (root / "override.cfg").read_text(encoding="utf-8")
    assert bridge._library.get(str(root))["status"] == "translated"
    run_sync(bridge, "restore_backup", "")
    assert not (root / eg.PATCH_NAME).exists() and not (root / eg.SCRIPT_NAME).exists()
    assert (root / "override.cfg").read_text(encoding="utf-8") == "[display]\nwindow/size/width=800\n", \
        "oyunun kendi override.cfg'si geri gelir"


def test_encrypted_pack_is_reported(tmp_path, monkeypatch):
    root = tmp_path / "Locked"
    root.mkdir()
    head = gf.PCK_MAGIC + struct.pack("<4I", 2, 4, 2, 0) + struct.pack("<IQ", gf.PACK_DIR_ENCRYPTED, 0) + bytes(64)
    (root / "Locked.pck").write_bytes(head + bytes(64))
    (root / "Locked.exe").write_bytes(b"MZ")
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    assert bridge._game["analysis"]["lines"] == 0 and "şifreli" in bridge._game["analysis"]["advice"][0]["text"]
