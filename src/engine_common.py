"""
Capri — Ortak Çeviri Motoru
======================================

Hem Ren'Py hem RPG Maker motorları tarafından kullanılan ortak çeviri
altyapısı: model yönetimi, önbellek, çeviri hafızası (TM), metin maskeleme,
sözlük, kalite kontrol, font doğrulama, ilerleme takibi ve yedekleme.
"""
from __future__ import annotations

import collections
import difflib
import hashlib
import io
import json
import re
import shutil
import struct
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ── Tip takma adları ─────────────────────────────────────────────────────────
LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


class TranslationCancelled(Exception):
    """Kullanıcı çeviriyi durdurdu (ilerleme geri çağrısından fırlatılır)."""

# ── Maske sabitleri ──────────────────────────────────────────────────────────
MASK_TOKEN = re.compile(r"XPH(\d{3})X")

# ── Yerleşik Türkçe sözlük (her iki motor için ortak) ────────────────────────
BUILTIN_GLOSSARY: dict[str, str] = {
    "Save": "Kaydet",
    "Load": "Yükle",
    "Settings": "Ayarlar",
    "Preferences": "Tercihler",
    "Gallery": "Galeri",
    "Replay": "Tekrar Oynat",
    "History": "Geçmiş",
    "Skip": "Atla",
    "Auto": "Otomatik",
    "Continue": "Devam Et",
    "Start": "Başla",
    "Main Menu": "Ana Menü",
    "Quit": "Çıkış",
    "Yes": "Evet",
    "No": "Hayır",
    "Return": "Geri Dön",
    "Back": "Geri",
    "About": "Hakkında",
    "Help": "Yardım",
    "Language": "Dil",
    "Tasks": "Görevler",
    "Task": "Görev",
    "Quest": "Görev",
    "Quests": "Görevler",
    "Objectives": "Hedefler",
    "Objective": "Hedef",
    "Notifications": "Bildirimler",
    "Notification": "Bildirim",
    "Messages": "Mesajlar",
    "Message": "Mesaj",
    "Contacts": "Kişiler",
    "Contact": "Kişi",
    "Inventory": "Envanter",
    "Map": "Harita",
    "Journal": "Günlük",
    "Hints": "İpuçları",
    "Hint": "İpucu",
    "Money": "Para",
    "Stats": "İstatistikler",
    "Status": "Durum",
    "Relationship": "İlişki",
    "Reputation": "İtibar",
    "Location": "Konum",
    "Morning": "Sabah",
    "Afternoon": "Öğleden sonra",
    "Evening": "Akşam",
    "Night": "Gece",
    "Day": "Gün",
    "Delete": "Sil",
    "Confirm": "Onayla",
    "Cancel": "İptal",
    "Close": "Kapat",
    "Next": "Sonraki",
    "Previous": "Önceki",
    "New Game": "Yeni Oyun",
    "Quick Save": "Hızlı Kaydet",
    "Quick Load": "Hızlı Yükle",
    "Fullscreen": "Tam Ekran",
    "Window": "Pencere",
    "Display": "Görüntü",
    "Music Volume": "Müzik Seviyesi",
    "Sound Volume": "Ses Efekti Seviyesi",
    "Voice Volume": "Konuşma Seviyesi",
    "Text Speed": "Metin Hızı",
    "Mute All": "Tümünü Sustur",
    "Phone": "Telefon",
    "OK": "Tamam",
}

# İngilizce sık kullanılan kelimeler — kalıntı oranı hesabı için
_COMMON_ENGLISH_WORDS = {
    "the", "and", "you", "your", "this", "that", "what", "with",
    "have", "not", "are", "was", "were", "but", "for", "from",
    "she", "they", "them", "her", "his", "can", "could", "would",
    "should", "there", "here", "about", "know", "want", "like",
    "really", "then", "when", "where", "why", "how", "only",
    "still", "because", "been", "will", "into",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Metin Maskeleme
# ═══════════════════════════════════════════════════════════════════════════════

def mask_text(text: str, pattern: re.Pattern) -> tuple[str, list[str]]:
    """Korunan belirteçleri XPH###X maskeleriyle değiştir."""
    values: list[str] = []

    def _replace(match: re.Match) -> str:
        values.append(match.group(0))
        return f"XPH{len(values) - 1:03d}X"

    masked = pattern.sub(_replace, text)
    return masked, values


def unmask_text(text: str, values: list[str]) -> str | None:
    """Maskeleri orijinal belirteçlere geri dönüştür. Tutarsızlıkta None döner."""
    found = [int(v) for v in MASK_TOKEN.findall(text)]
    if sorted(found) != list(range(len(values))) or len(found) != len(values):
        return None
    for idx, value in enumerate(values):
        text = text.replace(f"XPH{idx:03d}X", value)
    return text


def protected_content_valid(
    source: str, target: str, pattern: re.Pattern
) -> bool:
    """Kaynak ve hedef arasındaki korunan belirteçlerin eşleştiğini doğrula."""
    if not isinstance(source, str):
        source = str(source) if source is not None else ""
    if not isinstance(target, str):
        target = str(target) if target is not None else ""
    return (
        collections.Counter(pattern.findall(source))
        == collections.Counter(pattern.findall(target))
        and not re.search(r"XPH\d", target, flags=re.IGNORECASE)
    )


def english_residue_ratio(text: str, pattern: re.Pattern | None = None) -> float:
    """Metin içindeki İngilizce kalıntı oranını hesapla."""
    plain = pattern.sub(" ", text) if pattern else text
    words = re.findall(r"[A-Za-z]{2,}", plain.lower())
    if not words:
        return 0.0
    return sum(w in _COMMON_ENGLISH_WORDS for w in words) / len(words)


# ═══════════════════════════════════════════════════════════════════════════════
# Sözlük
# ═══════════════════════════════════════════════════════════════════════════════

def load_glossary(
    path: Path | None, builtin: dict[str, str] | None = None
) -> dict[str, str]:
    """Yerleşik sözlük + özel JSON sözlüğünü yükle."""
    glossary = dict(builtin or BUILTIN_GLOSSARY)
    if path and path.exists():
        try:
            custom = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                glossary.update(
                    {str(k): str(v) for k, v in custom.items()}
                )
        except (OSError, json.JSONDecodeError):
            pass
    return glossary


class Glossary:
    """Sözlük yöneticisi — tam ve kısmi eşleşme desteği."""

    def __init__(self, entries: dict[str, str] | None = None):
        self.entries: dict[str, str] = dict(entries or {})

    @classmethod
    def from_file(
        cls, path: Path | None, builtin: dict[str, str] | None = None
    ) -> Glossary:
        return cls(load_glossary(path, builtin))

    def lookup(self, text: str) -> str | None:
        """Tam eşleşme ara."""
        return self.entries.get(text)

    def apply_all(self, text: str) -> str:
        """Metin içindeki tüm sözlük eşleşmelerini uygula."""
        result = text
        for source, target in sorted(
            self.entries.items(), key=lambda x: -len(x[0])
        ):
            result = result.replace(source, target)
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Çeviri Önbelleği + Çeviri Hafızası (TM)
# ═══════════════════════════════════════════════════════════════════════════════

class TranslationCache:
    """JSON tabanlı çeviri önbelleği, bulanık eşleştirme (fuzzy match) destekli."""

    def __init__(self, path: Path, data: dict[str, str] | None = None):
        self.path = path
        # Verilen sözlük kopyalanmadan paylaşılır: set() ile eklenen çeviriler
        # çağıranın sözlüğüne de doğrudan yansır.
        self._data: dict[str, str] = data if data is not None else {}
        self._dirty = False
        self._lower: dict[str, str] = {}  # get_fuzzy için küçük harf önbelleği

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(
                    self.path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._dirty = False

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._dirty = True

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        # Motorlar "if self.cache:" ile önbellek verilip verilmediğine bakar;
        # boş önbellek de geçerli bir önbellektir (aksi hâlde hiç yazılmaz).
        return True

    def update(self, mapping: dict[str, str]) -> None:
        self._data.update(mapping)
        self._dirty = True

    def get_fuzzy(self, key: str, threshold: float = 0.75) -> str | None:
        """
        Bulanık eşleştirme ile en yakın önbellek kaydını bul.
        Eşik altındaysa None döner.
        """
        if not self._data or not key:
            return None
        best_match: str | None = None
        best_ratio = 0.0
        key_lower = key.lower()
        # Kısa metinlerde tam eşleşme gereksin
        if len(key) < 6:
            return self._data.get(key)
        key_len = len(key_lower)
        lower = self._lower
        matcher = difflib.SequenceMatcher(None, key_lower, "")
        for source, target in self._data.items():
            if not source or not target:
                continue
            source_lower = lower.get(source)
            if source_lower is None:
                source_lower = lower[source] = source.lower()
            # ratio() için ucuz üst sınırlar: sonucu değiştirmeden ağır
            # karşılaştırmayı yalnızca kazanma ihtimali olan adaylara uygula.
            total = key_len + len(source_lower)
            bound = 2.0 * min(key_len, len(source_lower)) / total
            if bound < threshold or bound <= best_ratio:
                continue
            matcher.set_seq2(source_lower)
            quick = matcher.quick_ratio()
            if quick < threshold or quick <= best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio and ratio >= threshold:
                best_ratio = ratio
                best_match = target
        return best_match

    @property
    def data(self) -> dict[str, str]:
        return self._data


# ═══════════════════════════════════════════════════════════════════════════════
# Kalite Kontrol (QA)
# ═══════════════════════════════════════════════════════════════════════════════

class QAChecker:
    """Çeviri kalite kontrol aracı."""

    def __init__(self, protected_pattern: re.Pattern | None = None):
        self.pattern = protected_pattern

    def check_protected_tokens(self, source: str, target: str) -> bool:
        """Korunan belirteçlerin kaynak ve hedefte eşleştiğini doğrula."""
        if self.pattern is None:
            return True
        return protected_content_valid(source, target, self.pattern)

    def check_length_ratio(
        self,
        source: str,
        target: str,
        min_r: float = 0.3,
        max_r: float = 3.0,
    ) -> bool:
        """Kaynak-hedef uzunluk oranının kabul edilebilir aralıkta olduğunu doğrula."""
        if not source:
            return True
        ratio = len(target) / max(1, len(source))
        return min_r <= ratio <= max_r

    def check_empty(self, source: str, target: str) -> bool:
        """Kaynak doluyken hedefin boş olmadığını doğrula."""
        return not (source and not target)

    def check_mask_artifacts(self, target: str) -> bool:
        """Maske artıklarının olmadığını doğrula."""
        return "XPH" not in target and not re.search(r"}X(?=\{|\n)", target)

    def check_english_residue(
        self, target: str, max_ratio: float = 0.5
    ) -> bool:
        """İngilizce kalıntı oranının kabul edilebilir seviyede olduğunu doğrula."""
        return english_residue_ratio(target, self.pattern) < max_ratio

    def check_duplicate_translation(
        self, source: str, target: str
    ) -> bool:
        """Çevirinin kaynağın aynısı olmadığını kontrol et (hâlâ İngilizce)."""
        if not source or not target:
            return True
        # Sadece alfabetik metinlerde kontrol et
        if not re.search(r"[A-Za-z]{3,}", source):
            return True
        return source.strip().lower() != target.strip().lower()

    def full_check(
        self, source: str, target: str
    ) -> dict[str, bool]:
        """Tüm kontrolleri çalıştır ve sonuçları döndür."""
        return {
            "protected_tokens": self.check_protected_tokens(source, target),
            "length_ratio": self.check_length_ratio(source, target),
            "not_empty": self.check_empty(source, target),
            "no_mask_artifacts": self.check_mask_artifacts(target),
            "low_english_residue": self.check_english_residue(target),
            "not_duplicate": self.check_duplicate_translation(source, target),
        }

    def run_batch(
        self, pairs: list[tuple[str, str]]
    ) -> dict[str, int]:
        """Toplu QA kontrolü çalıştır ve özet istatistikleri döndür."""
        stats: dict[str, int] = {
            "checked": 0,
            "token_errors": 0,
            "empty_errors": 0,
            "mask_artifacts": 0,
            "length_errors": 0,
            "english_residue": 0,
            "duplicate_errors": 0,
        }
        for source, target in pairs:
            stats["checked"] += 1
            if not self.check_protected_tokens(source, target):
                stats["token_errors"] += 1
            if not self.check_empty(source, target):
                stats["empty_errors"] += 1
            if not self.check_mask_artifacts(target):
                stats["mask_artifacts"] += 1
            if not self.check_length_ratio(source, target):
                stats["length_errors"] += 1
            if not self.check_english_residue(target):
                stats["english_residue"] += 1
            if not self.check_duplicate_translation(source, target):
                stats["duplicate_errors"] += 1
        return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Font Kontrolü
# ═══════════════════════════════════════════════════════════════════════════════

# Türkçe'ye özgü karakterler
_TURKISH_CHARS = set("şŞğĞıİöÖüÜçÇ")


class FontChecker:
    """TTF/OTF font dosyalarında Türkçe karakter desteğini kontrol eder."""

    @staticmethod
    def check_turkish_support(font_path: str | Path, chars: Any = None) -> dict:
        """
        Font dosyasını tarayarak hedef dilin karakterlerini (varsayılan Türkçe) kontrol eder.
        TTF/OTF cmap tablosunu okur.
        """
        chars = set(chars) if chars else _TURKISH_CHARS
        font_path = Path(font_path)
        result: dict[str, Any] = {
            "path": str(font_path),
            "exists": font_path.exists(),
            "supported_chars": [],
            "missing_chars": [],
            "fully_supported": False,
            "error": None,
        }
        if not font_path.exists():
            result["error"] = "Dosya bulunamadı"
            return result

        try:
            codepoints = FontChecker._read_cmap(font_path)
            for char in sorted(chars):
                if ord(char) in codepoints:
                    result["supported_chars"].append(char)
                else:
                    result["missing_chars"].append(char)
            result["fully_supported"] = len(result["missing_chars"]) == 0
        except Exception as e:
            result["error"] = str(e)
            result["missing_chars"] = sorted(chars)

        return result

    @staticmethod
    def _read_cmap(font_path: Path) -> set[int]:
        """TTF/OTF dosyasından cmap tablosunu oku ve desteklenen kod noktalarını döndür."""
        codepoints: set[int] = set()
        with font_path.open("rb") as f:
            # Offset Table
            data = f.read(12)
            if len(data) < 12:
                return codepoints
            sfversion = data[:4]
            num_tables = struct.unpack(">H", data[4:6])[0]

            # Tablo dizinini oku
            cmap_offset = 0
            for _ in range(num_tables):
                entry = f.read(16)
                if len(entry) < 16:
                    break
                tag = entry[:4]
                offset = struct.unpack(">I", entry[8:12])[0]
                if tag == b"cmap":
                    cmap_offset = offset
                    break

            if not cmap_offset:
                return codepoints

            # cmap tablosunu oku
            f.seek(cmap_offset)
            header = f.read(4)
            if len(header) < 4:
                return codepoints
            _, num_subtables = struct.unpack(">HH", header)

            # Format 4 (BMP) alt tablosunu bul
            for _ in range(num_subtables):
                sub_entry = f.read(8)
                if len(sub_entry) < 8:
                    break
                platform_id, encoding_id = struct.unpack(">HH", sub_entry[:4])
                sub_offset = struct.unpack(">I", sub_entry[4:8])[0]

                # Unicode veya Windows BMP
                if (platform_id == 0 or
                    (platform_id == 3 and encoding_id == 1)):
                    saved = f.tell()
                    f.seek(cmap_offset + sub_offset)
                    fmt = struct.unpack(">H", f.read(2))[0]

                    if fmt == 4:
                        codepoints.update(
                            FontChecker._parse_cmap_format4(f)
                        )
                        return codepoints
                    elif fmt == 12:
                        codepoints.update(
                            FontChecker._parse_cmap_format12(f)
                        )
                        return codepoints
                    f.seek(saved)

        return codepoints

    @staticmethod
    def _parse_cmap_format4(f: io.BufferedIOBase) -> set[int]:
        """cmap format 4 (Segment mapping) ayrıştır."""
        codepoints: set[int] = set()
        length = struct.unpack(">H", f.read(2))[0]
        _language = struct.unpack(">H", f.read(2))[0]
        seg_count_x2 = struct.unpack(">H", f.read(2))[0]
        seg_count = seg_count_x2 // 2
        f.read(6)  # searchRange, entrySelector, rangeShift

        end_codes = [struct.unpack(">H", f.read(2))[0] for _ in range(seg_count)]
        f.read(2)  # reservedPad
        start_codes = [struct.unpack(">H", f.read(2))[0] for _ in range(seg_count)]
        id_deltas = [struct.unpack(">h", f.read(2))[0] for _ in range(seg_count)]
        id_range_offset_pos = f.tell()
        id_range_offsets = [struct.unpack(">H", f.read(2))[0] for _ in range(seg_count)]

        for i in range(seg_count):
            start = start_codes[i]
            end = end_codes[i]
            delta = id_deltas[i]
            range_offset = id_range_offsets[i]

            if start == 0xFFFF:
                break

            for code in range(start, end + 1):
                if range_offset == 0:
                    glyph_id = (code + delta) & 0xFFFF
                else:
                    offset_addr = (
                        id_range_offset_pos + i * 2 + range_offset
                        + (code - start) * 2
                    )
                    saved = f.tell()
                    f.seek(offset_addr)
                    raw = f.read(2)
                    f.seek(saved)
                    if len(raw) < 2:
                        continue
                    glyph_id = struct.unpack(">H", raw)[0]
                    if glyph_id != 0:
                        glyph_id = (glyph_id + delta) & 0xFFFF

                if glyph_id != 0:
                    codepoints.add(code)

        return codepoints

    @staticmethod
    def _parse_cmap_format12(f: io.BufferedIOBase) -> set[int]:
        """cmap format 12 (Segmented coverage) ayrıştır."""
        codepoints: set[int] = set()
        f.read(2)  # reserved
        _length = struct.unpack(">I", f.read(4))[0]
        _language = struct.unpack(">I", f.read(4))[0]
        num_groups = struct.unpack(">I", f.read(4))[0]

        for _ in range(num_groups):
            start = struct.unpack(">I", f.read(4))[0]
            end = struct.unpack(">I", f.read(4))[0]
            _start_glyph = struct.unpack(">I", f.read(4))[0]
            # Türkçe karakterler BMP aralığında — tümünü eklememize gerek yok
            for code in range(start, min(end + 1, 0x500)):
                codepoints.add(code)

        return codepoints

    @staticmethod
    def scan_game_fonts(
        game_dir: Path, extensions: tuple[str, ...] = (".ttf", ".otf", ".woff")
    ) -> list[dict]:
        """Oyun klasöründeki tüm font dosyalarını tara ve Türkçe desteğini kontrol et."""
        results: list[dict] = []
        for path in game_dir.rglob("*"):
            if path.suffix.lower() in extensions and path.is_file():
                results.append(FontChecker.check_turkish_support(path))
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# İlerleme Takibi + ETA
# ═══════════════════════════════════════════════════════════════════════════════

class ProgressTracker:
    """İlerleme takibi ve tahmini kalan süre (ETA) hesaplayıcısı."""

    def __init__(self):
        self._total: int = 0
        self._done: int = 0
        self._start_time: float = 0.0
        self._last_update: float = 0.0

    def start(self, total: int) -> None:
        self._total = max(total, 1)
        self._done = 0
        self._start_time = time.monotonic()
        self._last_update = self._start_time

    def advance(self, n: int = 1) -> None:
        self._done = min(self._done + n, self._total)
        self._last_update = time.monotonic()

    @property
    def done(self) -> int:
        return self._done

    @property
    def total(self) -> int:
        return self._total

    def percent(self) -> float:
        if self._total == 0:
            return 0.0
        return (self._done / self._total) * 100.0

    def elapsed(self) -> float:
        """Geçen süre (saniye)."""
        return time.monotonic() - self._start_time

    def eta_seconds(self) -> float | None:
        """Tahmini kalan süre (saniye). Yeterli veri yoksa None."""
        if self._done == 0:
            return None
        elapsed = self.elapsed()
        if elapsed <= 0:
            return None
        rate = self._done / elapsed  # birim/saniye
        remaining = self._total - self._done
        return remaining / rate if rate > 0 else None

    def eta_str(self) -> str:
        """İnsan okunabilir ETA dizesi."""
        seconds = self.eta_seconds()
        if seconds is None:
            return "hesaplanıyor..."
        if seconds < 60:
            return f"~{int(seconds)} saniye"
        if seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"~{minutes} dakika {secs} saniye"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"~{hours} saat {minutes} dakika"

    def rate_str(self) -> str:
        """İşlem hızı dizesi."""
        elapsed = self.elapsed()
        if elapsed == 0 or self._done == 0:
            return "..."
        rate = self._done / elapsed
        return f"{rate:.1f} satır/sn"

    def summary(self) -> str:
        """Kısa özet dizesi."""
        return (
            f"{self._done}/{self._total} "
            f"({self.percent():.1f}%) — "
            f"ETA: {self.eta_str()} — "
            f"Hız: {self.rate_str()}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Yedekleme Yöneticisi
# ═══════════════════════════════════════════════════════════════════════════════

class BackupManager:
    """ZIP tabanlı yedekleme ve geri yükleme yöneticisi."""

    @staticmethod
    def create_backup(
        source_dir: Path,
        backup_dir: Path,
        prefix: str = "backup",
        log: LogFn = print,
    ) -> Path | None:
        """Kaynak klasörü ZIP olarak yedekle."""
        if not source_dir.exists():
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = backup_dir / f"{prefix}_{stamp}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in source_dir.rglob("*"):
                if path.is_file():
                    try:
                        archive.write(path, path.relative_to(source_dir.parent))
                    except (OSError, ValueError):
                        continue
        log(f"Yedek oluşturuldu: {target}")
        return target

    @staticmethod
    def list_backups(
        backup_dir: Path, prefix: str = "backup"
    ) -> list[Path]:
        """Yedekleri listele (en yeniden en eskiye)."""
        if not backup_dir.exists():
            return []
        return sorted(
            backup_dir.glob(f"{prefix}_*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    @staticmethod
    def restore_backup(
        backup_path: Path,
        target_dir: Path,
        log: LogFn = print,
    ) -> None:
        """Yedekten geri yükle."""
        if not backup_path.exists():
            raise FileNotFoundError(f"Yedek bulunamadı: {backup_path}")
        target_dir_resolved = target_dir.resolve()
        with zipfile.ZipFile(backup_path, "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                # Güvenlik kontrolü
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                dest = (target_dir_resolved / member_path).resolve()
                if target_dir_resolved not in dest.parents and dest != target_dir_resolved:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
        log(f"Yedekten geri yüklendi: {backup_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Çeviri Motoru (OPUS / NLLB ortak yükleyici ve toplu çevirici)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModelInfo:
    """Model bilgileri."""
    kind: str  # "opus" veya "nllb"
    directory: Path
    label: str
    files: dict[str, int] = field(default_factory=dict)
    base_url: str = ""


OPUS_MODEL_FILES = {
    "config.json": 1_137,
    "generation_config.json": 301,
    "pytorch_model.bin": 469_780_741,
    "source.spm": 796_953,
    "target.spm": 833_391,
    "special_tokens_map.json": 65,
    "tokenizer_config.json": 337,
    "vocab.json": 1_501_287,
}

NLLB_MODEL_FILES = {
    "config.json": 846,
    "generation_config.json": 189,
    "pytorch_model.bin": 2_460_457_927,
    "sentencepiece.bpe.model": 4_852_054,
    "special_tokens_map.json": 3_548,
    "tokenizer.json": 17_331_176,
    "tokenizer_config.json": 564,
}


def get_model_info(kind: str, base_dir: Path) -> ModelInfo:
    """Model türüne göre bilgileri döndür."""
    if kind == "gemini":
        return ModelInfo(
            kind="gemini",
            directory=base_dir / "portable_cache",
            label="Yapay Zeka (Gemini Flash)",
            files={},
            base_url="",
        )
    if kind == "nllb":
        return ModelInfo(
            kind="nllb",
            directory=base_dir / "model_nllb",
            label="NLLB kaliteli",
            files=NLLB_MODEL_FILES,
            base_url="https://huggingface.co/facebook/nllb-200-distilled-600M/resolve/main",
        )
    if kind == "ollama":
        # Ollama yerel LLM — dosya gerektirmez, servis kontrolü yapılır
        return ModelInfo(
            kind="ollama",
            directory=base_dir / "model_ollama",
            label="Ollama LLM (doğal çeviri)",
            files={},
            base_url="",
        )
    return ModelInfo(
        kind="opus",
        directory=base_dir / "model",
        label="OPUS hızlı",
        files=OPUS_MODEL_FILES,
        base_url="https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr/resolve/main",
    )


def model_ready(kind: str, base_dir: Path) -> bool:
    """Modelin indirilmiş ve hazır olduğunu kontrol et."""
    if kind == "gemini":
        try:
            from providers import load_provider_config
            if load_provider_config().gemini_keys:
                return True
        except Exception:
            pass
        candidates = [
            base_dir / "gemini_api_key.txt",
            Path("c:/RenPyTurkce/gemini_api_key.txt"),
            Path("C:/TurkceCeviri/gemini_api_key.txt"),
        ]
        return any(p.exists() and bool(p.read_text(encoding="utf-8").strip()) for p in candidates)
    if kind == "ollama":
        return ollama_service_running()
    info = get_model_info(kind, base_dir)
    for name, expected in info.files.items():
        path = info.directory / name
        if name == "pytorch_model.bin" and not path.exists():
            # fp16'ya küçültülmüş model: safetensors yaklaşık yarı boyuttadır
            path, expected = info.directory / "model.safetensors", expected // 2 - 1_000_000
        if not path.exists() or path.stat().st_size < max(1, expected - 16):
            return False
    return True


def ollama_service_running() -> bool:
    """Ollama servisinin çalışıp çalışmadığını kontrol et."""
    try:
        import urllib.request as _req
        with _req.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ollama_list_models() -> list[str]:
    """Ollama üzerinde yüklü modelleri listele."""
    try:
        import json as _json
        import urllib.request as _req
        with _req.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = _json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []



# Uygulama dil kodu → NLLB-200 (FLORES-200) kodu
NLLB_LANG_CODES = {
    "tr": "tur_Latn", "en": "eng_Latn", "es": "spa_Latn", "ru": "rus_Cyrl", "de": "deu_Latn",
    "fr": "fra_Latn", "it": "ita_Latn", "pt": "por_Latn", "pt-BR": "por_Latn", "pl": "pol_Latn",
    "ja": "jpn_Jpan", "zh-CN": "zho_Hans", "zh-TW": "zho_Hant", "ko": "kor_Hang", "ar": "arb_Arab",
    "uk": "ukr_Cyrl", "nl": "nld_Latn",
}


class TranslationEngine:
    """
    Yerel çeviri motoru — OPUS veya NLLB modeli ile toplu çeviri.
    Maskeleme, sözlük, önbellek ve TM entegreli.
    """

    def __init__(
        self,
        model_dir: Path,
        model_kind: str = "opus",
        cache: TranslationCache | None = None,
        glossary: Glossary | None = None,
        protected_pattern: re.Pattern | None = None,
        log: LogFn = print,
        source_lang: str = "en",
        target_lang: str = "tr",
    ):
        self.model_dir = model_dir
        self.model_kind = model_kind.casefold()
        self.source_lang = source_lang if source_lang and source_lang != "auto" else "en"
        self.target_lang = target_lang or "tr"
        self.cache = cache
        self.glossary = glossary
        self.pattern = protected_pattern
        self.log = log
        self._model = None
        self._tokenizer = None
        self._device: str = "cpu"
        self._forced_bos: int | None = None
        self._max_batch: int = 16
        self._token_budget: int = 512

    def load_model(self) -> None:
        """Çeviri modelini belleğe yükle."""
        import torch

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self._device == "cuda" else torch.float32

        if self.model_kind == "nllb":
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            self.log(
                f"NLLB modeli yükleniyor "
                f"({'GPU' if self._device == 'cuda' else 'CPU'})..."
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_dir), local_files_only=True,
                src_lang=NLLB_LANG_CODES.get(self.source_lang, "eng_Latn"),
            )
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                str(self.model_dir), local_files_only=True, dtype=dtype,
            ).to(self._device).eval()
            self._forced_bos = self._tokenizer.convert_tokens_to_ids(NLLB_LANG_CODES.get(self.target_lang, "tur_Latn"))
            self._max_batch = 32 if self._device == "cuda" else 4
            self._token_budget = 900 if self._device == "cuda" else 256
        else:
            from transformers import MarianMTModel, MarianTokenizer

            self.log(
                f"OPUS modeli yükleniyor "
                f"({'GPU' if self._device == 'cuda' else 'CPU'})..."
            )
            self._tokenizer = MarianTokenizer.from_pretrained(str(self.model_dir))
            self._model = MarianMTModel.from_pretrained(
                str(self.model_dir), dtype=dtype,
            ).to(self._device).eval()
            self._forced_bos = None
            self._max_batch = 96 if self._device == "cuda" else 16
            self._token_budget = 1200 if self._device == "cuda" else 512

    def set_languages(self, source_lang: str, target_lang: str) -> None:
        """NLLB'de kaynak/hedef dili değiştirir (model yeniden yüklenmez)."""
        self.source_lang = source_lang if source_lang and source_lang != "auto" else "en"
        self.target_lang = target_lang or "tr"
        if self.model_kind == "nllb" and self._tokenizer is not None:
            self._tokenizer.src_lang = NLLB_LANG_CODES.get(self.source_lang, "eng_Latn")
            self._forced_bos = self._tokenizer.convert_tokens_to_ids(NLLB_LANG_CODES.get(self.target_lang, "tur_Latn"))

    def unload_model(self) -> None:
        """Modeli bellekten kaldır."""
        import torch

        del self._model
        self._model = None
        if self._device == "cuda":
            torch.cuda.empty_cache()

    def _run_batch(self, texts: list[str], beams: int = 2) -> list[str]:
        """Bir partiyi çevir."""
        import torch

        if not texts:
            return []
        encoded = self._tokenizer(
            texts, return_tensors="pt", padding=True,
            truncation=True, max_length=512,
        ).to(self._device)
        longest_source = int(
            encoded["attention_mask"].sum(dim=1).max().item()
        )
        output_limit = min(320, max(32, int(longest_source * 1.6) + 24))
        with torch.inference_mode():
            gen_args: dict[str, Any] = {
                "max_new_tokens": output_limit,
                "num_beams": beams,
                "early_stopping": True,
                "no_repeat_ngram_size": 3,
                "repetition_penalty": 1.08,
            }
            if self._forced_bos is not None:
                gen_args["forced_bos_token_id"] = self._forced_bos
            generated = self._model.generate(**encoded, **gen_args)
        return self._tokenizer.batch_decode(generated, skip_special_tokens=True)

    def translate_batch(
        self,
        sources: list[str],
        progress: ProgressFn | None = None,
        tracker: ProgressTracker | None = None,
    ) -> dict[str, str]:
        """
        Kaynak metinleri toplu olarak çevir.
        Önbellek, sözlük ve TM desteği dahil.
        Dönen dict: {kaynak: çeviri}
        """
        import torch
        import collections as _collections

        if self._model is None:
            self.load_model()

        results: dict[str, str] = {}

        # 1) Önbellek, sözlük ve teknik metin filtresi
        to_translate: list[str] = []
        for source in sources:
            if not source or not source.strip():
                results[source] = source
                continue
            # Sözlük tam eşleşmesi
            if self.glossary:
                gl = self.glossary.lookup(source)
                if gl is not None:
                    results[source] = gl
                    continue
            # Önbellek tam eşleşmesi
            if self.cache and source in self.cache:
                results[source] = self.cache.get(source)
                continue
            # TM bulanık eşleşme
            if self.cache:
                fuzzy = self.cache.get_fuzzy(source, threshold=0.85)
                if fuzzy is not None:
                    results[source] = fuzzy
                    continue
            # Harf içermeyen teknik metinleri atla
            if not re.search(r"[A-Za-zÀ-ž]", source):
                results[source] = source
                continue
            to_translate.append(source)

        if not to_translate:
            return results

        # 2) Maskele ve uzunluklara göre sırala
        masked_data: list[tuple[str, str, list[str]]] = []
        lengths: list[int] = []
        for source in to_translate:
            if self.pattern:
                prepared, values = mask_text(source, self.pattern)
            else:
                prepared, values = source, []
            masked_data.append((source, prepared, values))
            lengths.append(
                len(self._tokenizer.encode(prepared, add_special_tokens=True))
            )

        order = sorted(range(len(masked_data)), key=lengths.__getitem__)

        # 3) Partilere ayır
        batches: list[list[int]] = []
        current: list[int] = []
        current_max = 0
        for idx in order:
            cand_max = max(current_max, lengths[idx])
            cand_size = len(current) + 1
            if current and (
                cand_size > self._max_batch
                or cand_max * cand_size > self._token_budget
            ):
                batches.append(current)
                current = []
                current_max = 0
            current.append(idx)
            current_max = max(current_max, lengths[idx])
        if current:
            batches.append(current)

        # 4) Parti parti çevir — orijinal engine.py mantığıyla
        pending = _collections.deque(batches)
        done_count = 0
        if tracker:
            tracker.start(len(to_translate))

        while pending:
            indexes = pending.popleft()
            longest = max(lengths[i] for i in indexes)
            batch_beams = 1 if longest > 160 else 2
            try:
                batch_results = self._run_batch(
                    [masked_data[i][1] for i in indexes],
                    beams=batch_beams,
                )
            except RuntimeError as error:
                if self._device == "cuda" and "out of memory" in str(error).lower():
                    torch.cuda.empty_cache()
                    if len(indexes) > 1:
                        mid = len(indexes) // 2
                        pending.appendleft(indexes[mid:])
                        pending.appendleft(indexes[:mid])
                        self.log(
                            f"GPU belleği doldu; parti {len(indexes)} → "
                            f"{mid}+{len(indexes)-mid} bölündü."
                        )
                        continue
                    self.log("Tek uzun metin düşük bellek modunda yeniden deneniyor.")
                    batch_results = self._run_batch([masked_data[indexes[0]][1]], beams=1)
                else:
                    raise

            for i, result in zip(indexes, batch_results):
                source, _, values = masked_data[i]
                if values:
                    restored = unmask_text(result, values)
                    if restored is None or (
                        self.pattern
                        and not protected_content_valid(source, restored, self.pattern)
                    ):
                        # Fallback: orijinal gibi parçalı çeviri
                        parts = self.pattern.split(source) if self.pattern else [source]
                        plain = [
                            p for p in parts
                            if p and not (self.pattern and self.pattern.fullmatch(p))
                        ]
                        if plain:
                            translated_parts = iter(self._run_batch(plain, beams=1))
                            restored = "".join(
                                p if (self.pattern and self.pattern.fullmatch(p))
                                else next(translated_parts, p)
                                for p in parts
                                if p
                            )
                        else:
                            restored = source
                    if self.pattern and not protected_content_valid(
                        source, restored, self.pattern
                    ):
                        restored = source
                else:
                    restored = result

                if source and not restored:
                    restored = source

                results[source] = restored
                if self.cache:
                    self.cache.set(source, restored)

            done_count += len(indexes)
            if self.cache and done_count % 50 == 0:
                self.cache.save()
            if progress:
                try:
                    progress(done_count, len(to_translate))
                except BaseException:
                    if self.cache:
                        self.cache.save()  # iptalde ilerleme kaybolmasın
                    raise
            if tracker:
                tracker.advance(len(indexes))



        if self.cache:
            self.cache.save()

        return results


# ═══════════════════════════════════════════════════════════════════════════════
# Yardımcı Fonksiyonlar
# ═══════════════════════════════════════════════════════════════════════════════

def encode_literal(value: str) -> str:
    """Python dizesini JSON string olarak kodla."""
    return json.dumps(value, ensure_ascii=False)


def decode_literal(value: str) -> str:
    """JSON veya Python string literalini çöz."""
    import ast
    return ast.literal_eval(value)


def cache_file_for(root: Path, app_data: Path, suffix: str = "") -> Path:
    """Oyun klasörüne özel önbellek dosya yolunu hesapla."""
    identity = hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:12]
    return app_data / "cache" / f"{identity}{suffix}.json"


def safe_archive_member(name: str) -> Path:
    """Güvensiz arşiv yollarını kontrol et."""
    from pathlib import PurePosixPath
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"Güvensiz arşiv yolu: {name}")
    return Path(*member.parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Ollama LLM Çeviri Motoru — Toplu (batch) API çağrısı desteği
# ═══════════════════════════════════════════════════════════════════════════════

class OllamaTranslationEngine:
    """
    Ollama üzerinden yerel LLM ile toplu çeviri motoru.

    Her API çağrısında BATCH_SIZE kadar cümle gönderilir (varsayılan 30).
    76k cümle için ~2.5k API çağrısı yapar (tek tek yerine 76k çağrı değil).

    Gereksinim: Ollama kurulu ve çalışıyor olmalı (https://ollama.com)
    Önerilen modeller:
      - qwen2.5:7b       (~4.5 GB, genel, iyi Türkçe)
      - qwen2.5:14b      (~8.7 GB, kaliteli)
      - dolphin-mistral  (sansürsüz, yetişkin içerik için ideal)
      - llama3.2:3b      (~2 GB, hızlı)
    """

    _SEP = "§SEP§"

    _SYSTEM_PROMPT_OTHER = (
        "\n\nKeep game codes such as \\C[1] \\V[2] {PlayerName} [name] %s exactly as they are. "
        "Write only the translations and separate each one with the exact token §SEP§."
    )
    _SYSTEM_PROMPT = (
        "Sen profesyonel bir İngilizce→Türkçe çevirmensin. "
        "Metinleri doğal, akıcı, günlük konuşma diline uygun Türkçeye çevir. "
        "KURALLAR: "
        "1) Sadece çevirileri yaz, başka hiçbir şey ekleme. "
        "2) Tonu koru: argo→argo, resmi→resmi, samimi→samimi. "
        "3) Karakter adlarını ve oyun terimlerini değiştirme. "
        "4) \\C[1] \\V[2] {PlayerName} [name] %s gibi oyun kodlarını OLDUĞU GİBİ bırak. "
        "5) Yetişkin içerikte tıbbi terimler yerine günlük Türkçe kullan. "
        "6) Her çeviriyi tam olarak §SEP§ belirteciyle ayır."
    )

    def __init__(
        self,
        model_name: str = "qwen2.5:7b",
        cache=None,
        glossary=None,
        protected_pattern=None,
        log=print,
        host: str = "http://localhost:11434",
        temperature: float = 0.1,
        batch_size: int = 30,
        target_lang: str = "tr",
        source_lang: str = "en",
    ):
        self.model_name = model_name
        self.cache = cache
        self.glossary = glossary
        self.pattern = protected_pattern
        self.log = log
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.batch_size = max(1, batch_size)
        self.target_lang = target_lang
        self.source_lang = source_lang

    def _api_batch(self, texts: list) -> list:
        """Birden fazla metni tek API çağrısıyla çevir, §SEP§ ile ayırır."""
        import json as _j
        import urllib.request as _r

        sep = self._SEP
        body = ("\n" + sep + "\n").join(texts)
        msg = (
            f"{len(texts)} metni sıraya göre Türkçeye çevir. "
            f"Her çeviriyi '{sep}' ile ayır, başka HİÇBİR ŞEY EKLEME:\n\n{body}"
        )
        total_chars = sum(len(t) for t in texts)
        payload = _j.dumps({
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user",   "content": msg},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": min(8192, max(512, total_chars * 4)),
                "num_ctx":     max(8192, total_chars * 5 + 1024),
            },
        }).encode("utf-8")

        req = _r.Request(
            f"{self.host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _r.urlopen(req, timeout=600) as r:
            raw = _j.loads(r.read())["message"]["content"].strip()

        parts = [p.strip() for p in raw.split(sep)]
        while len(parts) < len(texts):
            parts.append("")
        return parts[:len(texts)]

    def _system_prompt(self) -> str:
        if self.target_lang == "tr":
            return self._SYSTEM_PROMPT
        from languages import build_system_instruction
        return build_system_instruction(self.target_lang, self.source_lang, "video game") + self._SYSTEM_PROMPT_OTHER

    def translate_batch(self, sources: list, progress=None, tracker=None) -> dict:
        """Toplu çeviri — önbellek+sözlük filtresi, ardından BATCH_SIZE'lık API çağrıları."""
        results: dict = {}

        if tracker:
            tracker.start(len(sources))

        # Hızlı filtre: önbellek, sözlük, teknik metinler
        pending = []
        for i, src in enumerate(sources):
            if not src or not src.strip():
                results[src] = src
                if tracker: tracker.advance()
                continue
            if self.glossary:
                gl = self.glossary.lookup(src)
                if gl is not None:
                    results[src] = gl
                    if tracker: tracker.advance()
                    continue
            if self.cache and src in self.cache:
                results[src] = self.cache.get(src)
                if tracker: tracker.advance()
                continue
            if not re.search(r"[^\W\d_]", src):   # harf yoksa (sayı/simge) çevrilmez; her alfabe sayılır
                results[src] = src
                if tracker: tracker.advance()
                continue
            masked, vals = (mask_text(src, self.pattern) if self.pattern else (src, []))
            pending.append((i, src, masked, vals))

        if not pending:
            if self.cache: self.cache.save()
            return results

        total_batches = (len(pending) + self.batch_size - 1) // self.batch_size
        self.log(
            f"Ollama toplu çeviri: {len(pending)} metin, "
            f"{self.batch_size} cümle/istek = {total_batches} API çağrısı"
        )

        done = sum(1 for s in sources if s in results)

        for bi, bs in enumerate(range(0, len(pending), self.batch_size), 1):
            chunk = pending[bs: bs + self.batch_size]
            masked_list = [x[2] for x in chunk]

            try:
                translations = self._api_batch(masked_list)
            except Exception as e:
                self.log(f"Ollama hata (batch {bi}/{total_batches}): {e} — orijinal bırakılıyor")
                for _, src, _, _ in chunk:
                    results[src] = src
                    if tracker: tracker.advance()
                done += len(chunk)
                if progress: progress(done, len(sources))
                continue

            for (_, src, _, vals), tr in zip(chunk, translations):
                if not tr:
                    results[src] = src
                elif vals:
                    restored = unmask_text(tr, vals)
                    ok = restored and (
                        not self.pattern
                        or protected_content_valid(src, restored, self.pattern)
                    )
                    results[src] = restored if ok else src
                else:
                    results[src] = tr

                if self.cache and results[src] != src:
                    self.cache.set(src, results[src])
                if tracker:
                    tracker.advance()

            done += len(chunk)
            if self.cache: self.cache.save()
            if progress: progress(done, len(sources))
            self.log(
                f"[Ollama {bi}/{total_batches}] "
                f"{done}/{len(sources)} metin | "
                f"{tracker.eta_str() if tracker else ''}"
            )

        if self.cache:
            self.cache.save()
        return results


