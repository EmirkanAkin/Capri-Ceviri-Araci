"""
Capri — RPG Maker şifreli arşivleri (Game.rgssad / Game.rgss2a / Game.rgss3a)
============================================================================
XP ve VX arşivleri RGSSAD v1, VX Ace arşivleri v3 biçimindedir. İkisi de dosya verisini
32 bit XOR anahtar akışıyla (k → k*7+3) saklar; harici bir araç gerekmez.

Çeviri için arşiv oyun klasörüne açılır ve kendisi `_capri_backups/rgss_archive/` altına
taşınır (RGSS, arşiv yoksa dosyaları klasörden okur). `restore()` her şeyi geri alır.
"""
from __future__ import annotations

import json
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

MAGIC = b"RGSSAD\x00"
V1_KEY = 0xDEADCAFE
MASK = 0xFFFFFFFF
ARCHIVE_NAMES = ("Game.rgss3a", "Game.rgss2a", "Game.rgssad")
BACKUP_DIR = "_capri_backups/rgss_archive"
MANIFEST = "_capri_backups/rgss_extract.json"
LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


@dataclass
class Entry:
    name: str        # arşivdeki yol, "/" ile
    offset: int
    size: int
    key: int


def _next(key: int) -> int:
    return (key * 7 + 3) & MASK


def find_archive(game_root: Path) -> Optional[Path]:
    for name in ARCHIVE_NAMES:
        if (Path(game_root) / name).is_file():
            return Path(game_root) / name
    return None


def read_index(path: Path) -> Tuple[int, List[Entry]]:
    """(sürüm, girdiler) döndürür."""
    entries: List[Entry] = []
    with open(path, "rb") as f:
        header = f.read(8)
        if header[:7] != MAGIC or header[7:8] not in (b"\x01", b"\x03"):
            raise ValueError(f"RGSS arşivi değil: {Path(path).name}")
        version = header[7]
        total = Path(path).stat().st_size
        if version == 3:
            key = (struct.unpack("<I", f.read(4))[0] * 9 + 3) & MASK
            while True:
                raw = f.read(16)
                if len(raw) < 16:
                    break
                offset, size, file_key, name_len = (v ^ key for v in struct.unpack("<4I", raw))
                if offset == 0:
                    break
                name = bytes(b ^ ((key >> (8 * (i % 4))) & 0xFF) for i, b in enumerate(f.read(name_len)))
                entries.append(Entry(_decode(name), offset, size, file_key))
        else:
            key = V1_KEY
            while f.tell() < total:
                raw = f.read(4)
                if len(raw) < 4:
                    break
                name_len = struct.unpack("<I", raw)[0] ^ key
                key = _next(key)
                out = bytearray()
                for b in f.read(name_len):
                    out.append(b ^ (key & 0xFF))
                    key = _next(key)
                size = struct.unpack("<I", f.read(4))[0] ^ key
                key = _next(key)
                entries.append(Entry(_decode(bytes(out)), f.tell(), size, key))
                f.seek(size, 1)
    return version, entries


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp932", errors="replace")
    return text.replace("\\", "/")


def crypt(data: bytes, key: int) -> bytes:
    """Veri XOR akışı (şifreleme ve çözme aynı işlemdir)."""
    if not data:
        return b""
    pad = (-len(data)) % 4
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is None:
        words = struct.unpack(f"<{(len(data) + pad) // 4}I", data + b"\0" * pad)
        out = []
        for w in words:
            out.append(w ^ key)
            key = _next(key)
        return struct.pack(f"<{len(out)}I", *out)[:len(data)]
    words = np.frombuffer(data + b"\0" * pad, dtype="<u4").copy()
    block = 1 << 16
    powers = np.empty(block, dtype=np.uint32)          # 7^n
    powers[0] = 1
    powers[1:] = 7
    powers = np.cumprod(powers, dtype=np.uint32)
    offsets = np.zeros(block, dtype=np.uint32)         # 3·(7^0 + … + 7^(n-1))
    offsets[1:] = np.cumsum(powers[:-1], dtype=np.uint32) * np.uint32(3)
    step_a, step_b = int(powers[-1]) * 7 & MASK, (int(offsets[-1]) * 7 + 3) & MASK
    with np.errstate(over="ignore"):
        for start in range(0, len(words), block):
            n = min(block, len(words) - start)
            words[start:start + n] ^= powers[:n] * np.uint32(key) + offsets[:n]
            key = (step_a * key + step_b) & MASK
    return words.tobytes()[:len(data)]


def read_entry(path: Path, entry: Entry) -> bytes:
    with open(path, "rb") as f:
        f.seek(entry.offset)
        return crypt(f.read(entry.size), entry.key)


def _safe_target(root: Path, name: str) -> Optional[Path]:
    target = (root / name).resolve()
    return target if root in target.parents else None


def extract_data(path: Path, dest: Path, prefix: str = "data/") -> int:
    """Yalnızca Data/ girdilerini dest klasörüne açar (analiz için)."""
    _version, entries = read_index(path)
    dest = Path(dest).resolve()
    count = 0
    for entry in entries:
        if not entry.name.lower().startswith(prefix):
            continue
        target = _safe_target(dest, entry.name.split("/", 1)[1])
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_entry(path, entry))
            count += 1
    return count


def unpack(game_root: Path, log: LogFn = print, progress: Optional[ProgressFn] = None) -> Dict[str, object]:
    """Arşivi oyun klasörüne açar, arşivi yedeğe taşır ve geri alma manifesti yazar."""
    root = Path(game_root).resolve()
    archive = find_archive(root)
    if not archive:
        raise FileNotFoundError("Oyun klasöründe RGSS arşivi bulunamadı.")
    version, entries = read_index(archive)
    backup = root / BACKUP_DIR
    backup.mkdir(parents=True, exist_ok=True)
    extracted, replaced = [], []
    with open(archive, "rb") as f:
        for index, entry in enumerate(entries, 1):
            target = _safe_target(root, entry.name)
            if not target:
                log(f"Atlandı (güvensiz yol): {entry.name}")
                continue
            f.seek(entry.offset)
            data = crypt(f.read(entry.size), entry.key)
            rel = target.relative_to(root).as_posix()
            if target.exists():
                if target.read_bytes() == data:
                    continue
                keep = backup / "replaced" / rel
                keep.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(keep))
                replaced.append(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            extracted.append(rel)
            if progress and (index % 25 == 0 or index == len(entries)):
                progress(index, len(entries))
    shutil.move(str(archive), str(backup / archive.name))
    manifest = {"archive": archive.name, "version": version, "extracted": extracted, "replaced": replaced}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"{archive.name} açıldı: {len(extracted)} dosya çıkarıldı, arşiv yedeğe taşındı.")
    return manifest


def is_unpacked(game_root: Path) -> bool:
    return (Path(game_root) / MANIFEST).exists()


def restore(game_root: Path, log: LogFn = print) -> int:
    """unpack() işlemini geri alır: çıkarılan dosyaları siler, arşivi ve değişen dosyaları geri koyar."""
    root = Path(game_root).resolve()
    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError("Bu oyunda Capri ile açılmış bir arşiv yok.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = root / BACKUP_DIR
    removed = 0
    for rel in manifest["extracted"]:
        target = _safe_target(root, rel)
        if target and target.is_file():
            target.unlink()
            removed += 1
    for rel in manifest["replaced"]:
        src, target = backup / "replaced" / rel, _safe_target(root, rel)
        if target and src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
    shutil.move(str(backup / manifest["archive"]), str(root / manifest["archive"]))
    for folder in sorted({(root / rel).parent for rel in manifest["extracted"]}, key=lambda p: len(p.parts), reverse=True):
        while folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    manifest_path.unlink()
    shutil.rmtree(backup, ignore_errors=True)
    log(f"Arşiv geri yüklendi: {manifest['archive']} ({removed} çıkarılmış dosya silindi).")
    return removed


def write_archive(path: Path, files: Iterable[Tuple[str, bytes]], version: int = 3, seed: int = 0x1234ABCD) -> None:
    """Test ve paketleme için RGSSAD arşivi yazar (oyunun okuduğu biçimle aynı)."""
    files = [(name.replace("/", "\\").encode("utf-8"), data) for name, data in files]
    out = bytearray(MAGIC + bytes([version]))
    if version == 3:
        key = (seed * 9 + 3) & MASK
        out += struct.pack("<I", seed)
        index_size = sum(16 + len(name) for name, _ in files) + 16
        offset = len(out) + index_size
        blobs = []
        for i, (name, data) in enumerate(files):
            file_key = (seed + i * 0x9E3779B1) & MASK
            out += struct.pack("<4I", offset ^ key, len(data) ^ key, file_key ^ key, len(name) ^ key)
            out += bytes(b ^ ((key >> (8 * (j % 4))) & 0xFF) for j, b in enumerate(name))
            blobs.append(crypt(data, file_key))
            offset += len(data)
        out += struct.pack("<4I", key, 0, 0, 0)   # offset ^ key == 0 → son
        for blob in blobs:
            out += blob
    else:
        key = V1_KEY
        for name, data in files:
            out += struct.pack("<I", len(name) ^ key)
            key = _next(key)
            for b in name:
                out.append(b ^ (key & 0xFF))
                key = _next(key)
            out += struct.pack("<I", len(data) ^ key)
            key = _next(key)
            out += crypt(data, key)
    Path(path).write_bytes(bytes(out))
