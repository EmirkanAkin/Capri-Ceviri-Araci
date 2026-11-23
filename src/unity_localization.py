"""
Capri — Unity Localization paketi (com.unity.localization) dize tabloları
========================================================================
İki saklama biçimi desteklenir:

1. **Veri dosyası tabloları** (Unity 6): ``<Oyun>_Data/StreamingAssets/LocalizationTables/<Koleksiyon>_<dil>.json``.
   Unity bu klasördeki dosyalardan dilleri açılışta kendisi bulur; Capri kaynak dilin dosyasını kopyalayıp
   ``<Koleksiyon>_tr.json`` olarak yazar. Oyunun dosyalarına dokunulmaz, Türkçe oyunun dil listesine eklenir ve sistem
   dili Türkçe olan bilgisayarda kendiliğinden seçilir. Anahtarlar, kimlikler ve SchemaVersion aynen kalır.

2. **Addressables paketleri**: ``StreamingAssets/aa/<platform>/localization-string-tables-*.bundle``. StringTable
   bileşenlerindeki (m_TableData[i].m_Localized) kaynak dil metinleri yerinde çevrilir; oyunda dil olarak kaynak dil
   (çoğunlukla English) seçilince Türkçe görünür. Addressables yerel paketleri katalogdaki CRC ile doğrulayabildiği
   için değiştirilen paketin katalog.json'daki m_Crc değeri 0 yapılır (aynı uzunlukta, JSON geçerli kalır). CRC
   güvenle kapatılamazsa (ikili catalog.bin, eşleşmeyen paket adı) ya da bileşen birebir okunamazsa dosyalara
   dokunulmaz. Paket kaydedildikten sonra yeniden okunup yeni değerler denetlenir.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

LogFn = Callable[[str], None]
DATA_DIR_NAME = "LocalizationTables"
REQUEST_OPTIONS = b"UnityEngine.ResourceManagement.ResourceProviders.AssetBundleRequestOptions"
_FILE_NAME = re.compile(r"^(?P<collection>.+)_(?P<locale>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)\.json$")
_VALUE_FIELDS = ("Localized", "m_Localized", "LocalizedValue", "Value", "value", "m_Value", "Text", "text",
                 "Translation", "translation")
_KEYISH = re.compile(r"key|id$|guid|metadata|shared|smart|flag", re.I)
_UNITY_LOCALE = {"zh-hans": "zh-Hans", "zh-hant": "zh-Hant", "pt-br": "pt-BR", "en-us": "en-US", "es-419": "es-419"}


def unity_locale(code: str) -> str:
    return _UNITY_LOCALE.get(code.lower(), code)


def _same_lang(a: str, b: str) -> bool:
    return a.lower().replace("_", "-").split("-")[0] == b.lower().replace("_", "-").split("-")[0]


# ── 1. Veri dosyası tabloları (JSON) ────────────────────────────────────────
@dataclass
class FileTable:
    path: Path
    collection: str
    locale: str
    data: dict
    value_field: str = ""


def data_files(info: Any) -> List[Path]:
    base = Path(getattr(info, "streaming_assets_dir", "") or "") / DATA_DIR_NAME
    return sorted(p for p in base.glob("*.json") if _FILE_NAME.match(p.name)) if base.is_dir() else []


def _load(path: Path) -> Optional[FileTable]:
    m = _FILE_NAME.match(path.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not m or not isinstance(data, dict) or not isinstance(data.get("Entries"), list):
        return None
    locale = str(data.get("LocaleCode") or m.group("locale"))
    return FileTable(path, str(data.get("CollectionName") or m.group("collection")), locale, data)


def _value_field(table: FileTable, others: Iterable[FileTable]) -> str:
    """Girdilerde çevrilecek alan: başka bir dildeki aynı tabloyla farklılaşan dize alanı; yoksa bilinen adlar;
    yoksa anahtar/kimlik olmayan tek dize alanı."""
    entries = [e for e in table.data["Entries"] if isinstance(e, dict)]
    if not entries:
        return ""
    string_fields = [k for k, v in entries[0].items() if isinstance(v, str)]
    for other in others:
        o_entries = [e for e in other.data["Entries"] if isinstance(e, dict)]
        if len(o_entries) != len(entries):
            continue
        differing = [k for k in string_fields if any(a.get(k) != b.get(k) for a, b in zip(entries, o_entries))]
        if len(differing) == 1:
            return differing[0]
    for name in _VALUE_FIELDS:
        if name in string_fields:
            return name
    candidates = [k for k in string_fields if not _KEYISH.search(k)]
    return candidates[0] if len(candidates) == 1 else ""


def file_tables(info: Any, source: str = "en", log: LogFn = print) -> List[FileTable]:
    """Kaynak dildeki tablolar (koleksiyon başına bir tane)."""
    tables = [t for t in (_load(p) for p in data_files(info)) if t]
    by_collection: Dict[str, List[FileTable]] = {}
    for t in tables:
        by_collection.setdefault(t.collection, []).append(t)
    out = []
    for collection, group in sorted(by_collection.items()):
        src = next((t for t in group if _same_lang(t.locale, source)), None) or \
            next((t for t in group if _same_lang(t.locale, "en")), None) or group[0]
        src.value_field = _value_field(src, [t for t in group if t is not src])
        if not src.value_field:
            log(f"Unity Localization: {src.path.name} girdi biçimi tanınmadı (atlandı)")
            continue
        out.append(src)
    return out


def file_target_path(table: FileTable, target: str) -> Path:
    return table.path.with_name(f"{table.collection}_{unity_locale(target)}.json")


def write_file_table(table: FileTable, translations: Dict[str, str], target: str) -> Tuple[Path, int]:
    """Kaynak tablonun hedef dildeki kopyasını yazar: (dosya, çevrilen girdi)."""
    data = json.loads(json.dumps(table.data))
    data["LocaleCode"] = unity_locale(target)
    changed = 0
    for entry in data["Entries"]:
        if not isinstance(entry, dict):
            continue
        original = entry.get(table.value_field)
        new = translations.get(original) if isinstance(original, str) else None
        if new and new != original:
            entry[table.value_field] = new
            changed += 1
    path = file_target_path(table, target)
    from fileio import atomic_write
    atomic_write(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return path, changed


# ── 2. Addressables StringTable paketleri ───────────────────────────────────
def bundles(info: Any) -> List[Path]:
    base = Path(getattr(info, "streaming_assets_dir", "") or "") / "aa"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.bundle") if "localization" in p.name.lower() and "string" in p.name.lower())


def catalog_path(info: Any) -> Optional[Path]:
    base = Path(getattr(info, "streaming_assets_dir", "") or "") / "aa"
    for name in ("catalog.json",):
        if (base / name).is_file():
            return base / name
    found = sorted(base.glob("catalog*.json")) if base.is_dir() else []
    return found[0] if found else None


@dataclass
class BundleEntry:
    bundle: Path
    path_id: int
    index: int
    entry_id: int
    text: str
    locale: str


def _is_string_table(tree: Any) -> bool:
    return isinstance(tree, dict) and isinstance(tree.get("m_TableData"), list) and "m_LocaleId" in tree


def scan_bundles(info: Any, source: str = "en", log: LogFn = print) -> List[BundleEntry]:
    import UnityPy
    from unity_typed import read_exact
    out: List[BundleEntry] = []
    for path in bundles(info):
        try:
            env = UnityPy.load(path.read_bytes())
        except Exception as exc:
            log(f"Unity Localization paketi okunamadı: {path.name}: {exc}")
            continue
        found: Dict[str, List[BundleEntry]] = {}
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if not _is_string_table(tree):
                continue
            locale = str((tree.get("m_LocaleId") or {}).get("m_Code") or "")
            if read_exact(obj) is None:
                log(f"{path.name} #{obj.path_id}: dize tablosu birebir okunamadı; dokunulmayacak")
                continue
            for index, entry in enumerate(tree["m_TableData"]):
                text = entry.get("m_Localized") if isinstance(entry, dict) else None
                if isinstance(text, str) and re.search(r"[^\W\d_]", text):
                    found.setdefault(locale, []).append(BundleEntry(path, obj.path_id, index, int(entry.get("m_Id", 0)), text, locale))
        for locale, entries in found.items():
            if _same_lang(locale, source):
                out += entries
        del env
    return out


def zero_crcs(catalog_text: str, bundle_names: Iterable[str]) -> Tuple[str, List[str]]:
    """Katalogdaki AssetBundleRequestOptions JSON'larında, verilen paketlerin m_Crc değerini 0 yapar. Metin uzunluğu
    değişmez (sayı boşlukla doldurulur), böylece kataloğun kayma tabloları bozulmaz. (yeni metin, bulunan paketler)"""
    catalog = json.loads(catalog_text)
    extra = bytearray(base64.b64decode(catalog.get("m_ExtraDataString") or ""))
    wanted = {n.lower() for n in bundle_names}
    found: List[str] = []
    at = 0
    while True:
        at = extra.find(REQUEST_OPTIONS, at)
        if at < 0:
            break
        start = at + len(REQUEST_OPTIONS)
        at = start
        if start + 4 > len(extra):
            break
        length = int.from_bytes(extra[start:start + 4], "little")
        body = bytes(extra[start + 4:start + 4 + length])
        try:
            options = json.loads(body.decode("utf-16-le"))
        except (UnicodeDecodeError, ValueError):
            continue
        name = str(options.get("m_BundleName") or "")
        stem = name.lower()
        match = next((w for w in wanted if w == stem or w.startswith(stem) or stem.startswith(w)), None) if stem else None
        if not match:
            continue
        found.append(match)
        if not options.get("m_Crc"):
            continue
        text = body.decode("utf-16-le")
        m = re.search(r'"m_Crc"\s*:\s*(\d+)', text)
        if not m:
            continue
        digits = m.group(1)
        new_text = text[:m.start(1)] + "0" + " " * (len(digits) - 1) + text[m.end(1):]
        if json.loads(new_text).get("m_Crc") != 0:
            raise ValueError("CRC kapatılamadı")
        new_body = new_text.encode("utf-16-le")
        assert len(new_body) == len(body)
        extra[start + 4:start + 4 + length] = new_body
    catalog_new = dict(catalog)
    catalog_new["m_ExtraDataString"] = base64.b64encode(bytes(extra)).decode("ascii")
    if catalog_new["m_ExtraDataString"] == catalog.get("m_ExtraDataString"):
        return catalog_text, found
    # Yalnızca m_ExtraDataString değeri değişir; dosyanın geri kalanı bayt bayt aynı kalır
    old_value = json.dumps(catalog["m_ExtraDataString"])
    if catalog_text.count(old_value) != 1:
        raise ValueError("katalog biçimi beklenmedik")
    return catalog_text.replace(old_value, json.dumps(catalog_new["m_ExtraDataString"])), found


def _bundle_key(path: Path) -> str:
    return path.stem.lower()


def write_bundles(info: Any, translations: Dict[str, str], entries: List[BundleEntry], log: LogFn = print,
                  replace_file: Optional[Callable[[Path, bytes], None]] = None) -> int:
    import gc

    import UnityPy
    from UnityPy.files import BundleFile
    from unity_typed import read_exact

    from fileio import atomic_write
    write = replace_file or atomic_write
    by_bundle: Dict[Path, List[BundleEntry]] = {}
    for e in entries:
        new = translations.get(e.text)
        if new and new != e.text:
            by_bundle.setdefault(e.bundle, []).append(e)
    if not by_bundle:
        return 0
    catalog = catalog_path(info)
    if catalog is None:
        log("Unity Localization: Addressables kataloğu (catalog.json) bulunamadı; ikili katalogda CRC kapatılamadığı "
            "için paketlere dokunulmadı.")
        return 0
    catalog_text = catalog.read_text(encoding="utf-8")
    new_catalog, matched = zero_crcs(catalog_text, [_bundle_key(p) for p in by_bundle])
    missing = [p.name for p in by_bundle if not any(_bundle_key(p).startswith(m) or m.startswith(_bundle_key(p)) for m in matched)]
    if missing:
        log(f"Unity Localization: katalogda paket kaydı bulunamadı ({missing[0]}); paketlere dokunulmadı.")
        return 0
    outputs: Dict[Path, bytes] = {}
    written = 0
    for path, items in by_bundle.items():
        env = UnityPy.load(path.read_bytes())
        wanted: Dict[int, List[BundleEntry]] = {}
        for e in items:
            wanted.setdefault(e.path_id, []).append(e)
        expected: Dict[int, Dict[int, str]] = {}
        for obj in env.objects:
            if obj.path_id not in wanted:
                continue
            exact = read_exact(obj)
            if exact is None:
                continue
            node, tree = exact
            changed = 0
            for e in wanted[obj.path_id]:
                rows = tree["m_TableData"]
                if e.index >= len(rows) or rows[e.index].get("m_Localized") != e.text or int(rows[e.index].get("m_Id", 0)) != e.entry_id:
                    continue
                rows[e.index]["m_Localized"] = translations[e.text]
                expected.setdefault(obj.path_id, {})[e.index] = translations[e.text]
                changed += 1
            if changed:
                obj.save_typetree(tree, nodes=node)
                written += changed
        if not expected:
            continue
        data = env.file.save(packer="lz4") if isinstance(env.file, BundleFile) else env.file.save()
        del env
        gc.collect()
        check = UnityPy.load(data)
        for obj in check.objects:
            if obj.path_id in expected:
                rows = obj.read_typetree()["m_TableData"]
                if any(rows[i].get("m_Localized") != text for i, text in expected[obj.path_id].items()):
                    raise RuntimeError(f"{path.name}: kaydedilen paket doğrulanamadı; oyun dosyası değiştirilmedi")
        outputs[path] = data
    if not outputs:
        return 0
    for path, data in outputs.items():
        write(path, data)
    if new_catalog != catalog_text:
        atomic_write(catalog, new_catalog.encode("utf-8"))
        log("Unity Localization: değişen paketlerin katalog CRC denetimi kapatıldı")
    log(f"Unity Localization: {written} metin {len(outputs)} pakete yazıldı")
    return written


__all__ = ["data_files", "file_tables", "write_file_table", "file_target_path", "bundles", "scan_bundles",
           "write_bundles", "zero_crcs", "catalog_path", "unity_locale"]
