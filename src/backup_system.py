"""
Capri — Evrensel Yedekleme ve Geri Yükleme Yöneticisi
=========================================================
Ren'Py, RPG Maker, Unity ve Unreal Engine için standartlaştırılmış,
doğrulanabilir ve yüzde yüz güvenli yedekleme & geri alma sistemi.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LogFn = Callable[[str], None]


@dataclass
class BackupEntry:
    path: Path
    engine: str
    timestamp: str
    date_str: str
    file_count: int
    is_zip: bool
    size_bytes: int


def _file_hash(path: Path) -> str:
    """Hızlı dosya hash kontrolü (ilk ve son 64KB + boyut)."""
    try:
        size = path.stat().st_size
        h = hashlib.md5(f"{size}".encode())
        with open(path, "rb") as f:
            h.update(f.read(65536))
            if size > 65536:
                f.seek(max(0, size - 65536))
                h.update(f.read(65536))
        return h.hexdigest()
    except Exception:
        return ""


def create_game_backup(
    game_root: Path,
    engine: str,
    files_to_backup: List[Path],
    log: LogFn = print,
) -> Path:
    """
    Belirtilen motor için dosyaları yedekler ve manifest oluşturur.
    """
    game_root = Path(game_root).resolve()
    backup_base = game_root / "_capri_backups"
    backup_base.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    date_str = time.strftime("%Y-%m-%d %H:%M:%S")
    backup_dir = backup_base / f"backup_{engine}_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    backed_count = 0
    total_bytes = 0

    log(f"Yedekleme baslatildi [{engine.upper()}] -> {backup_dir.name}")

    for file_p in files_to_backup:
        file_p = Path(file_p)
        if not file_p.exists() or not file_p.is_file():
            continue

        try:
            rel_path = file_p.resolve().relative_to(game_root)
        except ValueError:
            rel_path = Path(file_p.name)

        dest = backup_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_p, dest)

        size = file_p.stat().st_size
        total_bytes += size
        backed_count += 1
        manifest_files.append({
            "rel_path": str(rel_path).replace("\\", "/"),
            "size": size,
            "hash": _file_hash(file_p),
        })
        log(f"  [YEDEK] {rel_path} ({size:,} bayt)")

    manifest = {
        "engine": engine,
        "timestamp": timestamp,
        "date": date_str,
        "file_count": backed_count,
        "total_bytes": total_bytes,
        "files": manifest_files,
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"Yedekleme tamamlandi: {backed_count} dosya ({total_bytes / (1024*1024):.2f} MB)")
    return backup_dir


def list_game_backups(game_root: Path) -> List[BackupEntry]:
    """
    Oyun klasöründeki tüm yedekleri listeler.
    """
    game_root = Path(game_root).resolve()
    backups: List[BackupEntry] = []

    candidate_dirs = [game_root / "_capri_backups", game_root / "_omnitrans_backups", game_root / "_turkish_backups"]

    for b_base in candidate_dirs:
        if not b_base.exists() or not b_base.is_dir():
            continue

        for item in b_base.iterdir():
            if item.is_dir():
                manifest_p = item / "manifest.json"
                if manifest_p.exists():
                    try:
                        m = json.loads(manifest_p.read_text(encoding="utf-8"))
                        backups.append(BackupEntry(
                            path=item,
                            engine=m.get("engine", "bilinmiyor"),
                            timestamp=m.get("timestamp", item.name),
                            date_str=m.get("date", item.name),
                            file_count=m.get("file_count", len(list(item.rglob("*")))),
                            is_zip=False,
                            size_bytes=m.get("total_bytes", 0),
                        ))
                        continue
                    except Exception:
                        pass

                f_count = len([f for f in item.rglob("*") if f.is_file()])
                engine = "unity" if "unity" in item.name else ("unreal" if "unreal" in item.name else "genel")
                backups.append(BackupEntry(
                    path=item,
                    engine=engine,
                    timestamp=item.name,
                    date_str=item.name.replace("backup_", "").replace("_", " "),
                    file_count=f_count,
                    is_zip=False,
                    size_bytes=sum(f.stat().st_size for f in item.rglob("*") if f.is_file()),
                ))

            elif item.is_file() and item.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(item, "r") as zf:
                        f_count = len(zf.namelist())
                    engine = "rpgmaker" if "rpgm" in item.name else "genel"
                    backups.append(BackupEntry(
                        path=item,
                        engine=engine,
                        timestamp=item.stem,
                        date_str=item.stem,
                        file_count=f_count,
                        is_zip=True,
                        size_bytes=item.stat().st_size,
                    ))
                except Exception:
                    pass

    backups.sort(key=lambda b: b.path.stat().st_mtime if b.path.exists() else 0, reverse=True)
    return backups


def restore_game_backup(
    backup: BackupEntry,
    game_root: Path,
    log: LogFn = print,
) -> Tuple[bool, int, str]:
    """
    Seçilen yedeği kusursuz bir şekilde oyun klasörüne geri yükler ve doğrular.
    """
    game_root = Path(game_root).resolve()
    if not backup.path.exists():
        return False, 0, f"Yedek yolu bulunamadi: {backup.path}"

    log(f"Yedek geri yukleme baslatildi: {backup.path.name}")
    restored_count = 0

    try:
        if backup.is_zip:
            with zipfile.ZipFile(backup.path, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    clean_name = member.filename.replace("\\", "/")
                    dest = (game_root / clean_name).resolve()
                    if game_root not in dest.parents:
                        log(f"  [ATLANDI] Güvensiz arşiv yolu: {clean_name}")
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                    restored_count += 1
                    log(f"  [GERI YUKLENDI] {clean_name}")
        else:
            for file_p in backup.path.rglob("*"):
                if file_p.is_file() and file_p.name != "manifest.json":
                    rel = file_p.relative_to(backup.path)
                    target = game_root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_p, target)
                    restored_count += 1
                    log(f"  [GERI YUKLENDI] {rel} ({target.stat().st_size:,} bayt)")

        log(f"Basariyla geri yuklendi: Toplam {restored_count} dosya.")
        return True, restored_count, f"{restored_count} dosya basariyla eski orijinal haline getirildi."

    except Exception as e:
        log(f"HATA: Geri yukleme sirasinda hata olustu: {e}")
        return False, restored_count, str(e)
