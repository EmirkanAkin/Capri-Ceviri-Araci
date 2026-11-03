"""engine_common.py birim testleri."""
import json
import re
import tempfile
from pathlib import Path

import pytest

from engine_common import (
    BackupManager,
    FontChecker,
    Glossary,
    ProgressTracker,
    QAChecker,
    TranslationCache,
    english_residue_ratio,
    load_glossary,
    mask_text,
    protected_content_valid,
    unmask_text,
)


# ── Maskeleme testleri ────────────────────────────────────────────────────────

SAMPLE_PATTERN = re.compile(r"(\{[^{}]*\}|\[[^\[\]]+\]|%[sd])")


class TestMaskUnmask:
    def test_basic_mask(self):
        text = "Hello {b}world{/b}!"
        masked, values = mask_text(text, SAMPLE_PATTERN)
        assert "XPH000X" in masked
        assert "XPH001X" in masked
        assert values == ["{b}", "{/b}"]

    def test_unmask_restores_original(self):
        text = "Hello {b}world{/b}!"
        masked, values = mask_text(text, SAMPLE_PATTERN)
        restored = unmask_text(masked, values)
        assert restored == text

    def test_unmask_fails_on_missing_token(self):
        result = unmask_text("Hello XPH000X", ["a", "b"])
        assert result is None

    def test_no_tokens_to_mask(self):
        text = "Hello world"
        masked, values = mask_text(text, SAMPLE_PATTERN)
        assert masked == text
        assert values == []

    def test_unmask_empty_values(self):
        result = unmask_text("Hello world", [])
        assert result == "Hello world"

    def test_multiple_same_tokens(self):
        text = "Say %s and %s"
        masked, values = mask_text(text, SAMPLE_PATTERN)
        assert len(values) == 2
        assert values == ["%s", "%s"]
        restored = unmask_text(masked, values)
        assert restored == text


class TestProtectedContentValid:
    def test_matching_tokens(self):
        assert protected_content_valid(
            "Hello {b}world{/b}", "Merhaba {b}dünya{/b}", SAMPLE_PATTERN
        )

    def test_mismatched_tokens(self):
        assert not protected_content_valid(
            "Hello {b}world{/b}", "Merhaba {b}dünya", SAMPLE_PATTERN
        )

    def test_mask_artifacts_rejected(self):
        assert not protected_content_valid(
            "Hello", "XPH000X dünya", SAMPLE_PATTERN
        )


# ── Sözlük testleri ──────────────────────────────────────────────────────────

class TestGlossary:
    def test_builtin_lookup(self):
        g = Glossary({"Save": "Kaydet", "Load": "Yükle"})
        assert g.lookup("Save") == "Kaydet"
        assert g.lookup("Load") == "Yükle"
        assert g.lookup("Unknown") is None

    def test_apply_all(self):
        g = Glossary({"Save": "Kaydet", "Load": "Yükle"})
        result = g.apply_all("Save and Load")
        assert "Kaydet" in result
        assert "Yükle" in result

    def test_from_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"Custom": "Özel"}, f, ensure_ascii=False)
            path = Path(f.name)
        try:
            g = Glossary.from_file(path, {"Base": "Taban"})
            assert g.lookup("Base") == "Taban"
            assert g.lookup("Custom") == "Özel"
        finally:
            path.unlink()

    def test_from_nonexistent_file(self):
        g = Glossary.from_file(Path("nonexistent.json"), {"A": "B"})
        assert g.lookup("A") == "B"


# ── Önbellek testleri ─────────────────────────────────────────────────────────

class TestTranslationCache:
    def test_set_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = TranslationCache(path)
            cache.set("hello", "merhaba")
            assert cache.get("hello") == "merhaba"
            assert "hello" in cache

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = TranslationCache(path)
            cache.set("hello", "merhaba")
            cache.save()
            assert path.exists()

            cache2 = TranslationCache(path)
            cache2.load()
            assert cache2.get("hello") == "merhaba"

    def test_fuzzy_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = TranslationCache(path)
            cache.set("I really love you", "Seni gerçekten seviyorum")
            result = cache.get_fuzzy("I really love you!", threshold=0.85)
            assert result is not None

    def test_fuzzy_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = TranslationCache(path)
            cache.set("hello world", "merhaba dünya")
            result = cache.get_fuzzy("completely different text", threshold=0.85)
            assert result is None

    def test_fuzzy_short_text_exact_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = TranslationCache(path)
            cache.set("Hi", "Merhaba")
            assert cache.get_fuzzy("Hi") == "Merhaba"
            assert cache.get_fuzzy("Ho") is None  # Kısa metinlerde fuzzy yok


# ── QA testleri ───────────────────────────────────────────────────────────────

class TestQAChecker:
    def test_protected_tokens_valid(self):
        qa = QAChecker(SAMPLE_PATTERN)
        assert qa.check_protected_tokens("{b}hello{/b}", "{b}merhaba{/b}")
        assert not qa.check_protected_tokens("{b}hello{/b}", "merhaba{/b}")

    def test_length_ratio(self):
        qa = QAChecker()
        assert qa.check_length_ratio("hello", "merhaba")
        assert not qa.check_length_ratio("hello", "a" * 500)

    def test_empty_check(self):
        qa = QAChecker()
        assert qa.check_empty("hello", "merhaba")
        assert not qa.check_empty("hello", "")
        assert qa.check_empty("", "")

    def test_mask_artifacts(self):
        qa = QAChecker()
        assert qa.check_mask_artifacts("merhaba dünya")
        assert not qa.check_mask_artifacts("XPH000X dünya")

    def test_english_residue(self):
        qa = QAChecker()
        assert qa.check_english_residue("Merhaba dünya nasılsın")
        assert not qa.check_english_residue(
            "the you and your this that what with have not are was"
        )

    def test_duplicate_check(self):
        qa = QAChecker()
        assert qa.check_duplicate_translation("Hello", "Merhaba")
        assert not qa.check_duplicate_translation("Hello world", "Hello world")
        assert qa.check_duplicate_translation("123", "123")  # Sayı — sorun yok

    def test_full_check(self):
        qa = QAChecker(SAMPLE_PATTERN)
        results = qa.full_check("{b}Hello{/b}", "{b}Merhaba{/b}")
        assert all(results.values())

    def test_batch_stats(self):
        qa = QAChecker()
        pairs = [
            ("Hello", "Merhaba"),
            ("World", ""),
            ("Test", "Test"),
        ]
        stats = qa.run_batch(pairs)
        assert stats["checked"] == 3
        assert stats["empty_errors"] == 1
        assert stats["duplicate_errors"] == 1


# ── İlerleme Takibi testleri ──────────────────────────────────────────────────

class TestProgressTracker:
    def test_basic_progress(self):
        tracker = ProgressTracker()
        tracker.start(100)
        assert tracker.percent() == 0.0
        tracker.advance(50)
        assert tracker.percent() == 50.0
        tracker.advance(50)
        assert tracker.percent() == 100.0

    def test_eta_initially_none(self):
        tracker = ProgressTracker()
        tracker.start(100)
        assert tracker.eta_seconds() is None

    def test_summary_string(self):
        tracker = ProgressTracker()
        tracker.start(100)
        tracker.advance(10)
        summary = tracker.summary()
        assert "10/100" in summary
        assert "ETA" in summary


# ── İngilizce kalıntı testleri ────────────────────────────────────────────────

class TestEnglishResidue:
    def test_turkish_text_low_residue(self):
        ratio = english_residue_ratio("Bu bir Türkçe cümledir")
        assert ratio < 0.1

    def test_english_text_high_residue(self):
        ratio = english_residue_ratio("the quick brown fox should have been there")
        assert ratio > 0.3

    def test_empty_text(self):
        assert english_residue_ratio("") == 0.0

    def test_numeric_only(self):
        assert english_residue_ratio("12345") == 0.0


# ── Yedekleme testleri ────────────────────────────────────────────────────────

class TestBackupManager:
    def test_create_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data"
            source.mkdir()
            (source / "test.txt").write_text("test content", encoding="utf-8")
            backup_dir = Path(tmp) / "backups"
            result = BackupManager.create_backup(source, backup_dir, "test_backup")
            assert result is not None
            assert result.exists()
            backups = BackupManager.list_backups(backup_dir, "test_backup")
            assert len(backups) == 1

    def test_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data"
            source.mkdir()
            (source / "test.txt").write_text("original", encoding="utf-8")
            backup_dir = Path(tmp) / "backups"
            backup = BackupManager.create_backup(source, backup_dir, "test")
            # Dosyayı değiştir
            (source / "test.txt").write_text("modified", encoding="utf-8")
            # Geri yükle
            BackupManager.restore_backup(backup, Path(tmp))
            assert (source / "test.txt").read_text(encoding="utf-8") == "original"

    def test_nonexistent_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "nonexistent"
            backup_dir = Path(tmp) / "backups"
            result = BackupManager.create_backup(source, backup_dir, "test")
            assert result is None


# ── Font kontrol testleri ─────────────────────────────────────────────────────

class TestFontChecker:
    def test_nonexistent_file(self):
        result = FontChecker.check_turkish_support("nonexistent.ttf")
        assert not result["exists"]
        assert result["error"] is not None

    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = FontChecker.scan_game_fonts(Path(tmp))
            assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
