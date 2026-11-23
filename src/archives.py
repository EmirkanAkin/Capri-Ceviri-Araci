"""
Capri — Oyun arşivleri: klasör, zip (NW.js package.nw ve exe'ye eklenmiş zip), Electron app.asar, KiriKiri xp3
=============================================================================================================
Hepsi aynı arayüzü sunar: names() → dosya adları, read(ad) → bayt. Yazma kabın türüne göre değişir:

* klasör: dosyalar yerinde (geçici dosya + tek adımda değiştirme) yazılır.
* zip / exe+zip / asar: arşiv yeniden kurulur; değişmeyen girdiler bayt bayt kopyalanır. Exe'ye eklenmiş zip'te
  çalıştırılabilir kısım aynen kalır, yeni zip arkasına eklenir (NW.js'in belgelediği "copy /b nw.exe+app.nw" biçimi).
* xp3: oyunun arşivine dokunulmaz; değişen dosyalar yeni bir yama arşivine (patchN.xp3) yazılır. KiriKiri yama
  arşivlerini asıl arşivin üstüne bindirir.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from fileio import atomic_write

LogFn = Callable[[str], None]


def _replace_file(path: Path, writer: Callable[[io.BufferedWriter], None]) -> None:
    atomic_write(path, writer=writer)


class Container:
    kind = "dir"

    def __init__(self, path: Path):
        self.path = Path(path)

    def names(self) -> List[str]:
        raise NotImplementedError

    def read(self, name: str) -> bytes:
        raise NotImplementedError

    def write(self, changes: Dict[str, bytes], log: LogFn = print) -> List[Path]:
        """Değişiklikleri yazar; oyunda değişen ya da yeni oluşan dosyaları döndürür."""
        raise NotImplementedError

    def touched_files(self) -> List[Path]:
        """Yazmadan önce yedeklenmesi gereken dosyalar."""
        return [self.path]


class DirContainer(Container):
    kind = "dir"

    def names(self) -> List[str]:
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file()
                      and "_capri_backups" not in p.parts)

    def read(self, name: str) -> bytes:
        return (self.path / name).read_bytes()

    def write(self, changes: Dict[str, bytes], log: LogFn = print) -> List[Path]:
        written = []
        for name, data in changes.items():
            target = (self.path / name).resolve()
            if self.path.resolve() not in target.parents:
                raise ValueError(f"Güvensiz yol: {name}")
            _replace_file(target, lambda out, d=data: out.write(d))
            written.append(target)
        return written

    def files(self, names: Iterable[str]) -> List[Path]:
        return [self.path / n for n in names]


class ZipContainer(Container):
    """package.nw (zip) ya da sonuna zip eklenmiş NW.js exe'si.

    Zip dizini bir kez okunur; okuma her seferinde dosyayı kısa süreliğine açar (açık tutamak Windows'ta yedekten geri
    yüklemeyi kilitlerdi). Yazarken değişmeyen girdiler yeniden sıkıştırılmadan, sıkıştırılmış baytlarıyla aynen
    kopyalanır ve arşiv belleğe değil doğrudan geçici dosyaya akar. Zip64 arşivlerde (4 GB üstü) zipfile'ın yavaş ama
    genel yolu kullanılır."""
    kind = "zip"

    def __init__(self, path: Path):
        super().__init__(path)
        with zipfile.ZipFile(self.path) as zf:
            self._infos = zf.infolist()
        self._by_name = {i.filename: i for i in self._infos}
        self.stub = min((i.header_offset for i in self._infos), default=0)   # exe kısmının boyu (düz zip'te 0)
        if self.stub:
            self.kind = "exe"

    def names(self) -> List[str]:
        return [i.filename for i in self._infos if not i.is_dir()]

    @staticmethod
    def _data_offset(f, info: zipfile.ZipInfo) -> int:
        f.seek(info.header_offset)
        head = f.read(30)
        if len(head) != 30 or head[:4] != b"PK\x03\x04":
            raise zipfile.BadZipFile(f"yerel başlık bulunamadı: {info.filename}")
        name_len, extra_len = struct.unpack("<HH", head[26:30])
        return info.header_offset + 30 + name_len + extra_len

    def _raw(self, f, info: zipfile.ZipInfo) -> bytes:
        f.seek(self._data_offset(f, info))
        raw = f.read(info.compress_size)
        if len(raw) != info.compress_size:
            raise zipfile.BadZipFile(f"girdi kısa: {info.filename}")
        return raw

    def read(self, name: str) -> bytes:
        info = self._by_name[name]
        if info.flag_bits & 0x1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with zipfile.ZipFile(self.path) as zf:             # şifreli ya da başka sıkıştırma: genel yol
                return zf.read(name)
        with open(self.path, "rb") as f:
            raw = self._raw(f, info)
        data = raw if info.compress_type == zipfile.ZIP_STORED else zlib.decompress(raw, -15)
        if len(data) != info.file_size or zlib.crc32(data) & 0xFFFFFFFF != info.CRC:
            raise zipfile.BadZipFile(f"CRC tutmuyor: {name}")
        return data

    def _needs_zip64(self) -> bool:
        limit = 0xFFFFFFFF
        return len(self._infos) >= 0xFFFF or any(
            i.file_size >= limit or i.compress_size >= limit or i.header_offset >= limit or b"\x01\x00" == i.extra[:2]
            for i in self._infos)

    def write(self, changes: Dict[str, bytes], log: LogFn = print) -> List[Path]:
        writer = self._write_slow if self._needs_zip64() else self._write_fast
        _replace_file(self.path, lambda out: writer(out, changes))
        self.__init__(self.path)
        with zipfile.ZipFile(self.path) as check:
            if [i.filename for i in check.infolist()] != [i.filename for i in self._infos]:
                raise OSError("Yazılan arşivin içeriği tutmuyor.")
            for info in check.infolist():               # her girdinin yerel başlığı yerinde mi (veri açılmadan)
                with check.open(info):
                    pass
        for name, data in changes.items():
            if self.read(name) != data:
                raise OSError(f"Yazılan arşiv doğrulanamadı: {name}")
        return [self.path]

    def _copy_stub(self, out) -> None:
        with open(self.path, "rb") as src:
            remaining = self.stub
            while remaining:
                chunk = src.read(min(remaining, 1 << 20))
                if not chunk:
                    raise OSError("Çalıştırılabilir dosya beklenenden kısa.")
                out.write(chunk)
                remaining -= len(chunk)

    @staticmethod
    def _dos_time(date_time) -> Tuple[int, int]:
        y, mo, d, h, mi, s = date_time
        return (h << 11) | (mi << 5) | (s // 2), (max(0, y - 1980) << 9) | (mo << 5) | d

    def _write_fast(self, out, changes: Dict[str, bytes]) -> None:
        """Zip'i konumları kendi başlangıcına göre olacak biçimde yazar (exe'de: "copy /b nw.exe+app.nw" ile aynı)."""
        self._copy_stub(out)
        base = out.tell()
        central = bytearray()
        with open(self.path, "rb") as src:
            for info in self._infos:
                name = info.filename.encode("utf-8") if info.flag_bits & 0x800 else info.orig_filename.encode("cp437", "replace")
                flags = info.flag_bits & ~0x08            # boyutlar yerel başlığa yazılır, veri tanımlayıcısı gerekmez
                method = info.compress_type
                if info.filename in changes:
                    data = changes[info.filename]
                    crc, size = zlib.crc32(data) & 0xFFFFFFFF, len(data)
                    if method != zipfile.ZIP_STORED:
                        method = zipfile.ZIP_DEFLATED
                        comp = zlib.compressobj(6, zlib.DEFLATED, -15)
                        payload = comp.compress(data) + comp.flush()
                    else:
                        payload = data
                    flags &= ~0x1
                else:
                    crc, size, payload = info.CRC, info.file_size, None
                csize = len(payload) if payload is not None else info.compress_size
                needed = 20 if method == zipfile.ZIP_DEFLATED else max(10, info.extract_version)
                dtime, ddate = self._dos_time(info.date_time)
                offset = out.tell() - base
                out.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, needed, flags, method, dtime, ddate, crc, csize, size,
                                      len(name), len(info.extra)) + name + info.extra)
                if payload is not None:
                    out.write(payload)
                else:
                    src.seek(self._data_offset(src, info))
                    remaining = info.compress_size
                    while remaining:
                        chunk = src.read(min(remaining, 1 << 20))
                        if not chunk:
                            raise OSError(f"Zip girdisi kısa: {info.filename}")
                        out.write(chunk)
                        remaining -= len(chunk)
                comment = info.comment or b""
                central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, (info.create_system << 8) | info.create_version,
                                       needed, flags, method, dtime, ddate, crc, csize, size, len(name), len(info.extra),
                                       len(comment), 0, info.internal_attr, info.external_attr, offset)
                central += name + info.extra + comment
        start = out.tell() - base
        out.write(central)
        out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(self._infos), len(self._infos), len(central), start, 0))

    def _write_slow(self, out, changes: Dict[str, bytes]) -> None:
        """Genel yol (zip64): girdiler zipfile ile yeniden yazılır; zip önce ayrı geçici dosyada kurulur."""
        self._copy_stub(out)
        tmp = self.path.with_name(self.path.name + ".capri_zip")
        try:
            with zipfile.ZipFile(self.path) as zin, zipfile.ZipFile(tmp, "w", allowZip64=True) as zout:
                for info in zin.infolist():
                    data = changes.get(info.filename)
                    if data is None:
                        data = zin.read(info)
                    clone = zipfile.ZipInfo(info.filename, info.date_time)
                    clone.compress_type = info.compress_type
                    clone.external_attr, clone.create_system, clone.comment = info.external_attr, info.create_system, info.comment
                    zout.writestr(clone, data)
            with open(tmp, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)
        finally:
            if tmp.exists():
                tmp.unlink()


# ── Electron app.asar ───────────────────────────────────────────────────────
class AsarContainer(Container):
    kind = "asar"
    BLOCK = 4 * 1024 * 1024

    def __init__(self, path: Path):
        super().__init__(path)
        with open(self.path, "rb") as f:
            head = f.read(16)
            if len(head) < 16:
                raise ValueError("asar başlığı eksik")
            _size_pickle, header_pickle, _payload, json_len = struct.unpack("<IIII", head)
            self.header = json.loads(f.read(json_len).decode("utf-8"))
        self.base = 8 + header_pickle
        self._files: Dict[str, dict] = {}
        self._walk(self.header, "")

    def _walk(self, node: dict, prefix: str) -> None:
        for name, entry in (node.get("files") or {}).items():
            path = f"{prefix}{name}"
            if "files" in entry:
                self._walk(entry, path + "/")
            elif "offset" in entry and not entry.get("unpacked"):
                self._files[path] = entry

    def names(self) -> List[str]:
        return sorted(self._files)

    def read(self, name: str) -> bytes:
        entry = self._files[name]
        with open(self.path, "rb") as f:
            f.seek(self.base + int(entry["offset"]))
            return f.read(int(entry["size"]))

    @classmethod
    def _integrity(cls, data: bytes) -> dict:
        blocks = [hashlib.sha256(data[i:i + cls.BLOCK]).hexdigest() for i in range(0, max(len(data), 1), cls.BLOCK)]
        return {"algorithm": "SHA256", "hash": hashlib.sha256(data).hexdigest(), "blockSize": cls.BLOCK, "blocks": blocks}

    def write(self, changes: Dict[str, bytes], log: LogFn = print) -> List[Path]:
        """Arşiv yeniden kurulur: değişen dosyalar yeni içerikle, diğerleri özgün baytlarıyla; konumlar ve (varsa)
        bütünlük özetleri güncellenir. Paket dışı (unpacked) dosyalara dokunulmaz."""
        order = sorted(self._files.items(), key=lambda kv: int(kv[1]["offset"]))
        old = {name: (int(entry["offset"]), int(entry["size"])) for name, entry in order}
        offset = 0
        for name, entry in order:
            size = len(changes[name]) if name in changes else old[name][1]
            entry["offset"], entry["size"] = str(offset), size
            if name in changes and "integrity" in entry:
                entry["integrity"] = self._integrity(changes[name])
            offset += size
        raw = json.dumps(self.header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        padded = len(raw) + (-len(raw) % 4)
        header = (struct.pack("<II", 4, padded + 8) + struct.pack("<II", padded + 4, len(raw)) + raw
                  + b"\0" * (padded - len(raw)))
        old_base = self.base

        def writer(out):
            out.write(header)
            with open(self.path, "rb") as src:
                for name, _entry in order:
                    if name in changes:
                        out.write(changes[name])
                        continue
                    src.seek(old_base + old[name][0])
                    remaining = old[name][1]
                    while remaining:
                        chunk = src.read(min(remaining, 1 << 20))
                        if not chunk:
                            raise OSError(f"asar okunamadı: {name}")
                        out.write(chunk)
                        remaining -= len(chunk)

        _replace_file(self.path, writer)
        self.__init__(self.path)
        for name, data in changes.items():
            if self.read(name) != data:
                raise OSError(f"Yazılan asar doğrulanamadı: {name}")
        return [self.path]


# ── KiriKiri xp3 ────────────────────────────────────────────────────────────
XP3_MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"
CAPRI_MARK = "capri_patch.txt"          # Capri'nin yazdığı yama arşivlerinde bulunur: kaynak olarak okunmaz


class Xp3Archive:
    """Okuma: sıkıştırılmış/sıkıştırılmamış dizin ve bölümler, 2.30+ başlığı. Yazma: sıkıştırmasız basit arşiv."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: Dict[str, List[Tuple[int, int, int, int]]] = {}      # ad → [(bayrak, konum, boy, paketli boy)]
        self.protected: Dict[str, bool] = {}
        with open(self.path, "rb") as f:
            if f.read(11) != XP3_MAGIC:
                raise ValueError("xp3 değil")
            index_offset = struct.unpack("<Q", f.read(8))[0]
            if index_offset == 0x17:                      # 2.30+: 0x13'te 1, 0x17'de 0x80 ve 0, dizin konumu 0x20'de
                f.seek(0x13)
                if struct.unpack("<I", f.read(4))[0] != 1:
                    raise ValueError("xp3 sürüm başlığı tanınmadı")
                f.seek(0x20)
                index_offset = struct.unpack("<Q", f.read(8))[0]
            f.seek(index_offset)
            flag = f.read(1)[0]
            if flag & 0x07 == 1:
                packed, size = struct.unpack("<QQ", f.read(16))
                index = zlib.decompress(f.read(packed))
                if len(index) != size:
                    raise ValueError("xp3 dizini bozuk")
            else:
                size = struct.unpack("<Q", f.read(8))[0]
                index = f.read(size)
        self._parse(index)

    @staticmethod
    def _chunks(data: bytes):
        pos = 0
        while pos + 12 <= len(data):
            tag = data[pos:pos + 4]
            size = struct.unpack("<Q", data[pos + 4:pos + 12])[0]
            yield tag, data[pos + 12:pos + 12 + size]
            pos += 12 + size

    def _parse(self, index: bytes) -> None:
        for tag, body in self._chunks(index):
            if tag != b"File":
                continue
            name, segments, flags = "", [], 0
            for sub, data in self._chunks(body):
                if sub == b"info":
                    flags = struct.unpack("<I", data[:4])[0]
                    length = struct.unpack("<H", data[20:22])[0]
                    name = data[22:22 + 2 * length].decode("utf-16-le")
                elif sub == b"segm":
                    for i in range(0, len(data) - 27, 28):
                        segments.append(struct.unpack("<IQQQ", data[i:i + 28]))
            if name:
                self.entries[name.replace("\\", "/")] = segments
                self.protected[name.replace("\\", "/")] = bool(flags & 0x80000000)

    def names(self) -> List[str]:
        return sorted(self.entries)

    def read(self, name: str) -> bytes:
        parts = []
        with open(self.path, "rb") as f:
            for flag, offset, size, packed in self.entries[name]:
                f.seek(offset)
                data = f.read(packed)
                if flag & 0x07 == 1:
                    data = zlib.decompress(data)
                if len(data) != size:
                    raise ValueError(f"xp3 bölümü bozuk: {name}")
                parts.append(data)
        return b"".join(parts)

    @staticmethod
    def write_new(path: Path, files: Dict[str, bytes]) -> Path:
        """Sıkıştırmasız yeni arşiv (yama). Dizin zlib'le sıkıştırılır (KiriKiri 2 ve Z okur)."""
        path = Path(path)
        body = bytearray()
        index = bytearray()
        offset = len(XP3_MAGIC) + 8
        for name, data in files.items():
            body += data
            wname = name.encode("utf-16-le")
            info = struct.pack("<IQQH", 0, len(data), len(data), len(wname) // 2) + wname
            segm = struct.pack("<IQQQ", 0, offset, len(data), len(data))
            adlr = struct.pack("<I", zlib.adler32(data) & 0xFFFFFFFF)
            chunk = (b"info" + struct.pack("<Q", len(info)) + info + b"segm" + struct.pack("<Q", len(segm)) + segm
                     + b"adlr" + struct.pack("<Q", len(adlr)) + adlr)
            index += b"File" + struct.pack("<Q", len(chunk)) + chunk
            offset += len(data)
        packed = zlib.compress(bytes(index), 9)

        def writer(out):
            out.write(XP3_MAGIC + struct.pack("<Q", len(XP3_MAGIC) + 8 + len(body)))
            out.write(body)
            out.write(b"\x01" + struct.pack("<QQ", len(packed), len(index)) + packed)
        _replace_file(path, writer)
        return path


class Xp3Container(Container):
    """Bir KiriKiri oyununun arşivleri birlikte: data.xp3, sonra patch.xp3, patch2.xp3… (sonraki öncekini ezer).
    Yazma: yeni bir yama arşivi."""
    kind = "xp3"

    def __init__(self, root: Path, archives: List[Path]):
        super().__init__(root)
        self.archives, self.own_patch = [], None
        for path in archives:
            archive = Xp3Archive(path)
            if CAPRI_MARK in archive.entries:
                self.own_patch = path              # önceki çeviri: kaynak değil, yeniden yazılacak
            else:
                self.archives.append(archive)
        self._owner: Dict[str, Xp3Archive] = {}
        for archive in self.archives:
            for name in archive.names():
                self._owner[name] = archive
        self.patch_path = self.own_patch or self._next_patch()

    def _next_patch(self) -> Path:
        existing = {p.name.lower() for p in self.path.glob("patch*.xp3")}
        if "patch.xp3" not in existing:
            return self.path / "patch.xp3"
        n = 2
        while f"patch{n}.xp3" in existing:
            n += 1
        return self.path / f"patch{n}.xp3"

    def names(self) -> List[str]:
        return sorted(self._owner)

    def read(self, name: str) -> bytes:
        return self._owner[name].read(name)

    def touched_files(self) -> List[Path]:
        return []

    def created_files(self) -> List[Path]:
        return [self.patch_path]

    def write(self, changes: Dict[str, bytes], log: LogFn = print) -> List[Path]:
        mark = b"Capri tarafindan olusturulan ceviri yamasi. Silinirse oyun orijinal metne doner.\r\n"
        Xp3Archive.write_new(self.patch_path, {**changes, CAPRI_MARK: mark})
        check = Xp3Archive(self.patch_path)
        for name, data in changes.items():
            if check.read(name) != data:
                raise OSError(f"Yama arşivi doğrulanamadı: {name}")
        log(f"Yama arşivi yazıldı: {self.patch_path.name} ({len(changes)} dosya)")
        return [self.patch_path]


__all__ = ["Container", "DirContainer", "ZipContainer", "AsarContainer", "Xp3Archive", "Xp3Container", "XP3_MAGIC",
           "CAPRI_MARK"]
