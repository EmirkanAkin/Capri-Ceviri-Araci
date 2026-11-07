"""
Unity Oyunları Türkçe Çeviri Motoru
===================================
Unity (Mono ve IL2CPP) oyunları için metin çıkarma, yapay zeka ile çeviri,
font uyumluluk denetimi ve varlık (asset) yamalama modülü.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import UnityPy

from engine_common import (
    BUILTIN_GLOSSARY,
    BackupManager,
    FontChecker,
    Glossary,
    LogFn,
    ProgressFn,
    ProgressTracker,
    QAChecker,
    TranslationCache,
    cache_file_for,
    load_glossary,
    mask_text,
    unmask_text,
    protected_content_valid,
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

    # 1. resources.assets içindeki TextAsset'leri tara
    if info.resources_assets_path and info.resources_assets_path.exists():
        log(f"Varlıklar taranıyor: {info.resources_assets_path.name}")
        try:
            env = UnityPy.load(str(info.resources_assets_path))
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

    log(f"Toplam çıkarılan metin girdisi: {len(items)}")
    return items


def backup_unity_assets(info: UnityGameInfo, log: LogFn = print) -> Optional[Path]:
    """Değiştirilecek Unity varlıklarının yedeğini alır."""
    backup_root = info.root / "_turkish_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"unity_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backed_up = 0
    if info.resources_assets_path and info.resources_assets_path.exists():
        target = backup_dir / info.resources_assets_path.name
        shutil.copy2(info.resources_assets_path, target)
        backed_up += 1

    log(f"Unity yedekleme oluşturuldu: {backup_dir.name} ({backed_up} dosya)")
    return backup_dir


def restore_unity_backup(info: UnityGameInfo, log: LogFn = print) -> bool:
    """En son alınan Unity yedeğini geri yükler."""
    backup_root = info.root / "_turkish_backups"
    if not backup_root.exists():
        log("Geri yüklenecek yedek klasörü bulunamadı.")
        return False

    backups = sorted(
        [d for d in backup_root.iterdir() if d.is_dir() and d.name.startswith("unity_backup_")],
        key=lambda d: d.name,
        reverse=True,
    )
    if not backups:
        log("Geri yüklenecek geçerli bir Unity yedeği bulunamadı.")
        return False

    latest = backups[0]
    log(f"Yedek geri yükleniyor: {latest.name}")
    restored = 0
    for f in latest.iterdir():
        target = info.data_dir / f.name
        shutil.copy2(f, target)
        restored += 1
        log(f"Geri yüklendi: {f.name}")

    log(f"Geri yükleme tamamlandı. Toplam {restored} dosya eski haline getirildi.")
    return True


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

    # 1. resources.assets içindeki TextAsset'leri güncelle
    if info.resources_assets_path and info.resources_assets_path.exists():
        try:
            env = UnityPy.load(str(info.resources_assets_path))
            assets_modified = False

            by_asset: Dict[str, List[UnityTextItem]] = {}
            for item in extracted_items:
                if item.source_file == "resources.assets":
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

    return modified_count


def qa_unity_translation(
    translations: Dict[str, str],
    log: LogFn = print,
) -> Dict[str, int]:
    """Çeviriler üzerinde etiket ve kalite kontrolü (QA) yapar."""
    qa_results = {
        "checked": 0,
        "empty": 0,
        "tag_mismatch": 0,
        "valid": 0,
    }

    for orig, trans in translations.items():
        qa_results["checked"] += 1
        if not trans or not trans.strip():
            qa_results["empty"] += 1
            continue

        orig_tags = PROTECTED_UNITY.findall(orig)
        trans_tags = PROTECTED_UNITY.findall(trans)
        if len(orig_tags) != len(trans_tags):
            qa_results["tag_mismatch"] += 1
        else:
            qa_results["valid"] += 1

    return qa_results
