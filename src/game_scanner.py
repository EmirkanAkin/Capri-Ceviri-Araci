"""
Capri — Bilgisayardaki oyunları bulma
=====================================
Steam kütüphaneleri, Epic ve GOG kurulumları, sürücülerdeki Games/Oyunlar klasörleri ve kullanıcının
eklediği klasörler taranır. Yalnızca okunur; hiçbir dosya değiştirilmez. Çevrilebilir motor algılananlar
öneri olarak listelenir, kütüphaneye ekleme kararı kullanıcınındır.
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import library

SKIP_NAMES = {"steamworks shared", "steam controller configs", "steamvr", "steamlinuxruntime", "proton experimental"}
COMMON_FOLDERS = ("Games", "Oyunlar", "Oyun", "SteamLibrary/steamapps/common")
DETECT_PAUSE = 0.005    # arayüz akıcı kalsın: oyunlar arasında kısa nefes


def _fixed_drives() -> List[Path]:
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [Path(f"{chr(65 + i)}:/") for i in range(26) if mask >> i & 1]
        return [d for d in drives if ctypes.windll.kernel32.GetDriveTypeW(str(d)) == 3]   # DRIVE_FIXED
    except (AttributeError, OSError):
        return []


def steam_folders() -> List[Path]:
    root = library._steam_root()
    return [lib / "steamapps" / "common" for lib in library._steam_libraries(root)] if root else []


def epic_games(manifests: Optional[Path] = None) -> List[Path]:
    base = manifests or Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Epic/EpicGamesLauncher/Data/Manifests"
    found = []
    for item in base.glob("*.item") if base.is_dir() else []:
        try:
            location = json.loads(item.read_text(encoding="utf-8")).get("InstallLocation")
            if location:
                found.append(Path(location))
        except (OSError, ValueError):
            continue
    return found


def gog_games() -> List[Path]:
    found = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, index)) as game:
                    found.append(Path(winreg.QueryValueEx(game, "path")[0]))
    except (OSError, ImportError):
        pass
    return found


def scan_sources(extra: Iterable[str] = (), drives: Optional[List[Path]] = None) -> Tuple[List[Path], List[Path]]:
    """(içindeki alt klasörler taranacak klasörler, doğrudan oyun klasörleri)."""
    parents = steam_folders()
    for drive in _fixed_drives() if drives is None else drives:
        parents += [drive / name for name in COMMON_FOLDERS]
    parents.append(Path.home() / "Games")
    parents += [Path(p) for p in extra]
    return list(dict.fromkeys(parents)), epic_games() + gog_games()


def _children(folder: Path) -> List[Path]:
    try:
        return [c for c in folder.iterdir() if c.is_dir() and not c.name.startswith((".", "_", "$"))
                and c.name.lower() not in SKIP_NAMES]
    except OSError:
        return []


def scan(detect: Callable[[str], Tuple[Optional[str], Any]], root_of: Callable[[str, Any, Path], Path],
         title_of: Callable[[str, Any, Path], str], parents: Iterable[Path], direct: Iterable[Path] = (),
         known: Iterable[str] = (), should_stop: Callable[[], bool] = lambda: False) -> List[Dict[str, str]]:
    """Algılanan oyunlar: {path, title, engine}. Kütüphanede olanlar (known) atlanır."""
    seen = {library.ProjectLibrary.key(k) for k in known}
    candidates: List[Path] = []
    for parent in parents:
        if parent.is_dir():
            candidates += _children(parent)
    candidates += [p for p in direct if p.is_dir()]
    games: List[Dict[str, str]] = []
    for path in dict.fromkeys(candidates):
        if should_stop():
            break
        time.sleep(DETECT_PAUSE)
        try:
            kind, info = detect(str(path))
            if not kind:
                continue
            root = Path(root_of(kind, info, path))
            key = library.ProjectLibrary.key(root)
            if key in seen:
                continue
            seen.add(key)
            games.append({"path": str(root), "title": title_of(kind, info, root), "engine": kind})
        except Exception:
            continue   # okunamayan klasör taramayı durdurmaz
    return sorted(games, key=lambda g: g["title"].casefold())
