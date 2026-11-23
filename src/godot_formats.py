"""
Capri — Godot dosya biçimleri: .pck paketleri, ikili kaynaklar (RSRC), çeviri tabloları
=====================================================================================
Biçimler Godot'nun açık kaynak kodundan (MIT) alınmıştır: core/io/file_access_pack.cpp, pck_packer.cpp,
resource_format_binary.cpp ve core/string/optimized_translation.cpp. Sıkıştırılmış çeviri metinleri için Godot'nun
kullandığı Smaz sözlüğü (BSD, Salvatore Sanfilippo) aşağıdadır; yalnızca okumada kullanılır, Capri çevirileri
sıkıştırmadan yazar (Godot bunu da okur).

Desteklenen: pck biçim sürümü 1 (Godot 3), 2-4 (Godot 4.x), ayrı .pck dosyası ya da exe'ye gömülü paket.
Şifreli paketler okunamaz.
"""
from __future__ import annotations

import hashlib
import struct
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PCK_MAGIC = b"GDPC"
PACK_DIR_ENCRYPTED = 1
PACK_REL_FILEBASE = 2
PACK_FILE_ENCRYPTED = 1
PACK_FILE_REMOVAL = 2


class GodotFormatError(ValueError):
    pass


# ── PCK ─────────────────────────────────────────────────────────────────────
@dataclass
class PckEntry:
    path: str
    offset: int          # dosya içindeki mutlak konum
    size: int
    md5: bytes
    flags: int = 0


@dataclass
class Pck:
    path: Path
    version: int
    engine: Tuple[int, int, int]
    flags: int
    start: int                          # paketin dosya içindeki başlangıcı (gömülü pakette > 0)
    entries: Dict[str, PckEntry] = field(default_factory=dict)

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & PACK_DIR_ENCRYPTED) or any(e.flags & PACK_FILE_ENCRYPTED for e in self.entries.values())

    _fh: Any = None

    @contextmanager
    def opened(self):
        """Çok sayıda girdi okunacaksa paketi bir kez aç (her girdide yeniden açmak yerine). Blok bitince kapanır;
        tutamak açık bırakılmaz (Windows'ta yedek geri yüklemeyi kilitlerdi)."""
        if self._fh is not None:
            yield self
            return
        self._fh = open(self.path, "rb")
        try:
            yield self
        finally:
            self._fh.close()
            self._fh = None

    def read(self, name: str) -> bytes:
        entry = self.entries[name]
        if entry.flags & PACK_FILE_ENCRYPTED:
            raise GodotFormatError(f"Şifreli dosya: {name}")
        if self._fh is not None:
            self._fh.seek(entry.offset)
            data = self._fh.read(entry.size)
        else:
            with open(self.path, "rb") as f:
                f.seek(entry.offset)
                data = f.read(entry.size)
        if len(data) != entry.size:
            raise GodotFormatError(f"Paket kısa: {name}")
        return data


def _find_embedded(f) -> int:
    """Exe'ye gömülü paketin başlangıcı (sonda: uint64 boy + 'GDPC'); yoksa -1."""
    f.seek(0, 2)
    end = f.tell()
    if end < 12:
        return -1
    f.seek(end - 4)
    if f.read(4) != PCK_MAGIC:
        return -1
    f.seek(end - 12)
    size = struct.unpack("<Q", f.read(8))[0]
    start = end - 12 - size
    if start < 0:
        return -1
    f.seek(start)
    return start if f.read(4) == PCK_MAGIC else -1


def read_pck(path: Path) -> Pck:
    path = Path(path)
    with open(path, "rb") as f:
        start = 0
        if f.read(4) != PCK_MAGIC:
            start = _find_embedded(f)
            if start < 0:
                raise GodotFormatError("Godot paketi değil")
            f.seek(start + 4)
        version, major, minor, patch = struct.unpack("<4I", f.read(16))
        if version > 4:
            raise GodotFormatError(f"Desteklenmeyen pck sürümü: {version}")
        flags, file_base, dir_offset = 0, 0, 0
        if version >= 2:
            flags = struct.unpack("<I", f.read(4))[0]
            file_base = struct.unpack("<Q", f.read(8))[0]
            if version >= 3:
                dir_offset = struct.unpack("<Q", f.read(8))[0]
        f.read(16 * 4)                                   # ayrılmış alanlar
        pck = Pck(path, version, (major, minor, patch), flags, start)
        if flags & PACK_DIR_ENCRYPTED:
            return pck
        if version >= 3:
            f.seek(start + dir_offset)
        base = start + file_base if version >= 2 and (flags & PACK_REL_FILEBASE) else start if version >= 2 else start
        count = struct.unpack("<I", f.read(4))[0]
        for _ in range(count):
            length = struct.unpack("<I", f.read(4))[0]
            name = f.read(length).rstrip(b"\0").decode("utf-8")
            offset, size = struct.unpack("<QQ", f.read(16))
            md5 = f.read(16)
            entry_flags = struct.unpack("<I", f.read(4))[0] if version >= 2 else 0
            if version >= 2 and not (flags & PACK_REL_FILEBASE):
                absolute = start + offset            # 4.0-4.1: konumlar paket başına göre
            elif version >= 2:
                absolute = base + offset
            else:
                absolute = start + offset            # Godot 3
            if name.startswith("res://"):
                name = name[6:]
            if entry_flags & PACK_FILE_REMOVAL:
                continue
            pck.entries[name] = PckEntry(name, absolute, size, md5, entry_flags)
    return pck


def write_pck(path: Path, files: Dict[str, bytes], engine: Tuple[int, int, int], version: int = 2) -> Path:
    """Küçük yama paketi (şifresiz, göreli dosya tabanı). version: 1 → Godot 3, 2 → Godot 4 (4.0+ hepsi okur)."""
    path = Path(path)
    names = list(files)
    header_size = 4 + 16 + (4 + 8 if version >= 2 else 0) + 64
    directory = bytearray(struct.pack("<I", len(names)))
    offsets, pos = [], 0
    for name in names:
        offsets.append(pos)
        pos += len(files[name]) + (-len(files[name]) % 32 if version >= 2 else 0)
    for name, offset in zip(names, offsets):
        raw = ("res://" + name if version == 1 else name).encode("utf-8")
        padded = raw + b"\0" * (-len(raw) % 4 or 4) if version >= 2 else raw
        directory += struct.pack("<I", len(padded)) + padded
        directory += struct.pack("<QQ", offset if version >= 2 else 0, len(files[name]))
        directory += hashlib.md5(files[name]).digest()
        if version >= 2:
            directory += struct.pack("<I", 0)
    if version >= 2:
        file_base = header_size + len(directory)
        file_base += -file_base % 32
        head = PCK_MAGIC + struct.pack("<4I", 2, *engine) + struct.pack("<IQ", PACK_REL_FILEBASE, file_base) + bytes(64)
        body = bytearray(head + directory + bytes(file_base - header_size - len(directory)))
        for name in names:
            body += files[name] + bytes(-len(files[name]) % 32)
    else:
        file_base = header_size + len(directory)
        head = PCK_MAGIC + struct.pack("<4I", 1, *engine) + bytes(64)
        body = bytearray(head)
        fixed = bytearray(struct.pack("<I", len(names)))
        cursor = file_base
        for name in names:                           # Godot 3: mutlak konumlar
            raw = ("res://" + name).encode("utf-8")
            fixed += struct.pack("<I", len(raw)) + raw + struct.pack("<QQ", cursor, len(files[name]))
            fixed += hashlib.md5(files[name]).digest()
            cursor += len(files[name])
        body += fixed
        for name in names:
            body += files[name]
    from fileio import atomic_write
    atomic_write(path, bytes(body))
    return path


# ── RSRC (ikili kaynak) ─────────────────────────────────────────────────────
V_NIL, V_BOOL, V_INT, V_FLOAT, V_STRING = 1, 2, 3, 4, 5
V_DICTIONARY, V_ARRAY, V_PACKED_BYTE, V_PACKED_INT32, V_PACKED_STRING = 26, 30, 31, 32, 34
V_INT64, V_DOUBLE, V_STRING_NAME = 40, 41, 44


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data, self.pos = data, pos
        self.real = 4                     # 8: kaynak çift duyarlıklı (real_t = double) kaydedilmiş
        self.strings: List[str] = []

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def raw(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        if len(v) != n:
            raise GodotFormatError("kaynak kısa")
        self.pos += n
        return v

    def ustr(self) -> str:
        n = self.u32()
        return self.raw(n).rstrip(b"\0").decode("utf-8", errors="replace") if n else ""

    def pad(self, n: int) -> None:
        self.pos += -n % 4


@dataclass
class Resource:
    """Ana kaynak (yalnızca alt kaynağı olmayan basit kaynaklar yeniden yazılabilir)."""
    data: bytes
    type: str
    major: int
    strings: List[str]
    main_offset: int
    props_start: int                     # özelliklerin başladığı konum (sayıdan sonra)
    props: List[Tuple[str, Any, int, int]]   # (ad, değer, değerin başı, sonu)
    writable: bool

    def get(self, name: str, default: Any = None) -> Any:
        return next((v for n, v, _a, _b in self.props if n == name), default)


_REALS = {10: 2, 11: 4, 12: 3, 13: 4, 14: 4, 15: 6, 16: 9, 17: 12, 18: 6, 50: 4, 52: 16}
_INTS = {45: 2, 46: 4, 47: 3, 51: 4}
_PACKED = {33: ("f", 4), 49: ("d", 8), 48: ("q", 8)}
_PACKED_REALS = {37: 2, 35: 3, 53: 4}


class _Opaque:
    """Çeviri için gerekmeyen değer (vektör, renk, nesne başvurusu…): yalnızca atlanır."""
    def __init__(self, kind: int):
        self.kind = kind


def _name(r: _Reader) -> str:
    sid = r.u32()
    if sid & 0x80000000:
        return r.raw(sid & 0x7FFFFFFF).rstrip(b"\0").decode("utf-8", errors="replace")
    return r.strings[sid] if sid < len(r.strings) else ""


def _variant(r: _Reader, major: int) -> Any:
    t = r.u32()
    if t == V_NIL:
        return None
    if t in _REALS:
        r.raw(_REALS[t] * r.real)
        return _Opaque(t)
    if t in _INTS:
        r.raw(_INTS[t] * 4)
        return _Opaque(t)
    if t == 20:                                   # Color: 4 float32
        r.raw(16)
        return _Opaque(t)
    if t == 23:                                   # RID
        r.u32()
        return _Opaque(t)
    if t == 22:                                   # NodePath
        names = struct.unpack_from("<H", r.data, r.pos)[0]
        subs = struct.unpack_from("<H", r.data, r.pos + 2)[0] & 0x7FFF
        r.pos += 4
        for _ in range(names + subs):
            _name(r)
        return _Opaque(t)
    if t == 24:                                   # Object
        kind = r.u32()
        if kind in (2, 3):
            r.u32()
        elif kind == 1:
            r.ustr()
            r.ustr()
        elif kind != 0:
            raise GodotFormatError("bilinmeyen nesne başvurusu")
        return _Opaque(t)
    if t in (42, 43):                             # Callable / Signal: veri yok
        return _Opaque(t)
    if t in _PACKED:
        n = r.u32()
        r.raw(n * _PACKED[t][1])
        return _Opaque(t)
    if t in _PACKED_REALS:
        n = r.u32()
        r.raw(n * _PACKED_REALS[t] * r.real)
        return _Opaque(t)
    if t == 36:                                   # PackedColorArray
        n = r.u32()
        r.raw(n * 16)
        return _Opaque(t)
    if t == V_BOOL:
        return bool(r.u32())
    if t == V_INT:
        return struct.unpack("<i", struct.pack("<I", r.u32()))[0]
    if t == V_INT64:
        return struct.unpack("<q", struct.pack("<Q", r.u64()))[0]
    if t == V_FLOAT:
        return struct.unpack("<f", r.raw(4))[0]
    if t == V_DOUBLE:
        return struct.unpack("<d", r.raw(8))[0]
    if t in (V_STRING, V_STRING_NAME) and not (major < 4 and t == V_STRING_NAME):
        return r.ustr()
    if t == V_DICTIONARY:
        n = r.u32() & 0x7FFFFFFF
        out = {}
        for _ in range(n):
            k = _variant(r, major)
            out[k] = _variant(r, major)
        return out
    if t == V_ARRAY:
        n = r.u32() & 0x7FFFFFFF
        return [_variant(r, major) for _ in range(n)]
    if t == V_PACKED_BYTE:
        n = r.u32()
        v = r.raw(n)
        r.pad(n)
        return bytes(v)
    if t == V_PACKED_INT32:
        n = r.u32()
        return list(struct.unpack(f"<{n}i", r.raw(4 * n)))
    if t == V_PACKED_STRING:
        n = r.u32()
        return [r.ustr() for _ in range(n)]
    raise GodotFormatError(f"Desteklenmeyen değer türü: {t}")


def read_resource(data: bytes) -> Resource:
    if data[:4] == b"RSCC":
        raise GodotFormatError("Sıkıştırılmış kaynak (RSCC) desteklenmiyor")
    if data[:4] != b"RSRC":
        raise GodotFormatError("Godot ikili kaynağı değil")
    r = _Reader(data, 4)
    if r.u32():
        raise GodotFormatError("Büyük endian kaynak desteklenmiyor")
    real64 = r.u32()
    major, _minor, fmt = r.u32(), r.u32(), r.u32()
    rtype = r.ustr()
    importmd = r.u64()
    flags = 0
    if major >= 4:
        flags = r.u32()
        r.u64()                                   # uid
        if flags & 8:                              # FORMAT_FLAG_HAS_SCRIPT_CLASS
            r.ustr()
        r.raw(11 * 4)
    else:
        r.raw(14 * 4)
    r.real = 8 if real64 or flags & 4 else 4       # FORMAT_FLAG_REAL_T_IS_DOUBLE
    strings = [r.ustr() for _ in range(r.u32())]
    r.strings = strings
    externals = r.u32()
    for _ in range(externals):
        r.ustr()
        r.ustr()
        if flags & 2:                              # FORMAT_FLAG_UIDS
            r.u64()
    internals = [(r.ustr(), r.u64()) for _ in range(r.u32())]
    if not internals:
        raise GodotFormatError("kaynak boş")
    main_offset = internals[-1][1]
    r.pos = main_offset
    main_type = r.ustr()
    count = r.u32()
    props_start = r.pos
    props = []
    for _ in range(count):
        name = _name(r)
        start = r.pos
        value = _variant(r, major)
        props.append((name, value, start, r.pos))
    tail = data[r.pos:]
    writable = len(internals) == 1 and externals == 0 and tail == b"RSRC" and (importmd == 0 or importmd < main_offset)
    return Resource(data, main_type or rtype, major, strings, main_offset, props_start, props, writable)


def _enc_ustr(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\0"
    return struct.pack("<I", len(raw)) + raw


def encode_variant(value: Any, kind: int) -> bytes:
    if kind in (V_STRING, V_STRING_NAME):
        return struct.pack("<I", kind) + _enc_ustr(value)
    if kind == V_PACKED_BYTE:
        return struct.pack("<II", V_PACKED_BYTE, len(value)) + bytes(value) + bytes(-len(value) % 4)
    if kind == V_PACKED_INT32:
        return struct.pack("<II", V_PACKED_INT32, len(value)) + struct.pack(f"<{len(value)}i", *value)
    raise GodotFormatError(f"yazılamayan tür: {kind}")


def replace_props(res: Resource, new_values: Dict[str, bytes]) -> bytes:
    """Ana kaynağın bazı özelliklerini (kodlanmış değer baytlarıyla) değiştirip kaynağı yeniden üretir."""
    if not res.writable:
        raise GodotFormatError("Bu kaynak güvenle yeniden yazılamıyor")
    out = bytearray(res.data[:res.props[0][2]] if res.props else res.data[:res.props_start])
    pos = res.props[0][2] if res.props else res.props_start
    for name, _value, start, end in res.props:
        out += res.data[pos:start]
        out += new_values.get(name, res.data[start:end])
        pos = end
    out += res.data[pos:]
    return bytes(out)


# ── Çeviri tabloları ────────────────────────────────────────────────────────
SMAZ_RCB = [  # Godot thirdparty/misc/smaz.c (BSD-3, Salvatore Sanfilippo)
    ' ', 'the', 'e', 't', 'a', 'of', 'o', 'and', 'i', 'n', 's', 'e ', 'r', ' th', ' t', 'in', 'he', 'th',
    'h', 'he ', 'to', '\r\n', 'l', 's ', 'd', ' a', 'an', 'er', 'c', ' o', 'd ', 'on', ' of', 're', 'of ',
    't ', ', ', 'is', 'u', 'at', '   ', 'n ', 'or', 'which', 'f', 'm', 'as', 'it', 'that', '\n', 'was', 'en',
    '  ', ' w', 'es', ' an', ' i', '\r', 'f ', 'g', 'p', 'nd', ' s', 'nd ', 'ed ', 'w', 'ed', 'http://',
    'for', 'te', 'ing', 'y ', 'The', ' c', 'ti', 'r ', 'his', 'st', ' in', 'ar', 'nt', ',', ' to', 'y', 'ng',
    ' h', 'with', 'le', 'al', 'to ', 'b', 'ou', 'be', 'were', ' b', 'se', 'o ', 'ent', 'ha', 'ng ', 'their',
    '"', 'hi', 'from', ' f', 'in ', 'de', 'ion', 'me', 'v', '.', 've', 'all', 're ', 'ri', 'ro', 'is ', 'co',
    'f t', 'are', 'ea', '. ', 'her', ' m', 'er ', ' p', 'es ', 'by', 'they', 'di', 'ra', 'ic', 'not', 's, ',
    'd t', 'at ', 'ce', 'la', 'h ', 'ne', 'as ', 'tio', 'on ', 'n t', 'io', 'we', ' a ', 'om', ', a', 's o',
    'ur', 'li', 'll', 'ch', 'had', 'this', 'e t', 'g ', 'e\r\n', ' wh', 'ere', ' co', 'e o', 'a ', 'us',
    ' d', 'ss', '\n\r\n', '\r\n\r', '="', ' be', ' e', 's a', 'ma', 'one', 't t', 'or ', 'but', 'el', 'so',
    'l ', 'e s', 's,', 'no', 'ter', ' wa', 'iv', 'ho', 'e a', ' r', 'hat', 's t', 'ns', 'ch ', 'wh', 'tr',
    'ut', '/', 'have', 'ly ', 'ta', ' ha', ' on', 'tha', '-', ' l', 'ati', 'en ', 'pe', ' re', 'there', 'ass',
    'si', ' fo', 'wa', 'ec', 'our', 'who', 'its', 'z', 'fo', 'rs', '>', 'ot', 'un', '<', 'im', 'th ', 'nc',
    'ate', '><', 'ver', 'ad', ' we', 'ly', 'ee', ' n', 'id', ' cl', 'ac', 'il', '</', 'rt', ' wi', 'div',
    'e, ', ' it', 'whi', ' ma', 'ge', 'x', 'e c', 'men', '.com',
]


def smaz_decompress(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        if c == 254:
            out.append(data[i + 1])
            i += 2
        elif c == 255:
            n = data[i + 1] + 1
            out += data[i + 2:i + 2 + n]
            i += 2 + n
        else:
            out += SMAZ_RCB[c].encode("latin-1")
            i += 1
    return bytes(out)


def ot_hash(d: int, text: bytes) -> int:
    """OptimizedTranslation'ın özet işlevi (FNV benzeri, 32 bit)."""
    if d == 0:
        d = 0x1000193
    for b in text:
        d = ((d * 0x1000193) & 0xFFFFFFFF) ^ b
    return d


@dataclass
class OptimizedTable:
    locale: str
    hash_table: List[int]
    bucket_table: List[int]
    strings: bytes

    def elements(self) -> List[Tuple[int, int]]:
        """[(bucket_table içindeki öğe konumu, anahtar özeti)] — oyundaki sırayla değil, tablo sırasıyla."""
        out = []
        bt = [v & 0xFFFFFFFF for v in self.bucket_table]
        seen = set()
        for start in (v & 0xFFFFFFFF for v in self.hash_table):
            if start == 0xFFFFFFFF or start in seen:
                continue
            seen.add(start)
            size = bt[start]
            for i in range(size):
                at = start + 2 + i * 4
                out.append((at, bt[at]))
        return out

    def message_at(self, at: int) -> str:
        bt = [v & 0xFFFFFFFF for v in self.bucket_table]
        offset, comp, uncomp = bt[at + 1], bt[at + 2], bt[at + 3]
        raw = self.strings[offset:offset + comp]
        data = raw if comp == uncomp else smaz_decompress(raw)
        return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")

    def messages(self) -> List[Tuple[int, str]]:
        return [(at, self.message_at(at)) for at, _h in self.elements()]

    def lookup(self, key: str) -> Optional[str]:
        """Godot'nun get_message'ı ile aynı yol (testlerde doğrulama için)."""
        if not self.hash_table:
            return None
        k = key.encode("utf-8")
        h = ot_hash(0, k)
        p = self.hash_table[h % len(self.hash_table)] & 0xFFFFFFFF
        if p == 0xFFFFFFFF:
            return None
        bt = [v & 0xFFFFFFFF for v in self.bucket_table]
        size, func = bt[p], bt[p + 1]
        h2 = ot_hash(func, k)
        for i in range(size):
            at = p + 2 + i * 4
            if bt[at] == h2:
                return self.message_at(at)
        return None

    def rebuilt(self, replacements: Dict[int, str]) -> "OptimizedTable":
        """Aynı özet tablosu, yeni metinler (sıkıştırmasız; Godot comp_size == uncomp_size ise düz okur)."""
        bt = [v & 0xFFFFFFFF for v in self.bucket_table]
        blob = bytearray()
        for at, _h in self.elements():
            text = replacements.get(at)
            raw = (text.encode("utf-8") if text is not None else self.message_at(at).encode("utf-8")) + b"\0"
            bt[at + 1], bt[at + 2], bt[at + 3] = len(blob), len(raw), len(raw)
            blob += raw
        signed = [struct.unpack("<i", struct.pack("<I", v))[0] for v in bt]
        return OptimizedTable(self.locale, self.hash_table, signed, bytes(blob))


def optimized_table(res: Resource) -> OptimizedTable:
    return OptimizedTable(str(res.get("locale", "")), list(res.get("hash_table", [])), list(res.get("bucket_table", [])),
                          bytes(res.get("strings", b"")))


def write_optimized(res: Resource, table: OptimizedTable) -> bytes:
    return replace_props(res, {"bucket_table": encode_variant(table.bucket_table, V_PACKED_INT32),
                               "strings": encode_variant(table.strings, V_PACKED_BYTE)})


# ── project.binary (ECFG) ───────────────────────────────────────────────────
def read_project_binary(data: bytes) -> Dict[str, Any]:
    """{ayar yolu: değer}; okunamayan türler atlanır (yalnızca gereken ayarlar okunur)."""
    if data[:4] != b"ECFG":
        raise GodotFormatError("project.binary değil")
    count = struct.unpack_from("<I", data, 4)[0]
    pos = 8
    out: Dict[str, Any] = {}
    for _ in range(count):
        n = struct.unpack_from("<I", data, pos)[0]
        key = data[pos + 4:pos + 4 + n].decode("utf-8")
        pos += 4 + n
        size = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        blob = data[pos:pos + size]
        pos += size
        try:
            out[key] = _decode_setting(blob)
        except (GodotFormatError, struct.error, UnicodeDecodeError):
            continue
    return out


def _decode_setting(blob: bytes) -> Any:
    """core/io/marshalls.cpp decode_variant'ın gereken alt kümesi: bool, int, String, dize dizisi."""
    header = struct.unpack_from("<I", blob, 0)[0]
    t = header & 0xFF
    if t == 1:
        return bool(struct.unpack_from("<I", blob, 4)[0])
    if t == 2:
        return struct.unpack_from("<q" if header & (1 << 16) else "<i", blob, 4)[0]
    if t in (4, 21):                               # String (3.x ve 4.x), StringName (4.x)
        n = struct.unpack_from("<I", blob, 4)[0]
        return blob[8:8 + n].decode("utf-8").rstrip("\0")
    if t in (34, 23):                              # PackedStringArray (4.x) / PoolStringArray (3.x)
        n = struct.unpack_from("<I", blob, 4)[0]
        pos, items = 8, []
        for _ in range(n):
            length = struct.unpack_from("<I", blob, pos)[0]
            items.append(blob[pos + 4:pos + 4 + length].decode("utf-8").rstrip("\0"))
            pos += 4 + length + (-length % 4)
        return items
    raise GodotFormatError(f"project.binary türü desteklenmiyor: {t}")
