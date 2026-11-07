from __future__ import annotations

import ast
import collections
import difflib
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]

QUOTED_ANY = re.compile(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')')
PROTECTED = re.compile(
    r"(\{[^{}\r\n]*\}|\[[\w\.\!]+\[[\w\.\!]+\][^\[\]\r\n]*\]|\[[^\[\]\r\n]+\]|"
    r"%\([^)]+\)[#0 +\-]?\d*(?:\.\d+)?[a-zA-Z]|%%|%[sdif]|"
    r"https?://[^\s]+|\\[nrt]|\r\n|\r|\n)"
)
MASK = re.compile(r"XPH(\d{3})X")

BUILTIN_GLOSSARY = {
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
    "Select your Language": "Dilini Seç",
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
    "Landlady": "Ev Sahibi",
    "Landlord": "Ev Sahibi",
    "Tenant": "Kiracı",
    "Waiter": "Garson",
    "Dancer": "Dansçı",
    "Phone": "Telefon",
    "⬆": "⬆",
    "⬇": "⬇",
    "←": "←",
    "→": "→",
    "<": "<",
    ">": ">",
}

STAGE_DIRECTIONS = {
    "*Whimpering*": "*İnleyerek*",
    "*Whimpers*": "*İnler*",
    "*Whimper*": "*İnler*",
    "*Groaning*": "*İnleyerek*",
    "*Groans*": "*İnler*",
    "*Groan*": "*İnler*",
    "*Moaning*": "*İnleyerek*",
    "*Moan*": "*İnler*",
    "*Gasp!*": "*Nefesi kesilir!*",
    "*Gasp*": "*Nefesi kesilir*",
    "*Gasps*": "*Nefesi kesilir*",
    "*Sigh*": "*İç çeker*",
    "*Sighs*": "*İç çeker*",
    "*sigh*": "*İç çeker*",
    "*sighs*": "*İç çeker*",
    "*Yawn*": "*Esner*",
    "*Yawns*": "*Esner*",
    "*yawn*": "*Esner*",
    "*yawns*": "*Esner*",
    "*Chuckle*": "*Kıkırdar*",
    "*Chuckles*": "*Kıkırdar*",
    "*chuckle*": "*Kıkırdar*",
    "*chuckles*": "*Kıkırdar*",
    "*Giggle*": "*Kıkırdar*",
    "*Giggles*": "*Kıkırdar*",
    "*giggle*": "*Kıkırdar*",
    "*giggles*": "*Kıkırdar*",
    "*Laughs*": "*Güler*",
    "*Laugh*": "*Güler*",
    "*laughs*": "*Güler*",
    "*laugh*": "*Güler*",
    "*Smiles*": "*Gülümser*",
    "*Smile*": "*Gülümser*",
    "*smiles*": "*Gülümser*",
    "*smile*": "*Gülümser*",
    "*Grins*": "*Sırıtır*",
    "*Grin*": "*Sırıtır*",
    "*grins*": "*Sırıtır*",
    "*grin*": "*Sırıtır*",
    "*Winks*": "*Göz kırpar*",
    "*Wink*": "*Göz kırpar*",
    "*winks*": "*Göz kırpar*",
    "*wink*": "*Göz kırpar*",
    "*Nods*": "*Başını sallar*",
    "*Nod*": "*Başını sallar*",
    "*nods*": "*Başını sallar*",
    "*nod*": "*Başını sallar*",
    "*Panting*": "*Soluk soluğa*",
    "*panting*": "*Soluk soluğa*",
    "*Gulp*": "*Yutkunur*",
    "*Gulps*": "*Yutkunur*",
    "*gulp*": "*Yutkunur*",
    "*gulps*": "*Yutkunur*",
    "*Sniff*": "*Burnunu çeker*",
    "*Sniffs*": "*Burnunu çeker*",
    "*sniff*": "*Burnunu çeker*",
    "*sniffs*": "*Burnunu çeker*",
    "*Shiver*": "*Ürperir*",
    "*Shivers*": "*Ürperir*",
    "*shiver*": "*Ürperir*",
    "*shivers*": "*Ürperir*",
    "*Cry*": "*Ağlar*",
    "*Cries*": "*Ağlar*",
    "*cry*": "*Ağlar*",
    "*cries*": "*Ağlar*",
    "*Sobbing*": "*Hıçkırarak*",
    "*sobbing*": "*Hıçkırarak*",
    "*Sobs*": "*Hıçkırır*",
    "*sobs*": "*Hıçkırır*",
    "*Huff*": "*Nefesini verir*",
    "*huff*": "*Nefesini verir*",
}

UI_VISIBLE_CONTEXT = re.compile(
    r"(^|\s)(?:text|textbutton|label|tooltip|caption|title|message)\s+"
    r"|renpy\.notify\s*\(|notify\s*\(|_\s*\(",
    re.IGNORECASE,
)
UI_DATA_KEY = re.compile(
    r"""(?ix)
    ["'](?:title|name|text|label|description|desc|tooltip|message|notification|
          notify|task|quest|objective|hint|caption|content|summary)["']\s*:
    """
)
UI_TECHNICAL_WORDS = {
    "idle",
    "hover",
    "selected_idle",
    "selected_hover",
    "insensitive",
    "action",
    "xalign",
    "yalign",
    "xpos",
    "ypos",
    "xsize",
    "ysize",
    "style",
    "default",
    "true",
    "false",
    "none",
    "null",
}


class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"RPA dizininde sınıfa izin verilmiyor: {module}.{name}")


@dataclass
class ArchiveInfo:
    path: Path
    version: str
    entries: dict
    rpy_count: int
    rpyc_count: int


@dataclass
class GameInfo:
    root: Path
    game_dir: Path
    executable: Path
    loose_rpy: int
    loose_rpyc: int
    archives: list[ArchiveInfo]
    packed_rpy: int
    packed_rpyc: int
    existing_tl_files: int
    language: str = "Turkish"      # Ren'Py dil klasörü: game/tl/<language>

    @property
    def tl_dir(self) -> Path:
        return self.game_dir / "tl" / self.language

    @property
    def support_file(self) -> Path:
        name = "zz_turkish_autoload.rpy" if self.language == "Turkish" else f"zz_capri_{self.language.lower()}_autoload.rpy"
        return self.game_dir / name


def _is_support_script(name: str) -> bool:
    return name.lower().startswith(("zz_turkish_autoload.", "turkish_support.", "zz_capri_"))


def normalize_game_root(selected: str | Path) -> tuple[Path, Path]:
    path = Path(selected).expanduser().resolve()
    if path.is_file():
        path = path.parent
    # Some distributions name the actual game root "game" as well. Prefer a
    # child game directory when the selected folder also contains the launcher.
    if (path / "game").is_dir() and any(path.glob("*.exe")):
        root, game_dir = path, path / "game"
    elif path.name.lower() == "game" and path.is_dir():
        root, game_dir = path.parent, path
    elif (path / "game").is_dir():
        root, game_dir = path, path / "game"
    else:
        raise ValueError("Seçilen klasörde 'game' klasörü bulunamadı.")
    return root, game_dir


def find_executable(root: Path) -> Path:
    excluded = ("unins", "renpurge", "crash", "python", "updater")
    candidates = [
        path
        for path in root.glob("*.exe")
        if not path.name.lower().startswith(excluded)
    ]
    if not candidates:
        raise ValueError("Oyun ana klasöründe Ren'Py çalıştırılabilir dosyası bulunamadı.")
    with_py = [path for path in candidates if path.with_suffix(".py").exists()]
    return sorted(with_py or candidates, key=lambda p: (len(p.name), p.name.lower()))[0]


def read_rpa_index(path: Path) -> tuple[str, dict]:
    with path.open("rb") as handle:
        header = handle.readline()
        if header.startswith(b"RPA-3.0 "):
            parts = header.decode("ascii").split()
            offset, key = int(parts[1], 16), int(parts[2], 16)
            handle.seek(offset)
            raw = zlib.decompress(handle.read())
            index = RestrictedUnpickler(io.BytesIO(raw)).load()
            decoded = {}
            for name, chunks in index.items():
                fixed = []
                for chunk in chunks:
                    if len(chunk) == 2:
                        start, length = chunk
                        prefix = b""
                    else:
                        start, length, prefix = chunk
                        if isinstance(prefix, str):
                            prefix = prefix.encode("latin-1")
                    fixed.append((start ^ key, length ^ key, prefix or b""))
                decoded[str(name)] = fixed
            return "3.0", decoded
        if header.startswith(b"RPA-2.0 "):
            offset = int(header[8:].strip(), 16)
            handle.seek(offset)
            raw = zlib.decompress(handle.read())
            index = RestrictedUnpickler(io.BytesIO(raw)).load()
            decoded = {}
            for name, chunks in index.items():
                fixed = []
                for chunk in chunks:
                    if len(chunk) == 2:
                        start, length = chunk
                        prefix = b""
                    else:
                        start, length, prefix = chunk
                    fixed.append((start, length, prefix or b""))
                decoded[str(name)] = fixed
            return "2.0", decoded
    raise ValueError(f"Desteklenmeyen RPA biçimi: {path.name}")


def inspect_archive(path: Path) -> ArchiveInfo | None:
    try:
        version, entries = read_rpa_index(path)
    except (OSError, ValueError, zlib.error, pickle.UnpicklingError):
        return None
    names = [name.replace("\\", "/") for name in entries]
    return ArchiveInfo(
        path,
        version,
        entries,
        sum(name.endswith(".rpy") and not name.startswith("tl/") for name in names),
        sum(name.endswith(".rpyc") and not name.startswith("tl/") for name in names),
    )


def analyze_game(selected: str | Path, log: LogFn = print, language: str = "Turkish") -> GameInfo:
    root, game_dir = normalize_game_root(selected)
    executable = find_executable(root)
    archives = []
    for path in sorted(game_dir.glob("*.rpa")):
        info = inspect_archive(path)
        if info:
            archives.append(info)
            if info.rpy_count or info.rpyc_count:
                log(
                    f"Arşiv: {path.name} — {info.rpy_count} RPY, "
                    f"{info.rpyc_count} RPYC"
                )
    loose = [
        p for p in game_dir.rglob("*.rpy")
        if "tl" not in {part.lower() for part in p.relative_to(game_dir).parts}
        and not _is_support_script(p.name)
    ]
    loose_c = [
        p for p in game_dir.rglob("*.rpyc")
        if "tl" not in {part.lower() for part in p.relative_to(game_dir).parts}
        and not _is_support_script(p.name)
    ]
    tl_dir = game_dir / "tl" / language
    info = GameInfo(
        root=root,
        game_dir=game_dir,
        executable=executable,
        loose_rpy=len(loose),
        loose_rpyc=len(loose_c),
        archives=archives,
        packed_rpy=sum(a.rpy_count for a in archives),
        packed_rpyc=sum(a.rpyc_count for a in archives),
        existing_tl_files=len(list(tl_dir.rglob("*.rpy"))) if tl_dir.exists() else 0,
        language=language,
    )
    log(f"Oyun: {root}")
    log(f"Çalıştırıcı: {executable.name}")
    log(
        f"Açık kaynak: {info.loose_rpy} RPY | "
        f"Paketli kaynak: {info.packed_rpy} RPY"
    )
    return info


def safe_archive_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"Güvensiz arşiv yolu: {name}")
    return member


def extract_entry(archive: Path, chunks, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("rb") as handle, target.open("wb") as output:
        for offset, length, prefix in chunks:
            output.write(prefix)
            handle.seek(offset)
            output.write(handle.read(length))


def backup_translation(info: GameInfo, log: LogFn = print) -> Path | None:
    tl_dir = info.tl_dir
    support = info.support_file
    if not tl_dir.exists() and not support.exists():
        return None
    backup_dir = info.root / "_turkish_backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"turkish_backup_{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        if tl_dir.exists():
            for path in tl_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(info.root))
        if support.exists():
            archive.write(support, support.relative_to(info.root))
    log(f"Yedek oluşturuldu: {target}")
    return target


def list_translation_backups(info: GameInfo) -> list[Path]:
    backup_dir = info.root / "_turkish_backups"
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob("turkish_backup_*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def restore_translation_backup(
    info: GameInfo, backup: Path | None = None, log: LogFn = print
) -> Path:
    backups = list_translation_backups(info)
    backup = backup or (backups[0] if backups else None)
    if backup is None:
        raise FileNotFoundError("Geri alınacak Türkçe yedek bulunamadı.")
    backup = Path(backup).resolve()
    backup_dir = (info.root / "_turkish_backups").resolve()
    if backup_dir not in backup.parents:
        raise ValueError("Yedek dosyası oyun klasörünün _turkish_backups dizininde olmalı.")
    if not backup.exists():
        raise FileNotFoundError(f"Yedek bulunamadı: {backup}")

    tl_dir = info.tl_dir
    support_files = [
        info.support_file,
        info.support_file.with_suffix(".rpyc"),
    ]
    if tl_dir.exists():
        shutil.rmtree(tl_dir)
    for support in support_files:
        if support.exists():
            support.unlink()

    root = info.root.resolve()
    with zipfile.ZipFile(backup, "r") as archive:
        for member in archive.infolist():
            safe_member = safe_archive_member(member.filename)
            target = (root / Path(*safe_member.parts)).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"Güvensiz yedek yolu: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    log(f"Yedekten geri alındı: {backup}")
    return backup


IMAGE_UI_TERMS = (
    "button",
    "buttons",
    "menu",
    "main_menu",
    "mainmenu",
    "gui/",
    "phone",
    "task",
    "quest",
    "hint",
    "notify",
    "notification",
    "warning",
    "warn",
    "disclaimer",
    "language",
    "pref",
    "preferences",
    "gallery",
    "choice",
    "back",
    "continue",
    "start",
    "load",
    "save",
    "quit",
)


def scan_image_ui_candidates(info: GameInfo, limit: int = 80) -> dict:
    """Report image assets that may contain baked, non-translatable UI text.

    This only inspects normal files and RPA archive indexes; it does not extract
    or modify game files.
    """
    extensions = (".png", ".jpg", ".jpeg", ".webp")
    loose: list[str] = []
    archived: list[str] = []

    def looks_relevant(name: str) -> bool:
        lowered = name.replace("\\", "/").lower()
        return lowered.endswith(extensions) and any(term in lowered for term in IMAGE_UI_TERMS)

    for path in info.game_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(info.game_dir).as_posix()
        except ValueError:
            continue
        if looks_relevant(relative):
            loose.append(relative)

    for archive in info.archives:
        for raw_name in archive.entries:
            name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
            normalized = name.replace("\\", "/")
            if looks_relevant(normalized):
                archived.append(f"{archive.path.name}:{normalized}")

    return {
        "loose": len(set(loose)),
        "archived": len(set(archived)),
        "total": len(set(loose)) + len(set(archived)),
        "samples": sorted(dict.fromkeys(loose + archived))[:limit],
    }


def scan_imagebutton_sources(info: GameInfo, limit: int = 60) -> dict:
    """Find custom screen source lines that use image-based UI controls."""
    patterns = ("imagebutton", "add \"gui/", "add 'gui/", "idle \"gui/", "hover \"gui/")
    hits: list[str] = []

    def inspect_text(name: str, text: str):
        for number, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            if any(pattern in lowered for pattern in patterns):
                hits.append(f"{name}:{number}: {line.strip()[:140]}")
                if len(hits) >= limit:
                    return

    for path in info.game_dir.rglob("*.rpy"):
        if len(hits) >= limit:
            break
        if "tl" in {part.lower() for part in path.relative_to(info.game_dir).parts}:
            continue
        try:
            inspect_text(
                path.relative_to(info.game_dir).as_posix(),
                path.read_text(encoding="utf-8", errors="ignore"),
            )
        except OSError:
            continue

    if len(hits) < limit:
        with tempfile.TemporaryDirectory(prefix="renptr_imagebutton_scan_") as temporary:
            temporary_root = Path(temporary)
            for archive in info.archives:
                if len(hits) >= limit:
                    break
                for raw_name, chunks in archive.entries.items():
                    if len(hits) >= limit:
                        break
                    name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
                    if not name.lower().endswith(".rpy"):
                        continue
                    target = temporary_root / safe_archive_member(name)
                    extract_entry(archive.path, chunks, target)
                    inspect_text(
                        f"{archive.path.name}:{name}",
                        target.read_text(encoding="utf-8", errors="ignore"),
                    )

    return {"count": len(hits), "samples": hits[:limit]}


def protect_runtime_cache(game_dir: Path) -> tuple[Path, bool]:
    cache_dir = game_dir / "cache"
    hidden = game_dir / "cache.renptr_backup"
    if hidden.exists():
        if not cache_dir.exists():
            hidden.replace(cache_dir)
        else:
            raise RuntimeError(
                "Önceki işlemden kalan Ren'Py cache yedeği bulundu: "
                f"{hidden}"
            )
    existed = cache_dir.exists()
    if existed:
        cache_dir.replace(hidden)
    return hidden, existed


def restore_runtime_cache(game_dir: Path, hidden: Path, existed: bool):
    cache_dir = game_dir / "cache"
    if not existed:
        return
    if not hidden.exists():
        raise RuntimeError("Ren'Py çalışma cache yedeği kayboldu.")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    hidden.replace(cache_dir)


def generate_templates(info: GameInfo, log: LogFn = print):
    script_archives = [archive for archive in info.archives if archive.rpy_count]
    if not script_archives and not info.loose_rpy:
        if info.packed_rpyc or info.loose_rpyc:
            existing = info.tl_dir
            if existing.exists() and list(existing.rglob("*.rpy")):
                log("Mevcut derlenmiş-oyun Türkçe şablonları kullanılacak.")
                return existing
            return generate_compiled_templates(info, log)
        raise RuntimeError("Çevrilebilir Ren'Py betiği bulunamadı.")

    created: list[Path] = []
    hidden: list[tuple[Path, Path]] = []
    cache_hidden, cache_existed = protect_runtime_cache(info.game_dir)
    try:
        for archive in script_archives:
            log(f"Kaynaklar hazırlanıyor: {archive.path.name}")
            for raw_name, chunks in archive.entries.items():
                name = raw_name.replace("\\", "/")
                if not name.endswith(".rpy") or name.startswith("tl/"):
                    continue
                member = safe_archive_member(name)
                target = info.game_dir.joinpath(*member.parts)
                if not target.exists():
                    extract_entry(archive.path, chunks, target)
                    created.append(target)
            hidden_path = archive.path.with_suffix(
                archive.path.suffix + ".renptr_backup"
            )
            if hidden_path.exists():
                raise RuntimeError(
                    f"Önceki işlemden kalan arşiv yedeği var: {hidden_path}"
                )
            archive.path.replace(hidden_path)
            hidden.append((archive.path, hidden_path))

        command = [
            str(info.executable),
            ".",
            "translate",
            info.language,
            "--empty",
        ]
        log("Ren'Py Türkçe şablonları üretiyor...")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            command,
            cwd=info.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            timeout=900,
        )
        if result.stdout.strip():
            log(result.stdout.strip())
        if result.stderr.strip():
            log(result.stderr.strip())
        if result.returncode:
            raise RuntimeError(f"Ren'Py translate komutu başarısız: {result.returncode}")
    finally:
        for original, hidden_path in reversed(hidden):
            if hidden_path.exists():
                hidden_path.replace(original)
        for source in created:
            compiled = Path(str(source) + "c")
            source.unlink(missing_ok=True)
            compiled.unlink(missing_ok=True)
        restore_runtime_cache(info.game_dir, cache_hidden, cache_existed)

    tl_dir = info.tl_dir
    files = list(tl_dir.rglob("*.rpy")) if tl_dir.exists() else []
    if not files:
        raise RuntimeError("Ren'Py Türkçe çeviri şablonu üretmedi.")
    log(f"Şablon hazır: {len(files)} dosya")
    return tl_dir


def generate_compiled_templates(info: GameInfo, log: LogFn = print):
    """
    Extracts translation nodes directly from RPYC AST data. It does not
    decompile or replace the game's executable scripts.
    """
    try:
        import rpycdec  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "Bu oyun yalnızca .rpyc içeriyor ve rpycdec destek paketi eksik "
            "(pip install -r requirements.txt)."
        ) from error

    tl_dir = info.tl_dir
    with tempfile.TemporaryDirectory(prefix="renptr_compiled_") as temporary_name:
        temporary = Path(temporary_name)
        source_dir = temporary / "rpyc"
        output_dir = temporary / "output"
        source_dir.mkdir()
        output_dir.mkdir()
        extracted = 0

        for archive in info.archives:
            if not archive.rpyc_count:
                continue
            log(f"Derlenmiş betikler okunuyor: {archive.path.name}")
            for raw_name, chunks in archive.entries.items():
                name = raw_name.replace("\\", "/")
                if not name.endswith(".rpyc") or name.startswith("tl/"):
                    continue
                member = safe_archive_member(name)
                target = source_dir.joinpath(*member.parts)
                extract_entry(archive.path, chunks, target)
                extracted += 1

        for source in info.game_dir.rglob("*.rpyc"):
            relative = source.relative_to(info.game_dir)
            if "tl" in {part.lower() for part in relative.parts}:
                continue
            if source.name.lower() in {
                "zz_turkish_autoload.rpyc",
                "turkish_support.rpyc",
                f"zz_capri_{info.language.lower()}_autoload.rpyc",
            }:
                continue
            target = source_dir / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                extracted += 1

        if not extracted:
            raise RuntimeError("Çıkarılabilecek RPYC betiği bulunamadı.")

        log(f"{extracted} RPYC içinden çeviri kimlikleri çıkarılıyor...")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = [
            sys.executable,
            "-m",
            "rpycdec",
            "extract-translate",
            str(source_dir),
            "--output",
            str(output_dir),
            "--language",
            info.language,
            "--empty",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            timeout=900,
        )
        if result.returncode:
            tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-30:])
            raise RuntimeError(f"RPYC çeviri çıkarımı başarısız:\n{tail}")
        generated = output_dir / "tl" / info.language
        files = list(generated.rglob("*.rpy")) if generated.exists() else []
        if not files:
            raise RuntimeError("RPYC ayrıştırıcısı çeviri şablonu üretmedi.")
        tl_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(generated, tl_dir, dirs_exist_ok=True)
        repair_say_prefixes(tl_dir, log)
        log(f"Derlenmiş oyun şablonu: {len(files)} dosya")

    # The RPYC extractor handles game dialogue and strings. Ren'Py itself can
    # still generate engine/common strings without source RPY files.
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [
            str(info.executable),
            ".",
            "translate",
            info.language,
            "--empty",
            "--strings-only",
        ],
        cwd=info.root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        timeout=900,
    )
    if result.returncode:
        log("Uyarı: Ren'Py ortak arayüz metinleri üretilemedi.")
    files = list(tl_dir.rglob("*.rpy"))
    log(f"Şablon hazır: {len(files)} dosya")
    return tl_dir


def repair_say_prefixes(tl_dir: Path, log: LogFn = print) -> dict[str, int]:
    """Kaynak yorumdaki say yapısını çeviri satırına birebir geri yükler."""
    checked = 0
    repaired = 0
    files_changed = 0

    for path in tl_dir.rglob("*.rpy"):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        changed = False
        in_strings = False

        for index, line in enumerate(lines):
            stripped_line = line.strip()
            if stripped_line.startswith("translate ") and "strings:" in stripped_line:
                in_strings = True
                continue
            elif stripped_line.startswith("translate ") and ":" in stripped_line:
                in_strings = False

            if in_strings:
                continue

            if line.lstrip().startswith(("#", "old ", "new ", "translate ")):
                continue
            ending = (
                "\r\n"
                if line.endswith("\r\n")
                else "\n"
                if line.endswith("\n")
                else ""
            )
            body = line[: -len(ending)] if ending else line
            target_match = last_literal_match(body)
            if not target_match:
                continue

            previous = index - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            if previous < 0:
                continue
            stripped = lines[previous].lstrip()
            if not stripped.startswith("#"):
                continue
            if stripped.startswith(("# renptr_", "# TODO", "# game/")) or "renptr_source" in stripped:
                continue
            statement = stripped[1:]
            if statement.startswith(" "):
                statement = statement[1:]
            statement = statement.rstrip("\r\n")
            source_match = last_literal_match(statement)
            if not source_match:
                continue

            prefix_candidate = statement[: source_match.start()].strip()
            if not prefix_candidate or prefix_candidate.startswith("renptr_"):
                continue

            checked += 1
            indentation = body[: len(body) - len(body.lstrip())]
            expected = (
                indentation
                + statement[: source_match.start()]
                + target_match.group(1)
                + body[target_match.end() :]
            )
            if body != expected:
                lines[index] = expected + ending
                repaired += 1
                changed = True

        if changed:
            temporary = path.with_suffix(path.suffix + ".prefix-fix.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(lines)
            temporary.replace(path)
            files_changed += 1

    log(
        "Say statement koruması: "
        f"{checked} satır kontrol, {repaired} onarım, "
        f"{files_changed} dosya"
    )
    return {
        "checked": checked,
        "repaired": repaired,
        "files_changed": files_changed,
    }


def decode_literal(value: str) -> str:
    return ast.literal_eval(value)


def encode_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def source_from_line(line: str) -> str | None:
    stripped = line.rstrip("\r\n")
    if stripped.lstrip().startswith("#"):
        position = stripped.index("#")
        stripped = stripped[:position] + stripped[position + 1 :]
    matches = list(QUOTED_ANY.finditer(stripped))
    if not matches:
        return None
    try:
        return decode_literal(matches[-1].group(1))
    except (SyntaxError, ValueError):
        return None


def last_literal_match(line: str):
    matches = list(QUOTED_ANY.finditer(line))
    return matches[-1] if matches else None


def can_skip_between_source_and_target(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped == "nvl clear"
        or stripped.startswith("nvl clear ")
        or stripped in {"window hide", "window show"}
        or stripped.startswith(("with ", "pause "))
    )


def find_source_before(lines: list[str], index: int) -> str | None:
    previous = index - 1
    while previous >= 0 and can_skip_between_source_and_target(lines[previous]):
        previous -= 1
    return source_from_line(lines[previous]) if previous >= 0 else None


TRANSLATE_HEADER = re.compile(r"^\s*translate\s+\S+\s+([^:]+):")


def restore_orphaned_translation_bytecode(
    game_dir: Path,
    log: LogFn = print,
) -> int:
    tl_root = game_dir / "tl"
    if not tl_root.exists():
        return 0
    restored = 0
    for backup in tl_root.rglob("*.rpyc.bak"):
        target = Path(str(backup)[:-4])
        if target.exists():
            continue
        backup.replace(target)
        restored += 1
    if restored:
        log(f"Hazır dil paketleri geri yüklendi: {restored} RPYC")
    return restored


def _decompile_language_sources(language_dir: Path, output_dir: Path):
    copied = set()
    for source in language_dir.rglob("*.rpy"):
        relative = source.relative_to(language_dir)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.add(relative.as_posix().casefold())

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for compiled in language_dir.rglob("*.rpyc"):
        relative = compiled.relative_to(language_dir).with_suffix(".rpy")
        if relative.as_posix().casefold() in copied:
            continue
        destination = output_dir / relative.parent
        destination.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rpycdec",
                "decompile",
                str(compiled),
                "--output",
                str(destination),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(
                f"İngilizce dil paketi okunamadı: {compiled.name}"
            )


def _translated_dialogue_map(source_dir: Path) -> dict[tuple[str, int], str]:
    mapped = {}
    for path in source_dir.rglob("*.rpy"):
        block = None
        ordinal = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        for line in lines:
            header = TRANSLATE_HEADER.match(line)
            if header:
                block = header.group(1).strip()
                ordinal = 0
                continue
            if (
                not block
                or block == "strings"
                or line.lstrip().startswith(("#", "old ", "new "))
            ):
                continue
            match = last_literal_match(line.rstrip("\r\n"))
            if not match:
                continue
            try:
                mapped[(block, ordinal)] = decode_literal(match.group(1))
            except (SyntaxError, ValueError):
                pass
            ordinal += 1
    return mapped


def _translated_string_map(source_dir: Path) -> dict[str, str]:
    mapped = {}
    for path in source_dir.rglob("*.rpy"):
        block = None
        old = None
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        for line in lines:
            header = TRANSLATE_HEADER.match(line)
            if header:
                block = header.group(1).strip()
                old = None
                continue
            if block != "strings" or line.lstrip().startswith("#"):
                continue
            match = last_literal_match(line.rstrip("\r\n"))
            if not match:
                continue
            try:
                value = decode_literal(match.group(1))
            except (SyntaxError, ValueError):
                continue
            if line.lstrip().startswith("old "):
                old = value
            elif line.lstrip().startswith("new ") and old is not None:
                mapped[old] = value
                old = None
    return mapped


def overlay_english_dialogue_sources(
    tl_dir: Path,
    english_dir: Path,
    clear_targets: bool = False,
    log: LogFn = print,
    clear_dialogues: bool | None = None,
    clear_strings: bool | None = None,
) -> dict[str, int]:
    if not english_dir.exists():
        return {"matched": 0, "files": 0}
    if clear_dialogues is None:
        clear_dialogues = clear_targets
    if clear_strings is None:
        clear_strings = clear_targets
    with tempfile.TemporaryDirectory(prefix="renptr_english_") as temporary:
        extracted = Path(temporary)
        _decompile_language_sources(english_dir, extracted)
        english = _translated_dialogue_map(extracted)
        english_strings = _translated_string_map(extracted)

    matched = 0
    string_matched = 0
    changed_files = 0
    for path in tl_dir.rglob("*.rpy"):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        block = None
        ordinal = 0
        changed = False
        for index, line in enumerate(lines):
            header = TRANSLATE_HEADER.match(line)
            if header:
                block = header.group(1).strip()
                ordinal = 0
                continue
            if (
                not block
                or block == "strings"
                or line.lstrip().startswith(("#", "old ", "new "))
            ):
                continue
            target = last_literal_match(line.rstrip("\r\n"))
            if not target:
                continue
            source = english.get((block, ordinal))
            ordinal += 1
            previous = index - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            if previous < 0 or not lines[previous].lstrip().startswith("#"):
                continue
            if source is None:
                continue

            source_line = lines[previous]
            source_ending = (
                "\r\n"
                if source_line.endswith("\r\n")
                else "\n"
                if source_line.endswith("\n")
                else ""
            )
            source_body = (
                source_line[: -len(source_ending)] if source_ending else source_line
            )
            source_match = last_literal_match(source_body)
            if source_match:
                replacement = (
                    source_body[: source_match.start()]
                    + encode_literal(source)
                    + source_body[source_match.end():]
                    + source_ending
                )
                if replacement != source_line:
                    lines[previous] = replacement
                    changed = True

            if clear_dialogues:
                target_line = lines[index]
                target_ending = (
                    "\r\n"
                    if target_line.endswith("\r\n")
                    else "\n"
                    if target_line.endswith("\n")
                    else ""
                )
                target_body = (
                    target_line[: -len(target_ending)]
                    if target_ending
                    else target_line
                )
                target_match = last_literal_match(target_body)
                if target_match:
                    lines[index] = (
                        target_body[: target_match.start()]
                        + '""'
                        + target_body[target_match.end():]
                        + target_ending
                    )
                    changed = True
            matched += 1

        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.lstrip().startswith("old "):
                index += 1
                continue
            old_match = last_literal_match(line.rstrip("\r\n"))
            if not old_match:
                index += 1
                continue
            try:
                old_value = decode_literal(old_match.group(1))
            except (SyntaxError, ValueError):
                index += 1
                continue
            english_value = english_strings.get(old_value)
            if english_value is None:
                index += 1
                continue
            new_index = index + 1
            while new_index < len(lines) and (
                not lines[new_index].strip()
                or lines[new_index].lstrip().startswith("#")
            ):
                new_index += 1
            if (
                new_index >= len(lines)
                or not lines[new_index].lstrip().startswith("new ")
            ):
                index += 1
                continue
            indentation = line[: len(line) - len(line.lstrip())]
            marker = indentation + "# renptr_source " + encode_literal(english_value) + "\n"
            marker_index = new_index - 1
            if (
                marker_index >= 0
                and lines[marker_index].lstrip().startswith("# renptr_source ")
            ):
                if lines[marker_index] != marker:
                    lines[marker_index] = marker
                    changed = True
            else:
                lines.insert(new_index, marker)
                new_index += 1
                changed = True

            if clear_strings:
                new_line = lines[new_index]
                ending = (
                    "\r\n"
                    if new_line.endswith("\r\n")
                    else "\n"
                    if new_line.endswith("\n")
                    else ""
                )
                body = new_line[: -len(ending)] if ending else new_line
                match = last_literal_match(body)
                if match:
                    replacement = (
                        body[: match.start()] + '""' + body[match.end():] + ending
                    )
                    if replacement != new_line:
                        lines[new_index] = replacement
                        changed = True
            string_matched += 1
            index = new_index + 1

        if changed:
            temporary = path.with_suffix(path.suffix + ".english.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(lines)
            temporary.replace(path)
            changed_files += 1

    if matched:
        log(
            f"İngilizce dil paketi kaynak olarak eşleştirildi: "
            f"{matched} diyalog + {string_matched} arayüz metni / "
            f"{changed_files} dosya"
        )
    return {
        "matched": matched,
        "strings": string_matched,
        "files": changed_files,
    }


def _existing_string_olds(tl_dir: Path) -> set[str]:
    values = set()
    for path in tl_dir.rglob("*.rpy"):
        block = None
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line in handle:
                header = TRANSLATE_HEADER.match(line)
                if header:
                    block = header.group(1).strip()
                    continue
                if block != "strings" or not line.lstrip().startswith("old "):
                    continue
                match = last_literal_match(line.rstrip("\r\n"))
                if not match:
                    continue
                try:
                    values.add(decode_literal(match.group(1)))
                except (SyntaxError, ValueError):
                    pass
    return values


def _looks_translatable_ui_text(value: str) -> bool:
    text = value.strip()
    if text != value or len(text) < 2 or len(text) > 240:
        return False
    visible_text = PROTECTED.sub("", text).strip()
    if not visible_text:
        return False
    if not re.search(r"[A-Za-zÀ-ž]", text):
        return False
    if re.fullmatch(r"[A-Za-z0-9_./\\:-]+", text) and (
        "/" in text
        or "\\" in text
        or "." in text
        or text.casefold() in UI_TECHNICAL_WORDS
    ):
        return False
    if re.search(
        r"\.(?:png|jpe?g|webp|gif|bmp|rpyc?|rpymc?|ogg|mp3|wav|webm|mp4|ttf|otf|json)$",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    lowered = text.casefold()
    if lowered in UI_TECHNICAL_WORDS:
        return False
    if lowered.startswith(("gui/", "images/", "audio/", "music/", "sfx/")):
        return False
    if re.fullmatch(r"[a-z_][a-z0-9_]*", text) and len(text) > 18:
        return False
    return True


def _string_literal_is_dict_key(line: str, match: re.Match) -> bool:
    tail = line[match.end():]
    return bool(re.match(r"\s*:", tail))


def _ui_literals_from_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []
    visible_context = bool(UI_VISIBLE_CONTEXT.search(line) or UI_DATA_KEY.search(line))
    if not visible_context:
        return []
    values = []
    for match in QUOTED_ANY.finditer(line):
        if _string_literal_is_dict_key(line, match):
            continue
        try:
            value = decode_literal(match.group(1))
        except (SyntaxError, ValueError):
            continue
        if _looks_translatable_ui_text(value):
            values.append(value)
    return values


def _copy_source_scripts_for_ui_scan(info: GameInfo, output_dir: Path, log: LogFn):
    copied = 0
    compiled = 0

    for source in info.game_dir.rglob("*.rpy"):
        relative = source.relative_to(info.game_dir)
        if "tl" in {part.lower() for part in relative.parts}:
            continue
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1

    for archive in info.archives:
        for raw_name, chunks in archive.entries.items():
            name = raw_name.replace("\\", "/")
            if name.startswith("tl/"):
                continue
            if name.endswith(".rpy"):
                member = safe_archive_member(name)
                target = output_dir.joinpath(*member.parts)
                if not target.exists():
                    extract_entry(archive.path, chunks, target)
                    copied += 1
            elif name.endswith(".rpyc"):
                member = safe_archive_member(name)
                target = output_dir.joinpath(*member.parts)
                if not target.exists():
                    extract_entry(archive.path, chunks, target)
                    compiled += 1

    for source in info.game_dir.rglob("*.rpyc"):
        relative = source.relative_to(info.game_dir)
        if "tl" in {part.lower() for part in relative.parts}:
            continue
        if _is_support_script(source.name):
            continue
        target = output_dir / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            compiled += 1

    if compiled:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for path in list(output_dir.rglob("*.rpyc")):
            if path.with_suffix(".rpy").exists():
                continue
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rpycdec",
                    "decompile",
                    str(path),
                    "--output",
                    str(path.parent),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
                timeout=120,
            )
            if result.returncode:
                continue
    log(f"Gelişmiş UI taraması kaynakları: {copied} RPY + {compiled} RPYC")


def augment_ui_string_templates(
    info: GameInfo,
    tl_dir: Path,
    log: LogFn = print,
    limit: int = 6000,
) -> dict[str, int]:
    """Screen/phone/task gibi arayüz metinleri için ek translate strings üretir."""
    target = tl_dir / "zz_renptr_ui_strings.rpy"
    target.unlink(missing_ok=True)
    existing = _existing_string_olds(tl_dir)
    found: collections.OrderedDict[str, str] = collections.OrderedDict()
    with tempfile.TemporaryDirectory(prefix="renptr_ui_scan_") as temporary:
        source_root = Path(temporary)
        _copy_source_scripts_for_ui_scan(info, source_root, log)
        for path in sorted(source_root.rglob("*.rpy")):
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    lines = handle.readlines()
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(lines, 1):
                for value in _ui_literals_from_line(line):
                    if value in existing or value in found:
                        continue
                    relative = path.relative_to(source_root).as_posix()
                    found[value] = f"{relative}:{line_no}"
                    if len(found) >= limit:
                        break
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break

    if not found:
        log("Gelişmiş UI taraması: eklenecek yeni arayüz metni bulunamadı.")
        return {"added": 0, "scanned": len(existing)}

    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Capri - ek arayüz/telefon/görev metinleri.\n",
        "# Bu dosya otomatik üretilir; oyun koduna dokunmadan strings çevirisi sağlar.\n",
        f"translate {tl_dir.name} strings:\n",
        "\n",
    ]
    for value, location in found.items():
        lines.append(f"    # renptr_ui_source {location}\n")
        lines.append(f"    old {encode_literal(value)}\n")
        lines.append('    new ""\n')
        lines.append("\n")
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.writelines(lines)
    temporary.replace(target)
    log(f"Gelişmiş UI taraması: {len(found)} ek arayüz metni şablona eklendi.")
    return {"added": len(found), "scanned": len(existing)}


def collect_empty_entries(root: Path):
    entries = []
    unparsed = []
    for path in sorted(root.rglob("*.rpy")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        for index, line in enumerate(lines):
            if line.lstrip().startswith(("#", "old ")):
                continue
            target = last_literal_match(line.rstrip("\r\n"))
            if not target:
                continue
            try:
                target_value = decode_literal(target.group(1))
            except (SyntaxError, ValueError):
                continue
            if target_value != "":
                continue
            source = find_source_before(lines, index)
            if source is None:
                unparsed.append((path, index + 1))
            else:
                entries.append((path, index, source))
    return entries, unparsed


def mask_text(text: str):
    values = []

    def replace(match):
        values.append(match.group(0))
        return f"XPH{len(values) - 1:03d}X"

    return PROTECTED.sub(replace, text), values


def unmask_text(text: str, values: list[str]) -> str | None:
    found = [int(value) for value in MASK.findall(text)]
    if sorted(found) != list(range(len(values))) or len(found) != len(values):
        return None
    for index, value in enumerate(values):
        text = text.replace(f"XPH{index:03d}X", value)
    return text


def protected_content_valid(source: str, target: str) -> bool:
    if not isinstance(source, str):
        source = str(source) if source is not None else ""
    if not isinstance(target, str):
        target = str(target) if target is not None else ""
    return (
        collections.Counter(PROTECTED.findall(source))
        == collections.Counter(PROTECTED.findall(target))
        and not re.search(r"XPH\d", target, flags=re.IGNORECASE)
    )



OUTER_TAG_START = re.compile(r"^(\s*(?:\{[^{}\r\n]+\})+)(.*)$", re.DOTALL)
OUTER_TAG_END = re.compile(
    r"^(.*?)((\s*\{(?:/[^{}\r\n]+|nw|fast|w(?:\=[^}]*)?|p(?:\=[^}]*)?)\})+\s*)$",
    re.DOTALL,
)


def extract_outer_tags(text: str) -> tuple[str, str, str]:
    leading = ""
    trailing = ""
    m_start = OUTER_TAG_START.match(text)
    if m_start:
        leading = m_start.group(1)
        text = m_start.group(2)
    m_end = OUTER_TAG_END.match(text)
    if m_end:
        trailing = m_end.group(2)
        text = m_end.group(1)
    return leading, text, trailing


def _case_preserving_replace(match: re.Match, target: str) -> str:
    word = match.group(0)
    if word.isupper():
        return target.upper()
    if word[0].isupper():
        return target.capitalize()
    return target.lower()


BUILTIN_EN_PRE_REPLACEMENTS = [
    (re.compile(r"\bpussy\b", re.I), lambda m: _case_preserving_replace(m, "vagina")),
    (re.compile(r"\bcunt\b", re.I), lambda m: _case_preserving_replace(m, "vagina")),
    (re.compile(r"\bcock\b", re.I), lambda m: _case_preserving_replace(m, "penis")),
    (re.compile(r"\bdick\b", re.I), lambda m: _case_preserving_replace(m, "penis")),
    (re.compile(r"\bcum\s+(aunt|mom|sister|mother|stepmom|babe|girl|lady|bro|brother)\b", re.I), r"cum, \1"),
    (re.compile(r"\bmy cum\b", re.I), lambda m: _case_preserving_replace(m, "my semen")),
    (re.compile(r"\bwith my cum\b", re.I), lambda m: _case_preserving_replace(m, "with my semen")),
    (re.compile(r"\b(?:I'm|I am)\s+gonna\s+cum\b", re.I), "I am going to ejaculate"),
    (re.compile(r"\b(?:I will|I'll)\s+cum\b", re.I), "I will ejaculate"),
    (re.compile(r"\bgoing to cum\b", re.I), "going to ejaculate"),
    (re.compile(r"\bto cum\b", re.I), "to ejaculate"),
    (re.compile(r"\bwant to cum\b", re.I), "want to ejaculate"),
    (re.compile(r"\bgonna cum\b", re.I), "going to ejaculate"),
]

BUILTIN_TR_POST_REPLACEMENTS = [
    (re.compile(r"\beskisiyor\b", re.I), lambda m: _case_preserving_replace(m, "eskimiyor")),
    (re.compile(r"\beskisiyecek\b", re.I), lambda m: _case_preserving_replace(m, "eskiyecek")),
    (re.compile(r"\beskisidi\b", re.I), lambda m: _case_preserving_replace(m, "eskidi")),
    (re.compile(r"\b(?:vagina|vajina)s[ıi]na\s+siktir\b", re.I), lambda m: _case_preserving_replace(m, "amını sik")),
    (re.compile(r"\b(?:vagina|vajina)s[ıi]n[ıi]\s+kullan\b", re.I), lambda m: _case_preserving_replace(m, "amını kullan")),
    (re.compile(r"\b(?:vaginine|vajinine)\s+de\b", re.I), lambda m: _case_preserving_replace(m, "amına da")),
    (re.compile(r"\b(?:vaginim|vajinim|vaginam|vajinam)de\b", re.I), lambda m: _case_preserving_replace(m, "amımda")),
    (re.compile(r"\b(?:vaginim|vajinim|vaginam|vajinam)[ıi]\b", re.I), lambda m: _case_preserving_replace(m, "amımı")),
    (re.compile(r"\b(?:vaginim|vajinim|vaginam|vajinam)e\b", re.I), lambda m: _case_preserving_replace(m, "amıma")),
    (re.compile(r"\b(?:vaginim|vajinim|vaginam|vajinam)\b", re.I), lambda m: _case_preserving_replace(m, "amım")),
    (re.compile(r"\b(?:vagina|vajina)s[ıi]na\b", re.I), lambda m: _case_preserving_replace(m, "amına")),
    (re.compile(r"\b(?:vagina|vajina)s[ıi]n[ıi]\b", re.I), lambda m: _case_preserving_replace(m, "amını")),
    (re.compile(r"\b(?:vagina|vajina)s[ıi]nda\b", re.I), lambda m: _case_preserving_replace(m, "amında")),
    (re.compile(r"\b(?:vaginine|vajinine)\b", re.I), lambda m: _case_preserving_replace(m, "amına")),
    (re.compile(r"\b(?:vagina|vajina)\b", re.I), lambda m: _case_preserving_replace(m, "am")),
    (re.compile(r"\bpenisimi\b", re.I), lambda m: _case_preserving_replace(m, "sikimi")),
    (re.compile(r"\bpenisime\b", re.I), lambda m: _case_preserving_replace(m, "sikime")),
    (re.compile(r"\bpenisinde\b", re.I), lambda m: _case_preserving_replace(m, "sikinde")),
    (re.compile(r"\bpenisini\b", re.I), lambda m: _case_preserving_replace(m, "sikini")),
    (re.compile(r"\bpenisine\b", re.I), lambda m: _case_preserving_replace(m, "sikine")),
    (re.compile(r"\bpenisim\b", re.I), lambda m: _case_preserving_replace(m, "sikim")),
    (re.compile(r"\bpenis\b", re.I), lambda m: _case_preserving_replace(m, "sik")),
    (re.compile(r"\bspermimle kapataca[gğ][ıi]m\b", re.I), lambda m: _case_preserving_replace(m, "dölümle kaplayacağım")),
    (re.compile(r"^I\s+şimdi\b", re.I), "Şimdi"),
    (re.compile(r"^I\s+(artık|hemen|biraz|daha|şurada|burada)\b", re.I), r"\1"),
]


def load_terms_rules(terms_path: Path | None = None) -> tuple[list, list]:
    en_pre = list(BUILTIN_EN_PRE_REPLACEMENTS)
    tr_post = list(BUILTIN_TR_POST_REPLACEMENTS)
    if terms_path is None:
        from paths import APP_DIR
        terms_path = APP_DIR / "data" / "terms.json"
    if terms_path.exists():
        try:
            data = json.loads(terms_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                custom_en = data.get("en_pre", {})
                if isinstance(custom_en, dict):
                    for k, v in custom_en.items():
                        en_pre.insert(0, (re.compile(rf"\b{re.escape(k)}\b", re.I), lambda m, t=v: _case_preserving_replace(m, t)))
                custom_tr = data.get("tr_post", {})
                if isinstance(custom_tr, dict):
                    for k, v in custom_tr.items():
                        tr_post.insert(0, (re.compile(rf"\b{re.escape(k)}\b", re.I), lambda m, t=v: _case_preserving_replace(m, t)))
        except (OSError, json.JSONDecodeError):
            pass
    return en_pre, tr_post


def preprocess_source_text(text: str, en_pre: list | None = None) -> str:
    rules = en_pre if en_pre is not None else BUILTIN_EN_PRE_REPLACEMENTS
    for pattern, repl in rules:
        text = pattern.sub(repl, text)
    return text


def postprocess_turkish_text(text: str, tr_post: list | None = None) -> str:
    rules = tr_post if tr_post is not None else BUILTIN_TR_POST_REPLACEMENTS
    for pattern, repl in rules:
        text = pattern.sub(repl, text)
    return text


def load_glossary(path: Path | None) -> dict[str, str]:
    glossary = dict(BUILTIN_GLOSSARY)
    if path and path.exists():
        custom = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("glossary.json bir JSON nesnesi olmalı.")
        glossary.update({str(key): str(value) for key, value in custom.items()})
    return glossary


@dataclass
class QualityEntry:
    path: Path
    index: int
    source: str
    draft: str
    speaker: str
    previous: list[str]
    following: str


def collect_quality_entries(tl_dir: Path) -> list[QualityEntry]:
    entries = []
    for path in sorted(tl_dir.rglob("*.rpy")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        raw_entries = []
        for index, line in enumerate(lines):
            if line.lstrip().startswith(("#", "old ", "translate ")):
                continue
            target_match = last_literal_match(line.rstrip("\r\n"))
            if not target_match:
                continue
            previous = index - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            if previous < 0 or not lines[previous].lstrip().startswith("#"):
                continue
            statement = lines[previous].lstrip()[1:].lstrip().rstrip("\r\n")
            source_match = last_literal_match(statement)
            if not source_match:
                continue
            try:
                source = decode_literal(source_match.group(1))
                draft = decode_literal(target_match.group(1))
            except (SyntaxError, ValueError):
                continue
            prefix = statement[: source_match.start()].strip()
            speaker = prefix.split()[0] if prefix else "Anlatıcı"
            raw_entries.append((index, source, draft, speaker))

        for position, (index, source, draft, speaker) in enumerate(raw_entries):
            if not source or not draft or not re.search(r"[A-Za-zÀ-ž]", source):
                continue
            previous_text = [
                value[1] for value in raw_entries[max(0, position - 3):position]
            ]
            following = (
                raw_entries[position + 1][1]
                if position + 1 < len(raw_entries)
                else ""
            )
            entries.append(
                QualityEntry(
                    path=path,
                    index=index,
                    source=source,
                    draft=draft,
                    speaker=speaker,
                    previous=previous_text,
                    following=following,
                )
            )
    return entries


def quality_cache_key(entry: QualityEntry, tl_dir: Path) -> str:
    payload = {
        "file": entry.path.relative_to(tl_dir).as_posix(),
        "source": entry.source,
        "speaker": entry.speaker,
        "previous": entry.previous,
        "following": entry.following,
        "editor": 2,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_editor_json(text: str) -> dict[int, str]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    payload = None
    if start >= 0 and end >= start:
        try:
            payload = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    if payload is None:
        # Recover complete objects from an otherwise truncated response.
        payload = []
        decoder = json.JSONDecoder()
        cursor = 0
        while cursor < len(text):
            object_start = text.find("{", cursor)
            if object_start < 0:
                break
            try:
                item, consumed = decoder.raw_decode(text[object_start:])
            except json.JSONDecodeError:
                cursor = object_start + 1
                continue
            if isinstance(item, dict):
                payload.append(item)
            cursor = object_start + consumed
    result = {}
    if not isinstance(payload, list):
        return result
    for item in payload:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        translated = item.get("tr")
        if isinstance(identifier, int) and isinstance(translated, str):
            result[identifier] = translated.strip()
    return result


def parse_editor_translation(text: str) -> str:
    match = re.search(r"<TR>\s*(.*?)\s*</TR>", text, flags=re.IGNORECASE | re.DOTALL)
    if match and match.group(1).strip().casefold() not in {"çeviri", "?eviri"}:
        return match.group(1).strip()
    cleaned = text.strip()
    cleaned = re.sub(
        r"^(?:Türkçe\s+)?(?:çeviri|cevap)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def english_residue_ratio(text: str) -> float:
    plain = PROTECTED.sub(" ", text)
    words = re.findall(r"[A-Za-z]{2,}", plain.lower())
    if not words:
        return 0.0
    common = {
        "the", "and", "you", "your", "this", "that", "what", "with",
        "have", "not", "are", "was", "were", "but", "for", "from",
        "she", "they", "them", "her", "his", "can", "could", "would",
        "should", "there", "here", "about", "know", "want", "like",
        "really", "then", "when", "where", "why", "how", "only",
        "still", "because", "been", "will", "into",
    }
    return sum(word in common for word in words) / len(words)


def editor_candidate_valid(
    source: str,
    draft: str,
    candidate: str,
    speaker: str = "",
    following: str = "",
) -> bool:
    if not candidate or not protected_content_valid(source, candidate):
        return False
    lowered = candidate.lower()
    refusal_markers = (
        "yardımcı olamam",
        "bu içeriği çeviremem",
        "bu talebi yerine getiremem",
        "i can't assist",
        "i cannot assist",
    )
    if any(marker in lowered for marker in refusal_markers):
        return False
    source_plain = PROTECTED.sub("", source).strip()
    draft_plain = PROTECTED.sub("", draft).strip()
    candidate_plain = PROTECTED.sub("", candidate).strip()
    draft_residue = english_residue_ratio(draft)
    candidate_residue = english_residue_ratio(candidate)
    needs_retranslation = (
        source_plain.casefold() == draft_plain.casefold()
        or draft_residue >= 0.15
    )
    if source_plain:
        ratio = len(candidate_plain) / max(1, len(source_plain))
        if ratio < 0.22 or ratio > 3.2:
            return False
    if draft_plain:
        draft_ratio = len(candidate_plain) / max(1, len(draft_plain))
        similarity = difflib.SequenceMatcher(
            None,
            draft_plain.casefold(),
            candidate_plain.casefold(),
        ).ratio()
        if not needs_retranslation and (
            draft_ratio < 0.65 or draft_ratio > 1.40 or similarity < 0.78
        ):
            return False
    if needs_retranslation and candidate_plain.casefold() != draft_plain.casefold():
        if candidate_residue >= draft_residue:
            return False
    speaker_marker = speaker.strip()
    if (
        speaker_marker
        and speaker_marker.casefold() not in {"anlatıcı", "narrator"}
        and re.match(
            rf"^\s*(?:\*{re.escape(speaker_marker)}\*|"
            rf"{re.escape(speaker_marker)}\s*:)",
            candidate,
            flags=re.IGNORECASE,
        )
        and not re.match(
            rf"^\s*(?:\*{re.escape(speaker_marker)}\*|"
            rf"{re.escape(speaker_marker)}\s*:)",
            draft,
            flags=re.IGNORECASE,
        )
    ):
        return False
    following_plain = PROTECTED.sub("", following).strip()
    if (
        following_plain
        and len(following_plain) <= 24
        and following_plain.casefold() in candidate_plain.casefold()
        and following_plain.casefold() not in draft_plain.casefold()
        and following_plain.casefold() not in source_plain.casefold()
    ):
        return False
    if candidate_residue > draft_residue + 0.15:
        return False
    return True


def quality_entry_needs_edit(entry: QualityEntry) -> bool:
    source = PROTECTED.sub("", entry.source).strip()
    draft = PROTECTED.sub("", entry.draft).strip()
    if not source or not draft:
        return False
    length_ratio = len(draft) / max(1, len(source))
    return (
        source.casefold() == draft.casefold()
        or english_residue_ratio(entry.draft) >= 0.15
        or length_ratio < 0.58
        or length_ratio > 1.70
    )


def write_quality_replacements(resolved: dict[tuple[Path, int], str]):
    by_file = collections.defaultdict(dict)
    for (path, index), value in resolved.items():
        by_file[path][index] = value
    for path, replacements in by_file.items():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        changed_file = False
        for index, value in replacements.items():
            raw = lines[index]
            ending = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
            body = raw[: -len(ending)] if ending else raw
            target = last_literal_match(body)
            if not target:
                continue
            replacement = (
                body[: target.start()]
                + encode_literal(value)
                + body[target.end():]
                + ending
            )
            if replacement != raw:
                lines[index] = replacement
                changed_file = True
        if changed_file:
            temporary = path.with_suffix(path.suffix + ".quality.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(lines)
            temporary.replace(path)


def quality_edit_templates(
    tl_dir: Path,
    model_dir: Path,
    cache_path: Path,
    log: LogFn = print,
    progress: ProgressFn | None = None,
) -> dict[str, int]:
    entries = collect_quality_entries(tl_dir)
    if not entries:
        log("Kaliteli mod: düzenlenecek diyalog bulunamadı.")
        return {"checked": 0, "edited": 0, "fallback": 0}
    candidates = [entry for entry in entries if quality_entry_needs_edit(entry)]
    skipped = len(entries) - len(candidates)
    log(
        f"Kaliteli editör ön eleme: toplam={len(entries)} | "
        f"bağlam hedefi={len(candidates)} | güvenli kısa satır={skipped}"
    )
    if not candidates:
        return {
            "checked": len(entries),
            "model_targets": 0,
            "skipped": skipped,
            "edited": 0,
            "unchanged": 0,
            "fallback": 0,
        }

    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}

    pending = []
    resolved = {}
    for entry in candidates:
        key = quality_cache_key(entry, tl_dir)
        value = cache.get(key)
        if isinstance(value, str) and protected_content_valid(entry.source, value):
            resolved[(entry.path, entry.index)] = value
        else:
            pending.append((entry, key))

    log(
        f"Kaliteli editör: {len(candidates)} hedef | "
        f"önbellek={len(candidates)-len(pending)} | model={len(pending)}"
    )
    if not pending:
        write_quality_replacements(resolved)
        return {
            "checked": len(entries),
            "model_targets": len(candidates),
            "skipped": skipped,
            "edited": 0,
            "unchanged": len(candidates),
            "fallback": 0,
        }

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    log(
        "Bağlamlı editör yükleniyor "
        f"({'GPU' if device == 'cuda' else 'CPU — bu mod yavaş olabilir'})..."
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir),
        local_files_only=True,
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir),
        local_files_only=True,
        trust_remote_code=False,
        dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device).eval()

    system_prompt = (
        "Sen profesyonel bir İngilizce-Türkçe görsel roman editörüsün. "
        "TÜRKÇE TASLAK metnini hafifçe düzenle; sıfırdan yeniden yazma. "
        "İNGİLİZCE satırı yalnızca anlam kontrolü için kullan. Önceki/sonraki "
        "bağlamı ve konuşmacı bilgisini cevaba dahil etme. Anlamı, özneyi, "
        "zamanı, özel adları, karakter sesini ve anlatıcı bakışını değiştirme. "
        "Taslak doğal ve doğruysa aynen döndür. Metne yeni bilgi, ünlem veya "
        "üç nokta ekleme. Argo/kekeleme biçimini "
        "ve yetişkin kurgu içeriğini sansürlemeden koru. XPH000X biçimindeki "
        "bütün teknik işaretleri birebir koru. Yalnızca düzeltilmiş Türkçe "
        "metni döndür; açıklama, ön ek, tırnak veya teknik çıktı etiketi ekleme."
    )

    def prepare_item(local_id: int, entry: QualityEntry):
        masked_source, source_tokens = mask_text(entry.source)
        masked_draft, draft_tokens = mask_text(entry.draft)
        if source_tokens != draft_tokens:
            masked_draft = masked_source
        return {
            "id": local_id,
            "speaker": entry.speaker,
            "previous_context": entry.previous,
            "next_context": entry.following,
            "source_en": masked_source,
            "draft_tr": masked_draft,
        }, source_tokens

    def run_batch(batch):
        rendered_prompts = []
        token_sets = {}
        draft_lengths = []
        for local_id, (entry, _) in enumerate(batch):
            item, tokens = prepare_item(local_id, entry)
            token_sets[local_id] = tokens
            draft_lengths.append(len(item["draft_tr"]))
            untranslated = (
                PROTECTED.sub("", entry.source).strip().casefold()
                == PROTECTED.sub("", entry.draft).strip().casefold()
                or english_residue_ratio(entry.draft) >= 0.15
            )
            edit_instruction = (
                "Taslak çevrilmemiş veya İngilizce kalmış olabilir; eksiksiz "
                "Türkçeye çevir."
                if untranslated
                else "Taslağı yalnızca anlam hatası ve ciddi akıcılık sorunu "
                "varsa düzelt."
            )
            user_prompt = (
                "İngilizce metni bağlama göre Türkçeye çevir ve taslağı düzelt.\n"
                f"GÖREV: {edit_instruction}\n"
                f"KONUŞMACI: {item['speaker']}\n"
                "ÖNCEKİ BAĞLAM: "
                + json.dumps(item["previous_context"], ensure_ascii=False)
                + "\n"
                f"SONRAKİ BAĞLAM: {item['next_context']}\n"
                f"İNGİLİZCE: {item['source_en']}\n"
                f"TÜRKÇE TASLAK: {item['draft_tr']}\n"
                "DÜZELTİLMİŞ TÜRKÇE:"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            rendered_prompts.append(
                tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            )
        tokenizer.padding_side = "left"
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token_id = tokenizer.eos_token_id
        encoded = tokenizer(
            rendered_prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=1024,
        ).to(device)
        source_length = encoded["input_ids"].shape[-1]
        output_limit = min(256, max(48, max(draft_lengths) + 32))
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=output_limit,
                do_sample=False,
                use_cache=True,
                pad_token_id=tokenizer.eos_token_id,
            )
        output = []
        for local_id, (entry, key) in enumerate(batch):
            response = tokenizer.decode(
                generated[local_id][source_length:],
                skip_special_tokens=True,
            )
            candidate = parse_editor_translation(response)
            restored = unmask_text(candidate, token_sets[local_id]) if candidate else None
            if (
                restored is None
                or not editor_candidate_valid(
                    entry.source,
                    entry.draft,
                    restored,
                    entry.speaker,
                    entry.following,
                )
            ):
                output.append((entry, key, entry.draft, False, False))
            else:
                output.append(
                    (entry, key, restored, restored != entry.draft, True)
                )
        return output

    groups = []
    current = []
    current_path = None
    for item in pending:
        if current and (item[0].path != current_path or len(current) >= 16):
            groups.append(current)
            current = []
        current.append(item)
        current_path = item[0].path
    if current:
        groups.append(current)

    queue = collections.deque(groups)
    done = 0
    edited = 0
    fallback = 0
    accepted_unchanged = 0
    last_flush = 0
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    while queue:
        batch = queue.popleft()
        try:
            results = run_batch(batch)
        except RuntimeError as error:
            if device == "cuda" and "out of memory" in str(error).lower():
                torch.cuda.empty_cache()
                if len(batch) > 1:
                    middle = len(batch) // 2
                    queue.appendleft(batch[middle:])
                    queue.appendleft(batch[:middle])
                    log(
                        "Editör GPU belleği doldu; bağlam partisi "
                        f"{len(batch)} → {middle}+{len(batch)-middle} bölündü."
                    )
                    continue
            raise

        for entry, key, value, changed, valid in results:
            resolved[(entry.path, entry.index)] = value
            cache[key] = value
            edited += int(changed)
            fallback += int(not valid)
            accepted_unchanged += int(valid and not changed)
        done += len(batch)
        if done - last_flush >= 64 or done == len(pending):
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(cache, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(cache_path)
            last_flush = done
        if progress:
            progress(done, len(pending))
        if done % 30 == 0 or done == len(pending):
            log(f"Bağlamlı editör: {done}/{len(pending)}")

    write_quality_replacements(resolved)

    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    log(
        f"Kaliteli editör tamamlandı: düzenlenen={edited}, "
        f"geçerli-değişmeyen={accepted_unchanged}, "
        f"güvenli taslak fallback={fallback}"
    )
    return {
        "checked": len(entries),
        "model_targets": len(candidates),
        "skipped": skipped,
        "edited": edited,
        "unchanged": accepted_unchanged,
        "fallback": fallback,
    }



CACHE_FLUSH_INTERVAL = 5.0  # saniye; önbellek en fazla bu aralıkla diske yazılır


def _write_cache_file(cache: dict[str, str], cache_path: Path, skip: set[str] | None = None) -> None:
    """Önbelleği atomik olarak (geçici dosya + replace) diske yazar."""
    data = {k: v for k, v in cache.items() if k not in skip} if skip else cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache_path)


QUALITY_SYSTEM_TR = (
    "Sen deneyimli bir video oyunu / görsel roman yerelleştirme editörüsün. Her öğede İngilizce kaynak ('en'), "
    "Türkçe taslak çeviri ('tr'), konuşan karakter ('speaker') ve önceki satırlar ('context') var.\n"
    "Görevin taslağı düzeltmek: anlam hataları, çevrilmeden kalan İngilizce, doğal olmayan veya robotik ifadeler, "
    "karakterin konuşma tarzına ve önceki satırlara uymayan hitap.\n"
    "Kurallar: {i}, [mc], {color=...} gibi etiketleri ve değişkenleri harfi harfine koru. İyi olan taslağı "
    "gereksiz yere değiştirme. Konuşmacı adını cümleye ekleme. Sansür yapma.\n"
    "YALNIZCA şu biçimde geçerli JSON dizi döndür: [{\"id\": 0, \"tr\": \"düzeltilmiş çeviri\"}, ...]"
)


def quality_edit_with_llm(
    tl_dir: Path,
    cache_path: Path,
    complete: Callable[[str, str], str],
    log: LogFn = print,
    progress: ProgressFn | None = None,
    extra_instruction: str = "",
    batch_size: int = 20,
    only_flagged: bool = True,
) -> dict[str, int]:
    """
    Kalite editörü: Türkçe taslakları bağlamıyla (konuşmacı + önceki satırlar) bir sohbet modeline
    gönderip düzeltir. `complete(system, user) -> str` herhangi bir sağlayıcı olabilir. Öneriler
    `editor_candidate_valid` ile doğrulanır; etiketi bozan veya taslaktan aşırı sapan öneri uygulanmaz.
    """
    entries = collect_quality_entries(tl_dir)
    candidates = [e for e in entries if quality_entry_needs_edit(e)] if only_flagged else entries
    quality_path = cache_path.with_name(cache_path.stem + "_quality.json")
    try:
        qcache: dict[str, str] = json.loads(quality_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        qcache = {}
    system = QUALITY_SYSTEM_TR + (f"\n\n{extra_instruction}" if extra_instruction else "")
    resolved: dict[tuple[Path, int], str] = {}
    source_updates: dict[str, str] = {}
    pending = []
    for entry in candidates:
        key = quality_cache_key(entry, tl_dir)
        if key in qcache:
            value = qcache[key]
            if value != entry.draft and editor_candidate_valid(entry.source, entry.draft, value, entry.speaker, entry.following):
                resolved[(entry.path, entry.index)] = value
            continue
        pending.append((key, entry))
    log(f"Kalite editörü: {len(entries)} satır · düzeltme adayı {len(candidates)} · modele gidecek {len(pending)}")
    edited = rejected = 0

    def flush():
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = quality_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(qcache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(quality_path)

    for start in range(0, len(pending), batch_size):
        chunk = pending[start:start + batch_size]
        payload = [{"id": n, "speaker": e.speaker, "context": e.previous[-2:], "en": e.source, "tr": e.draft}
                   for n, (_, e) in enumerate(chunk)]
        try:
            parsed = parse_editor_json(complete(system, json.dumps(payload, ensure_ascii=False)))
        except Exception as exc:
            log(f"Kalite editörü uyarısı: {exc}")
            parsed = {}
        for n, (key, entry) in enumerate(chunk):
            candidate = parsed.get(n)
            if candidate and candidate != entry.draft and editor_candidate_valid(
                    entry.source, entry.draft, candidate, entry.speaker, entry.following):
                resolved[(entry.path, entry.index)] = candidate
                source_updates[entry.source] = candidate
                qcache[key] = candidate
                edited += 1
            elif n in parsed:
                qcache[key] = entry.draft
                rejected += candidate is not None and candidate != entry.draft
        flush()
        if progress:
            progress(min(start + batch_size, len(pending)), len(pending))
    write_quality_replacements(resolved)
    if source_updates and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cache.update(source_updates)
            _write_cache_file(cache, cache_path)
        except (OSError, ValueError):
            pass
    log(f"Kalite editörü: {edited} satır düzeltildi, {rejected} öneri doğrulamadan geçemedi, {len(resolved)} satır yazıldı.")
    return {"checked": len(entries), "candidates": len(candidates), "edited": edited,
            "rejected": rejected, "applied": len(resolved)}


def load_gemini_api_keys() -> list[str]:
    try:  # Güvenli depo (Windows Kimlik Bilgisi Yöneticisi) + ayar dosyası
        from providers import load_provider_config
        keys = [k for k in load_provider_config().gemini_keys if k.strip()]
        if keys:
            return keys
    except Exception:
        pass
    candidates = [
        Path("gemini_api_key.txt"),
        __import__("paths").APP_DIR / "gemini_api_key.txt",
        Path("c:/RenPyTurkce/gemini_api_key.txt"),
        Path("C:/TurkceCeviri/gemini_api_key.txt"),
    ]
    for p in candidates:
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8").strip()
                keys = [k.strip() for k in raw.replace(",", "\n").splitlines() if k.strip() and not k.strip().startswith("#")]
                if keys:
                    return keys
            except OSError:
                continue
    return []

def load_gemini_api_key() -> str:
    keys = load_gemini_api_keys()
    return keys[0] if keys else ""


def translate_with_gemini(
    missing: list[str],
    cache: dict[str, str],
    cache_path: Path,
    api_key: str,
    log: LogFn = print,
    progress: ProgressFn | None = None,
    target_lang: str = "tr",
    source_lang: str = "en",
    game_engine: str = "Ren'Py Visual Novel",
    failed_out: set[str] | None = None,
    max_workers: int | None = None,
    extra_instruction: str = "",
) -> int:
    if not missing:
        return 0

    log(f"Yapay Zeka (Gemini Flash) ile {len(missing)} benzersiz satır çevriliyor... [Hedef: {target_lang}]")

    try:
        from languages import build_system_instruction
        system_instruction = build_system_instruction(target_lang, source_lang, game_engine)
        if extra_instruction:
            system_instruction += "\n\n" + extra_instruction
    except Exception:
        system_instruction = (
            "Sen profesyonel bir görsel roman (Ren'Py Visual Novel) İngilizce-Türkçe çevirmenisin.\n"
            "Görevin: Verilen JSON string listesini (list of strings) Türkçeye çevirmek.\n"
            "Kurallar:\n"
            "1. Tamamen doğal, akıcı günlük konuşma dili kullan. Deyimleri Türkçe konuşma diline uyarla.\n"
            "2. Sansür yapma, yetişkin/argo ifadeleri sahnenin doğallığına uygun çevir.\n"
            "3. Ren'Py etiketlerini ({i}, {b}, {color=...}, [mc], [nor], [ofr] vb.) ve değişkenlerini harfi harfine koru.\n"
            "4. Giriş listesindeki string sayısı ile çıkıştaki string sayısı BİREBİR AYNI olmalıdır.\n"
            "5. YALNIZCA geçerli bir JSON listesi (array of strings) döndür."
        )

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
    ]

    api_keys = load_gemini_api_keys() or ([api_key] if api_key else [])
    # API'den geçerli yanıt alınamayan satırlar: bellekte kaynak metinle
    # doldurulur ama diske yazılmaz, böylece sonraki çalıştırmada tekrar denenir.
    failed: set[str] = failed_out if failed_out is not None else set()
    # Sabit modelde kalma: anahtarın erişebildiği tüm uygun modeller hız sırasıyla denenir
    try:
        from providers import gemini_model_order, load_provider_config
        model_order = gemini_model_order(load_provider_config().gemini_model, api_keys[0] if api_keys else "")
    except Exception:
        model_order = ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash"]
    log(f"Gemini model sırası ({len(model_order)}): {', '.join(model_order[:5])}{' …' if len(model_order) > 5 else ''}")

    def _make_worker(start_key: int):
        """Her iş parçacığı kendi anahtarı, model sırası ve kota durumuyla çalışır."""
        # Model öncelik listesi (SADECE 0.7s - 1.3s arası roket gibi çalışanlar)
        all_models = list(model_order)  # her iş parçacığının kendi sırası (çalışan model öne alınır)
        active_key_idx = [start_key % max(1, len(api_keys))]
        # Sadece GERÇEK 24 saatlik günlük kotası dolan modeller
        quota_exhausted: set[str] = set()
        # Geçici hata (dakikalık 15-RPM hız sınırı veya 503) — 15 sn sonra tekrar açılır
        temp_failed: dict[str, float] = {}
        _logged_exhausted: set[str] = set()

        def _get_candidates() -> list[str]:
            now = time.monotonic()
            return [
                m for m in all_models
                if m not in quota_exhausted
                and (m not in temp_failed or now - temp_failed[m] > 15)
            ]

        def _call_gemini_api(items: list[str]) -> list[str] | None:
            if not items:
                return []
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"{system_instruction}\n\nİşte çevrilecek liste:\n{json.dumps(items, ensure_ascii=False)}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
                "safetySettings": safety_settings,
            }
            data = json.dumps(payload).encode("utf-8")

            for attempt in range(4):
                candidates = _get_candidates()
                if not candidates:
                    # Tüm modeller geçici hız sınırında (RPM) — 5 sn nefes al ve tekrar dene
                    time.sleep(5)
                    candidates = _get_candidates()
                    if not candidates:
                        # Hâlâ yoksa temp_failed temizle ve devam et
                        temp_failed.clear()
                        candidates = [m for m in all_models if m not in quota_exhausted]
                        if not candidates:
                            if len(api_keys) > 1:
                                active_key_idx[0] = (active_key_idx[0] + 1) % len(api_keys)
                                quota_exhausted.clear()
                                temp_failed.clear()
                                log(f"Bilgi: 24 saatlik kota doldu, {active_key_idx[0] + 1}. API anahtarına geçildi! Kotası sıfırlandı, roket gibi devam ediyor...")
                                candidates = list(all_models)
                            else:
                                return None

                for model_name in candidates:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                    req = urllib.request.Request(
                        url,
                        data=data,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": api_keys[active_key_idx[0]],
                        },
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            res_data = json.loads(resp.read().decode("utf-8"))
                            parts = (
                                res_data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [])
                            )
                            if parts and "text" in parts[0]:
                                parsed = json.loads(parts[0]["text"])
                                if isinstance(parsed, list) and len(parsed) == len(items):
                                    # Çalışan modeli listenin başına al (ve diğer çevirilerle paylaş)
                                    try:
                                        from providers import note_gemini_success
                                        note_gemini_success(model_name)
                                    except Exception:
                                        pass
                                    if model_name in all_models and all_models[0] != model_name:
                                        all_models.remove(model_name)
                                        all_models.insert(0, model_name)
                                    return [str(x) if x is not None else "" for x in parsed]
                    except urllib.error.HTTPError as e:
                        body = ""
                        try:
                            body = e.read().decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    
                        is_daily_limit = (
                            "generaterequestsperday" in body.lower()
                            or "per_day" in body.lower()
                            or "limit: 20" in body.lower()
                        )

                        if is_daily_limit:
                            quota_exhausted.add(model_name)
                            if model_name not in _logged_exhausted:
                                log(f"Bilgi: {model_name} günlük kotası doldu (24 saatlik limit). Diğer modele geçiliyor.")
                                _logged_exhausted.add(model_name)
                            continue
                        elif e.code == 429:
                            # Dakikalık 15-RPM hız sınırı — modeli kalıcı öldürme, 10 sn nefes aldır
                            temp_failed[model_name] = time.monotonic()
                            time.sleep(3)
                            continue
                        elif e.code in (503, 502, 500):
                            temp_failed[model_name] = time.monotonic()
                            time.sleep(2)
                            continue
                        elif e.code in (400, 404):
                            # Model yok ya da bu isteği desteklemiyor → bu çalıştırmada bir daha deneme
                            quota_exhausted.add(model_name)
                            continue
                        else:
                            continue
                    except Exception:
                        temp_failed[model_name] = time.monotonic()
                        continue
            return None

        def _translate_subchunk(items: list[str]) -> dict[str, str]:
            if not items:
                return {}
            try:
                translated = _call_gemini_api(items)
                if translated is not None:
                    results = {}
                    for src, tr in zip(items, translated):
                        src_str = str(src) if src is not None else ""
                        tr_str = str(tr) if tr is not None else ""
                        if tr_str and protected_content_valid(src_str, tr_str):
                            results[src_str] = tr_str
                        else:
                            results[src_str] = src_str
                            failed.add(src_str)
                    return results

                if len(items) > 1:
                    mid = len(items) // 2
                    left = _translate_subchunk(items[:mid])
                    right = _translate_subchunk(items[mid:])
                    left.update(right)
                    return left
                else:
                    s0 = str(items[0]) if items[0] is not None else ""
                    failed.add(s0)
                    return {s0: s0}
            except Exception as err:
                log(f"Uyarı: Parça çevirisinde hata ({err}), kaynak metin korundu.")
                failed.update(str(x) for x in items)
                return {str(x): str(x) for x in items}

        return _translate_subchunk

    batch_size = 75
    done = 0
    total = len(missing)
    last_flush = time.monotonic()
    chunks = [missing[i : i + batch_size] for i in range(0, total, batch_size)]
    workers = max(1, min(max_workers or len(api_keys) or 1, 4, len(chunks)))

    def _after_chunk(chunk: list[str], sub_results: dict[str, str]) -> None:
        nonlocal done, last_flush
        cache.update(sub_results)
        done += len(chunk)
        if done >= total or time.monotonic() - last_flush >= CACHE_FLUSH_INTERVAL:
            _write_cache_file(cache, cache_path, failed)
            last_flush = time.monotonic()
        log(f"Gemini Çevrildi: {done}/{total}")
        if progress:
            try:
                progress(done, total)
            except BaseException:
                _write_cache_file(cache, cache_path, failed)  # iptalde ilerleme kaybolmasın
                raise

    if workers == 1:
        translate_chunk = _make_worker(0)
        for chunk in chunks:
            _after_chunk(chunk, translate_chunk(chunk))
            if done < total:
                time.sleep(0.8)
    else:
        # Birden fazla API anahtarı: her anahtar kendi iş parçacığında, kendi kota
        # durumuyla ve sabit bir parti diliminde (i, i+W, i+2W…) çalışır.
        import queue
        import threading

        log(f"Paralel mod: {workers} API anahtarı aynı anda kullanılıyor.")
        results: "queue.Queue[tuple[list[str], dict[str, str]] | None]" = queue.Queue()
        stop = threading.Event()

        def _worker(index: int) -> None:
            try:
                translate_chunk = _make_worker(index)
                for chunk in chunks[index::workers]:
                    if stop.is_set():
                        break
                    results.put((chunk, translate_chunk(chunk)))
                    time.sleep(0.8)
            finally:
                results.put(None)

        threads = [threading.Thread(target=_worker, args=(i,), daemon=True) for i in range(workers)]
        for thread in threads:
            thread.start()
        finished = 0
        try:
            while finished < workers:
                item = results.get()
                if item is None:
                    finished += 1
                else:
                    _after_chunk(*item)
        except BaseException:
            stop.set()
            raise

    if failed:
        log(
            f"Uyarı: {len(failed)} satır Gemini'den geçerli yanıt alınamadığı için "
            "kaynak metinle bırakıldı; önbelleğe yazılmadı, bir sonraki çalıştırmada yeniden denenecek."
        )
    return done


def translate_with_transformers(
    missing: list[str],
    cache: dict[str, str],
    cache_path: Path,
    model_dir: Path,
    selected_model: str,
    log: LogFn = print,
    progress: ProgressFn | None = None,
    target_lang: str = "tr",
    source_lang: str = "en",
):
    import torch
    from engine_common import NLLB_LANG_CODES

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    selected_model = selected_model.casefold()
    if selected_model == "nllb":
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        log(
            "Model yükleniyor: NLLB kaliteli "
            f"({'GPU' if device == 'cuda' else 'CPU'})..."
        )
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir),
            local_files_only=True,
            src_lang=NLLB_LANG_CODES.get(source_lang, "eng_Latn"),
        )
        model = AutoModelForSeq2SeqLM.from_pretrained(
            str(model_dir),
            local_files_only=True,
            dtype=dtype,
        ).to(device).eval()
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(NLLB_LANG_CODES.get(target_lang, "tur_Latn"))
        max_batch_size = 32 if device == "cuda" else 4
        token_budget = 900 if device == "cuda" else 256
    else:
        from transformers import MarianMTModel, MarianTokenizer

        log(
            "Model yükleniyor: OPUS hızlı "
            f"({'GPU' if device == 'cuda' else 'CPU'})..."
        )
        tokenizer = MarianTokenizer.from_pretrained(str(model_dir))
        model = MarianMTModel.from_pretrained(
            str(model_dir), dtype=dtype
        ).to(device).eval()
        forced_bos_token_id = None
        max_batch_size = 96 if device == "cuda" else 16
        token_budget = 1200 if device == "cuda" else 512

    en_pre, tr_post = load_terms_rules()
    masked = []
    lengths = []
    for source in missing:
        lead, inner, trail = extract_outer_tags(source)
        if inner and re.search(r"[A-Za-zÀ-ž]", inner):
            cleaned_inner = preprocess_source_text(inner, en_pre)
            prepared, values = mask_text(cleaned_inner)
        else:
            cleaned_inner = inner
            prepared, values = mask_text(inner)
        masked.append((source, prepared, values, lead, trail, cleaned_inner))
        lengths.append(len(tokenizer.encode(prepared, add_special_tokens=True)))
    order = sorted(range(len(masked)), key=lengths.__getitem__)

    def run_batch(values: list[str], beams: int = 2):
        if not values:
            return []
        encoded = tokenizer(
            values,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        ).to(device)
        longest_source = int(encoded["attention_mask"].sum(dim=1).max().item())
        output_limit = min(320, max(32, int(longest_source * 1.6) + 24))
        with torch.inference_mode():
            generate_args = {
                "max_new_tokens": output_limit,
                "num_beams": beams,
                "early_stopping": True,
                "no_repeat_ngram_size": 3,
                "repetition_penalty": 1.08,
            }
            if forced_bos_token_id is not None:
                generate_args["forced_bos_token_id"] = forced_bos_token_id
            generated = model.generate(**encoded, **generate_args)
        return tokenizer.batch_decode(generated, skip_special_tokens=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    batches = []
    current = []
    current_max = 0
    for index in order:
        candidate_max = max(current_max, lengths[index])
        candidate_size = len(current) + 1
        if current and (
            candidate_size > max_batch_size
            or candidate_max * candidate_size > token_budget
        ):
            batches.append(current)
            current = []
            current_max = 0
        current.append(index)
        current_max = max(current_max, lengths[index])
    if current:
        batches.append(current)

    pending = collections.deque(batches)
    done = 0
    batch_number = 0
    last_flush = time.monotonic()
    while pending:
        indexes = pending.popleft()
        longest = max(lengths[index] for index in indexes)
        batch_beams = 1 if longest > 160 else 2
        log(
            f"Parti işleniyor: {done}/{len(order)} "
            f"(boyut {len(indexes)}, azami {longest} token)"
        )
        try:
            results = run_batch(
                [masked[index][1] for index in indexes],
                beams=batch_beams,
            )
        except RuntimeError as error:
            out_of_memory = "out of memory" in str(error).lower()
            if device == "cuda" and out_of_memory:
                torch.cuda.empty_cache()
                if len(indexes) > 1:
                    middle = len(indexes) // 2
                    pending.appendleft(indexes[middle:])
                    pending.appendleft(indexes[:middle])
                    log(
                        "GPU belleği doldu; parti otomatik olarak ikiye bölündü "
                        f"({len(indexes)} → {middle}+{len(indexes)-middle})."
                    )
                    continue
                log("Tek uzun metin düşük bellek modunda yeniden deneniyor.")
                results = run_batch([masked[indexes[0]][1]], beams=1)
            else:
                raise
        for index, result in zip(indexes, results):
            source, _, tokens, lead, trail, cleaned_inner = masked[index]
            restored = unmask_text(result, tokens)
            if restored is None:
                parts = PROTECTED.split(cleaned_inner)
                plain = [
                    part for part in parts
                    if part and not PROTECTED.fullmatch(part)
                ]
                if plain:
                    translated_plain = iter(run_batch(plain))
                    restored = "".join(
                        part
                        if PROTECTED.fullmatch(part)
                        else next(translated_plain)
                        for part in parts
                        if part
                    )
                else:
                    restored = cleaned_inner
            if restored is not None:
                if target_lang == "tr":
                    restored = postprocess_turkish_text(restored, tr_post)
                restored = f"{lead}{restored}{trail}"
            if not protected_content_valid(source, restored):
                parts = PROTECTED.split(source)
                plain = [
                    part for part in parts
                    if part and not PROTECTED.fullmatch(part)
                ]
                if plain:
                    translated_plain = iter(run_batch(plain, beams=1))
                    restored = "".join(
                        part
                        if PROTECTED.fullmatch(part)
                        else next(translated_plain)
                        for part in parts
                        if part
                    )
                else:
                    restored = source
            if not protected_content_valid(source, restored):
                restored = source
            for old, new in STAGE_DIRECTIONS.items():
                restored = restored.replace(old, new)
            if source and not restored:
                restored = source
            cache[source] = restored
        done += len(indexes)
        batch_number += 1
        if not pending or time.monotonic() - last_flush >= CACHE_FLUSH_INTERVAL:
            _write_cache_file(cache, cache_path)
            last_flush = time.monotonic()
        if progress:
            try:
                progress(done, len(order))
            except BaseException:
                _write_cache_file(cache, cache_path)  # iptalde ilerleme kaybolmasın
                raise
        log(
            f"Çevrildi: {done}/{len(order)} "
            f"(parti {batch_number}, boyut {len(indexes)}, azami {longest} token)"
        )
    del model
    if device == "cuda":
        torch.cuda.empty_cache()

def translate_templates(
    tl_dir: Path,
    model_dir: Path,
    cache_path: Path,
    glossary_path: Path | None = None,
    log: LogFn = print,
    progress: ProgressFn | None = None,
    model_kind: str = "opus",
    ollama_model: str = "qwen2.5:7b",
    ollama_host: str = "http://localhost:11434",
    failed_out: set[str] | None = None,
    extra_instruction: str = "",
    target_lang: str = "tr",
    source_lang: str = "en",
):
    entries, unparsed = collect_empty_entries(tl_dir)
    if unparsed:
        raise RuntimeError(f"{len(unparsed)} boş hedef ayrıştırılamadı.")
    if not entries:
        log("Yeni çevrilecek boş satır yok.")
        return 0

    glossary = load_glossary(glossary_path)
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    cache.update(glossary)
    if target_lang == "tr":     # sahne yönergeleri tablosu Türkçedir
        cache.update(STAGE_DIRECTIONS)

    # Diyalog sırası korunur: aynı partide ardışık konuşmalar birlikte gider (model bağlamı görür)
    unique = list(dict.fromkeys(source for _, _, source in entries))
    for source in unique:
        if not PROTECTED.sub("", source).strip():
            cache[source] = source
        elif not re.search(r"[A-Za-zÀ-ž]", source):
            cache[source] = source
        elif source not in cache and re.fullmatch(
            r"[A-Z][A-Za-zÀ-ž'’-]{1,24}", source
        ):
            cache[source] = source
    missing = [source for source in unique if source not in cache]
    log(
        f"Çeviri satırı: {len(entries)} | Benzersiz: {len(unique)} | "
        f"Model bekleyen: {len(missing)}"
    )

    if missing:
        selected_model = model_kind.casefold()
        if selected_model == "gemini":
            api_key = load_gemini_api_key()
            if not api_key:
                raise RuntimeError(
                    "Gemini API Anahtarı bulunamadı! Lütfen gemini_api_key.txt dosyasına geçerli bir anahtar kaydedin."
                )
            translate_with_gemini(
                missing=missing,
                cache=cache,
                cache_path=cache_path,
                api_key=api_key,
                log=log,
                progress=progress,
                failed_out=failed_out,
                extra_instruction=extra_instruction,
                target_lang=target_lang,
                source_lang=source_lang,
            )
        elif selected_model in ("openai", "anthropic", "deepl"):
            from providers import translate_with_cloud

            translate_with_cloud(
                selected_model, missing, cache, cache_path, log=log, progress=progress,
                game_engine="Ren'Py Visual Novel", failed_out=failed_out, extra_instruction=extra_instruction,
                target_lang=target_lang, source_lang=source_lang,
            )
        elif selected_model == "ollama":
            from engine_common import OllamaTranslationEngine, TranslationCache

            engine = OllamaTranslationEngine(
                model_name=ollama_model,
                cache=TranslationCache(cache_path, cache),
                protected_pattern=PROTECTED,
                log=log,
                host=ollama_host,
                target_lang=target_lang,
                source_lang=source_lang,
            )
            cache.update(engine.translate_batch(missing, progress=progress))
        else:
            translate_with_transformers(
                missing=missing,
                cache=cache,
                cache_path=cache_path,
                model_dir=model_dir,
                selected_model=selected_model,
                log=log,
                progress=progress,
                target_lang=target_lang,
                source_lang=source_lang,
            )

    by_file = {}
    for path, index, source in entries:
        by_file.setdefault(path, []).append((index, source))
    written = 0
    for path, file_entries in by_file.items():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        for index, source in file_entries:
            raw = lines[index]
            ending = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
            body = raw[: -len(ending)] if ending else raw
            target = last_literal_match(body)
            if not target:
                continue
            lines[index] = (
                body[: target.start()]
                + encode_literal(cache[source])
                + body[target.end() :]
                + ending
            )
            written += 1
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.writelines(lines)
        temporary.replace(path)
    log(f"Dosyalara yazıldı: {written} satır")
    return written


def enable_turkish(info: GameInfo, force: bool, log: LogFn = print):
    """Çeviriyi oyunun varsayılan dili yapar (ad tarihsel: info.language hangi dilse o)."""
    from languages import NO_FONT_FALLBACK, SUPPORTED_LANGUAGES, code_for_renpy_name
    language = info.language
    code = code_for_renpy_name(language)
    native = SUPPORTED_LANGUAGES[code].name_native
    support = info.support_file
    if not force:
        support.unlink(missing_ok=True)
        return
    # Başka bir dilin desteği kalırsa iki dil birbirini ezer; çeviri klasörleri silinmez
    for other in info.game_dir.glob("zz_*_autoload.rpy*"):
        if other.stem != support.stem and _is_support_script(other.name):
            other.unlink(missing_ok=True)

    # Hedef dilin karakterleri eksik olan fontları tespit et
    bad_font_names = []
    try:
        fonts = scan_game_fonts(info)
        for f in fonts:
            if f.get("missing_chars"):
                fname = Path(f["path"]).name
                if fname not in bad_font_names:
                    bad_font_names.append(fname)
    except Exception:
        pass

    dejavu_src = info.root / "renpy" / "common" / "DejaVuSans.ttf"
    dejavu_bold_src = info.root / "renpy" / "common" / "DejaVuSans-Bold.ttf"
    tl_turkish = info.tl_dir
    if code in NO_FONT_FALLBACK:   # DejaVu bu yazıyı içermez: yanlış fonta geçmek metni bozar
        if bad_font_names:
            log(f"Uyarı: oyunun fontları {native} karakterlerini içermiyor; bu dil için font elle eklenmeli.")
        bad_font_names = []
    if tl_turkish.exists() and dejavu_src.exists():
        for bad_name in bad_font_names:
            target = tl_turkish / bad_name
            if not target.exists():
                try:
                    src = dejavu_bold_src if "bold" in bad_name.lower() and dejavu_bold_src.exists() else dejavu_src
                    shutil.copy2(src, target)
                    log(f"Font otomatik yamandı: {bad_name} -> DejaVuSans")
                except Exception:
                    pass

    font_block = ""
    if bad_font_names:
        bad_fonts_repr = repr(bad_font_names)
        font_block = (
            "\n"
            f"translate {language} python:\n"
            "    gui.text_font = \"DejaVuSans.ttf\"\n"
            "    gui.name_text_font = \"DejaVuSans.ttf\"\n"
            "    gui.interface_text_font = \"DejaVuSans.ttf\"\n"
            "    gui.button_text_font = \"DejaVuSans.ttf\"\n"
            "    gui.choice_button_text_font = \"DejaVuSans.ttf\"\n"
            "\n"
            "init 1503 python:\n"
            f"    for _orig in {bad_fonts_repr}:\n"
            "        config.font_replacement_map[_orig, False, False] = (\"DejaVuSans.ttf\", False, False)\n"
            "        config.font_replacement_map[_orig, True, False] = (\"DejaVuSans-Bold.ttf\", False, False)\n"
            "        config.font_replacement_map[_orig, False, True] = (\"DejaVuSans.ttf\", False, True)\n"
            "        config.font_replacement_map[_orig, True, True] = (\"DejaVuSans-Bold.ttf\", False, True)\n"
        )

    script = (
        "# Capri tarafından oluşturuldu.\n"
        "init 1499 python:\n"
        "    config.default_language = \"Turkish\"\n"
        "\n"
        "init 1501 python:\n"
        "    def _renptr_start_in_turkish():\n"
        "        if (getattr(persistent, \"_renptr_turkish_version\", None) or 0) < 5:\n"
        "            renpy.change_language(\"Turkish\", force=True)\n"
        "            persistent._renptr_turkish_version = 5\n"
        "    if _renptr_start_in_turkish not in config.start_interact_callbacks:\n"
        "        config.start_interact_callbacks.append(_renptr_start_in_turkish)\n"
        "    try:\n"
        "        if isinstance(available_langs, dict):\n"
        "            available_langs[\"Turkish\"] = [\"tr\", \"Türkçe\"]\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "screen renptr_language_switcher():\n"
        "    if renpy.get_screen(\"preferences\"):\n"
        "        frame:\n"
        "            xalign 0.98\n"
        "            yalign 0.98\n"
        "            hbox:\n"
        "                spacing 12\n"
        "                textbutton \"English\" action Language(None)\n"
        "                textbutton \"Türkçe\" action Language(\"Turkish\")\n"
        "\n"
        "init 999 python:\n"
        "    if \"renptr_language_switcher\" not in config.overlay_screens:\n"
        "        config.overlay_screens.append(\"renptr_language_switcher\")\n"
        "\n"
    )
    # Akrabalık adları tablosu yalnızca Türkçe için
    names_block = (
        "init 1502 python:\n"
        "    _renptr_orig_names = {}\n"
        "    _renptr_char_map = {\n"
        "        'Mom': 'Anne', 'mom': 'anne', 'Dad': 'Baba', 'dad': 'baba',\n"
        "        'Sister': 'Kardeşim', 'sister': 'kardeşim', 'Brother': 'Kardeşim', 'brother': 'kardeşim',\n"
        "        'Stepmom': 'Üvey Anne', 'stepmom': 'üvey anne', 'Stepdad': 'Üvey Baba', 'stepdad': 'üvey baba',\n"
        "        'Stepsister': 'Üvey Kardeş', 'stepsister': 'üvey kardeş', 'Stepbrother': 'Üvey Kardeş', 'stepbrother': 'üvey kardeş',\n"
        "        'Aunt': 'Teyze', 'aunt': 'teyze', 'Uncle': 'Amca', 'uncle': 'amca',\n"
        "        'Cousin': 'Kuzen', 'cousin': 'kuzen', 'Grandma': 'Büyükanne', 'grandma': 'büyükanne',\n"
        "        'Grandpa': 'Büyükbaba', 'grandpa': 'büyükbaba', 'Landlady': 'Ev Sahibi', 'landlady': 'ev sahibi',\n"
        "        'Landlord': 'Ev Sahibi', 'landlord': 'ev sahibi', 'Maid': 'Hizmetçi', 'maid': 'hizmetçi',\n"
        "        'Boss': 'Patron', 'boss': 'patron', 'Tenant': 'Kiracı', 'tenant': 'kiracı',\n"
        "        'Friend': 'Arkadaş', 'friend': 'arkadaş'\n"
        "    }\n"
        "    def _renptr_fix_characters():\n"
        "        try:\n"
        "            is_tr = (getattr(renpy.game.preferences, 'language', None) == 'Turkish')\n"
        "            for var_name in dir(store):\n"
        "                if var_name.startswith('_'):\n"
        "                    continue\n"
        "                ch = getattr(store, var_name, None)\n"
        "                if ch is not None and hasattr(ch, 'name') and isinstance(getattr(ch, 'name', None), str):\n"
        "                    cname = ch.name\n"
        "                    if is_tr and cname in _renptr_char_map:\n"
        "                        if var_name not in _renptr_orig_names:\n"
        "                            _renptr_orig_names[var_name] = cname\n"
        "                        ch.name = _renptr_char_map[cname]\n"
        "                    elif not is_tr and var_name in _renptr_orig_names:\n"
        "                        ch.name = _renptr_orig_names[var_name]\n"
        "        except Exception:\n"
        "            pass\n"
        "    if _renptr_fix_characters not in config.start_interact_callbacks:\n"
        "        config.start_interact_callbacks.append(_renptr_fix_characters)\n"
    )
    version_key = "_renptr_turkish_version" if language == "Turkish" else f"_renptr_{language.lower()}_version"
    script = script.replace('"Turkish"', f'"{language}"').replace('"tr", "Türkçe"', f'"{code}", "{native}"') \
        .replace('"Türkçe"', f'"{native}"').replace("_renptr_turkish_version", version_key)
    if code == "tr":
        script += names_block
    support.write_text(script, encoding="utf-8")
    log(f"{native} varsayılan dil olarak etkinleştirildi.")


def repair_safe_issues(tl_dir: Path, log: LogFn = print) -> int:
    repaired = 0
    for path in tl_dir.rglob("*.rpy"):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        changed = False
        for index, line in enumerate(lines):
            if line.lstrip().startswith("renptr_source "):
                indentation = line[: len(line) - len(line.lstrip())]
                rest = line.lstrip()[len("renptr_source "):]
                lines[index] = indentation + "new " + rest
                changed = True
                repaired += 1
                line = lines[index]
            if line.lstrip().startswith(("#", "old ")):
                continue
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            body = line[: -len(ending)] if ending else line
            match = last_literal_match(body)
            if not match:
                continue
            source = find_source_before(lines, index)
            if source is None:
                continue
            target = decode_literal(match.group(1))
            sanitized = re.sub(r"}X(?=\{|\n)", "}", target)
            if sanitized != target:
                target = sanitized
                lines[index] = (
                    body[: match.start()]
                    + encode_literal(target)
                    + body[match.end():]
                    + ending
                )
                body = lines[index].rstrip("\r\n")
                match = last_literal_match(body)
                changed = True
                repaired += 1
            source_tokens = collections.Counter(PROTECTED.findall(source))
            target_tokens = collections.Counter(PROTECTED.findall(target))
            safe_identity = not re.search(r"[A-Za-zÀ-ž]", source)
            unsafe_tokens = (
                source_tokens != target_tokens
                or re.search(r"XPH\d", target, flags=re.IGNORECASE)
            )
            if (
                (source and not target)
                or (safe_identity and source_tokens != target_tokens)
                or unsafe_tokens
            ):
                lines[index] = (
                    body[: match.start()]
                    + encode_literal(source)
                    + body[match.end() :]
                    + ending
                )
                changed = True
                repaired += 1
        if changed:
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(lines)
            temporary.replace(path)
    if repaired:
        log(f"Güvenli QA onarımı: {repaired} satır")
    return repaired


def qa_translation(tl_dir: Path) -> dict[str, int]:
    token_errors = 0
    empty_errors = 0
    artifacts = 0
    checked = 0
    for path in tl_dir.rglob("*.rpy"):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        for index, line in enumerate(lines):
            if line.lstrip().startswith(("#", "old ")):
                continue
            match = last_literal_match(line.rstrip("\r\n"))
            if not match:
                continue
            source = find_source_before(lines, index)
            if source is None:
                continue
            target = decode_literal(match.group(1))
            checked += 1
            if collections.Counter(PROTECTED.findall(source)) != collections.Counter(
                PROTECTED.findall(target)
            ):
                token_errors += 1
            if source and not target:
                empty_errors += 1
            if "XPH" in target or re.search(r"}X(?=\{|\n)", target):
                artifacts += 1
    return {
        "checked": checked,
        "token_errors": token_errors,
        "empty_errors": empty_errors,
        "artifacts": artifacts,
    }


def run_lint(info: GameInfo, log: LogFn = print) -> int:
    log("Ren'Py lint çalışıyor...")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [str(info.executable), ".", "lint"],
        cwd=info.root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        timeout=900,
    )
    log(f"Lint çıkış kodu: {result.returncode}")
    return result.returncode


def cache_file_for(root: Path, app_data: Path) -> Path:
    identity = hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:12]
    return app_data / "cache" / f"{identity}.json"


def scan_game_fonts(info: GameInfo) -> list[dict]:
    """Oyun fontlarını tarayarak Türkçe karakter desteğini kontrol eder."""
    font_dirs = []
    gui_dir = info.game_dir / "gui"
    if gui_dir.exists():
        font_dirs.append(gui_dir)
    font_dirs.append(info.game_dir)
    font_dirs.append(info.root)

    from languages import LANGUAGE_CHARS, code_for_renpy_name
    chars = LANGUAGE_CHARS.get(code_for_renpy_name(info.language))
    results: list[dict] = []
    seen: set[Path] = set()
    for directory in font_dirs:
        for path in directory.rglob("*"):
            if path.suffix.lower() in (".ttf", ".otf", ".woff") and path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    try:
                        from engine_common import FontChecker
                        results.append(FontChecker.check_turkish_support(path, chars))
                    except Exception:
                        pass
    return results

