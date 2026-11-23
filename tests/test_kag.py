"""
TyranoScript ve KiriKiri (KAG senaryo dili): çözümleme, kaçışlar, arşivler (klasör, zip, exe+zip, asar, xp3) ve
uygulama içinden uçtan uca çeviri / geri alma.
"""
import hashlib
import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

import app_modern
import archives
import engine_kag
import kag_script as k
import providers
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401 (fixture)

SCENE = """;サンプル
*start
[cm  ]
[chara_new  name="akane" storage="chara/akane/normal.png" jname="あかね"  ]
@chara_new name=yamato storage=y.png jname=やまと
/* çok satırlı
   yorum: burada metin yok */
#
さて、ゲームを作ろう。[p]
#akane
こんにちは。[l][r]
#?
誰だ！？[p]
#先生
[font size=40]大きな文字[resetfont][p]
[ruby text=かん]簡[ruby text=たん]単にできます[l]
[iscript]
tf.text = "ここは実行される";
[endscript]
[html]
<div>表示されない</div>
[endhtml]
[glink color=blue text=はい target=*yes]
[glink color="blue" text="いいえ、違います" target="*no"]
[ptext layer=0 text=&tf.savetext]
変数は[emb exp="f.name"]です。[p]
[[注意]]を読む。
……[p]
"""


def test_tyrano_units_cover_dialogue_names_choices_and_skip_code():
    ids = k.character_ids([SCENE])
    assert ids == {"akane": "あかね", "yamato": "やまと"}
    units = k.extract(SCENE, "scene.ks", "tyrano", ids)
    got = [(u.context, u.original, u.speaker) for u in units]
    assert got == [
        ("name", "あかね", ""), ("name", "やまと", ""),
        ("dialogue", "さて、ゲームを作ろう。[p]", ""),
        ("dialogue", "こんにちは。[l][r]", "あかね"),
        ("dialogue", "誰だ！？[p]", ""),
        ("name", "先生", ""),
        ("dialogue", "[font size=40]大きな文字[resetfont][p]", "先生"),
        ("dialogue", "簡単にできます[l]", "先生"),
        ("choice", "はい", ""), ("choice", "いいえ、違います", ""),
        ("dialogue", 'は[emb exp="f.name"]です。[p]'.replace("は", "変数は", 1), "先生"),
        ("dialogue", "[[注意]]を読む。", "先生"),
    ]


def test_apply_escapes_syntax_and_keeps_everything_else():
    ids = k.character_ids([SCENE])
    units = k.extract(SCENE, "scene.ks", "tyrano", ids)
    tr = {u.original: f"T[{u.original}]" for u in units}
    tr.update({"さて、ゲームを作ろう。[p]": "#Hadi oyun [yapalım].\nTamam[p]", "はい": 'Evet "tamam"',
               "先生": "Öğretmen: Bay", "簡単にできます[l]": "Kolayca yapılır[l]"})
    new, changed = k.apply(SCENE, units, tr)
    lines = new.split("\n")
    assert changed == len(units)
    assert len(lines) == len(SCENE.split("\n"))
    assert "＃Hadi oyun ［yapalım］. Tamam[p]" in lines, "satır başı # ve köşeli parantez kaçırılır, tek satır kalır"
    assert '[glink color=blue text="Evet ”tamam”" target=*yes]' in lines, "tırnaksız değer tırnağa alınır"
    assert "#Öğretmen： Bay" in lines, "isimdeki ':' yüz ayıracı sanılmasın"
    assert "Kolayca yapılır[l]" in lines, "ruby etiketleri çeviride düşer"
    for keep in ('tf.text = "ここは実行される";', "<div>表示されない</div>", "[ptext layer=0 text=&tf.savetext]",
                 "#akane", "#?", "……[p]", "*start", ";サンプル"):
        assert keep in lines
    again = k.extract(new, "scene.ks", "tyrano", k.character_ids([new]))
    assert len(again) == len(units)


def test_kirikiri_names_in_brackets_and_encoding_fallback():
    text = "*start\r\n【アリス】\r\n「おはよう」[p]\r\n@seladd text=\"行く\" target=*go\r\n[link target=*a]ここ[endlink]\r\n"
    units = k.extract(text, "a.ks", "kirikiri")
    assert [(u.context, u.original, u.speaker) for u in units] == [
        ("name", "アリス", ""), ("dialogue", "「おはよう」[p]", "アリス"), ("choice", "行く", ""),
        ("dialogue", "[link target=*a]ここ[endlink]", "アリス")]
    new, _ = k.apply(text, units, {"アリス": "Alice", "「おはよう」[p]": "“Günaydın”[p]"})
    assert "\r\n" in new and "【Alice】\r\n“Günaydın”[p]\r\n" in new
    raw = k.encode(new, "cp932", "kirikiri")
    assert raw.startswith(b"\xff\xfe"), "Shift-JIS'e sığmayan harf: UTF-16LE (BOM)"
    assert k.decode(raw) == (new, "utf-16-le-bom")
    assert k.encode("テスト", "cp932", "kirikiri") == "テスト".encode("cp932")
    assert k.decode("テスト".encode("cp932"))[1] == "cp932"


def test_source_language_detection():
    assert app_modern.detect_source_language(["こんにちは。", "ありがとう"]) == "ja"
    assert app_modern.detect_source_language(["안녕하세요"]) == "ko"
    assert app_modern.detect_source_language(["你好，世界", "再见"]) == "zh-CN"
    assert app_modern.detect_source_language(["Hello there.", "OK"]) == "en"


# ── Arşivler ────────────────────────────────────────────────────────────────
def _tyrano_files():
    return {"data/scenario/first.ks": "*start\n[jump storage=scene.ks]\n".encode(), "data/scenario/scene.ks": SCENE.encode(),
            "index.html": b"<html></html>", "tyrano/tyrano.js": b"//", "data/bgimage/a.png": bytes(range(256)) * 40}


def test_zip_and_exe_appended_zip_roundtrip(tmp_path):
    nw = tmp_path / "package.nw"
    with zipfile.ZipFile(nw, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in _tyrano_files().items():
            zf.writestr(name, data)
    exe = tmp_path / "Game.exe"
    stub = b"MZ" + bytes(2 << 20)
    exe.write_bytes(stub + nw.read_bytes())
    for path, kind in ((nw, "zip"), (exe, "exe")):
        c = archives.ZipContainer(path)
        assert c.kind == kind and "data/scenario/scene.ks" in c.names()
        c.write({"data/scenario/scene.ks": b"yeni"})
        again = archives.ZipContainer(path)
        assert again.read("data/scenario/scene.ks") == b"yeni"
        assert again.read("data/bgimage/a.png") == _tyrano_files()["data/bgimage/a.png"]
        if kind == "exe":
            assert path.read_bytes()[:len(stub)] == stub, "exe kısmı aynen kalır"
            data = path.read_bytes()[len(stub):]
            assert zipfile.ZipFile(io.BytesIO(data)).read("data/scenario/scene.ks") == b"yeni", \
                "eklenen zip tek başına da geçerli (copy /b nw.exe+app.nw biçimi)"


def _make_asar(path: Path, files: dict, unpacked=()):
    """Electron'un asar biçimi (chromium pickle başlığı + JSON + veriler)."""
    tree, offset, blobs = {"files": {}}, 0, []
    for name, data in files.items():
        node = tree
        parts = name.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
        if name in unpacked:
            node["files"][parts[-1]] = {"size": len(data), "unpacked": True}
            continue
        node["files"][parts[-1]] = {"size": len(data), "offset": str(offset),
                                    "integrity": {"algorithm": "SHA256", "hash": hashlib.sha256(data).hexdigest(),
                                                  "blockSize": 4194304, "blocks": [hashlib.sha256(data).hexdigest()]}}
        offset += len(data)
        blobs.append(data)
    raw = json.dumps(tree).encode()
    padded = len(raw) + (-len(raw) % 4)
    path.write_bytes(struct.pack("<IIII", 4, padded + 8, padded + 4, len(raw)) + raw + b"\0" * (padded - len(raw))
                     + b"".join(blobs))


def test_asar_rewrite_keeps_other_files_and_updates_integrity(tmp_path):
    path = tmp_path / "app.asar"
    files = _tyrano_files()
    _make_asar(path, files, unpacked={"data/bgimage/a.png"})
    c = archives.AsarContainer(path)
    assert "data/bgimage/a.png" not in c.names(), "paket dışı dosya okunmaz"
    c.write({"data/scenario/scene.ks": "değişti".encode()})
    again = archives.AsarContainer(path)
    assert again.read("data/scenario/scene.ks") == "değişti".encode()
    assert again.read("data/scenario/first.ks") == files["data/scenario/first.ks"]
    entry = again._files["data/scenario/scene.ks"]
    assert entry["integrity"]["hash"] == hashlib.sha256("değişti".encode()).hexdigest()


def _xp3(path: Path, files: dict, compress=True, v2=False):
    """KiriKiri xp3: isteğe bağlı 2.30 başlığı, zlib'li dizin ve bölümler."""
    body, index = bytearray(), bytearray()
    base = 11 + 8 + (21 if v2 else 0)
    for name, data in files.items():
        stored = zlib.compress(data) if compress else data
        offset = base + len(body)
        body += stored
        w = name.encode("utf-16-le")
        info = struct.pack("<IQQH", 0, len(data), len(stored), len(w) // 2) + w
        segm = struct.pack("<IQQQ", 1 if compress else 0, offset, len(data), len(stored))
        adlr = struct.pack("<I", zlib.adler32(data))
        chunk = b"info" + struct.pack("<Q", len(info)) + info + b"segm" + struct.pack("<Q", len(segm)) + segm \
            + b"adlr" + struct.pack("<Q", len(adlr)) + adlr
        index += b"File" + struct.pack("<Q", len(chunk)) + chunk
    packed = zlib.compress(bytes(index))
    index_offset = base + len(body)
    head = archives.XP3_MAGIC
    if v2:
        head += struct.pack("<Q", 0x17) + struct.pack("<I", 1) + b"\x80" + struct.pack("<Q", 0) + struct.pack("<Q", index_offset)
    else:
        head += struct.pack("<Q", index_offset)
    path.write_bytes(head + body + b"\x01" + struct.pack("<QQ", len(packed), len(index)) + packed)


@pytest.mark.parametrize("compress, v2", [(True, False), (False, False), (True, True)])
def test_xp3_reader_handles_compression_and_new_header(tmp_path, compress, v2):
    path = tmp_path / "data.xp3"
    files = {"scenario/first.ks": "テスト[p]\r\n".encode("cp932"), "startup.tjs": b"Storages.addAutoPath();"}
    _xp3(path, files, compress, v2)
    arc = archives.Xp3Archive(path)
    assert arc.names() == ["scenario/first.ks", "startup.tjs"]
    assert arc.read("scenario/first.ks") == files["scenario/first.ks"]


def test_xp3_patch_overrides_and_own_patch_is_reused(tmp_path):
    _xp3(tmp_path / "data.xp3", {"scenario/a.ks": b"old", "b.ks": b"b"})
    _xp3(tmp_path / "patch.xp3", {"scenario/a.ks": b"official update"})
    c = archives.Xp3Container(tmp_path, engine_kag._xp3_order(tmp_path))
    assert c.read("scenario/a.ks") == b"official update", "resmi yama data.xp3'ü ezer"
    assert c.patch_path.name == "patch2.xp3"
    c.write({"scenario/a.ks": b"ceviri"})
    again = archives.Xp3Container(tmp_path, engine_kag._xp3_order(tmp_path))
    assert again.read("scenario/a.ks") == b"official update", "Capri'nin yaması kaynak sayılmaz"
    assert again.patch_path.name == "patch2.xp3", "kendi yamamız yeniden yazılır, yenisi açılmaz"
    assert archives.Xp3Archive(tmp_path / "patch2.xp3").read("scenario/a.ks") == b"ceviri"


# ── Uygulama içinden ────────────────────────────────────────────────────────
def _tyrano_game(root: Path) -> Path:
    for name, data in _tyrano_files().items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    (root / "Game.exe").write_bytes(b"MZ")
    return root


def _accept(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_ask", lambda *a, **kw: True)


def test_tyrano_folder_game_end_to_end(tmp_path, monkeypatch, fake_ollama):
    root = _tyrano_game(tmp_path / "Demo")
    original = (root / "data/scenario/scene.ks").read_bytes()
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    _accept(bridge, monkeypatch)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    assert bridge._select_game(str(root))["engine"] == "tyrano"
    run_sync(bridge, "analyze")
    assert "Kaynak dil: ja (otomatik algılandı)" in bridge._game["analysis"]["notes"]
    run_sync(bridge, "translate")
    text = (root / "data/scenario/scene.ks").read_text(encoding="utf-8")
    assert "TR(さて、ゲームを作ろう。[p])" in text and 'text="TR(いいえ、違います)"' in text
    assert bridge._library.get(str(root))["status"] == "translated"
    # Editörde düzelt → oyuna uygula: dosya orijinalinden yeniden üretilir
    assert bridge.editor_save("ollama", {"こんにちは。[l][r]": "Merhaba.[l][r]"})["ok"]
    run_sync(bridge, "editor_apply", "ollama")
    text = (root / "data/scenario/scene.ks").read_text(encoding="utf-8")
    assert "Merhaba.[l][r]" in text and "TR(TR(" not in text
    run_sync(bridge, "restore_backup", "")
    assert (root / "data/scenario/scene.ks").read_bytes() == original


def test_kirikiri_xp3_game_writes_a_patch_and_restore_removes_it(tmp_path, monkeypatch, fake_ollama):
    root = tmp_path / "Kiri"
    root.mkdir()
    (root / "krkr.exe").write_bytes(b"MZ")
    scenario = "*start\r\n【アリス】\r\n「おはよう」[p]\r\n".encode("cp932")
    _xp3(root / "data.xp3", {"scenario/first.ks": scenario, "startup.tjs": b"// startup"})
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    _accept(bridge, monkeypatch)
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    assert bridge._select_game(str(root))["engine"] == "kirikiri"
    run_sync(bridge, "translate")
    patch = root / "patch.xp3"
    arc = archives.Xp3Archive(patch)
    assert archives.CAPRI_MARK in arc.names()
    out = k.decode(arc.read("scenario/first.ks"))[0]
    assert "【TR(アリス)】" in out and "TR(「おはよう」[p])" in out
    data_before = (root / "data.xp3").read_bytes()
    run_sync(bridge, "restore_backup", "")
    assert not patch.exists(), "geri yükleme Capri'nin yamasını siler"
    assert (root / "data.xp3").read_bytes() == data_before, "oyunun arşivine hiç dokunulmaz"


def test_encrypted_kirikiri_archive_is_reported_not_broken(tmp_path, monkeypatch):
    root = tmp_path / "Locked"
    root.mkdir()
    (root / "game.exe").write_bytes(b"MZ")
    _xp3(root / "data.xp3", {"scenario/first.ks": bytes((i * 37) % 256 for i in range(4000))})
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    analysis = bridge._game["analysis"]
    assert analysis["lines"] == 0 and "şifre" in analysis["advice"][0]["text"]
    run_sync(bridge, "translate")
    assert not (root / "patch.xp3").exists()
