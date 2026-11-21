"""engine_renpy.py birim testleri."""
import json
import re
import tempfile
from pathlib import Path

import pytest


class TestRenPyPatterns:
    """Ren'Py regex kalıplarının doğruluğunu test eder."""

    def test_quoted_any(self):
        from engine_renpy import QUOTED_ANY
        line = 'mc "Hello world" with dissolve'
        matches = list(QUOTED_ANY.finditer(line))
        assert len(matches) == 1
        assert matches[0].group(1) == '"Hello world"'

    def test_protected_renpy_tags(self):
        from engine_renpy import PROTECTED
        text = "Hello {b}world{/b} [name] %s"
        matches = PROTECTED.findall(text)
        assert "{b}" in matches
        assert "{/b}" in matches
        assert "[name]" in matches
        assert "%s" in matches

    def test_last_literal_match(self):
        from engine_renpy import last_literal_match
        line = '    mc "Hello" "World"'
        match = last_literal_match(line)
        assert match is not None
        assert match.group(1) == '"World"'

    def test_last_literal_no_match(self):
        from engine_renpy import last_literal_match
        line = "    translate Turkish start_123:"
        match = last_literal_match(line)
        assert match is None


class TestSourceDetection:
    """Kaynak satır bulma fonksiyonlarını test eder."""

    def test_source_from_line(self):
        from engine_renpy import source_from_line
        assert source_from_line('# mc "Hello world"') == "Hello world"
        assert source_from_line("# some comment without quotes") is None

    def test_find_source_before(self):
        from engine_renpy import find_source_before
        lines = [
            '# mc "Hello world"\n',
            '    mc ""\n',
        ]
        result = find_source_before(lines, 1)
        assert result == "Hello world"

    def test_find_source_with_nvl_clear(self):
        from engine_renpy import find_source_before
        lines = [
            '# mc "Hello"\n',
            '    nvl clear\n',
            '    mc ""\n',
        ]
        result = find_source_before(lines, 2)
        assert result == "Hello"


class TestSkipBetweenLines:
    """Kaynak-hedef arası atlanabilir satırları test eder."""

    def test_empty_line(self):
        from engine_renpy import can_skip_between_source_and_target
        assert can_skip_between_source_and_target("")
        assert can_skip_between_source_and_target("   ")

    def test_nvl_clear(self):
        from engine_renpy import can_skip_between_source_and_target
        assert can_skip_between_source_and_target("    nvl clear")

    def test_with_statement(self):
        from engine_renpy import can_skip_between_source_and_target
        assert can_skip_between_source_and_target("    with dissolve")

    def test_normal_line(self):
        from engine_renpy import can_skip_between_source_and_target
        assert not can_skip_between_source_and_target('    mc "Hello"')


class TestLiteralEncoding:
    """Literal kodlama/çözme fonksiyonlarını test eder."""

    def test_encode_decode_roundtrip(self):
        from engine_renpy import decode_literal
        from engine_common import encode_literal
        original = "Merhaba dünya! Nasılsın?"
        encoded = encode_literal(original)
        decoded = decode_literal(encoded)
        assert decoded == original

    def test_encode_special_chars(self):
        from engine_common import encode_literal
        result = encode_literal("Türkçe: şŞğĞıİöÖüÜçÇ")
        assert "Türkçe" in result
        assert "ş" in result


class TestMaskingCompatibility:
    """Ren'Py maskeleme uyumluluk fonksiyonlarını test eder."""

    def test_mask_renpy(self):
        from engine_renpy import mask_text, unmask_text
        text = "Hello {b}world{/b}!"
        masked, values = mask_text(text)
        assert "XPH" in masked
        restored = unmask_text(masked, values)
        assert restored == text

    def test_mask_with_variable(self):
        from engine_renpy import mask_text, unmask_text
        text = "Welcome [player_name], you have %s items"
        masked, values = mask_text(text)
        assert "[player_name]" in values
        assert "%s" in values
        restored = unmask_text(masked, values)
        assert restored == text


class TestTranslateHeader:
    """Translate header regex'ini test eder."""

    def test_basic_header(self):
        from engine_renpy import TRANSLATE_HEADER
        match = TRANSLATE_HEADER.match("translate Turkish start_1234abcd:")
        assert match is not None
        assert match.group(1).strip() == "start_1234abcd"

    def test_strings_header(self):
        from engine_renpy import TRANSLATE_HEADER
        match = TRANSLATE_HEADER.match("translate Turkish strings:")
        assert match is not None
        assert match.group(1).strip() == "strings"


class TestUITextDetection:
    """UI metin algılama fonksiyonlarını test eder."""

    def test_looks_translatable(self):
        from engine_renpy import _looks_translatable_ui_text
        assert _looks_translatable_ui_text("Save Game")
        assert _looks_translatable_ui_text("Notifications")
        assert not _looks_translatable_ui_text("")
        assert not _looks_translatable_ui_text("a")  # Çok kısa
        assert not _looks_translatable_ui_text("gui/button.png")  # Dosya yolu
        assert not _looks_translatable_ui_text("idle")  # Teknik terim

    def test_technical_words_excluded(self):
        from engine_renpy import _looks_translatable_ui_text
        for word in ("idle", "hover", "selected_idle", "xalign", "yalign"):
            assert not _looks_translatable_ui_text(word)


class TestStageDirections:
    """Sahne yönergeleri sözlüğünü test eder."""

    def test_stage_directions_exist(self):
        from engine_renpy import STAGE_DIRECTIONS
        assert "*Sigh*" in STAGE_DIRECTIONS
        assert STAGE_DIRECTIONS["*Sigh*"] == "*İç çeker*"
        assert "*Gasp!*" in STAGE_DIRECTIONS


class TestFontScanning:
    """Font tarama fonksiyonunu test eder."""

    def test_scan_empty_dir(self):
        from engine_renpy import GameInfo
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game_dir = root / "game"
            game_dir.mkdir()
            # Sahte GameInfo
            info = GameInfo(
                root=root, game_dir=game_dir,
                executable=root / "game.exe",
                loose_rpy=0, loose_rpyc=0,
                archives=[], packed_rpy=0, packed_rpyc=0,
                existing_tl_files=0,
            )
            from engine_renpy import scan_game_fonts
            results = scan_game_fonts(info)
            assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_ui_string_scan_is_not_cut_at_a_few_thousand(tmp_path):
    """Diyaloğu argümanla veren oyunlar (call show_line(..., text="…")) binlerce satır üretir; eskiden
    6000'de kesiliyordu ve alfabetik sırada sonra gelen karakterlerin sahneleri İngilizce kalıyordu."""
    import engine_renpy
    from types import SimpleNamespace

    game_dir = tmp_path / "game"
    (game_dir / "scripts").mkdir(parents=True)
    lines = "label start:\n" + "".join(
        f'    call show_line(npc, look = "smile", text = "Line number {i} is here.")\n' for i in range(6500))
    (game_dir / "scripts" / "zz_last.rpy").write_text(lines, encoding="utf-8")
    tl_dir = game_dir / "tl" / "Turkish"
    tl_dir.mkdir(parents=True)
    info = SimpleNamespace(game_dir=game_dir, archives=[])
    logs = []
    result = engine_renpy.augment_ui_string_templates(info, tl_dir, logs.append)
    assert result["added"] == 6500 and not result["truncated"]
    text = (tl_dir / "zz_renptr_ui_strings.rpy").read_text(encoding="utf-8")
    assert 'old "Line number 6499 is here."' in text
    assert engine_renpy.augment_ui_string_templates(info, tl_dir, logs.append, limit=10)["truncated"]
    assert any("UYARI" in line for line in logs), "sınır aşılırsa sessizce kesilmez"


def test_short_exclamations_are_text_but_file_names_are_not():
    import engine_renpy
    for text in ("A-Alright.", "Aaah...", "A-Ah...", "Okay."):
        assert engine_renpy._looks_translatable_ui_text(text), text
    for text in ("Save.es3", "gui.button", "images/bg.png", "a.b"):
        assert not engine_renpy._looks_translatable_ui_text(text), text


def _compile_game(tmp_path):
    import engine_renpy
    root = tmp_path / "Oyun"
    tl = root / "game" / "tl" / "Turkish"
    tl.mkdir(parents=True)
    (root / "Oyun.exe").write_bytes(b"MZ")
    (tl / "script.rpy").write_text(
        "translate Turkish start_1a2b:\n\n"
        "    # e \"Hello there.\"\n"
        "    e \"Merhaba \"orada\".\"\n\n"
        "translate Turkish strings:\n\n"
        "    old \"Save\"\n"
        "    new \"Kaydet\" \"bozuk\n", encoding="utf-8")
    info = engine_renpy.GameInfo(root=root, game_dir=root / "game", executable=root / "Oyun.exe", loose_rpy=0,
                                 loose_rpyc=0, archives=[], packed_rpy=0, packed_rpyc=0, existing_tl_files=0)
    return info, tl / "script.rpy"


def test_compile_errors_are_parsed_from_errors_txt():
    import engine_renpy
    text = ("\ufeffI'm sorry, but errors were detected in your script.\n\n"
            'File "game/tl/Turkish/common.rpy", line 7: is not terminated with a newline.\n'
            "    new \"x\" \"y\n\n"
            'File "game\\script.rpy", line 12: expected statement.\n')
    errors = engine_renpy.parse_compile_errors(text)
    assert errors == [
        {"file": "game/tl/Turkish/common.rpy", "line": 7, "message": "is not terminated with a newline."},
        {"file": "game/script.rpy", "line": 12, "message": "expected statement."}]


def test_compile_check_reverts_only_broken_translation_lines(tmp_path):
    """Oyunun Ren'Py'si hata verirse hatalı çeviri satırı orijinaline döner, oyunun kendi betiğine dokunulmaz."""
    import engine_renpy
    info, path = _compile_game(tmp_path)
    calls = []

    def fake_runner(_info):
        calls.append(path.read_text(encoding="utf-8"))
        lines = path.read_text(encoding="utf-8").splitlines()
        errors = [f'File "game/tl/Turkish/script.rpy", line {i + 1}: syntax error' for i, l in enumerate(lines)
                  if l.strip().startswith(("e ", "new ")) and l.count('"') % 2 == 1 or '"orada"' in l]
        errors.append('File "game/script.rpy", line 3: oyunun kendi hatası')
        return 1, "\n".join(errors)

    logs = []
    report = engine_renpy.compile_check(info, path.parent, logs.append, runner=fake_runner)
    text = path.read_text(encoding="utf-8")
    assert '    e "Hello there."\n' in text, "diyalog yorumdaki orijinaline döner"
    assert '    new "Save"\n' in text, "new satırı old metnine döner"
    assert report["reverted"] == 2 and not report["errors"]
    assert sorted(report["reverted_sources"]) == ["Hello there.", "Save"], "editörde incelenmek üzere kaynak metinler"
    assert report["game_errors"] and report["game_errors"][0]["file"] == "game/script.rpy"
    assert any("oyunun kendi betiğinde" in line for line in logs)


def test_compile_check_passes_clean_translation_and_skips_without_executable(tmp_path):
    import engine_renpy
    info, path = _compile_game(tmp_path)
    report = engine_renpy.compile_check(info, path.parent, lambda _m: None, runner=lambda _i: (0, ""))
    assert report["ok"] and report["reverted"] == 0
    info.executable = tmp_path / "yok.exe"
    logs = []
    report = engine_renpy.compile_check(info, path.parent, logs.append)
    assert not report["ran"] and any("atlandı" in line for line in logs)


def test_compile_check_with_a_real_renpy_game(tmp_path):
    """CAPRI_RENPY_SAMPLE: bir Ren'Py oyununun KOPYASI (oyunun kendisi değil). Çeviri dosyası bozulur, denetim düzeltir."""
    import os, shutil
    import pytest
    import engine_renpy
    sample = os.environ.get("CAPRI_RENPY_SAMPLE")
    if not sample:
        pytest.skip("CAPRI_RENPY_SAMPLE tanımlı değil")
    root = Path(sample)
    exe = next(p for p in root.glob("*.exe") if not p.stem.endswith("-32"))
    info = engine_renpy.GameInfo(root=root, game_dir=root / "game", executable=exe, loose_rpy=0, loose_rpyc=0,
                                 archives=[], packed_rpy=0, packed_rpyc=0, existing_tl_files=0)
    target = next(info.tl_dir.rglob("*.rpy"))
    original = target.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    index = next(i for i, l in enumerate(lines) if l.lstrip().startswith("new "))
    lines[index] = lines[index].rstrip("\n") + ' "bozuk\n'
    target.write_text("".join(lines), encoding="utf-8")
    try:
        report = engine_renpy.compile_check(info, info.tl_dir, lambda _m: None)
        assert report["ran"] and report["ok"] and report["reverted"] == 1
    finally:
        target.write_text(original, encoding="utf-8")


def test_runtime_errors_from_translated_lines_are_found_and_repaired(tmp_path, monkeypatch):
    """Oyun çalışırken bir çeviri satırı çökertirse (traceback.txt) Capri uyarır; düzeltme o satırı orijinaline döndürür,
    editörde incelenmeye düşürür ve aynı kayıt bir daha uyarı üretmez. Oyunun hata kayıtlarına dokunulmaz."""
    import os
    import time as _time
    import app_modern
    import engine_renpy
    from test_app import make_bridge, run_sync
    root = tmp_path / "Oyun"
    tl = root / "game" / "tl" / "Turkish"
    tl.mkdir(parents=True)
    script = tl / "script.rpy"
    script.write_text("translate Turkish start_1:\n\n    # e \"Hello [name].\"\n    e \"Merhaba [isim].\"\n", encoding="utf-8")
    trace = root / "traceback.txt"
    trace.write_text("I'm sorry, but an uncaught exception occurred.\n\nWhile running game code:\n"
                     '  File "game/tl/Turkish/script.rpy", line 4, in script\n    e "Merhaba [isim]."\n'
                     '  File "game/tl/japanese/x.rpy", line 9, in script\n'
                     "NameError: name 'isim' is not defined\n", encoding="utf-8")
    found = engine_renpy.runtime_translation_errors(root, "Turkish", 0)
    assert found == [{"file": "game/tl/Turkish/script.rpy", "line": 4,
                      "message": "NameError: name 'isim' is not defined", "log": "traceback.txt"}]
    assert engine_renpy.runtime_translation_errors(root, "Turkish", _time.time() + 60) == [], "çeviriden eski kayıt sayılmaz"

    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._game = {"root": str(root), "type": "renpy", "title": "Oyun", "analysis": {"advice": []}}
    bridge._library.upsert(root, status="translated", translated_at=_time.time() - 100)
    os.utime(trace, (_time.time(), _time.time()))
    analysis = bridge._game["analysis"]
    bridge._check_runtime_errors(bridge._game, analysis, bridge._library.get(root))
    assert analysis["advice"][0]["action"] == "fix-runtime" and analysis["runtime_errors"]
    before = trace.read_bytes()
    run_sync(bridge, "repair_runtime_errors")
    assert '    e "Hello [name]."\n' in script.read_text(encoding="utf-8")
    assert trace.read_bytes() == before, "oyunun hata kaydına dokunulmaz"
    review = app_modern._read_json(app_modern.review_path_for(bridge._cache_path()), [])
    assert "Hello [name]." in review
    analysis = {"advice": []}
    bridge._check_runtime_errors(bridge._game, analysis, bridge._library.get(root))
    assert not analysis["advice"], "düzeltilmiş kayıt yeniden uyarı üretmez"
