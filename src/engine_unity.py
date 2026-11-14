"""
Unity Oyunları Türkçe Çeviri Motoru
===================================
Unity (Mono ve IL2CPP) oyunları için metin çıkarma, yapay zeka ile çeviri,
font uyumluluk denetimi ve varlık (asset) yamalama modülü.
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import UnityPy

from engine_common import (
    FontChecker,
    Glossary,
    LogFn,
    ProgressFn,
    ProgressTracker,
    TranslationCache,
)

# Unity metinlerindeki etiketler ve değişkenler (korunacak desenler)
PROTECTED_UNITY = re.compile(
    r"("
    r"<color=[^>]+>.*?</color>"
    r"|<size=[^>]+>.*?</size>"
    r"|</?[biu]>"
    r"|<[^>]+>"
    r"|\[[A-Za-z0-9_]+\]"          # [NAME], [SURNAME], [S], [/S], [mc] vb.
    r"|\[/[A-Za-z0-9_]+\]"
    r"|\{[0-9]+\}"                 # {0}, {1}, {2} string format
    r"|%[0-9]*[sdf]"               # %s, %d, %1$s
    r"|\\n|\\r|\\t"                # Escape karakterleri
    r")",
    re.IGNORECASE,
)

UNITY_BUILTIN_GLOSSARY = {
    "New Game": "Yeni Oyun",
    "Load Game": "Oyunu Yükle",
    "Save Game": "Oyunu Kaydet",
    "Options": "Seçenekler",
    "Settings": "Ayarlar",
    "Credits": "Emeği Geçenler",
    "Quit": "Çıkış",
    "Exit": "Çıkış",
    "Exit to Main Menu": "Ana Menüye Çık",
    "Exit to Desktop": "Masaüstüne Çık",
    "Resume": "Devam Et",
    "Pause": "Duraklat",
    "Audio": "Ses",
    "Video": "Görüntü",
    "Graphics": "Grafikler",
    "Controls": "Kontroller",
    "Language": "Dil",
    "English": "İngilizce",
    "Turkish": "Türkçe",
    "Music": "Müzik",
    "Sound": "Ses Efektleri",
    "SFX": "Ses Efektleri",
    "Voice": "Seslendirme",
    "Master Volume": "Genel Ses",
    "Fullscreen": "Tam Ekran",
    "Windowed": "Pencereli",
    "Resolution": "Çözünürlük",
    "Confirm": "Onayla",
    "Cancel": "İptal",
    "Back": "Geri",
    "Next": "İleri",
    "Close": "Kapat",
    "Apply": "Uygula",
    "Delete": "Sil",
    "Empty": "Boş",
    "Yes": "Evet",
    "No": "Hayır",
    "OK": "Tamam",
    "Auto": "Otomatik",
    "Skip": "Atla",
    "Log": "Kayıt",
    "Inventory": "Envanter",
    "Map": "Harita",
    "Shop": "Mağaza",
    "Warning": "Uyarı",
    "Error": "Hata",
}


@dataclass
class UnityTextItem:
    """Unity varlıklarından çıkarılan tek bir metin girdisi."""
    source_file: str       # Varlık dosyası adı (örn: 'resources.assets')
    asset_name: str        # TextAsset adı (örn: 'Q_LHS - General - English')
    line_index: int        # Satır no (0 tabanlı)
    key_id: str            # Varsa anahtar (örn: 'ID_MAINMENU_NEW_GAME')
    original: str          # Orijinal İngilizce metin
    format_type: str = "tsv"  # 'tsv', 'csv', 'json', 'raw'


@dataclass
class UnityGameInfo:
    """Algılanan Unity oyununun yapısal bilgileri."""
    root: Path
    data_dir: Path
    exe_path: Optional[Path]
    game_title: str
    runtime: str           # 'Mono' veya 'IL2CPP'
    unity_version: str     # örn: '2019.4.15f1'
    has_resources_assets: bool
    resources_assets_path: Optional[Path]
    sharedassets_files: List[Path] = field(default_factory=list)
    streaming_assets_dir: Optional[Path] = None
    localization_text_assets: List[str] = field(default_factory=list)
    embedded_fonts: List[str] = field(default_factory=list)
    font_turkish_support: bool = True
    missing_font_chars: List[str] = field(default_factory=list)
    scanned: bool = False          # varlık/font taraması yapıldı mı (bkz. scan_unity_assets)
    tmp_fonts: List[str] = field(default_factory=list)      # TextMeshPro font varlıkları
    tmp_glyphs: Set[int] = field(default_factory=set)       # bu fontların içerdiği karakterler (birleşim)


def detect_unity_game(selected: Union[str, Path]) -> Optional[UnityGameInfo]:
    """
    Seçilen dizinin Unity oyunu olup olmadığını tespit eder ve
    tüm yapısal bilgilerini döndürür.
    """
    path = Path(selected).expanduser().resolve()
    if not path.exists():
        return None
    if path.is_file():
        path = path.parent

    # 1. *_Data klasörünü bul
    data_dir = None
    if path.name.endswith("_Data") and path.is_dir():
        data_dir = path
        root = path.parent
    else:
        root = path
        for item in root.iterdir():
            if item.is_dir() and item.name.endswith("_Data"):
                data_dir = item
                break

    if not data_dir or not data_dir.is_dir():
        return None

    # Unity belirteçlerini doğrula
    has_ggm = (data_dir / "globalgamemanagers").exists()
    has_boot = (data_dir / "boot.config").exists()
    has_res = (data_dir / "resources.assets").exists()
    if not (has_ggm or has_boot or has_res):
        return None

    # 2. Çalıştırılabilir dosyayı (.exe) bul
    exe_path = None
    for f in root.glob("*.exe"):
        if f.name.lower() not in ("unitycrashhandler64.exe", "unitycrashhandler32.exe"):
            exe_path = f
            break

    # Oyun başlığı
    game_title = exe_path.stem if exe_path else data_dir.name.replace("_Data", "")

    # 3. Çalışma zamanı tespiti (Mono vs IL2CPP)
    runtime = "Mono"
    if (data_dir / "il2cpp_data").exists() or (root / "GameAssembly.dll").exists():
        runtime = "IL2CPP"
    elif (data_dir / "Managed").exists() or (root / "MonoBleedingEdge").exists():
        runtime = "Mono"

    # 4. Unity sürümünü oku
    unity_version = "Bilinmiyor"
    boot_config = data_dir / "boot.config"
    if boot_config.exists():
        try:
            for line in boot_config.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("player-connection-project-name="):
                    game_title = line.split("=", 1)[1].strip() or game_title
        except Exception:
            pass

    # 5. Asset dosyalarını tara
    res_assets_path = data_dir / "resources.assets" if (data_dir / "resources.assets").exists() else None
    shared_files = sorted(data_dir.glob("sharedassets*.assets"))
    streaming_dir = data_dir / "StreamingAssets" if (data_dir / "StreamingAssets").is_dir() else None

    return UnityGameInfo(
        root=root,
        data_dir=data_dir,
        exe_path=exe_path,
        game_title=game_title,
        runtime=runtime,
        unity_version=unity_version,
        has_resources_assets=bool(res_assets_path),
        resources_assets_path=res_assets_path,
        sharedassets_files=shared_files,
        streaming_assets_dir=streaming_dir,
    )


def _asset_name(obj: Any) -> str:
    """Varlığın adı; içeriğini okumadan (büyük varlıklarda çok daha hızlı)."""
    try:
        return obj.peek_name() or ""
    except Exception:
        return getattr(obj.read(), "m_Name", "") or ""


def scan_unity_assets(info: "UnityGameInfo", log: LogFn = print, env: Any = None) -> None:
    """
    Lokalizasyon varlıklarını ve font uyumunu bulur. resources.assets ayrıştırması büyük oyunlarda saniyeler sürer;
    bu yüzden algılamada değil analizde, çağıranın zaten yüklediği ortam üzerinden yapılır.
    """
    info.scanned = True
    missing_chars: Set[str] = set()
    tested = 0
    fonts_ok = True

    def check_fonts(environment: Any) -> None:
        nonlocal tested, fonts_ok
        for obj in environment.objects:
            if obj.type.name != "Font":
                continue
            data = obj.read()
            name = getattr(data, "m_Name", "") or "Font"
            if name not in info.embedded_fonts:
                info.embedded_fonts.append(name)
            if any(k in name.lower() for k in ("cjk", "japanese", "chinese")):  # yalnızca Latin fontları test edilir
                continue
            ttf = getattr(data, "m_FontData", None)
            if not ttf:
                continue
            with tempfile.TemporaryDirectory() as folder:   # oyun klasörüne geçici dosya yazılmaz
                temp = Path(folder) / f"font_{tested}.ttf"
                temp.write_bytes(bytes(ttf))
                result = FontChecker.check_turkish_support(temp)
            tested += 1
            if not result.get("fully_supported", True):
                missing_chars.update(result.get("missing_chars", []))
                fonts_ok = False

    if env is None and info.resources_assets_path and info.resources_assets_path.exists():
        env = UnityPy.load(str(info.resources_assets_path))
    if env is not None:
        try:
            for obj in env.objects:
                if obj.type.name == "TextAsset":
                    name = _asset_name(obj)
                    if any(k in name.lower() for k in ("english", "localization", "language", "dialog", "strings", "text")):
                        info.localization_text_assets.append(name)
            check_fonts(env)
        except Exception as exc:
            log(f"Varlık taraması tamamlanamadı: {exc}")
    shared = info.data_dir / "sharedassets0.assets"
    if not tested and shared.exists():   # font resources.assets'te yoksa bir kez daha yükleme gerekir
        try:
            check_fonts(UnityPy.load(str(shared)))
        except Exception as exc:
            log(f"Font taraması tamamlanamadı: {exc}")
    info.font_turkish_support = fonts_ok
    info.missing_font_chars = sorted(missing_chars)


def extract_texts_unity(info: UnityGameInfo, log: LogFn = print) -> List[UnityTextItem]:
    """
    Unity oyununun kaynaklarından çevrilebilir metinleri çıkarır.
    Öncelikle resources.assets ve StreamingAssets içindeki TSV/CSV/JSON dosyalarını tarar.
    """
    items: List[UnityTextItem] = []
    loaded: Dict[str, Any] = {}

    # 1. resources.assets içindeki TextAsset'leri tara
    if info.resources_assets_path and info.resources_assets_path.exists():
        log(f"Varlıklar taranıyor: {info.resources_assets_path.name}")
        try:
            env = UnityPy.load(str(info.resources_assets_path))
            loaded[info.resources_assets_path.name] = env   # tablo taraması yeniden yüklemesin
            if not info.scanned:
                scan_unity_assets(info, log, env)
            for obj in env.objects:
                if obj.type.name == "TextAsset":
                    name = _asset_name(obj)
                    # İngilizce veya ana diyalog dosyalarını belirle (diğerleri hiç okunmaz)
                    if "english" not in name.lower() and name not in info.localization_text_assets:
                        continue
                    data = obj.read()
                    name = getattr(data, "m_Name", name)
                    script = getattr(data, "m_Script", "")
                    if not script:
                        continue

                    lines = script.splitlines()
                    first_line = lines[0] if lines else ""
                    is_tsv = "\t" in first_line

                    for idx, line in enumerate(lines):
                        if idx == 0 and ("id\t" in line.lower() or line.lower().startswith("id")):
                            continue  # Başlık satırını atla

                        if is_tsv:
                            parts = line.split("\t")
                            if len(parts) >= 2:
                                key = parts[0].strip()
                                val = parts[1].strip()
                                if val and re.search(r"[A-Za-z]", val):
                                    items.append(
                                        UnityTextItem(
                                            source_file="resources.assets",
                                            asset_name=name,
                                            line_index=idx,
                                            key_id=key,
                                            original=val,
                                            format_type="tsv",
                                        )
                                    )
                        else:
                            val = line.strip()
                            if len(val) > 2 and re.search(r"[A-Za-z]", val):
                                items.append(
                                    UnityTextItem(
                                        source_file="resources.assets",
                                        asset_name=name,
                                        line_index=idx,
                                        key_id=f"LINE_{idx}",
                                        original=val,
                                        format_type="raw",
                                    )
                                )

        except Exception as e:
            log(f"resources.assets metin çıkarma hatası: {e}")

    # 2. StreamingAssets klasörünü tara (varsa)
    if info.streaming_assets_dir and info.streaming_assets_dir.is_dir():
        log("StreamingAssets klasörü taranıyor...")
        for ext in ("*.tsv", "*.csv", "*.txt", "*.json"):
            for text_file in info.streaming_assets_dir.rglob(ext):
                try:
                    content = text_file.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()
                    for idx, line in enumerate(lines):
                        if "\t" in line:
                            parts = line.split("\t")
                            if len(parts) >= 2 and re.search(r"[A-Za-z]", parts[1]):
                                items.append(
                                    UnityTextItem(
                                        source_file=str(text_file.relative_to(info.root)),
                                        asset_name=text_file.name,
                                        line_index=idx,
                                        key_id=parts[0].strip(),
                                        original=parts[1].strip(),
                                        format_type="tsv_file",
                                    )
                                )
                except Exception as e:
                    log(f"StreamingAssets dosyası okuma hatası {text_file.name}: {e}")

    # 3. Utage senaryo kitapları ve çok dilli tablolar (sharedassets dahil; IL2CPP'de de okunur)
    items.extend(extract_asset_tables(info, log, loaded))
    if info.tmp_glyphs:   # TextMeshPro atlaslarında olmayan Türkçe harfler (TTF taraması bunları göremez)
        absent = [c for c in "ğĞşŞıİçÇöÖüÜ" if ord(c) not in info.tmp_glyphs]
        if absent:
            info.font_turkish_support = False
            info.missing_font_chars = sorted(set(info.missing_font_chars) | set(absent))
            log(f"TextMeshPro fontlarında eksik harfler: {''.join(absent)} (en yakın harfle yazılacak)")

    log(f"Toplam çıkarılan metin girdisi: {len(items)}")
    return items


# ─── Utage kitapları ve çok dilli tablolar ────────────────────────────────────
TABLE_FORMATS = ("utage", "tsv_col", "i2")


def _table_asset_files(info: UnityGameInfo) -> List[Path]:
    files = [info.resources_assets_path] if info.resources_assets_path else []
    files += [p for p in info.sharedassets_files if p.suffix == ".assets"]
    return [p for p in files if p and p.exists()]


def _english_tsv_column(script: str) -> Optional[int]:
    """İlk satırı "Key<TAB>Japanese<TAB>English" gibi bir başlıksa İngilizce sütunun sırası."""
    header = script.lstrip("﻿").split("\n", 1)[0].rstrip("\r").split("\t")
    lowered = [h.strip().casefold() for h in header]
    if len(header) >= 2 and "english" in lowered and lowered.index("english") > 0:
        return lowered.index("english")
    return None


def _tmp_font_name(obj: Any) -> str:
    """TextMeshPro font varlıkları geleneksel olarak "<Font> SDF" adını taşır."""
    try:
        name = obj.peek_name() or ""
    except Exception:
        return ""
    return name if name.endswith(" SDF") or " SDF " in name else ""


def tmp_character_table(raw: bytes) -> Set[int]:
    """TMP_FontAsset ham verisindeki karakter tablosu: her kayıt (unicode, glif no, ölçek=1.0) üçlüsüdür."""
    import struct

    count = len(raw) // 4
    values = struct.unpack_from(f"<{count}I", raw[:count * 4])
    one = 0x3F800000
    table = {values[i] for i in range(count - 2)
             if values[i + 2] == one and 32 <= values[i] < 0x110000 and values[i + 1] < 1_000_000}
    # Gerçek bir karakter tablosunda en azından Latin harflerin çoğu bulunur; yoksa yanlış eşleşmedir
    return table if sum(1 for c in "abcdefghijklmnopqrstuvwxyz" if ord(c) in table) >= 20 else set()


# Fontta olmayan harfler için en yakın karşılık (ayrıştırılamayanlar); diğerleri aksan atılarak bulunur
_GLYPH_FALLBACK = {"ı": "i", "İ": "I", "ß": "ss", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
                   "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE"}


def glyph_fallback(text: str, glyphs: Set[int]) -> str:
    """Oyunun fontunda olmayan harfleri en yakın harfle değiştirir (ğ→g, ş→s, ı→i); diğer her şey aynen kalır."""
    import unicodedata

    if not glyphs:
        return text
    out = []
    for char in text:
        if ord(char) < 128 or ord(char) in glyphs or not char.isalpha():
            out.append(char)
            continue
        alternative = _GLYPH_FALLBACK.get(char) or unicodedata.normalize("NFKD", char)[0]
        usable = all(ord(a) < 128 or ord(a) in glyphs for a in alternative)
        out.append(alternative if usable else char)
    return "".join(out)


def _text_asset_script(data: Any) -> str:
    script = getattr(data, "m_Script", "")
    return script if isinstance(script, str) else bytes(script).decode("utf-8", "ignore")


def extract_asset_tables(info: UnityGameInfo, log: LogFn = print, loaded: Optional[Dict[str, Any]] = None) -> List[UnityTextItem]:
    """Utage senaryo kitapları, I2 Localization kaynakları ve İngilizce sütunlu sekmeli tablolar."""
    import unity_i2
    import unity_utage

    items: List[UnityTextItem] = []
    for path in _table_asset_files(info):
        try:
            env = (loaded or {}).get(path.name) or UnityPy.load(str(path))
        except Exception as error:
            log(f"{path.name} okunamadı: {error}")
            continue
        books = rows_found = 0
        for obj in env.objects:
            kind = obj.type.name
            try:
                if kind == "MonoBehaviour" and getattr(obj, "byte_size", 0) >= 256:
                    raw = obj.get_raw_data()
                    font_name = _tmp_font_name(obj)
                    if font_name:
                        glyphs = tmp_character_table(raw)
                        if glyphs:
                            info.tmp_fonts.append(font_name)
                            info.tmp_glyphs |= glyphs
                        continue
                    if unity_i2.looks_like_source("", raw[:256]):
                        try:
                            source = unity_i2.parse_source(raw)
                        except unity_utage.UtageFormatError as error:
                            log(f"I2 dil kaynağı okunamadı ({path.name} #{obj.path_id}): {error}; dokunulmadı")
                            continue
                        column = source.column("English")
                        if column is None and len(source.languages) <= 1:
                            column = 0
                        if column is None:
                            log(f"I2 dil kaynağında İngilizce yok ({', '.join(source.languages)}); atlandı")
                            continue
                        terms = 0
                        for index, cells in enumerate(source.cells):
                            # Resim/ses terimlerinin değeri dosya adıdır; çevrilirse oyun logoyu/resmi bulamaz
                            if not source.is_text(index):
                                continue
                            if len(cells) > column and re.search(r"[^\W\d_]", cells[column].text):
                                terms += 1
                                items.append(UnityTextItem(
                                    source_file=path.name, asset_name=f"i2:{obj.path_id}", line_index=index,
                                    key_id=str(column), original=cells[column].text, format_type="i2"))
                        log(f"I2 Localization: {path.name} — {terms} terim ({source.languages[column] if source.languages else 'tek dil'})")
                        continue
                    if not unity_utage.looks_like_book(raw):
                        continue
                    try:
                        grids = unity_utage.parse_book(raw)
                    except unity_utage.UtageFormatError as error:
                        log(f"Utage kitabı okunamadı ({path.name} #{obj.path_id}): {error}; dokunulmadı")
                        continue
                    for number, grid in enumerate(grids):
                        column = unity_utage.text_column(grid)
                        if column is None:
                            continue
                        books += 1
                        for row in grid.rows:
                            if len(row) > column and row[column].text.strip():
                                rows_found += 1
                                items.append(UnityTextItem(
                                    source_file=path.name, asset_name=f"utage:{obj.path_id}",
                                    line_index=row[column].row, key_id=f"{number}:{column}",
                                    original=row[column].text, format_type="utage"))
                elif kind == "TextAsset":
                    data = obj.read()
                    script = _text_asset_script(data)
                    column = _english_tsv_column(script)
                    if column is None:
                        continue
                    name = getattr(data, "m_Name", "")
                    for index, line in enumerate(script.lstrip("﻿").split("\n")[1:], start=1):
                        parts = line.rstrip("\r").split("\t")
                        if len(parts) > column and re.search(r"[A-Za-z]", parts[column]):
                            items.append(UnityTextItem(
                                source_file=path.name, asset_name=name, line_index=index,
                                key_id=str(column), original=parts[column], format_type="tsv_col"))
            except Exception as error:
                log(f"{path.name} #{obj.path_id} atlandı: {error}")
        if books:
            log(f"Utage senaryosu: {path.name} — {books} tablo, {rows_found} satır")
    tables = sum(1 for i in items if i.format_type == "tsv_col")
    if tables:
        log(f"Çok dilli tablolardan {tables} arayüz metni")
    return items


def _replace_file(path: Path, data: bytes) -> None:
    """Önce geçici dosyaya yazıp yerine taşır. UnityPy'nin döngüsel referansları dosyayı çöp toplanana kadar
    açık tutabildiğinden önce çöp toplanır; Windows yine izin vermezse dosyanın üzerine doğrudan yazılır."""
    import gc

    temporary = path.with_suffix(path.suffix + ".capri-tmp")
    temporary.write_bytes(data)
    gc.collect()
    try:
        temporary.replace(path)
    except PermissionError:
        with open(path, "r+b") as handle:
            handle.write(data)
            handle.truncate()
        temporary.unlink(missing_ok=True)


def write_asset_tables(info: UnityGameInfo, translations: Dict[str, str], items: List[UnityTextItem],
                       log: LogFn = print) -> int:
    """Utage kitaplarına, I2 kaynaklarına ve sekmeli tablolara çevirileri yazar; yalnızca değişen hücreler değişir."""
    import unity_i2
    import unity_utage

    by_file: Dict[str, List[UnityTextItem]] = {}
    for item in items:
        if item.format_type in TABLE_FORMATS:
            by_file.setdefault(item.source_file, []).append(item)
    written = 0
    for file_name, file_items in by_file.items():
        path = info.data_dir / file_name
        # Bellekten yüklenir: UnityPy diskteki dosyayı açık tutarsa Windows yerine yazmaya izin vermez
        env = UnityPy.load(path.read_bytes())
        changed_any = False
        books: Dict[int, List[UnityTextItem]] = {}
        tables: Dict[str, List[UnityTextItem]] = {}
        sources: Dict[int, List[UnityTextItem]] = {}
        for item in file_items:
            if item.format_type == "utage":
                books.setdefault(int(item.asset_name.split(":", 1)[1]), []).append(item)
            elif item.format_type == "i2":
                sources.setdefault(int(item.asset_name.split(":", 1)[1]), []).append(item)
            else:
                tables.setdefault(item.asset_name, []).append(item)
        for obj in env.objects:
            if obj.path_id in sources and obj.type.name == "MonoBehaviour":
                raw = obj.get_raw_data()
                source = unity_i2.parse_source(raw)
                cells = {c.start: c for row in source.cells for c in row}
                replacements = {}
                for item in sources[obj.path_id]:
                    column = int(item.key_id)
                    row = source.cells[item.line_index] if item.line_index < len(source.cells) else []
                    if row and not source.is_text(item.line_index):
                        continue
                    new = translations.get(item.original)
                    if len(row) <= column or row[column].text != item.original or not new or new == item.original:
                        continue
                    replacements[row[column].start] = new
                if replacements:
                    obj.set_raw_data(unity_utage.rewrite(raw, replacements, cells))
                    changed_any = True
                    written += len(replacements)
                    log(f"I2 Localization güncellendi: {len(replacements)} terim")
            elif obj.path_id in books and obj.type.name == "MonoBehaviour":
                raw = obj.get_raw_data()
                grids = unity_utage.parse_book(raw)
                cells = {}
                lookup = {}
                for number, grid in enumerate(grids):
                    for row in grid.rows:
                        for cell in row:
                            cells[cell.start] = cell
                            lookup[(number, cell.column, cell.row)] = cell
                replacements = {}
                for item in books[obj.path_id]:
                    number, column = (int(x) for x in item.key_id.split(":"))
                    cell = lookup.get((number, column, item.line_index))
                    new = translations.get(item.original)
                    if cell is None or cell.text != item.original or not new or new == item.original:
                        continue
                    replacements[cell.start] = new
                if replacements:
                    obj.set_raw_data(unity_utage.rewrite(raw, replacements, cells))
                    changed_any = True
                    written += len(replacements)
                    log(f"Utage senaryosu güncellendi: {len(replacements)} satır")
            elif obj.type.name == "TextAsset" and tables:
                data = obj.read()
                name = getattr(data, "m_Name", "")
                if name not in tables:
                    continue
                script = _text_asset_script(data)
                bom = "﻿" if script.startswith("﻿") else ""
                lines = script[len(bom):].split("\n")
                changed = 0
                for item in tables[name]:
                    column = int(item.key_id)
                    if item.line_index >= len(lines):
                        continue
                    body = lines[item.line_index]
                    ending = "\r" if body.endswith("\r") else ""
                    parts = body[:len(body) - len(ending)].split("\t")
                    new = translations.get(item.original)
                    if len(parts) <= column or parts[column] != item.original or not new or new == item.original:
                        continue
                    parts[column] = new.replace("\t", " ").replace("\n", " ")
                    lines[item.line_index] = "\t".join(parts) + ending
                    changed += 1
                if changed:
                    data.m_Script = bom + "\n".join(lines)
                    data.save()
                    changed_any = True
                    written += changed
                    log(f"Güncellendi: {name} ({changed} satır)")
        if changed_any:
            data_bytes = env.file.save()
            _replace_file(path, data_bytes)
            log(f"Kaydedildi: {file_name}")
    return written


def translate_texts_unity(
    unique_sources: List[str],
    cache_path: Path,
    target_lang: str = "tr",
    source_lang: str = "en",
    glossary: Optional[Glossary] = None,
    log: LogFn = print,
    progress: ProgressFn | None = None,
    tracker: Optional[ProgressTracker] = None,
    model_kind: str = "gemini",
    model_dir: Optional[Path] = None,
    ollama_model: str = "qwen2.5:7b",
    ollama_host: str = "http://localhost:11434",
    failed_out: Optional[set] = None,
    extra_instruction: str = "",
) -> Dict[str, str]:
    """
    Unity metinlerini seçilen model (Gemini Flash, Ollama, NLLB) ile çevirir.
    Önbellek ve sözlük desteği tam entegredir.
    """
    # 1. Önbelleği yükle
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # Sözlük ve gömülü Unity terimleri ile güncelle
    cache.update(UNITY_BUILTIN_GLOSSARY)
    if glossary and hasattr(glossary, "entries"):
        cache.update(glossary.entries)

    # Metin filtreleme: harf içermeyenler veya tek harflileri olduğu gibi bırak
    for s in unique_sources:
        if not re.search(r"[A-Za-z]", s):
            cache[s] = s

    missing = [s for s in unique_sources if s not in cache]
    log(f"Toplam benzersiz: {len(unique_sources)} | Önbellekte: {len(unique_sources) - len(missing)} | Çevrilecek: {len(missing)}")

    if not missing:
        log("Tüm metinler önbellekte mevcut, yeni çeviri gerekmiyor.")
        return cache

    selected_model = model_kind.casefold()

    # 2. Gemini ile çeviri
    if selected_model == "gemini":
        from engine_renpy import translate_with_gemini, load_gemini_api_key
        api_key = load_gemini_api_key()
        if not api_key:
            raise RuntimeError("Gemini API Anahtarı bulunamadı! Lütfen gemini_api_key.txt dosyasına geçerli bir anahtar kaydedin.")

        translate_with_gemini(
            missing=missing,
            cache=cache,
            cache_path=cache_path,
            api_key=api_key,
            log=log,
            progress=progress,
            target_lang=target_lang,
            source_lang=source_lang,
            game_engine="Unity Game",
            failed_out=failed_out,
            extra_instruction=extra_instruction,
        )

    elif selected_model in ("openai", "anthropic", "deepl"):
        from providers import translate_with_cloud
        translate_with_cloud(
            selected_model, missing, cache, cache_path, log=log, progress=progress,
            target_lang=target_lang, source_lang=source_lang,
            game_engine="Unity Game", failed_out=failed_out, extra_instruction=extra_instruction,
        )

    # 3. Ollama veya offline modeller
    elif selected_model == "ollama":
        from engine_common import OllamaTranslationEngine
        trans_cache = TranslationCache(cache_path, cache)
        engine = OllamaTranslationEngine(
            model_name=ollama_model,
            cache=trans_cache,
            glossary=glossary,
            protected_pattern=PROTECTED_UNITY,
            log=log,
            host=ollama_host,
            target_lang=target_lang,
            source_lang=source_lang,
        )
        cache.update(engine.translate_batch(missing, progress=progress, tracker=tracker))

    else:
        # Offline model (NLLB / OPUS)
        from engine_common import TranslationEngine
        trans_cache = TranslationCache(cache_path, cache)
        engine = TranslationEngine(
            model_dir=model_dir or __import__("paths").APP_DIR / "model",
            model_kind=selected_model,
            cache=trans_cache,
            glossary=glossary,
            protected_pattern=PROTECTED_UNITY,
            log=log,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        cache.update(engine.translate_batch(missing, progress=progress, tracker=tracker))

    return cache


def write_translations_unity(
    info: UnityGameInfo,
    translations: Dict[str, str],
    extracted_items: List[UnityTextItem],
    log: LogFn = print,
) -> int:
    """
    Çevrilen metinleri Unity varlıklarına (resources.assets ve dosyalara) yazar.
    """
    if not translations:
        log("Yazılacak çeviri bulunamadı.")
        return 0

    log("Unity varlıklarına çeviriler işleniyor...")
    modified_count = 0
    if info.tmp_glyphs:   # oyunun TextMeshPro fontunda olmayan harfler kutu olarak görünmesin
        adjusted = {source: glyph_fallback(text, info.tmp_glyphs) for source, text in translations.items()}
        replaced = sorted({c for source, text in translations.items() for c in text
                           if c not in adjusted[source] and c.isalpha()})
        if replaced:
            log(f"Oyunun fontunda olmayan harfler en yakın harfle yazıldı: {''.join(replaced)}")
        translations = adjusted

    # 1. resources.assets içindeki TextAsset'leri güncelle (yalnızca bu tür metin varsa açılır)
    legacy = any(i.source_file == "resources.assets" and i.format_type in ("tsv", "raw") for i in extracted_items)
    if legacy and info.resources_assets_path and info.resources_assets_path.exists():
        try:
            env = UnityPy.load(info.resources_assets_path.read_bytes())   # dosya açık kalmasın
            assets_modified = False

            by_asset: Dict[str, List[UnityTextItem]] = {}
            for item in extracted_items:
                if item.source_file == "resources.assets" and item.format_type in ("tsv", "raw"):
                    by_asset.setdefault(item.asset_name, []).append(item)

            for obj in env.objects:
                if obj.type.name == "TextAsset":
                    data = obj.read()
                    name = getattr(data, "m_Name", "")
                    if name in by_asset:
                        original_script = getattr(data, "m_Script", "")
                        lines = original_script.splitlines()
                        item_map = {item.line_index: item for item in by_asset[name]}

                        new_lines = []
                        changed_in_file = 0
                        for idx, line in enumerate(lines):
                            if idx in item_map:
                                item = item_map[idx]
                                orig = item.original
                                if orig in translations and translations[orig] != orig:
                                    translated = translations[orig]
                                    if item.format_type == "tsv":
                                        parts = line.split("\t")
                                        if len(parts) >= 2:
                                            parts[1] = translated
                                            new_lines.append("\t".join(parts))
                                            changed_in_file += 1
                                            modified_count += 1
                                            continue
                                    elif item.format_type == "raw":
                                        new_lines.append(translated)
                                        changed_in_file += 1
                                        modified_count += 1
                                        continue
                            new_lines.append(line)

                        if changed_in_file > 0:
                            data.m_Script = "\r\n".join(new_lines)
                            data.save()
                            assets_modified = True
                            log(f"Güncellendi: {name} ({changed_in_file} satır)")

            if assets_modified:
                log(f"{info.resources_assets_path.name} kaydediliyor...")
                new_asset_bytes = env.file.save()
                with open(info.resources_assets_path, "wb") as f:
                    f.write(new_asset_bytes)
                log(f"Başarıyla kaydedildi: {info.resources_assets_path.name} (Boyut: {len(new_asset_bytes):,} bayt)")

        except Exception as e:
            log(f"resources.assets yazma hatası: {e}")
            raise e

    # 2. StreamingAssets metin dosyaları (sekmeyle ayrılmış: anahtar <tab> metin)
    by_file: Dict[str, List[UnityTextItem]] = {}
    for item in extracted_items:
        if item.format_type == "tsv_file":
            by_file.setdefault(item.source_file, []).append(item)
    for relative, items in by_file.items():
        path = info.root / relative
        try:
            content = path.read_bytes().decode("utf-8")   # kayıpsız okunamayan dosyaya dokunulmaz
        except (OSError, UnicodeDecodeError) as e:
            log(f"Atlandı: {path.name} ({e})")
            continue
        lines = content.splitlines(keepends=True)
        changed = 0
        for item in items:
            translated = translations.get(item.original)
            if not translated or translated == item.original or item.line_index >= len(lines):
                continue
            raw = lines[item.line_index]
            body = raw.rstrip("\r\n")
            ending = raw[len(body):]
            parts = body.split("\t")
            if len(parts) < 2 or parts[1].strip() != item.original:
                continue
            parts[1] = parts[1].replace(item.original, translated)
            lines[item.line_index] = "\t".join(parts) + ending
            changed += 1
        if changed:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes("".join(lines).encode("utf-8"))
            temporary.replace(path)
            modified_count += changed
            log(f"Güncellendi: {path.name} ({changed} satır)")

    # 3. Utage senaryo kitapları ve çok dilli tablolar
    modified_count += write_asset_tables(info, translations, extracted_items, log)
    return modified_count

