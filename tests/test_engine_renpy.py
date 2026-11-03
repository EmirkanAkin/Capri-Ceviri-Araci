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
