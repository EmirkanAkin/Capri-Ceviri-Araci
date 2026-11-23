"""
Capri — WOLF RPG Editor veri dosyaları (harita .mps ve CommonEvent.dat)
======================================================================
Biçim, açık kaynak WolfTL'den (MIT, Sinflower) alınmıştır: WolfRPG/Map.hpp, Command.hpp, RouteCommand.hpp,
CommonEvents.hpp, FileCoder.hpp. Dosyalar sıralıdır ve dizeler uzunluk önekiyle saklanır; Capri dosyayı motorun
okuduğu sırayla gezer, çevrilecek dizelerin yerini kaydeder ve yazarken yalnızca bu dizeleri (uzunluklarıyla)
değiştirir. Yazılan her dosya yeniden çözümlenir; yapı tutmazsa dosyaya dokunulmaz.

2.x dosyaları Shift-JIS, 3.x dosyaları UTF-8'dir; 3.x'te gövde LZ4 ile sıkıştırılmıştır. Şifreli (Pro) dosyalar
okunmaz. Çevrilen komutlar: Mesaj (101), Seçenek (102), metin resmi (150). Dize değişkeni (122), dize karşılaştırma
(112) ve veritabanı (250) komutları oyun mantığında kullanılabildiği için çevrilmez.

Veritabanları (DataBase / CDataBase): .project dosyası alan adlarını ve alan türlerini, .dat dosyası değerleri tutar
(UberWolf Database.hpp). Yalnızca "dosya" türünde olmayan metin alanları çevrilir (eşya/beceri adları, açıklamalar,
savaş mesajları); dosya yolları, alan ve kayıt adları (olaylar kayıtlara adla başvurabilir) ve sistem veritabanı
(SysDatabase: değişken adları, müzik listeleri) olduğu gibi kalır.
"""
from __future__ import annotations

import re
import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import lz4.block as _lz4
except ImportError:  # pragma: no cover - UnityPy ile birlikte gelir
    _lz4 = None

MAP_MAGIC = bytes([0] * 10) + b"WOLFM\x00\x00\x00\x00\x00"
DB_TYPE_SEPARATOR = b"\xfe\xff\xff\xff"
DB_STRING_START, DB_UNKNOWN2 = 0x07D0, 0x0001D4C0
# Dosya yolu gibi görünen değerler (alan türü işaretlenmemiş olsa da) çevrilmez
_PATHLIKE = re.compile(r"^[\w ./\\()\-\[\]]+\.(png|jpe?g|bmp|gif|ogg|wav|mp3|mid|midi|mps|dat|txt|csv|ttf|otf|ico)"
                       r"(\r?\n.*)?$", re.I | re.S)
COMMON_MAGIC = b"W\x00\x00OL\x00FC\x00"
MESSAGE, CHOICES, PICTURE = 101, 102, 150


class WolfFormatError(ValueError):
    pass


@dataclass
class Slot:
    offset: int            # gövde içinde uzunluk önekinin konumu
    size: int              # önek dahil toplam bayt
    raw: bytes             # dizenin baytları (sondaki 0 dahil)
    text: str
    context: str           # dialogue | choice | ui


@dataclass
class WolfDoc:
    kind: str              # map | common
    header: bytes          # sıkıştırmanın dışında kalan baş kısım
    body: bytes            # (açılmış) gövde
    compressed: bool
    utf8: bool
    slots: List[Slot] = field(default_factory=list)
    encrypted: bool = False
    project: bytes = b""   # veritabanı: alan türlerini tutan .project dosyası
    total: int = -1        # çözümlemede bulunan dize sayısı (çağıran bazılarını çeviri dışı bırakabilir)


class _R:
    def __init__(self, data: bytes, utf8: bool, slots: Optional[List[Slot]] = None):
        self.d, self.p, self.utf8, self.slots = data, 0, utf8, slots

    def u8(self) -> int:
        if self.p >= len(self.d):
            raise WolfFormatError("dosya beklenenden kısa")
        v = self.d[self.p]
        self.p += 1
        return v

    def u32(self) -> int:
        if self.p + 4 > len(self.d):
            raise WolfFormatError("dosya beklenenden kısa")
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def skip(self, n: int) -> None:
        if self.p + n > len(self.d):
            raise WolfFormatError("dosya beklenenden kısa")
        self.p += n

    def expect(self, magic: bytes) -> None:
        if self.d[self.p:self.p + len(magic)] != magic:
            raise WolfFormatError(f"beklenmeyen bayt ({self.p:#x})")
        self.p += len(magic)

    def string(self, context: str = "", allow_empty: bool = False) -> str:
        start = self.p
        n = self.u32()
        if (n == 0 and not allow_empty) or self.p + n > len(self.d):
            raise WolfFormatError(f"geçersiz dize ({start:#x})")
        raw = self.d[self.p:self.p + n]
        self.p += n
        text = decode(raw, self.utf8)
        if context and self.slots is not None:
            self.slots.append(Slot(start, 4 + n, raw, text, context))
        return text


def decode(raw: bytes, utf8: bool) -> str:
    body = raw[:-1] if raw.endswith(b"\0") else raw
    return body.decode("utf-8" if utf8 else "cp932", errors="replace")


_FALLBACK = str.maketrans({"ı": "i", "İ": "I", "ğ": "g", "Ğ": "G", "ş": "s", "Ş": "S", "ç": "c", "Ç": "C",
                           "ö": "o", "Ö": "O", "ü": "u", "Ü": "U"})


def encode(text: str, utf8: bool, template: bytes) -> Tuple[bytes, bool]:
    """(bayt, kayıplı mı). Shift-JIS'e sığmayan harfler en yakın harfe indirilir (ğ → g, é → e)."""
    tail = b"\0" if template.endswith(b"\0") else b""
    if utf8:
        return text.encode("utf-8") + tail, False
    try:
        return text.encode("cp932") + tail, False
    except UnicodeEncodeError:
        simple = text.translate(_FALLBACK)
        simple = "".join(ch for ch in unicodedata.normalize("NFKD", simple) if not unicodedata.combining(ch))
        return simple.encode("cp932", errors="replace") + tail, True


# ── Komutlar ────────────────────────────────────────────────────────────────
def _route(r: _R) -> None:
    r.u8()
    for _ in range(r.u8()):
        r.u32()
    r.expect(b"\x01\x00")


def _command(r: _R, v35: bool) -> None:
    argc = r.u8() - 1
    code = r.u32()
    args = [r.u32() for _ in range(argc)]
    r.u8()                                         # girinti
    strings = r.u8()
    for i in range(strings):
        if code == MESSAGE and i == 0:
            ctx = "dialogue"
        elif code == CHOICES:
            ctx = "choice"
        elif code == PICTURE and i == 0 and args and (args[0] >> 4) & 0x07 == 2:
            ctx = "ui"
        else:
            ctx = ""
        r.string(ctx)
    terminator = r.u8()
    if terminator not in (0x00, 0x01):
        raise WolfFormatError(f"komut sonu beklenmedik ({terminator:#x})")
    if terminator == 0x01 or code == 201:          # Hareket komutu: ek veri + rota (WolfTL ile aynı kural)
        r.skip(5)
        r.u8()
        for _ in range(r.u32()):
            _route(r)
    if v35:
        r.skip(r.u8())


def _commands(r: _R, v35: bool) -> None:
    for _ in range(r.u32()):
        _command(r, v35)


# ── Harita ──────────────────────────────────────────────────────────────────
def _page(r: _R, v35: bool) -> None:
    r.u32()
    r.string()
    r.skip(4)
    r.skip(1 + 4 + 16 + 16)                         # koşullar
    r.skip(4)                                       # hareket
    r.u8()
    r.u8()
    for _ in range(r.u32()):
        _route(r)
    _commands(r, v35)
    features = r.u32()
    r.skip(3)
    if features > 3:
        r.u8()
    if r.u8() != 0x7A:
        raise WolfFormatError("sayfa sonu bulunamadı")


def _event(r: _R, v35: bool) -> None:
    r.expect(b"\x39\x30\x00\x00")
    r.u32()
    r.string()
    r.u32()
    r.u32()
    pages = r.u32()
    r.expect(b"\x00\x00\x00\x00")
    read = 0
    while True:
        indicator = r.u8()
        if indicator != 0x79:
            break
        _page(r, v35)
        read += 1
    if indicator != 0x70 or read != pages:
        raise WolfFormatError("olay yapısı tutmuyor")


def _map_body(r: _R, version: int) -> None:
    r.string()
    r.u32()                                         # karo seti
    width, height, events = r.u32(), r.u32(), r.u32()
    layers, v35 = 3, False
    if version >= 0x67:
        r.u32()
        layers = r.u32()
        v35 = True
    if r.p == len(r.d) - 1:
        if r.u8() != 0x66:
            raise WolfFormatError("harita sonu bulunamadı")
        return
    read_tiles = True
    if r.utf8:
        if struct.unpack_from("<i", r.d, r.p)[0] == -1:
            r.p += 4
            read_tiles = False
    if read_tiles:
        r.skip(width * height * layers * 4)
    count = 0
    while True:
        indicator = r.u8()
        if indicator != 0x6F:
            break
        _event(r, v35)
        count += 1
    if indicator != 0x66 or count != events or r.p != len(r.d):
        raise WolfFormatError("harita yapısı tutmuyor")


def _unpack(data: bytes, at: int) -> Tuple[bytes, bytes]:
    if _lz4 is None:
        raise WolfFormatError("LZ4 kitaplığı yok")
    dec, enc = struct.unpack_from("<II", data, at)
    if at + 8 + enc > len(data):
        raise WolfFormatError("sıkıştırılmış veri eksik")
    body = _lz4.decompress(data[at + 8:at + 8 + enc], uncompressed_size=dec)
    if len(body) != dec:
        raise WolfFormatError("açılan veri boyu tutmuyor")
    return data[:at], body


def _pack(body: bytes) -> bytes:
    packed = _lz4.compress(body, store_size=False)
    return struct.pack("<II", len(body), len(packed)) + packed


def parse_map(data: bytes) -> WolfDoc:
    if len(data) < 25 or data[:10] != MAP_MAGIC[:10] or data[10:15] != b"WOLFM":
        raise WolfFormatError("WOLF haritası değil")
    utf8 = data[16] == 0x55
    version = struct.unpack_from("<I", data, 20)[0]
    if version >= 0x65:
        header, body = _unpack(data, 25)
        compressed = True
    else:
        header, body, compressed = data[:25], data[25:], False
    doc = WolfDoc("map", header, body, compressed, utf8)
    r = _R(body, utf8, doc.slots)
    _map_body(r, version)
    return doc


# ── Ortak olaylar ───────────────────────────────────────────────────────────
def _common_event(r: _R, v35: bool) -> None:
    if r.u8() != 0x8E:
        raise WolfFormatError("ortak olay başı bulunamadı")
    r.u32()
    r.u32()
    r.skip(7)
    r.string()
    _commands(r, v35)
    r.string()
    r.string()
    if r.u8() != 0x8F:
        raise WolfFormatError("ortak olay yapısı tutmuyor")
    for _ in range(r.u32()):
        r.string()
    r.skip(r.u32())
    for _ in range(r.u32()):
        for _ in range(r.u32()):
            r.string()
    for _ in range(r.u32()):
        r.skip(4 * r.u32())
    r.skip(0x1D)
    for _ in range(100):
        r.string()
    if r.u8() != 0x91:
        raise WolfFormatError("ortak olay sonu bulunamadı")
    r.string()
    indicator = r.u8()
    if indicator == 0x91:
        return
    if indicator != 0x92:
        raise WolfFormatError("ortak olay sonu bulunamadı")
    r.string()
    r.u32()
    if r.u8() != 0x92:
        raise WolfFormatError("ortak olay sonu bulunamadı")


def parse_common_events(data: bytes) -> WolfDoc:
    if len(data) < 12 or data[0] != 0 or data[1:4] != b"W\x00\x00" or data[4:6] != b"OL" or data[7:10] != b"FC\x00":
        if len(data) > 5 and data[1] == 0x50:
            return WolfDoc("common", data, b"", False, True, encrypted=True)
        raise WolfFormatError("CommonEvent.dat değil")
    utf8 = data[6] == 0x55
    version = data[10]
    v35 = version in (0x93, 0xCC)
    if v35:
        header, body = _unpack(data, 11)
        compressed = True
    else:
        header, body, compressed = data[:11], data[11:], False
    doc = WolfDoc("common", header, body, compressed, utf8)
    r = _R(body, utf8, doc.slots)
    for _ in range(r.u32()):
        _common_event(r, v35)
    if r.u8() < 0x89 or r.p != len(body):
        raise WolfFormatError("CommonEvent.dat yapısı tutmuyor")
    return doc


# ── Veritabanı ──────────────────────────────────────────────────────────────
def _db_project(data: bytes, utf8: bool) -> List[Tuple[List[str], List[int]]]:
    """[(alan adları, alan türleri)] — tür 0: özel ayar yok; 1: dosya; 2: veritabanı başvurusu; 3: elle liste."""
    r = _R(data, utf8)
    types = []
    for _ in range(r.u32()):
        r.string(allow_empty=True)                               # tür adı
        fields = [r.string(allow_empty=True) for _ in range(r.u32())]
        for _ in range(r.u32()):
            r.string(allow_empty=True)                           # kayıt adları
        r.string(allow_empty=True)                               # açıklama
        listed = r.u32()
        if listed < len(fields):
            raise WolfFormatError("veritabanı alan listesi tutmuyor")
        kinds = [r.u8() for _ in fields]
        r.skip(listed - len(fields))
        for _ in range(r.u32()):
            r.string(allow_empty=True)
        for _ in range(r.u32()):
            for _ in range(r.u32()):
                r.string(allow_empty=True)
        for _ in range(r.u32()):
            r.skip(4 * r.u32())
        r.skip(4 * r.u32())
        types.append((fields, kinds))
    if r.p != len(data):
        raise WolfFormatError(".project yapısı tutmuyor")
    return types


def _db_context(text: str) -> str:
    return "dialogue" if "\n" in text or len(text) > 40 else "ui"


def parse_database(data: bytes, project: bytes) -> WolfDoc:
    if len(data) > 5 and data[1] == 0x50:
        return WolfDoc("db", data, b"", False, True, encrypted=True, project=project)
    if len(data) < 12 or data[1:4] != b"W\x00\x00" or data[4:6] != b"OL" or data[7:10] != b"FM\x00":
        raise WolfFormatError("veritabanı (.dat) değil")
    utf8 = data[6] == 0x55
    version = data[10]
    if version == 0xC4:
        header, body = _unpack(data, 11)
        compressed = True
    else:
        header, body, compressed = data[:11], data[11:], False
    types = _db_project(project, utf8)
    doc = WolfDoc("db", header, body, compressed, utf8, project=project)
    r = _R(body, utf8)
    if r.u32() != len(types):
        raise WolfFormatError("veritabanı tür sayısı .project ile tutmuyor")
    for fields, kinds in types:
        r.expect(DB_TYPE_SEPARATOR)
        marker = r.u32()
        count = r.u32()
        if marker >= DB_UNKNOWN2:                # 0x1D4C0, yeni sürümlerde 0x1FBD0: ardından bir dize gelir
            r.string(allow_empty=True)
        index = [r.u32() for _ in range(count)]
        strings = sorted((info - DB_STRING_START, k) for k, info in enumerate(index) if info >= DB_STRING_START)
        ints = sum(1 for info in index if info < DB_STRING_START)
        for _ in range(r.u32()):
            r.skip(4 * ints)
            for _slot, field_index in strings:
                start = r.p
                text = r.string(allow_empty=True)
                kind = kinds[field_index] if field_index < len(kinds) else 1
                if kind == 0 and text.strip() and not _PATHLIKE.match(text.strip()):
                    doc.slots.append(Slot(start, r.p - start, r.d[start + 4:r.p], text, _db_context(text)))
    if r.u8() != version or r.p != len(body):
        raise WolfFormatError("veritabanı yapısı tutmuyor")
    return doc


def parse(kind: str, data: bytes, project: bytes = b"") -> WolfDoc:
    if kind == "db":
        return parse_database(data, project)
    return parse_map(data) if kind == "map" else parse_common_events(data)


def rebuild(doc: WolfDoc, translations: Dict[str, str]) -> Tuple[Optional[bytes], int, int]:
    """(yeni dosya ya da değişiklik yoksa None, değişen dize, harf kaybı olan dize). Yazılan veri yeniden çözümlenir."""
    if doc.encrypted:
        return None, 0, 0
    out = bytearray()
    pos = changed = lossy = 0
    for slot in doc.slots:
        target = translations.get(slot.text)
        if not target or target == slot.text:
            continue
        raw, lost = encode(target, doc.utf8, slot.raw)
        out += doc.body[pos:slot.offset] + struct.pack("<I", len(raw)) + raw
        pos = slot.offset + slot.size
        changed += 1
        lossy += lost
    if not changed:
        return None, 0, 0
    out += doc.body[pos:]
    body = bytes(out)
    data = doc.header + (_pack(body) if doc.compressed else body)
    check = parse(doc.kind, data, doc.project)
    if len(check.slots) != (doc.total if doc.total >= 0 else len(doc.slots)):
        raise WolfFormatError("yazılan dosya doğrulanamadı")
    return data, changed, lossy


__all__ = ["WolfDoc", "Slot", "parse_map", "parse_common_events", "parse_database", "parse", "rebuild",
           "WolfFormatError", "decode", "encode"]
