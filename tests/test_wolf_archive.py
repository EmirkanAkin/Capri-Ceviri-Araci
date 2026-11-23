"""
WOLF .wolf arşivleri (DXArchive 3/6/8 + WOLF şifreleri). Arşivler testte üretilir (wolf_dxa_writer). Çözücü ayrıca
WOLF 2.01, 2.10, 2.20, 2.225, 3.14 ve 3.50 ile dağıtılmış 17 ücretsiz oyunun arşivinde doğrulandı: 11.000'den fazla
dosyanın tamamı açıldı, resim/ses imzaları ve harita/veritabanı yapıları tuttu (oyun verisi depoya eklenmedi).
"""
import hashlib
import os
import random

import pytest

import engine_wolf as ew
import wolf_archive as wa
import wolf_formats as wf
from test_wolf import make_common, make_map
from test_app import fake_ollama  # noqa: F401 (fixture)
from wolf_dxa_writer import build_v56, build_v8, huffman_encode, lz_encode


def sample_files(seed=1):
    rnd = random.Random(seed)
    text = ("WOLF RPG のテストデータ。" * 300).encode("cp932")
    return {
        "BasicData/CommonEvent.dat": make_common(utf8=True, v3=True),
        "MapData/Map001.mps": make_map(utf8=True, v3=True),
        "MapData/ダンジョン.mps": make_map(utf8=True, v3=True),
        "Picture/big.bin": bytes(rnd.getrandbits(8) for _ in range(5000)) + text,
        "Picture/zeros.bin": bytes(7000),
        "SE/tiny.ogg": b"OggS" + b"\x01" * 3,
        "readme.txt": text[:3000],
        "empty.txt": b"",
    }


def test_lz_and_huffman_round_trip():
    rnd = random.Random(7)
    for data in (b"", b"a", b"abcabcabcabcabcabc" * 50, bytes(rnd.getrandbits(8) for _ in range(4000)),
                 b"\x00" * 9000, bytes(range(256)) * 20):
        assert wa.lz_decode(lz_encode(data)) == data
        if data:
            assert wa.huffman_decode(huffman_encode(data)) == data
    with pytest.raises(wa.WolfArchiveError):
        wa.lz_decode(lz_encode(b"hello world hello world")[:-3] + b"\x00\x00\x00")


def test_chacha20_matches_rfc7539():
    key = bytes(range(32))
    nonce = bytes.fromhex("000000000000004a00000000")
    plain = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
             b"sunscreen would be it.")
    out = wa.chacha20_xor(plain, key, nonce, 0)
    assert out[:16].hex() == "6e2e359a2568f98041ba0728dd0d6981"
    assert out[-8:].hex() == "5af90bbf74a35be6b40b8eedf2785e42874d"[-16:]
    assert wa.chacha20_xor(out[70:], key, nonce, 70) == plain[70:], "konumdan başlayan çözme"


@pytest.mark.parametrize("label", ["WOLF 2.225", "WOLF 3.00", "WOLF 3.14", "WOLF 3.31", "WOLF 3.50", "WOLF ChaCha20"])
@pytest.mark.parametrize("mode", ["mixed", "lzhuff"])
def test_dxarchive8_versions(tmp_path, label, mode):
    files = sample_files()
    path = tmp_path / "Data.wolf"
    path.write_bytes(build_v8(files, label, mode=mode))
    arc = wa.open_archive(path)
    assert arc.label == label and arc.version == 8
    got = {e.path: wa.read_entry(arc, e) for e in arc.entries}
    assert got == files


@pytest.mark.parametrize("label, version", [("WOLF 2.20", 6), ("WOLF 2.10", 5), ("WOLF 2.01", 3), ("WOLF 2.10", 3)])
def test_old_dxarchive_versions(tmp_path, label, version):
    files = sample_files(2)
    path = tmp_path / "Data.wolf"
    path.write_bytes(build_v56(files, label, version=version))
    arc = wa.open_archive(path)
    assert arc.label == label and arc.version == version
    assert {e.path: wa.read_entry(arc, e) for e in arc.entries} == files


def test_protection_note_is_removed_and_pro_is_refused(tmp_path):
    db = b"\x00W\x00\x00OLUFM\x00\xc4"
    files = {"BasicData/DataBase.dat": wa.ANTI_UNPACK + db, "Picture/a.png": wa.ANTI_UNPACK + b"x",
             "Picture/fill.bin": os.urandom(2048)}
    path = tmp_path / "Data.wolf"
    path.write_bytes(build_v8(files, "WOLF 3.50"))
    arc = wa.open_archive(path)
    got = {e.path: wa.read_entry(arc, e) for e in arc.entries}
    assert got["BasicData/DataBase.dat"] == db, "veritabanı dosyalarındaki çıkarma notu kaldırılır"
    assert got["Picture/a.png"] == wa.ANTI_UNPACK + b"x", "diğer dosyalara dokunulmaz"
    pro = bytearray(path.read_bytes())
    pro[46:48] = (1000).to_bytes(2, "little")                     # şifre sürümü ≥ 1000: WOLF Pro
    path.write_bytes(bytes(pro))
    with pytest.raises(wa.WolfArchiveError, match="Pro"):
        wa.open_archive(path)
    path.write_bytes(os.urandom(4096))
    with pytest.raises(wa.WolfArchiveError):
        wa.open_archive(path)


def _db_pair(utf8=True):
    """Küçük bir veritabanı: tür 0 → [ad (metin), simge (dosya), açıklama (metin), değer (sayı)]."""
    import struct
    enc = "utf-8" if utf8 else "cp932"

    def st(t):
        raw = t.encode(enc) + b"\0"
        return struct.pack("<I", len(raw)) + raw

    fields = ["Name", "Icon", "Description", "Price"]
    records = [("Potion", "Picture/potion.png", "Heals 50 HP.\r\nUse in battle.", 10),
               ("Ether", "Picture/ether.png", "Restores SP.", 20),
               ("potion", "", "", 0)]                    # 'potion' bir dosya adıyla aynı → çevrilmez
    project = struct.pack("<I", 1) + st("Items") + struct.pack("<I", 4) + b"".join(st(f) for f in fields)
    project += struct.pack("<I", 3) + b"".join(st(r[0]) for r in records) + st("desc")
    project += struct.pack("<I", 100) + bytes([0, 1, 0, 0]) + bytes(96)
    project += struct.pack("<I", 4) + b"".join(st("") for _ in fields)
    project += struct.pack("<I", 4) + b"".join(struct.pack("<I", 0) for _ in fields)
    project += struct.pack("<I", 4) + b"".join(struct.pack("<I", 0) for _ in fields)
    project += struct.pack("<I", 4) + bytes(16)
    body = struct.pack("<I", 1) + b"\xfe\xff\xff\xff" + struct.pack("<II", 0, 4)
    body += struct.pack("<4I", 0x7D0, 0x7D1, 0x7D2, 0x3E8) + struct.pack("<I", 3)
    for name, icon, desc, price in records:
        body += struct.pack("<I", price) + st(name) + st(icon) + st(desc)
    magic = b"\x00W\x00\x00OL" + (b"U" if utf8 else b"\x00") + b"FM\x00"
    return magic + b"\xc1" + body + b"\xc1", project


def test_database_parse_and_rebuild():
    dat, project = _db_pair()
    doc = wf.parse("db", dat, project)
    assert [(s.text, s.context) for s in doc.slots] == [
        ("Potion", "ui"), ("Heals 50 HP.\r\nUse in battle.", "dialogue"), ("Ether", "ui"), ("Restores SP.", "ui"),
        ("potion", "ui")], "dosya türündeki alan (Icon) ve sayılar çevrilmez"
    new, changed, lossy = wf.rebuild(doc, {"Potion": "İksir", "Restores SP.": "SP yeniler."})
    again = wf.parse("db", new, project)
    assert changed == 2 and not lossy
    assert [s.text for s in again.slots][:4] == ["İksir", "Heals 50 HP.\r\nUse in battle.", "Ether", "SP yeniler."]
    with pytest.raises(wf.WolfFormatError):
        wf.parse("db", dat[:-5], project)


def _packed_game(root, label="WOLF 3.50"):
    dat, project = _db_pair()
    files = {"BasicData/CommonEvent.dat": make_common(True, True), "BasicData/Game.dat": b"\x00game",
             "BasicData/DataBase.dat": wa.ANTI_UNPACK + dat, "BasicData/DataBase.project": project,
             "MapData/Map001.mps": make_map(True, True), "Picture/potion.png": b"\x89PNG" + bytes(3000)}
    root.mkdir(parents=True)
    (root / "Game.exe").write_bytes(b"MZ")
    (root / "Data.wolf").write_bytes(build_v8(files, label))
    return root


def _hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_packed_game_preview_unpack_translate_and_restore(tmp_path):
    root = _packed_game(tmp_path / "Packed")
    before = _hashes(root)
    info = ew.detect_wolf(root)
    assert info.archived and info.archive_supported and info.archive_label == "WOLF 3.50"
    texts = ew.extract_texts(info, log=lambda m: None)
    originals = {t.original for t in texts}
    assert {"Take the sword", "Potion", "Heals 50 HP.\r\nUse in battle."} <= originals
    assert "potion" not in originals, "oyundaki bir dosyanın adıyla aynı veritabanı değeri korunur"
    assert _hashes(root) == before, "analiz oyun klasörüne dokunmaz"
    info = ew.unpack_archives(info, log=lambda m: None)
    assert not (root / "Data.wolf").exists() and (root / "Data/BasicData/DataBase.dat").read_bytes()[:2] == b"\x00W"
    written, _lossy = ew.write_translations(ew.detect_wolf(root), {"Potion": "İksir", "Take the sword": "Kılıcı al"},
                                            log=lambda m: None)
    assert written == 3                                    # harita ve ortak olaydaki seçenek + veritabanı adı
    again = {t.original for t in ew.extract_texts(ew.detect_wolf(root), log=lambda m: None)}
    assert {"İksir", "Kılıcı al"} <= again and "potion" not in again
    wa.restore(root, log=lambda m: None)
    assert _hashes(root) == before, "geri yükleme oyunu birebir eski hâline getirir"


def test_pro_archive_is_reported(tmp_path):
    root = tmp_path / "Pro"
    root.mkdir()
    (root / "Game.exe").write_bytes(b"MZ")
    (root / "Data.wolf").write_bytes(os.urandom(2048))
    info = ew.detect_wolf(root)
    assert info.archived and not info.archive_supported and ew.extract_texts(info) == []


def test_bridge_translates_packed_game_and_restores_archive(tmp_path, monkeypatch, fake_ollama):
    import app_modern
    import providers
    from test_app import make_bridge, run_sync
    root = _packed_game(tmp_path / "PackedGame", label="WOLF 3.14")
    before = _hashes(root)
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, *a, **k: asked.append(title) or True)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    analysis = bridge._game["analysis"]
    assert analysis["lines"] > 0 and any("arşivi" in n for n in analysis["notes"])
    assert _hashes(root) == before
    run_sync(bridge, "translate")
    assert "Şifreli arşiv açılacak" in asked and not (root / "Data.wolf").exists()
    names = [s.text for s in wf.parse("db", (root / "Data/BasicData/DataBase.dat").read_bytes(),
                                      (root / "Data/BasicData/DataBase.project").read_bytes()).slots]
    assert "TR(Potion)" in names and "potion" in names
    assert any(b["engine"] == "Şifreli arşiv" for b in bridge.list_backups())
    run_sync(bridge, "restore_archive")
    after = {k: v for k, v in _hashes(root).items() if not k.startswith("_capri_backups/backup_")}
    assert after == before, "dosya yedekleri dışında oyun birebir eski hâline döner"
