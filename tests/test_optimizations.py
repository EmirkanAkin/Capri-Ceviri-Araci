"""
OPTIMIZATIONS.md'deki iyileştirmelerin doğruluk testleri: davranış eskisiyle aynı kalmalı, gereksiz iş yapılmamalı.
"""
import builtins
import json
import random
import re
import string
import zipfile
from pathlib import Path

import pytest

import app_modern
import archives
import engine_godot as eg
import engine_wolf as ew
import fileio
import text_fit
import wolf_formats as wf
from test_app import make_bridge, make_rpgmaker_game, run_sync
from test_wolf import make_common, make_map

DATA = Path(__file__).parent / "data"


# ── F1: terim denetimi ──────────────────────────────────────────────────────
def _old_term_inconsistencies(cache, terms):
    rules = []
    for source, target in terms.items():
        source, target = str(source).strip(), str(target or "").strip()
        if len(source) < 3 or not target:
            continue
        flags = 0 if source[:1].isupper() else re.IGNORECASE
        rules.append((re.compile(r"(?<![\w])" + re.escape(source) + r"(?![\w])", flags), target.casefold()))
    return [s for s, t in cache.items() if t and t != s and any(rx.search(s) and tg not in t.casefold() for rx, tg in rules)]


def test_combined_term_check_matches_the_old_per_term_check():
    random.seed(7)
    words = ["the", "Mary", "Mary Jane", "Ann", "Anna", "castle", "CASTLE", "İstanbul", "istanbul", "Elena", "Elenas",
             "ab", "night"]
    terms = {"Mary": "Mary", "Mary Jane": "Meri Jane", "Ann": "Ann", "castle": "kale", "İstanbul": "İstanbul",
             "Elena": "Elena", "ab": "x", "Ghost": ""}
    terms.update({"".join(random.choice(string.ascii_lowercase) for _ in range(5)).capitalize(): "y" for _ in range(50)})
    cache = {}
    for i in range(3000):
        src = " ".join(random.choice(words) for _ in range(6)) + f" {i}"
        tr = random.choice([src, src.replace("Mary", "Meri"), src.replace("castle", "saray"), "çeviri " + src.lower(),
                            src.replace("İstanbul", "Ankara"), ""])
        cache[src] = tr
    assert app_modern.term_inconsistencies(cache, terms) == _old_term_inconsistencies(cache, terms)


# ── F2 / F15: kuyruk ────────────────────────────────────────────────────────
def test_queue_changes_while_running_are_respected(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    games = [make_rpgmaker_game(tmp_path / n) for n in ("a", "b", "c")]
    for g in games:
        bridge._select_game(str(g))
    bridge.queue_add([str(games[0]), str(games[1])])
    translated = []

    def fake():
        root = bridge._game["root"]
        translated.append(Path(root).name)
        if Path(root).name == "a":                   # birinci çevrilirken: ikinciyi çıkar, üçüncüyü ekle
            bridge.queue_remove(str(games[1]))
            bridge.queue_add([str(games[2])])
        bridge._library.upsert(root, status="translated")

    monkeypatch.setattr(bridge, "_translate_game", fake)
    run_sync(bridge, "queue_start")
    assert translated == ["a", "c"]
    assert [(Path(i["path"]).name, i["state"]) for i in bridge.queue_state()["items"]] == [("a", "done"), ("c", "done")]


def test_queue_does_not_wait_five_minutes_for_an_unanswered_question(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    game = make_rpgmaker_game(tmp_path / "a")
    bridge._select_game(str(game))
    bridge.queue_add([str(game)])
    monkeypatch.setattr(app_modern, "QUEUE_ASK_TIMEOUT", 0.01)
    waited = []

    def fake():
        waited.append(bridge._ask("Şifreli arşiv açılacak", "Açılsın mı?"))
        raise app_modern.TranslationCancelled()

    monkeypatch.setattr(bridge, "_translate_game", fake)
    run_sync(bridge, "queue_start")
    assert waited == [False]
    assert bridge.queue_state()["items"][0]["note"] == "Onay verilmedi: Şifreli arşiv açılacak"


# ── F7 / F8 / F9: editör ve çeviri sonu ─────────────────────────────────────
def test_editor_context_is_read_once_per_change(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "g")))
    run_sync(bridge, "analyze")
    app_modern._write_json(bridge._cache_path(), {"The king is waiting for you.": "Kral seni bekliyor."})
    calls = []
    real = text_fit.load_limits
    monkeypatch.setattr(text_fit, "load_limits", lambda p: calls.append(p) or real(p))
    for query in ("k", "ki", "kin", "king"):
        assert bridge.editor_load("gemini", query=query)["total"] == 1
    assert len(calls) == 1, "sınır dosyası her aramada yeniden okunmaz"
    bridge.project_glossary_save([["King", "Kral"]])       # sözlük değişince bağlam yenilenir
    bridge.editor_load("gemini", query="king")
    assert len(calls) == 2


def test_renpy_without_translation_folder_is_not_reanalyzed(tmp_path, monkeypatch):
    import engine_renpy
    bridge = make_bridge(tmp_path, monkeypatch)
    game = {"root": str(tmp_path / "vn"), "type": "renpy"}
    (tmp_path / "vn" / "game").mkdir(parents=True)
    calls = []

    class Info:
        tl_dir = tmp_path / "vn" / "game" / "tl" / "turkish"
        game_dir = tmp_path / "vn" / "game"

    monkeypatch.setattr(engine_renpy, "analyze_game", lambda *a, **k: calls.append(1) or Info)
    assert bridge._fit_limits(game) == {} and bridge._fit_limits(game) == {}
    assert len(calls) == 1


def test_editor_search_uses_prefolded_text(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "g")))
    app_modern._write_json(bridge._cache_path(), {"İstanbul gate": "İstanbul kapısı", "Other": "Diğer"})
    assert [i["src"] for i in bridge.editor_load("gemini", query="KAPISI".replace("I", "ı"))["items"]] == ["İstanbul gate"]
    assert [i["src"] for i in bridge.editor_load("gemini", query="diğer")["items"]] == ["Other"]
    assert bridge.editor_load("gemini", query="\0")["total"] == 0, "ayraç aramayı karıştırmaz"


def test_translation_end_reads_the_cache_once(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "g")))
    cache_path = bridge._cache_path()
    monkeypatch.setattr(bridge, "_translate_rpgmaker", lambda g, f: app_modern._write_json(cache_path, {"A": "B"}) or 1)
    monkeypatch.setattr(bridge, "_check_model_ready", lambda *_: None)
    reads = []
    real = app_modern._read_json
    monkeypatch.setattr(app_modern, "_read_json", lambda p, d: (reads.append(Path(p)) if Path(p) == cache_path else None) or real(p, d))
    run_sync(bridge, "translate")
    after_write = reads[reads.index(cache_path):] if cache_path in reads else []
    assert 0 < len(after_write) <= 2, f"önbellek {len(after_write)} kez okundu"


# ── F3: tarama ──────────────────────────────────────────────────────────────
def test_scan_reuses_line_counts_of_unchanged_games(tmp_path, monkeypatch):
    game = {"path": str(make_rpgmaker_game(tmp_path / "g")), "engine": "rpgmaker", "title": "G"}
    counted = []
    monkeypatch.setattr(app_modern, "quick_line_count", lambda g: counted.append(1) or 7)
    first = dict(game)
    app_modern.CapriBridge._scan_line_count(first, None)
    second = dict(game)
    app_modern.CapriBridge._scan_line_count(second, first)
    assert first["lines"] == second["lines"] == 7 and len(counted) == 1
    data = Path(game["path"]) / "www" / "data" / "Map001.json"
    data.write_text(data.read_text(encoding="utf-8") + " ", encoding="utf-8")
    import os
    os.utime(data, (data.stat().st_atime, data.stat().st_mtime + 5))
    third = dict(game)
    app_modern.CapriBridge._scan_line_count(third, first)
    assert len(counted) == 2, "oyun dosyası değişince yeniden sayılır"


# ── F4: Godot paketini tek tutamakla okuma ──────────────────────────────────
def test_godot_extraction_opens_the_pack_once(tmp_path, monkeypatch):
    import shutil
    root = tmp_path / "Demo"
    root.mkdir()
    shutil.copy(DATA / "godot4_demo.pck", root / "Demo.pck")
    (root / "Demo.exe").write_bytes(b"MZ")
    info = eg.detect_godot(root)
    opened = []
    real = builtins.open

    def counting(file, *a, **k):
        if Path(str(file)).name == "Demo.pck":
            opened.append(1)
        return real(file, *a, **k)

    monkeypatch.setattr(builtins, "open", counting)
    units = eg.extract_texts(info)
    assert len(units) == 4 and len(opened) <= 2
    opened.clear()
    eg.write_translations(info, {"Start Game": "Oyuna başla"}, units=units)
    assert len(opened) <= 2


# ── F5 / F6: zip ────────────────────────────────────────────────────────────
def _raw_entries(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
    out = {}
    with open(path, "rb") as f:
        for i in infos:
            f.seek(i.header_offset)
            head = f.read(30)
            n, m = int.from_bytes(head[26:28], "little"), int.from_bytes(head[28:30], "little")
            f.seek(i.header_offset + 30 + n + m)
            out[i.filename] = f.read(i.compress_size)
    return out


@pytest.mark.parametrize("exe", [False, True])
def test_zip_rewrite_copies_unchanged_entries_raw(tmp_path, exe):
    path = tmp_path / ("Game.exe" if exe else "package.nw")
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr(zipfile.ZipInfo("data/bg.png"), bytes(range(256)) * 300, compress_type=zipfile.ZIP_STORED)
        z.writestr("data/scenario/a.ks", "*start\nmetin[p]\n" * 50, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("data/scenario/b.ks", "*b\n" * 20, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("Türkçe.txt", "ç", compress_type=zipfile.ZIP_DEFLATED)
    path.write_bytes((b"MZ" + bytes(4096) if exe else b"") + plain.read_bytes())
    before = _raw_entries(path)
    archives.ZipContainer(path).write({"data/scenario/a.ks": b"*start\nyeni[p]\n"})
    after = _raw_entries(path)
    assert {k: v for k, v in after.items() if k != "data/scenario/a.ks"} == \
        {k: v for k, v in before.items() if k != "data/scenario/a.ks"}, "değişmeyenler bayt bayt aynı"
    c = archives.ZipContainer(path)
    assert c.read("data/scenario/a.ks") == b"*start\nyeni[p]\n" and c.read("Türkçe.txt") == "ç".encode()
    assert zipfile.ZipFile(path).testzip() is None


def test_zip64_archives_use_the_general_path(tmp_path, monkeypatch):
    path = tmp_path / "package.nw"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a.ks", "eski")
    monkeypatch.setattr(archives.ZipContainer, "_needs_zip64", lambda self: True)
    archives.ZipContainer(path).write({"a.ks": b"yeni"})
    assert zipfile.ZipFile(path).read("a.ks") == b"yeni"
    assert not list(tmp_path.glob("*.capri_*")), "geçici dosya kalmaz"


def test_zip_reads_check_the_crc(tmp_path):
    path = tmp_path / "package.nw"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a.ks", "metin" * 10, compress_type=zipfile.ZIP_STORED)
    data = bytearray(path.read_bytes())
    data[data.index(b"metin")] = ord("M")
    path.write_bytes(bytes(data))
    with pytest.raises(zipfile.BadZipFile):
        archives.ZipContainer(path).read("a.ks")


# ── F14: WOLF belgeleri bir kez çözümlenir ──────────────────────────────────
def test_wolf_files_are_parsed_once_for_analysis_and_writing(tmp_path, monkeypatch):
    from test_wolf import _game
    root = _game(tmp_path / "W")
    info = ew.detect_wolf(root)
    calls = []
    real = wf.parse
    monkeypatch.setattr(wf, "parse", lambda kind, data, project=b"": calls.append(kind) or real(kind, data, project))
    ew.extract_texts(info)
    assert len(calls) == 2
    calls.clear()
    written, _ = ew.write_translations(info, {"Take the sword": "Kılıcı al"})
    assert written == 2 and calls == ["common", "map"], "yalnızca yazılan dosyaların doğrulama çözümlemesi"


# ── F12: güvenli yazma ──────────────────────────────────────────────────────
def test_atomic_write_keeps_the_original_when_writing_fails(tmp_path):
    path = tmp_path / "a.json"
    path.write_text("eski", encoding="utf-8")

    def broken(out):
        out.write(b"yar")
        raise RuntimeError("disk dolu")

    with pytest.raises(RuntimeError):
        fileio.atomic_write(path, writer=broken)
    assert path.read_text(encoding="utf-8") == "eski" and not fileio.temp_path(path).exists()
    fileio.atomic_write_text(path, "a\nb")
    assert path.read_bytes() == b"a\nb", "satır sonları çevrilmez"


def test_json_writes_go_through_the_atomic_helper(tmp_path, monkeypatch):
    seen = []
    real = fileio.atomic_write
    monkeypatch.setattr(fileio, "atomic_write", lambda path, *a, **k: seen.append(Path(path).name) or real(path, *a, **k))
    app_modern._write_json(tmp_path / "x.json", {"a": 1})
    assert seen == ["x.json"] and json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == {"a": 1}
