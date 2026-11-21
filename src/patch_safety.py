"""
Yama güvenliği: başkasından gelen .capripatch dosyası oyun dosyalarına yazılacak metin taşır.

Çeviriler oyunda çalışan yerlere gider: Ren'Py betikleri ({a=…} bağlantıları, [ifade] yerleştirmeleri), RPG Maker
MV/MZ mesajları (bazı eklentiler \\js<…> içindeki JavaScript'i çalıştırır; oyun nw.js'de tam bilgisayar erişimiyle
çalışır), Unity/Unreal metin tabloları. Bu yüzden içe aktarılan her satır şu kurallara uymalı:

  - motorun etiket/kod kuralına göre çeviride kaynaktakinden farklı (yeni ya da eksik) etiket, kod, değişken olmamalı;
  - bağlantı, betik ya da kod çalıştırabilecek kalıplar kaynakta yoksa çeviride de olmamalı;
  - kaynaktan fazla satır sonu ve kontrol karakteri olmamalı; çeviri makul uzunlukta olmalı.

Uymayan satır alınmaz. Arşiv boyutu ve satır sayısı da sınırlıdır (sıkıştırma bombasına karşı).
"""
from __future__ import annotations

import collections
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Tuple

MAX_MANIFEST = 64 * 1024
MAX_TRANSLATIONS = 32 * 1024 * 1024
MAX_ENTRIES = 300_000
MAX_SOURCE = 8_000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Hangi motorda olursa olsun: kaynakta yoksa çeviriye eklenemez
_RISKY = re.compile(
    r"\{\s*a\s*=|\\js\b|<\s*script|javascript:|https?://|\beval\s*\(|\bexec\s*\(|\bimport\s+\w|__\w+__|\$\{|`",
    re.IGNORECASE)


def engine_pattern(engine: str) -> "re.Pattern":
    """Motorun çeviride birebir korunması gereken etiket/kod kuralı (çeviri motorlarının kullandığı kuralın aynısı)."""
    if engine == "renpy":
        from engine_renpy import PROTECTED
        return PROTECTED
    if engine == "rpgmaker":
        from engine_rpgmaker import PROTECTED_RPGM
        return PROTECTED_RPGM
    if engine == "unity":
        from engine_unity import PROTECTED_UNITY
        return PROTECTED_UNITY
    if engine == "unreal":
        from engine_unreal import PROTECTED_UNREAL
        return PROTECTED_UNREAL
    from providers import CLOUD_PROTECTED
    return CLOUD_PROTECTED


def _tokens(pattern: "re.Pattern", text: str) -> collections.Counter:
    return collections.Counter(m.group(0) for m in pattern.finditer(text))


def safe_entry(source: Any, target: Any, pattern: "re.Pattern") -> bool:
    if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
        return False
    if len(source) > MAX_SOURCE or len(target) > 3 * len(source) + 200:
        return False
    if _CONTROL.search(target) or target.count("\n") > source.count("\n") or target.count("\r") > source.count("\r"):
        return False
    if _tokens(pattern, source) != _tokens(pattern, target):
        return False
    return all(_tokens(_RISKY, target)[k] <= n for k, n in _tokens(_RISKY, source).items()) and \
        not (set(_tokens(_RISKY, target)) - set(_tokens(_RISKY, source)))


def filter_translations(translations: Dict[Any, Any], engine: str) -> Tuple[Dict[str, str], int]:
    """(güvenli satırlar, alınmayan satır sayısı)"""
    pattern = engine_pattern(engine)
    safe = {k: v for k, v in translations.items() if safe_entry(k, v, pattern)}
    return safe, len(translations) - len(safe)


def read_patch(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Yama arşivini sınırlarla okur: yalnızca manifest.json ve translations.json, boyutları açılmadan denetlenir."""
    with zipfile.ZipFile(path) as archive:
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        if sizes.get("manifest.json", MAX_MANIFEST + 1) > MAX_MANIFEST:
            raise ValueError("manifest eksik ya da çok büyük")
        if sizes.get("translations.json", MAX_TRANSLATIONS + 1) > MAX_TRANSLATIONS:
            raise ValueError("çeviri dosyası eksik ya da çok büyük")
        manifest = json.loads(archive.read("manifest.json"))
        translations = json.loads(archive.read("translations.json"))
    if not isinstance(manifest, dict) or not isinstance(translations, dict) or len(translations) > MAX_ENTRIES:
        raise ValueError("yama biçimi geçersiz")
    return manifest, translations


# ── Tablo (CSV) dışa/içe aktarma ─────────────────────────────────────────────
# Çeviriyi Excel / Google E-Tablolar'da düzeltip geri almak için. Dışa aktarma Excel'in Türkçe/Avrupa ayarında doğrudan
# sütunlara bölünsün diye noktalı virgüllü ve UTF-8 BOM'ludur; içe aktarmada ayraç (; , sekme) kendiliğinden bulunur.
CSV_HEADER = ("Kaynak", "Çeviri", "İncelenmeli")
MAX_CSV = 64 * 1024 * 1024


def csv_export(cache: Dict[str, str], review: Any = ()) -> str:
    import csv
    import io
    flagged = set(review or ())
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for src in list(cache) + [r for r in flagged if r not in cache]:
        writer.writerow((src, cache.get(src, ""), "evet" if src in flagged else ""))
    return "﻿" + out.getvalue()


def csv_import(text: str, cache: Dict[str, str], known: Any, engine: str) -> Dict[str, Any]:
    """CSV'deki düzeltmeleri ayıklar. Yalnızca oyunda zaten bulunan kaynak satırlar alınır; her satır yama kuralıyla
    denetlenir. Döner: {"changes": {kaynak: çeviri}, "unchanged", "unknown", "rejected"}"""
    import csv
    import io
    if len(text) > MAX_CSV:
        raise ValueError("dosya çok büyük")
    text = text.lstrip("﻿")
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if rows and [c.strip().casefold() for c in rows[0][:2]] in (
            [h.casefold() for h in CSV_HEADER[:2]], ["source", "translation"]):
        rows = rows[1:]
    known = set(known)
    candidates: Dict[str, str] = {}
    unchanged = unknown = 0
    for row in rows[:MAX_ENTRIES]:
        if len(row) < 2 or not row[0]:
            continue
        src, tr = row[0], row[1]
        if src not in known:
            unknown += 1
        elif not tr.strip() or tr == cache.get(src, ""):
            unchanged += 1
        else:
            candidates[src] = tr
    safe, rejected = filter_translations(candidates, engine)
    return {"changes": safe, "unchanged": unchanged, "unknown": unknown, "rejected": rejected}
