"""
WOLF RPG: harita (.mps) ve CommonEvent.dat çözümleme/yazma. Dosyalar burada biçime göre küçük örnekler olarak
üretilir (2.x Shift-JIS düz, 3.x UTF-8 + LZ4). Ayrıca WOLF RPG Editor 2.281 ve 3.737'nin örnek oyunundaki bütün
harita ve ortak olay dosyaları elle doğrulandı (depoya eklenmedi).
"""
import struct

import lz4.block
import pytest

import app_modern
import engine_wolf as ew
import providers
import wolf_formats as wf
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401 (fixture)


def s(text, utf8):
    raw = text.encode("utf-8" if utf8 else "cp932") + b"\0"
    return struct.pack("<I", len(raw)) + raw


def cmd(code, ints=(), strings=(), utf8=True, move=False, v35=False):
    out = bytes([len(ints) + 1]) + struct.pack("<I", code) + b"".join(struct.pack("<I", i) for i in ints)
    out += b"\x00" + bytes([len(strings)]) + b"".join(s(t, utf8) for t in strings)
    if move:
        out += b"\x01" + bytes(5) + b"\x00" + struct.pack("<I", 1) + b"\x03\x01" + struct.pack("<I", 7) + b"\x01\x00"
    else:
        out += b"\x00"
    if v35:
        out += b"\x02\xaa\xbb"
    return out


def commands(utf8, v35=False):
    items = [cmd(101, (), ["@1\nHello \\cself[1]!"], utf8, v35=v35), cmd(102, (2,), ["Take the sword", "Leave it"], utf8, v35=v35),
             cmd(150, (2 << 4, 1), ["Menu"], utf8, v35=v35), cmd(150, (0, 1), ["pic.png"], utf8, v35=v35),
             cmd(122, (5,), ["flag_key"], utf8, v35=v35), cmd(201, (0,), (), utf8, move=True, v35=v35),
             cmd(0, (), (), utf8, v35=v35)]
    return struct.pack("<I", len(items)) + b"".join(items)


def page(utf8, v35=False):
    out = struct.pack("<I", 0) + s("", utf8) + bytes(4) + bytes(37) + bytes(4) + b"\x00\x00"
    out += struct.pack("<I", 1) + b"\x02\x00\x01\x00"            # bir rota komutu
    out += commands(utf8, v35) + struct.pack("<I", 0) + bytes(3) + b"\x7a"
    return out


def make_map(utf8=False, v3=False):
    w, h, layers = 2, 2, 3
    body = s("", utf8) + struct.pack("<IIII", 1, w, h, 1)
    if v3:
        body += struct.pack("<II", 0, layers)
    body += bytes(w * h * layers * 4)
    body += b"\x6f" + b"\x39\x30\x00\x00" + struct.pack("<I", 1) + s("EV001", utf8) + struct.pack("<III", 1, 1, 1)
    body += bytes(4) + b"\x79" + page(utf8, v3) + b"\x70" + b"\x66"
    magic = bytearray(wf.MAP_MAGIC)
    if utf8:
        magic[16] = 0x55
    version = 0x67 if v3 else 0x64
    head = bytes(magic) + struct.pack("<I", version) + b"\x00"
    if v3:
        packed = lz4.block.compress(body, store_size=False)
        return head + struct.pack("<II", len(body), len(packed)) + packed
    return head + body


def make_common(utf8=False, v3=False):
    ev = b"\x8e" + struct.pack("<II", 0, 0) + bytes(7) + s("Ortak", utf8) + commands(utf8, v3) + s("", utf8) + s("desc", utf8)
    ev += b"\x8f" + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 0) + bytes(0x1D)
    ev += b"".join(s("", utf8) for _ in range(100)) + b"\x91" + s("", utf8) + b"\x91"
    body = struct.pack("<I", 1) + ev + b"\x8a"
    magic = bytearray(wf.COMMON_MAGIC)
    if utf8:
        magic[5] = 0x55
    head = b"\x00" + bytes(magic) + bytes([0x93 if v3 else 0x8f])
    if v3:
        packed = lz4.block.compress(body, store_size=False)
        return head + struct.pack("<II", len(body), len(packed)) + packed
    return head + body


@pytest.mark.parametrize("utf8, v3", [(False, False), (True, True)])
def test_map_and_common_events_parse_and_rebuild(utf8, v3):
    for kind, data in (("map", make_map(utf8, v3)), ("common", make_common(utf8, v3))):
        doc = wf.parse(kind, data)
        assert doc.utf8 == utf8 and doc.compressed == v3
        assert [(x.context, x.text) for x in doc.slots] == [
            ("dialogue", "@1\nHello \\cself[1]!"), ("choice", "Take the sword"), ("choice", "Leave it"), ("ui", "Menu")], \
            "dize değişkeni (122) ve dosya adlı resim çevrilmez"
        new, changed, lossy = wf.rebuild(doc, {"Take the sword": "Kılıcı al", "Menu": "Menü", "@1\nHello \\cself[1]!": "@1\nMerhaba \\cself[1]!"})
        assert changed == 3 and lossy == (0 if utf8 else 2)
        again = wf.parse(kind, new)
        assert [x.text for x in again.slots] == ["@1\nMerhaba \\cself[1]!", "Kılıcı al" if utf8 else "Kilici al",
                                                 "Leave it", "Menü" if utf8 else "Menu"]
        assert wf.rebuild(doc, {})[0] is None


def test_structure_errors_are_detected():
    data = bytearray(make_map())
    data[-1] = 0x00                                       # harita sonu bozuk
    with pytest.raises(wf.WolfFormatError):
        wf.parse("map", bytes(data))
    with pytest.raises(wf.WolfFormatError):
        wf.parse("common", make_common()[:-30])
    encrypted = b"\x00\x50" + bytes(40)
    assert wf.parse("common", encrypted).encrypted


def test_sjis_fallback_keeps_text_readable():
    raw, lost = wf.encode("Gülüşmeler ıssız çöl", False, b"x\0")
    assert lost and raw == "Gulusmeler issiz col".encode("cp932") + b"\0"
    assert wf.encode("こんにちは", False, b"\0") == ("こんにちは".encode("cp932") + b"\0", False)


def _game(root, utf8=True, v3=True):
    (root / "Data" / "BasicData").mkdir(parents=True)
    (root / "Data" / "MapData").mkdir()
    (root / "Data" / "BasicData" / "CommonEvent.dat").write_bytes(make_common(utf8, v3))
    (root / "Data" / "MapData" / "Map001.mps").write_bytes(make_map(utf8, v3))
    (root / "Game.exe").write_bytes(b"MZ")
    return root


def test_bridge_end_to_end_and_restore(tmp_path, monkeypatch, fake_ollama):
    root = _game(tmp_path / "Wolf")
    before = {p: p.read_bytes() for p in (root / "Data").rglob("*") if p.is_file()}
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: True)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    assert bridge._select_game(str(root))["engine"] == "wolf"
    run_sync(bridge, "translate")
    doc = wf.parse("map", (root / "Data/MapData/Map001.mps").read_bytes())
    assert [x.text for x in doc.slots][1:3] == ["TR(Take the sword)", "TR(Leave it)"]
    assert bridge._library.get(str(root))["status"] == "translated"
    run_sync(bridge, "restore_backup", "")
    assert all(p.read_bytes() == data for p, data in before.items())


def test_unreadable_archive_is_reported(tmp_path, monkeypatch):
    root = tmp_path / "Packed"
    root.mkdir()
    (root / "Game.exe").write_bytes(b"MZ")
    (root / "Data.wolf").write_bytes(b"\x00" * 64)
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    assert bridge._game["type"] == "wolf" and "açamıyor" in bridge._game["analysis"]["advice"][0]["text"]
    assert bridge._game["analysis"]["lines"] == 0


def test_sjis_game_warns_about_letters(tmp_path, monkeypatch):
    root = _game(tmp_path / "Old", utf8=False, v3=False)
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    assert any("Shift-JIS" in a["text"] for a in bridge._game["analysis"]["advice"])
