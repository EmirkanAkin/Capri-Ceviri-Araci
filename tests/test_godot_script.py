"""
GDScript betiklerine gömülü metinler: düz metin (.gd), Godot 3 derlenmiş (.gdc, GDSC 13) ve Godot 4.3+ ikili
belirteçler (GDSC 101, zstd). İkili örnekler tests/data altındaki gerçek Godot 3.6.3 / 4.7.2 paketlerinden okunur.
"""
import json
import shutil
import struct
from pathlib import Path

import pytest

import engine_godot as eg
import godot_formats as gf
import godot_script as gs

DATA = Path(__file__).parent / "data"

SOURCE = '''extends Control
# "Bu yorum" çevrilmez
const SAVE := "user://save.json"
var lines = ["The door is locked.", 'You found a key!', """Multi
line text"""]
func _ready():
    $Label.text = "Hello, %s!" % name
    if Input.is_action_pressed("ui_accept"):
        emit_signal("door_opened")
    var node = get_node(^"Panel/Box")
    var key = &"item_key"
    $Title.text = "Start"
    print(r"C:\\raw\\path.txt")
    play("RunCycle")
    var tag = "PlayerController"
    var esc = "Tab\\there \\u00e7"
'''


def test_text_tokenizer_handles_quotes_escapes_and_prefixes():
    strings = gs.text_strings(SOURCE)
    assert "Bu yorum" not in " ".join(strings), "yorumlar atlanır"
    assert "Panel/Box" not in strings and "item_key" not in strings, "NodePath ve StringName dizeleri alınmaz"
    assert "Multi\nline text" in strings and "Tab\there ç" in strings
    assert "C:\\raw\\path.txt" in strings, "ham dizede kaçış çözülmez"
    shown = [s for s in strings if gs.is_display_text(s)]
    assert shown == ["The door is locked.", "You found a key!", "Multi\nline text", "Hello, %s!", "Start", "Tab\there ç"]


@pytest.mark.parametrize("text, ok", [
    ("Game Over", True), ("OK", True), ("Kapı kilitli.", True), ("扉は閉まっている。", True), ("Options", True),
    ("res://scenes/main.tscn", False), ("ui_accept", False), ("PlayerController", False), ("idle", False),
    ("#ff8800", False), ("%d/%d", False), ("SCORE_KEY=", False), ("player/hp", False), ("data.json", False),
    ("ITEM_SWORD", False), ("Level2", False), ("", False),
])
def test_display_text_filter(text, ok):
    assert gs.is_display_text(text) == ok


@pytest.mark.parametrize("fixture, expected", [
    ("godot3_demo.pck", ["tr_TR", "GREETING=", "GREETING", "\nMENU_START=", "MENU_START", "\nDRAWN=", "\n", "/result.txt"]),
    ("godot4_demo.pck", ["en", "CAPRI_RESULT GREETING=", "GREETING", "CAPRI_RESULT MENU_START=", "MENU_START",
                         "CAPRI_RESULT LABEL=", " | DRAWN=", "CAPRI_RESULT LOCALE="]),
])
def test_real_compiled_scripts(fixture, expected):
    data = gf.read_pck(DATA / fixture).read("main.gdc")
    assert gs.script_strings(data) == expected
    assert not [s for s in expected if gs.is_display_text(s)], "deneme betiğindeki kayıt/anahtar dizeleri metin sayılmaz"


def _gdc4(constants, compress=True):
    """Godot 4.3+ GDSC 101 biçiminde küçük bir betik (yalnızca tanımlayıcı ve sabit tabloları)."""
    def ident(s):
        return struct.pack("<I", len(s)) + b"".join(bytes(b ^ 0xB6 for b in struct.pack("<I", ord(c))) for c in s)

    def string(t, kind=4):
        raw = t.encode("utf-8")
        return struct.pack("<II", kind, len(raw)) + raw + bytes(-len(raw) % 4)

    body = struct.pack("<4I", 2, len(constants), 0, 0) + ident("Node") + ident("text")
    body += b"".join(string(c) if isinstance(c, str) else c for c in constants)
    if not compress:
        return b"GDSC" + struct.pack("<II", 101, 0) + body
    import zstandard
    return b"GDSC" + struct.pack("<II", 101, len(body)) + zstandard.ZstdCompressor().compress(body)


def test_godot4_binary_tokens_with_other_constant_types():
    consts = ["Welcome back!", struct.pack("<II", 2, 7), struct.pack("<I", 1 << 16 | 3) + struct.pack("<d", 1.5),
              struct.pack("<II", 21, 4) + b"name", struct.pack("<I", 0), "Bye."]
    for compress in (True, False):
        assert gs.binary_strings(_gdc4(consts, compress)) == ["Welcome back!", "Bye."]
    with pytest.raises(gs.GodotScriptError):
        gs.binary_strings(_gdc4([struct.pack("<I", 24)]))           # nesne sabiti olamaz
    with pytest.raises(gs.GodotScriptError):
        gs.binary_strings(b"GDSC" + struct.pack("<I", 42) + bytes(8))


def test_script_texts_are_extracted_and_written_to_the_patch(tmp_path):
    src = gf.read_pck(DATA / "godot4_demo.pck")
    files = {name: src.read(name) for name in src.entries}
    files["ui/dialog.gd"] = SOURCE.encode("utf-8")
    files["ui/hud.gdc"] = _gdc4(["Score", "Press any key to continue."])
    files["addons/plugin/tool.gd"] = b'var x = "Plugin text here."'
    root = tmp_path / "Demo"
    root.mkdir()
    gf.write_pck(root / "Demo.pck", files, src.engine)
    (root / "Demo.exe").write_bytes(b"MZ" + bytes(100))
    info = eg.detect_godot(root)
    units = eg.extract_texts(info, log=lambda m: None)
    script_units = {u.original: u.context for u in units if u.path in ("ui/dialog.gd", "ui/hud.gdc")}
    assert script_units == {"The door is locked.": "dialogue", "You found a key!": "dialogue",
                            "Multi\nline text": "dialogue", "Hello, %s!": "dialogue", "Start": "ui",
                            "Tab\there ç": "ui", "Score": "ui", "Press any key to continue.": "dialogue"}
    assert not any(u.path.startswith("addons/") for u in units), "eklenti betikleri atlanır"
    written = eg.write_translations(info, {"The door is locked.": "Kapı kilitli.", "Score": "Puan"},
                                    log=lambda m: None, units=units)
    assert written == 2
    patch = gf.read_pck(root / eg.PATCH_NAME)
    messages = json.loads(patch.read(eg.MESSAGES_PATH))
    assert messages["The door is locked."] == "Kapı kilitli." and messages["Score"] == "Puan"
    assert "ui/dialog.gd" not in patch.entries, "betiklerin kendisi değiştirilmez"
