"""
Unreal Engine (UE4 / UE5) Çeviri Motoru
=======================================
Unreal Engine oyunlarında yer alan .locres (Localization Resource),
.locmeta ve paketlenmiş lokalizasyon varlıklarının okunması,
çevrilmesi ve yeniden oluşturulması modülü.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from pylocres import LocresFile, Namespace, Entry, LocresVersion

from engine_common import (
    BackupManager,
    Glossary,
    LogFn,
    ProgressFn,
    ProgressTracker,
    QAChecker,
    TranslationCache,
    cache_file_for,
    load_glossary,
)

# Unreal Engine metinlerindeki etiketler ve format belirteçleri
PROTECTED_UNREAL = re.compile(
    r"("
    r"\{[0-9A-Za-z_]+\}"           # {0}, {1}, {PlayerName}, {Time}
    r"|<[A-Za-z0-9_.\-]+(?: [^>]+)?>.*?</[A-Za-z0-9_.\-]+>"  # <RichText.Bold>...</>
    r"|<[A-Za-z0-9_.\-]+(?: [^>]+)?>|</[A-Za-z0-9_.\-]+>|<[^>]+/>"
    r"|%[0-9]*[sdf]"               # %s, %d
    r"|\\n|\\r|\\t"                # Escape karakterleri
    r"|`[^`]+`"                    # Inline kod/değişkenler
    r")",
    re.IGNORECASE,
)

UNREAL_BUILTIN_GLOSSARY = {
    "New Game": "Yeni Oyun",
    "Continue": "Devam Et",
    "Load Game": "Oyunu Yükle",
    "Save Game": "Oyunu Kaydet",
    "Settings": "Ayarlar",
    "Options": "Seçenekler",
    "Audio": "Ses",
    "Video": "Görüntü",
    "Graphics": "Grafikler",
    "Display": "Ekran",
    "Controls": "Kontroller",
    "Gameplay": "Oynanış",
    "Accessibility": "Erişilebilirlik",
    "Language": "Dil",
    "Subtitles": "Altyazılar",
    "Master Volume": "Ana Ses",
    "Music Volume": "Müzik Sesi",
    "SFX Volume": "Efekt Sesi",
    "Voice Volume": "Seslendirme",
    "Fullscreen": "Tam Ekran",
    "Windowed": "Pencereli",
    "Borderless": "Çerçevesiz Pencereli",
    "Resolution": "Çözünürlük",
    "V-Sync": "Dikey Eşitleme (V-Sync)",
    "Frame Rate Limit": "Kare Hızı Sınırı",
    "Motion Blur": "Hareket Bulanıklığı",
    "Quality": "Kalite",
    "Low": "Düşük",
    "Medium": "Orta",
    "High": "Yüksek",
    "Epic": "Epik",
    "Cinematic": "Sinematik",
    "Ultra": "Ultra",
    "Apply": "Uygula",
    "Cancel": "İptal",
    "Confirm": "Onayla",
    "Back": "Geri",
    "Next": "İleri",
    "Quit": "Çıkış",
    "Exit Game": "Oyundan Çık",
    "Exit to Main Menu": "Ana Menüye Çık",
    "Exit to Desktop": "Masaüstüne Çık",
    "Restart": "Yeniden Başlat",
    "Resume": "Devam Et",
    "Pause": "Duraklat",
    "Yes": "Evet",
    "No": "Hayır",
    "Accept": "Kabul Et",
    "Decline": "Reddet",
}


@dataclass
class UnrealTextItem:
    """Unreal Engine lokalizasyonundan çıkarılan tek bir metin."""
    locres_path: Path
    namespace: str
    key: str
    original: str
    source_hash: int = 0


@dataclass
class UnrealGameInfo:
    """Algılanan Unreal Engine oyununun yapısal bilgileri."""
    root: Path
    game_project_name: str
    engine_version: str            # 'UE4' veya 'UE5'
    exe_path: Optional[Path]
    content_dir: Path
    paks_dir: Optional[Path]
    localization_dirs: List[Path] = field(default_factory=list)
    locres_files: List[Path] = field(default_factory=list)
    has_iostore: bool = False      # .utoc/.ucas kullanımı
    pak_files: List[Path] = field(default_factory=list)
    target_lang_code: str = "tr"


def detect_unreal_game(selected: Union[str, Path]) -> Optional[UnrealGameInfo]:
    """
    Seçilen dizinin Unreal Engine (UE4 / UE5) oyunu olup olmadığını tespit eder.
    """
    path = Path(selected).expanduser().resolve()
    if not path.exists():
        return None
    if path.is_file():
        path = path.parent

    # 1. Oyun kökünü veya proje klasörünü belirle
    # Tipik UE dizin yapısı:
    # Root/
    #   Engine/
    #   ProjectName/
    #     Binaries/Win64/ProjectName-Win64-Shipping.exe
    #     Content/
    #       Paks/
    #       Localization/
    project_dir = None
    engine_dir = None
    root = path

    # Eğer doğrudan Content veya Proje klasörü seçildiyse yukarı çık
    if (path / "Engine").is_dir() or any((p / "Binaries").is_dir() for p in path.iterdir() if p.is_dir()):
        root = path
    elif path.parent and ((path.parent / "Engine").is_dir() or (path.parent / "Content").is_dir()):
        root = path.parent
        if (root.parent / "Engine").is_dir():
            root = root.parent

    # Engine ve Proje klasörlerini bul
    for item in root.iterdir():
        if item.is_dir():
            if item.name.lower() == "engine":
                engine_dir = item
            elif (item / "Content").is_dir() or (item / "Binaries").is_dir():
                project_dir = item

    if not project_dir:
        # Alternatif: Kök klasörün kendisi Content barındırıyor olabilir
        if (root / "Content").is_dir():
            project_dir = root

    if not project_dir:
        return None

    content_dir = project_dir / "Content"
    project_name = project_dir.name

    # 2. Çalıştırılabilir dosyayı (.exe) bul
    exe_path = None
    binaries_dir = project_dir / "Binaries" / "Win64"
    if binaries_dir.is_dir():
        for f in binaries_dir.glob("*.exe"):
            if not f.name.lower().endswith(("_be.exe", "_eac.exe", "crashreportclient.exe")):
                exe_path = f
                if "shipping" in f.name.lower():
                    break
    if not exe_path:
        for f in root.glob("*.exe"):
            if not f.name.lower().endswith(("_be.exe", "_eac.exe", "crashreportclient.exe")):
                exe_path = f
                break

    # 3. Motor Sürümü (UE4 vs UE5)
    engine_version = "UE4"
    paks_dir = content_dir / "Paks" if (content_dir / "Paks").is_dir() else None
    has_iostore = False
    pak_files = []

    if paks_dir and paks_dir.exists():
        pak_files = list(paks_dir.glob("*.pak"))
        has_iostore = bool(list(paks_dir.glob("*.utoc")) or list(paks_dir.glob("*.ucas")))
        if has_iostore or any("ue5" in str(p).lower() for p in root.rglob("*.ini")):
            engine_version = "UE5"

    # 4. Localization ve .locres dosyalarını tara
    loc_dirs = []
    locres_files = []

    # Standart yerler: Content/Localization, Engine/Content/Localization
    for search_base in [content_dir, root / "Engine" / "Content" if (root / "Engine" / "Content").exists() else None]:
        if search_base and search_base.exists():
            for l_dir in search_base.glob("**/Localization*"):
                if l_dir.is_dir():
                    loc_dirs.append(l_dir)
            for lf in search_base.glob("**/*.locres"):
                locres_files.append(lf)

    return UnrealGameInfo(
        root=root,
        game_project_name=project_name,
        engine_version=engine_version,
        exe_path=exe_path,
        content_dir=content_dir,
        paks_dir=paks_dir,
        localization_dirs=loc_dirs,
        locres_files=sorted(locres_files),
        has_iostore=has_iostore,
        pak_files=sorted(pak_files),
    )


def extract_texts_unreal(
    info: UnrealGameInfo,
    source_lang_code: str = "en",
    log: LogFn = print,
) -> List[UnrealTextItem]:
    """
    Unreal Engine oyunundaki .locres dosyalarından çevrilebilir metinleri çıkarır.
    """
    items: List[UnrealTextItem] = []

    if not info.locres_files:
        log("Doğrudan klasörde açık .locres dosyası bulunamadı (Metinler .pak/IoStore içinde olabilir).")
        return items

    log(f"Unreal Engine lokalizasyon dosyaları taranıyor ({len(info.locres_files)} adet)...")

    for locres_path in info.locres_files:
        # İlgili dil klasöründe mi kontrol et
        parent_name = locres_path.parent.name.lower()
        if source_lang_code.lower() not in parent_name and parent_name not in ("game", "localization", "words"):
            # Başka bir dilin locres dosyası ise (örn: fr, de, es) kaynak değilse atla
            continue

        try:
            locres = LocresFile()
            locres.read(str(locres_path))

            for ns in locres:
                ns_name = ns.name or ""
                for entry in ns:
                    text_val = entry.translation or ""
                    # Anlamlı metin kontrolü
                    if text_val and re.search(r"[A-Za-z]", text_val):
                        items.append(
                            UnrealTextItem(
                                locres_path=locres_path,
                                namespace=ns_name,
                                key=entry.key or "",
                                original=text_val,
                                source_hash=getattr(entry, "hash", 0),
                            )
                        )
            log(f"Ayrıştırıldı: {locres_path.name} -> {len(items)} satır metin")
        except Exception as e:
            log(f"HATA: {locres_path.name} okunamadı: {e}")

    log(f"Toplam çıkarılan Unreal Engine metin girdisi: {len(items)}")
    return items


def backup_unreal_assets(info: UnrealGameInfo, log: LogFn = print) -> Optional[Path]:
    """Değiştirilecek Unreal Engine dosyalarının yedeğini alır."""
    backup_root = info.root / "_turkish_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"unreal_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backed_up = 0
    for locres in info.locres_files:
        rel = locres.relative_to(info.root)
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(locres, dest)
        backed_up += 1

    log(f"Unreal Engine yedekleme oluşturuldu: {backup_dir.name} ({backed_up} dosya)")
    return backup_dir


def restore_unreal_backup(info: UnrealGameInfo, log: LogFn = print) -> bool:
    """En son alınan Unreal Engine yedeğini geri yükler."""
    backup_root = info.root / "_turkish_backups"
    if not backup_root.exists():
        log("Geri yüklenecek yedek klasörü bulunamadı.")
        return False

    backups = sorted(
        [d for d in backup_root.iterdir() if d.is_dir() and d.name.startswith("unreal_backup_")],
        key=lambda d: d.name,
        reverse=True,
    )
    if not backups:
        log("Geri yüklenecek geçerli bir Unreal Engine yedeği bulunamadı.")
        return False

    latest = backups[0]
    log(f"Yedek geri yükleniyor: {latest.name}")
    restored = 0
    for f in latest.rglob("*"):
        if f.is_file():
            rel = f.relative_to(latest)
            target = info.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            restored += 1

    log(f"Geri yükleme tamamlandı. Toplam {restored} dosya eski haline getirildi.")
    return True


def translate_texts_unreal(
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
    Unreal Engine metinlerini istenen hedef dile çevirir.
    """
    cache: Dict[str, str] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    if target_lang.lower() in ("tr", "turkish", "türkçe"):
        cache.update(UNREAL_BUILTIN_GLOSSARY)

    if glossary and hasattr(glossary, "entries"):
        cache.update(glossary.entries)

    for s in unique_sources:
        if not re.search(r"[A-Za-z]", s):
            cache[s] = s

    missing = [s for s in unique_sources if s not in cache]
    log(f"Toplam benzersiz: {len(unique_sources)} | Önbellekte: {len(unique_sources) - len(missing)} | Çevrilecek: {len(missing)}")

    if not missing:
        log("Tüm metinler önbellekte mevcut, yeni çeviri gerekmiyor.")
        return cache

    selected_model = model_kind.casefold()

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
            game_engine="Unreal Engine Game",
            failed_out=failed_out,
            extra_instruction=extra_instruction,
        )

    elif selected_model in ("openai", "anthropic", "deepl"):
        from providers import translate_with_cloud
        translate_with_cloud(
            selected_model, missing, cache, cache_path, log=log, progress=progress,
            target_lang=target_lang, source_lang=source_lang,
            game_engine="Unreal Engine Game", failed_out=failed_out, extra_instruction=extra_instruction,
        )
    elif selected_model == "ollama":
        from engine_common import OllamaTranslationEngine
        trans_cache = TranslationCache(cache_path, cache)
        engine = OllamaTranslationEngine(
            model_name=ollama_model,
            cache=trans_cache,
            glossary=glossary,
            protected_pattern=PROTECTED_UNREAL,
            log=log,
            host=ollama_host,
        )
        cache.update(engine.translate_batch(missing, progress=progress, tracker=tracker))
    else:
        from engine_common import TranslationEngine
        trans_cache = TranslationCache(cache_path, cache)
        engine = TranslationEngine(
            model_dir=model_dir or __import__("paths").APP_DIR / "model",
            model_kind=selected_model,
            cache=trans_cache,
            glossary=glossary,
            protected_pattern=PROTECTED_UNREAL,
            log=log,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        cache.update(engine.translate_batch(missing, progress=progress, tracker=tracker))

    return cache


def write_translations_unreal(
    info: UnrealGameInfo,
    translations: Dict[str, str],
    extracted_items: List[UnrealTextItem],
    target_lang_code: str = "tr",
    create_lang_folder: bool = True,
    log: LogFn = print,
) -> int:
    """
    Çevrilen metinleri Unreal Engine .locres dosyalarına yazar.
    İsteğe bağlı olarak hedef dil klasörü (örn: 'tr') oluşturup oraya yazar.
    """
    if not translations or not extracted_items:
        log("Yazılacak Unreal Engine çevirisi bulunamadı.")
        return 0

    log(f"Unreal Engine .locres dosyaları yazılıyor (Hedef Dil: {target_lang_code})...")
    modified_count = 0

    # Dosya bazında grupla
    by_file: Dict[Path, List[UnrealTextItem]] = {}
    for item in extracted_items:
        by_file.setdefault(item.locres_path, []).append(item)

    for locres_path, items in by_file.items():
        try:
            locres = LocresFile()
            locres.read(str(locres_path))

            # Hızlı erişim tablosu: (namespace, key) -> translation
            lookup = {}
            for it in items:
                orig = it.original
                if orig in translations and translations[orig] != orig:
                    lookup[(it.namespace, it.key)] = translations[orig]

            changed_in_file = 0
            for ns in locres:
                ns_name = ns.name or ""
                for entry in ns:
                    pair = (ns_name, entry.key)
                    if pair in lookup:
                        entry.translation = lookup[pair]
                        changed_in_file += 1
                        modified_count += 1

            if changed_in_file > 0:
                # Hedef dosya yolu
                out_path = locres_path
                if create_lang_folder:
                    # e.g. Content/Localization/Game/en/Game.locres -> Content/Localization/Game/tr/Game.locres
                    target_dir = locres_path.parent.parent / target_lang_code
                    target_dir.mkdir(parents=True, exist_ok=True)
                    out_path = target_dir / locres_path.name

                locres.write(str(out_path))
                log(f"Başarıyla kaydedildi: {out_path.name} -> {out_path} ({changed_in_file} satır)")

        except Exception as e:
            log(f"HATA: {locres_path.name} yazılırken hata oluştu: {e}")

    return modified_count


def qa_unreal_translation(
    translations: Dict[str, str],
    log: LogFn = print,
) -> Dict[str, int]:
    """Unreal Engine çevirilerinde etiket ve değişken koruma testi."""
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

        orig_tags = PROTECTED_UNREAL.findall(orig)
        trans_tags = PROTECTED_UNREAL.findall(trans)
        if len(orig_tags) != len(trans_tags):
            qa_results["tag_mismatch"] += 1
        else:
            qa_results["valid"] += 1

    return qa_results


def create_unreal_mod_pak(
    info: UnrealGameInfo,
    mod_files_dir: Path,
    mod_name: str = "TurkishLanguage_P",
    log: LogFn = print,
) -> Optional[Path]:
    """
    Unreal Engine için otomatik '_P.pak' mod paketi oluşturma rehberi / aracı.
    Unreal Engine, 'Paks/' klasöründeki '*_P.pak' (Patch PAK) dosyalarını
    orijinal oyun dosyalarının üzerine otomatik olarak bindirir!
    """
    if not info.paks_dir or not info.paks_dir.exists():
        log("Paks klasörü bulunamadı.")
        return None

    pak_target = info.paks_dir / f"{mod_name}.pak"
    log(f"Unreal Engine Patch PAK hedefi: {pak_target}")
    return pak_target
