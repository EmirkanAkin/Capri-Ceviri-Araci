"""
Capri — WOLF RPG Editor arşivleri (Data.wolf ve Data/*.wolf)
===========================================================
WOLF oyunları verilerini DxLib'in DXArchive biçiminde, sürüme göre değişen bir anahtarla şifrelenmiş arşivlerde
saklar. Biçim ve anahtarlar açık kaynak UberWolf / WolfDec'ten (MIT, Sinflower) ve DxLib'in DXArchive kaynağından
alınmıştır:

* WOLF 2.01 / 2.10 — DXArchive sürüm 5 (32 bit tablolar), 12 baytlık döngüsel XOR anahtarı
* WOLF 2.20       — DXArchive sürüm 6 (64 bit tablolar), aynı anahtar yapısı
* WOLF 2.225+     — DXArchive sürüm 8: dosya başına CRC32'den türetilen 7 baytlık anahtar, LZ + Huffman sıkıştırma
* WOLF 3.00/3.14  — sürüm 8, uzun anahtar dizesi
* WOLF 3.31/3.50  — sürüm 8 + ek şifreleme: adres karıştırma, değiştirilmiş AES-128-CTR ve 768 baytlık XOR anahtarı
* ChaCha20 (v1)   — sürüm 8, dosya verisi standart ChaCha20 ile

WOLF Pro (oyuna özel anahtar) arşivleri desteklenmez; kullanıcıya anlaşılır biçimde söylenir.

Çeviri için arşiv yanına açılır (Data.wolf → Data/, Data/BasicData.wolf → Data/BasicData/) ve arşiv
`_capri_backups/wolf_archive/` altına taşınır; WOLF, arşiv yoksa klasörü okur. `restore()` her şeyi geri alır.
"""
from __future__ import annotations

import heapq
import json
import shutil
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:  # pragma: no cover - exe ile birlikte gelir
    np = None

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]
BACKUP_DIR = "_capri_backups/wolf_archive"
MANIFEST = "_capri_backups/wolf_extract.json"
NONE64 = 0xFFFFFFFFFFFFFFFF
NONE32 = 0xFFFFFFFF
FILE_ATTRIBUTE_DIRECTORY = 0x10
DXA_FLAG_NO_KEY = 0x1
DXA_FLAG_NO_HEAD_PRESS = 0x2
DEFAULT_KEY = b"DXBDXARC"
# Arşivden doğrudan çıkarmaya karşı motorun veritabanı dosyalarının başına koyduğu not; dosya klasörden
# okunurken bu not olmamalı (UberWolf da aynı şekilde kaldırır).
ANTI_UNPACK = b"Extracting data from encrypted files violates the guidelines.\x00"
ANTI_UNPACK_FILES = ("game.dat", "cdatabase.dat", "database.dat", "commonevent.dat")

# (ad, DXArchive sürümü, şifre sürümü, anahtar)
KEYS: List[Tuple[str, int, int, bytes]] = [
    ("WOLF 2.01", 5, 0, bytes.fromhex("0f53e13e04371217600f53e1")),
    ("WOLF 2.10", 5, 0, bytes.fromhex("4cd92ab7289bac073e77ec4c")),
    ("WOLF 2.20", 6, 0, bytes.fromhex("38504028724f21703b733538")),
    ("WOLF 2.225", 8, 0, b"WLFRPrO!p(;s5((8P@((UFWlu$#5(="),
    ("WOLF 3.00", 8, 0x12C, bytes.fromhex("0f53e13e8eb54191521655ae34c98f79592f596b95199b1b359a2fdec97c1296c314b50f53e13e8e")),
    ("WOLF 3.14", 8, 0x13A, bytes.fromhex("31f90136a3e38d3c7bc37d25ad6328191bf78e6cc4e5e27682ea4fed61dae0445bb6463b06d5ceb67858d07c82")),
    ("WOLF 3.31", 8, 0x14B, bytes.fromhex("ca084c5d170ddaa1d727c8415438823254b7f9468e136bcad05c9595e2dc0353609b4a3817f36959a4c79a4363e654afdbbb4358")),
    ("WOLF 3.50", 8, 0x15E, bytes.fromhex("d284ce28ce8882e42a182e4c06b4ea8406b8c6885aa09e7c5640ba3452ccc67c2e141268fe5c769486788e4cbe88669c1ee08e6c")),
    ("WOLF ChaCha20", 8, 0x64, bytes.fromhex("c982f8b42c939e830ebcbc92688d59a14a9e7fb0acaf1d8f8eb83b9ee889d9adffbc2dab9d8b0fb4bb9a6985")),
    ("WOLF (özel anahtar A)", 8, 0, b"nGui9('&1=@3#a"),
    ("WOLF (özel anahtar B)", 8, 0, b"Ph=X3^]o2A(,1=@3#a"),
]


class WolfArchiveError(ValueError):
    pass


@dataclass
class Entry:
    path: str                  # arşiv içi yol, "/" ile
    data_offset: int           # dosyadaki mutlak konum
    size: int                  # açılmış boy
    press: int                 # LZ ile sıkıştırılmış boy (ya da -1)
    huff: int                  # Huffman ile sıkıştırılmış boy (ya da -1)
    key: Optional[bytes]       # 7 / 12 baytlık anahtar (ya da None)
    key_at: int = -1           # XOR anahtarının başladığı konum (-1: açılmış boy; DXArchive < 5'te dosya konumu)


@dataclass
class Archive:
    path: Path
    label: str
    version: int
    crypt_version: int
    entries: List[Entry] = field(default_factory=list)
    huff_kb: int = 0xFF
    source: Optional["_Source"] = None      # aralık okuyucu (dosya belleğe alınmaz)
    special_key: Optional[bytes] = None     # 768 baytlık XOR anahtarı (3.31+)
    chacha: bool = False
    data: Optional[bytes] = None            # (eski alan; kullanılmıyor)


class _Source:
    """Arşivden aralık okur. WOLF 3.31+ katmanları konuma bağlı XOR olduğundan her aralığa ayrı uygulanabilir: dosya
    gövdesine "other" XOR'u, baştaki ~1 KB ve sondaki tablolara (AES bölgeleri) önceden çözülmüş kopya yerleştirilir.
    Böylece birkaç GB'lık arşivde de bellek kullanımı en büyük tek dosya kadardır."""

    def __init__(self, path: Path, size: int):
        self.path, self.size = path, size
        self.other: Optional[bytes] = None
        self.cv = 0
        self.patches: List[Tuple[int, bytes]] = []

    def raw(self, at: int, n: int) -> bytes:
        with open(self.path, "rb") as f:
            f.seek(at)
            return f.read(n)

    def read(self, at: int, n: int) -> bytes:
        data = self.raw(at, n)
        end = at + len(data)
        if self.other is not None:
            lo, hi = max(at, 64), min(end, self.size - 64)
            if lo < hi:
                data = data[:lo - at] + wolf_crypt(self.other, data[lo - at:hi - at], lo, self.cv) + data[hi - at:]
        for start, blob in self.patches:
            lo, hi = max(at, start), min(end, start + len(blob))
            if lo < hi:
                data = data[:lo - at] + blob[lo - start:hi - start] + data[hi - at:]
        return data


# ── Küçük yardımcılar ──────────────────────────────────────────────────────
def _need_numpy() -> None:
    if np is None:
        raise WolfArchiveError("Bu arşivi açmak için numpy gerekli.")


class _MsRand:
    """MSVC rand() (WolfCrypt'in kullandığı)."""

    def __init__(self, seed: int):
        self.x = seed & 0xFFFFFFFF

    def __call__(self) -> int:
        self.x = (self.x * 214013 + 2531011) & 0xFFFFFFFF
        return (self.x >> 16) & 0x7FFF


class _XorShift:
    def __init__(self, seed: int):
        self.s = seed & 0xFFFFFFFF

    def __call__(self) -> int:
        s = self.s
        s ^= (s << 11) & 0xFFFFFFFF
        s ^= s >> 19
        s ^= (s << 7) & 0xFFFFFFFF
        self.s = s
        return s


def _rotr8(v: int, n: int) -> int:
    return ((v >> n) | (v << (8 - n))) & 0xFF


def _cstr(b: bytes) -> bytes:
    i = b.find(b"\0")
    return b if i < 0 else b[:i]


def _is_v35(cv: int) -> bool:
    return (0x15E <= cv < 0x3E8) or cv >= 0x3FC


def _new_crypt(cv: int) -> bool:
    return 331 <= cv < 1000 or cv >= 1010


def _xor_repeat(data: bytes, key: bytes, position: int) -> bytes:
    """data ^ key[(position + i) % len(key)]."""
    if not data:
        return b""
    n, k = len(data), len(key)
    start = position % k
    rot = key[start:] + key[:start]
    stream = (rot * (n // k + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(n, "little")


# ── DxLib anahtarları ──────────────────────────────────────────────────────
def key_create_v8(source: bytes) -> bytes:
    """DXArchive 8 anahtarı: çift ve tek konumdaki baytların CRC32'si (7 bayt)."""
    if len(source) < 4:
        source = source + DEFAULT_KEY
    c0 = zlib.crc32(source[0::2]) & 0xFFFFFFFF
    c1 = zlib.crc32(source[1::2]) & 0xFFFFFFFF
    return struct.pack("<I", c0) + struct.pack("<I", c1)[:3]


def key_create_v6(source: Optional[bytes]) -> bytes:
    """DXArchive 5/6 anahtarı (12 bayt)."""
    if source is None:
        key = bytearray(b"\xaa" * 12)
    else:
        source = _cstr(source)
        if len(source) > 12:
            key = bytearray(source[:12])
        else:
            key = bytearray((source * (12 // len(source) + 1))[:12])
    key[0] = ~key[0] & 0xFF
    key[1] = ((key[1] >> 4) | (key[1] << 4)) & 0xFF
    key[2] ^= 0x8A
    key[3] = ~((key[3] >> 4) | (key[3] << 4)) & 0xFF
    key[4] = ~key[4] & 0xFF
    key[5] ^= 0xAC
    key[6] = ~key[6] & 0xFF
    key[7] = ~((key[7] >> 3) | (key[7] << 5)) & 0xFF
    key[8] = ((key[8] >> 5) | (key[8] << 3)) & 0xFF
    key[9] ^= 0x7F
    key[10] = (((key[10] >> 4) | (key[10] << 4)) & 0xFF) ^ 0xD6
    key[11] ^= 0xCC
    return bytes(key)


# ── Sıkıştırma ─────────────────────────────────────────────────────────────
def lz_decode(src: bytes) -> bytes:
    """DxLib LZ açıcı."""
    try:
        return _lz_decode(src)
    except IndexError:
        raise WolfArchiveError("bozuk LZ verisi") from None


def _lz_decode(src: bytes) -> bytes:
    if len(src) < 9:
        raise WolfArchiveError("sıkıştırılmış veri kısa")
    dest_size, packed = struct.unpack_from("<II", src, 0)
    end = min(len(src), packed)
    key = src[8]
    keyb = bytes([key])
    out = bytearray()
    sp = 9
    find = src.find
    while sp < end:
        k = find(keyb, sp, end)
        if k < 0:
            out += src[sp:end]
            break
        if k > sp:
            out += src[sp:k]
        b1 = src[k + 1]
        if b1 == key:
            out.append(key)
            sp = k + 2
            continue
        code = b1 - 1 if b1 > key else b1
        sp = k + 2
        length = code >> 3
        if code & 4:
            length |= src[sp] << 5
            sp += 1
        length += 4
        size = code & 3
        if size == 0:
            index = src[sp]
            sp += 1
        elif size == 1:
            index = src[sp] | (src[sp + 1] << 8)
            sp += 2
        else:
            index = src[sp] | (src[sp + 1] << 8) | (src[sp + 2] << 16)
            sp += 3
        index += 1
        start = len(out) - index
        if start < 0:
            raise WolfArchiveError("bozuk LZ verisi")
        if index >= length:
            out += out[start:start + length]
        else:
            chunk = bytes(out[start:])
            out += (chunk * (length // index + 1))[:length]
    if len(out) != dest_size:
        raise WolfArchiveError("açılan veri boyu tutmuyor")
    return bytes(out)


class _BitsMSB:
    def __init__(self, data: bytes):
        self.d, self.pos = data, 0

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


TABLE_BITS = 11


def huffman_decode(src: bytes) -> bytes:
    """DxLib Huffman açıcı (ağaç, sıkıştırıcıyla aynı eşitlik kuralıyla kurulur)."""
    try:
        return _huffman_decode(src)
    except IndexError:
        raise WolfArchiveError("bozuk Huffman verisi") from None


def _huffman_decode(src: bytes) -> bytes:
    bits = _BitsMSB(src)
    original = bits.read(bits.read(6) + 1)
    bits.read(bits.read(6) + 1)                      # sıkıştırılmış boy
    weights = []
    prev = 0
    for i in range(256):
        nbits = (bits.read(3) + 1) * 2
        minus = bits.read(1)
        val = bits.read(nbits)
        prev = val if i == 0 else ((prev - val) if minus else (prev + val)) & 0xFFFF
        weights.append(prev)
    head = (bits.pos + 7) >> 3
    # Ağaç: her adımda (ağırlık, sıra) olarak en küçük iki düğüm birleşir; 0. çocuk en küçüğü
    child0 = [-1] * 511
    child1 = [-1] * 511
    heap = [(w, i) for i, w in enumerate(weights)]
    heapq.heapify(heap)
    node = 256
    while len(heap) > 1:
        w1, a = heapq.heappop(heap)
        w2, b = heapq.heappop(heap)
        child0[node], child1[node] = a, b
        heapq.heappush(heap, (w1 + w2, node))
        node += 1
    root = node - 1
    # TABLE_BITS bitlik arama tablosu: (sembol ya da düğüm, tüketilen bit)
    size = 1 << TABLE_BITS
    t_sym = [0] * size
    t_len = [0] * size
    for prefix in range(size):
        n, used = root, 0
        while n > 255 and used < TABLE_BITS:
            n = child1[n] if (prefix >> used) & 1 else child0[n]
            used += 1
        t_sym[prefix], t_len[prefix] = n, used
    data = src[head:]
    out = bytearray(original)
    acc = 0
    nacc = 0
    pos = 0
    total = len(data)
    mask = size - 1
    for i in range(original):
        if nacc < 64:                                # kodlar 64 bitten kısa (ağırlıklar 16 bit)
            acc |= int.from_bytes(data[pos:pos + 8], "little") << nacc
            nacc += 64
            pos += 8
        idx = acc & mask
        n = t_sym[idx]
        used = t_len[idx]
        acc >>= used
        nacc -= used
        while n > 255:
            n = child1[n] if acc & 1 else child0[n]
            acc >>= 1
            nacc -= 1
        out[i] = n
    if pos * 8 - nacc > total * 8:
        raise WolfArchiveError("bozuk Huffman verisi")
    return bytes(out)


# ── WOLF 3.31+ ek şifreleme ────────────────────────────────────────────────
def _calc_salt(s: bytes) -> bytes:
    s = _cstr(s)
    return bytes(((i // len(s)) + s[i % len(s)]) & 0xFF for i in range(128))


def init_wolf_crypt(cv: int, pw: bytes, key2: Optional[bytes] = None, other: bool = False,
                    key_string: bytes = b"") -> bytes:
    """WolfCrypt::initWolfCrypt — 768 baytlık XOR anahtarı."""
    s0, s1, s2, s3 = pw[2], pw[5], pw[12], 0
    if not other:
        for i in range(pw[11] // 3):
            s3 = (i ^ _rotr8(s3 ^ pw[i % 15], 3)) & 0xFF
    else:
        for i in range(pw[8] // 4):
            s3 = (i ^ _rotr8(s3 ^ pw[i % 15], 2)) & 0xFF
    rand = _MsRand(s0 * s1 + s2 + s3)
    fac = [0, 0, 0]
    fac[s3 % 3] = rand() % 256
    if not other and _is_v35(cv):
        fac[1] = rand() % 0xFB
    key = bytearray(768)
    for i in range(256):
        rn = rand()
        key[i] = (fac[0] ^ (rand() & 0xFF)) & 0xFF
        key[i + 256] = (fac[1] ^ (rn >> 8)) & 0xFF
        key[i + 512] = (fac[2] ^ rn) & 0xFF
    if key2:
        for j in range(128):
            rn = rand()
            key[j] ^= (s3 ^ key2[2] ^ (rn >> 8)) & 0xFF
            key[j + 256] ^= (s3 ^ key2[0] ^ rn) & 0xFF
    if other:
        salt = _calc_salt(b"958" if cv == 0x15E else key_string)
        mod = 7
        if _is_v35(cv):
            s3 = (s3 + 0x22) & 0xFF
            mod = 16
        for i in range(3):
            t = s3
            for j in range(256):
                skip = False
                cs, cs2 = salt[j & 0x7F], salt[(j + i) % 0x80]
                ck = key[i * 256 + j]
                sxk = cs ^ ck
                rnd = ((cs2 | (cs << 8)) % mod) & 0xFF
                nk = sxk
                if rnd == 1:
                    if cs2 % 0xB == 0:
                        nk = ck
                elif rnd == 2:
                    if cs % 0x1D == 0:
                        nk = ~sxk & 0xFF
                elif rnd == 3:
                    if (rnd + j) % 0x25 == 0:
                        nk = cs2 ^ sxk
                elif rnd == 4:
                    if (cs + cs2) % 97 == 0:
                        nk = (cs + sxk) & 0xFF
                elif rnd == 5:
                    if (j * rnd) % 0x7B == 0:
                        nk = (sxk ^ t) & 0xFF
                elif rnd == 6:
                    if cs == 0xFF and cs2 == 0:
                        nk, skip = 0, True
                elif rnd == 7:
                    if not (cv < 0x154 or 0x3E8 < cv < 0x3FC):
                        if (rnd + j) % 0x33 == 0 or cv >= 0x3FC:
                            nk ^= cs
                elif rnd == 8:
                    if not (cv < 0x154 or 0x3E8 < cv < 0x3FC):
                        if cs % 0x1D == 0 or cv >= 0x3FC:
                            nk ^= cs
                if (j + i) % (cs % 5 + 1) == 0:
                    nk = (nk ^ t) & 0xFF
                elif skip:
                    nk = ~sxk & 0xFF
                key[i * 256 + j] = nk & 0xFF
                t += i
    return bytes(key)


def wolf_crypt(key: bytes, data: bytes, position: int, cv: int) -> bytes:
    """WolfCrypt::wolfCrypt — konuma bağlı 2/3 katmanlı XOR (çözme ve şifreleme aynı)."""
    if not data:
        return b""
    _need_numpy()
    k = np.frombuffer(key, dtype=np.uint8)
    arr = np.frombuffer(data, dtype=np.uint8).copy()
    if _is_v35(cv):
        idx = np.arange(512)
        mk = (k[idx % 256] ^ ((7 * idx) & 0xFF)).astype(np.uint8)
    step = 1 << 22
    for s in range(0, len(arr), step):
        pos = np.arange(position + s, position + min(len(arr), s + step), dtype=np.int64)
        if _is_v35(cv):
            arr[s:s + len(pos)] ^= mk[pos & 255] ^ mk[256 + ((pos >> 8) & 255)]
        else:
            arr[s:s + len(pos)] ^= k[pos & 255] ^ k[256 + ((pos >> 8) & 255)] ^ k[512 + ((pos >> 16) & 255)]
    return arr.tobytes()


def crypt_addresses(head: bytearray, pw: bytes, cv: int) -> None:
    """Başlıktaki tablo adreslerinin karıştırmasını çözer (yerinde)."""
    if _is_v35(cv):
        rand = _MsRand(0xC + pw[9] * pw[10] + pw[3])
        off = 8
        for _ in range(2):
            for j in (3, 2, 1, 0):
                v = struct.unpack_from("<H", head, off + 2 * j)[0] ^ (rand() & 0xFFFF)
                struct.pack_into("<H", head, off + 2 * j, v)
            off += 8
        r0 = rand() << 17
        r1 = rand() << 31
        v0 = ((r0 & 0xFFFFFFFF) | (r1 & 0xFFFFFFFF) | rand()) & 0xFFFFFFFF
        v1 = ((r0 >> 32) | (r1 >> 32)) & 0xFFFFFFFF
        a, b = struct.unpack_from("<II", head, off)
        struct.pack_into("<II", head, off, a ^ v0, b ^ v1)
        off += 8
        for j in (3, 2, 1, 0):
            v = struct.unpack_from("<H", head, off + 2 * j)[0] ^ (rand() & 0xFFFF)
            struct.pack_into("<H", head, off + 2 * j, v)
    else:
        rand = _MsRand(pw[0] + pw[7] * pw[12])
        off = 8
        for _ in range(4):
            for j in (3, 2, 1, 0):
                v = struct.unpack_from("<H", head, off + 2 * j)[0] ^ (rand() & 0xFFFF)
                struct.pack_into("<H", head, off + 2 * j, v)
            off += 8


_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b27509832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cfd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdbe0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9ee1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_RCON = (0x8D, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(x: int) -> int:
    return ((x << 1) ^ (0x1B if x & 0x80 else 0)) & 0xFF


def _key_expansion(key: bytes) -> bytes:
    """WOLF'un değiştirilmiş AES-128 anahtar genişletmesi."""
    rk = bytearray(176)
    rk[:16] = key
    for i in range(4, 44):
        t = list(rk[(i - 1) * 4:(i - 1) * 4 + 4])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[t[0]] ^ _RCON[i // 4], _SBOX[t[1]] >> 4, ~_SBOX[t[2]] & 0xFF,
                 ((_SBOX[t[3]] >> 7) | (_SBOX[t[3]] << 1)) & 0xFF]
        for n in range(4):
            rk[i * 4 + n] = rk[(i - 4) * 4 + n] ^ t[n]
    return bytes(rk)


def init_aes128(pw: bytes, pro_key: Optional[bytes], cv: int) -> Tuple[bytes, bytearray]:
    """(genişletilmiş anahtar, IV)."""
    pk = pro_key or b"\0\0\0\0"
    key = bytearray(16)
    iv = bytearray(16)
    if _is_v35(cv):
        for i in range(15):
            e = pk[i % 4]
            ik = ((i * (e % 5 + 7)) ^ (3 * pw[i])) % 15
            iv_i = ((i * ((pk[(i + 1) % 4] % 7) + 0xB)) ^ (5 * pw[(i + 3) % 15])) % 15
            key[i] ^= (((i ^ e) + (pw[ik] << (i % 3))) % 0xFB) & 0xFF
            iv[i] ^= (((pw[iv_i] >> (i % 2)) + ((i * i) ^ pk[(i + 2) % 4])) % 0xF6) & 0xFF
            key[15] ^= (7 * (pw[i] + ((i + 1) ^ e)) % 0xFD) & 0xFF
            iv[15] ^= (11 * ((pw[i] - ((i * 2) ^ pk[(i + 2) % 4])) & 0xFFFF) % 0x100) & 0xFF
    elif cv == 0x3F2:
        for i in range(15):
            key[i] ^= ((pw[(i * 7) % 15] + pk[i & 3]) * i * i) & 0xFF
            iv[i] ^= ((pw[(i * 11) % 15] + pk[(i + 2) % 4]) - i * i) & 0xFF
            key[15] ^= ((i * 3) + pw[i] + pk[i & 3]) & 0xFF
            iv[15] ^= ((i * 5) + pw[i] + pk[(i + 2) % 4]) & 0xFF
    else:
        for i in range(15):
            key[i] ^= (pw[(i * 7) % 15] + i * i) & 0xFF
            iv[i] ^= (pw[(i * 11) % 15] - i * i) & 0xFF
            key[15] ^= (pw[i] + i * 3) & 0xFF
            iv[15] ^= (pw[i] + i * 5) & 0xFF
    key[0] ^= pk[0]
    iv[10] ^= pk[0]
    key[4] ^= pk[1]
    iv[1] ^= pk[1]
    key[8] ^= pk[2]
    iv[4] ^= pk[2]
    key[12] ^= pk[3]
    iv[7] ^= pk[3]
    return _key_expansion(bytes(key)), iv


def _aes_block(state: bytearray, rk: bytes) -> bytes:
    s = bytearray(a ^ b for a, b in zip(state, rk[:16]))
    for rnd in range(1, 11):
        s = bytearray(_SBOX[x] for x in s)
        s = bytearray((s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
                       s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]))
        if rnd != 10:
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c:c + 4]
                tmp = a0 ^ a1 ^ a2 ^ a3
                s[c] = a0 ^ tmp ^ _xtime(a0 ^ a1)
                s[c + 1] = a1 ^ tmp ^ _xtime(a1 ^ a2)
                s[c + 2] = a2 ^ tmp ^ _xtime(a2 ^ a3)
                s[c + 3] = a3 ^ tmp ^ _xtime(a3 ^ a0)
        s = bytearray(a ^ b for a, b in zip(s, rk[rnd * 16:rnd * 16 + 16]))
    return bytes(s)


def aes_ctr(data: bytearray, offset: int, size: int, rk: bytes, iv: bytearray) -> None:
    """Yerinde AES-CTR; IV sayacı çağrılar arasında sürer (motor ikinci bölgeyi aynı sayaçla çözer)."""
    stream = bytearray()
    while len(stream) < size:
        stream += _aes_block(iv, rk)
        for bi in range(15, -1, -1):
            if iv[bi] == 0xFF:
                iv[bi] = 0
                continue
            iv[bi] += 1
            break
    end = offset + size
    data[offset:end] = (int.from_bytes(data[offset:end], "little")
                        ^ int.from_bytes(bytes(stream[:size]), "little")).to_bytes(size, "little")


# ── ChaCha20 (RFC 7539, sayaç 1'den) ───────────────────────────────────────
def _chacha_blocks(key: bytes, nonce: bytes, first: int, count: int) -> bytes:
    _need_numpy()
    st = np.zeros((count, 16), dtype=np.uint32)
    st[:, 0:4] = np.frombuffer(b"expand 32-byte k", dtype="<u4")
    st[:, 4:12] = np.frombuffer(key, dtype="<u4")
    ctr = np.arange(first, first + count, dtype=np.uint64)
    st[:, 12] = (ctr & 0xFFFFFFFF).astype(np.uint32)
    nn = np.frombuffer(nonce, dtype="<u4").astype(np.uint64)
    st[:, 13] = ((nn[0] + (ctr >> 32)) & 0xFFFFFFFF).astype(np.uint32)
    st[:, 14] = nn[1]
    st[:, 15] = nn[2]
    x = st.copy()

    def rotl(v, n):
        return (v << np.uint32(n)) | (v >> np.uint32(32 - n))

    def qr(a, b, c, d):
        x[:, a] += x[:, b]; x[:, d] = rotl(x[:, d] ^ x[:, a], 16)
        x[:, c] += x[:, d]; x[:, b] = rotl(x[:, b] ^ x[:, c], 12)
        x[:, a] += x[:, b]; x[:, d] = rotl(x[:, d] ^ x[:, a], 8)
        x[:, c] += x[:, d]; x[:, b] = rotl(x[:, b] ^ x[:, c], 7)

    with np.errstate(over="ignore"):
        for _ in range(10):
            qr(0, 4, 8, 12); qr(1, 5, 9, 13); qr(2, 6, 10, 14); qr(3, 7, 11, 15)
            qr(0, 5, 10, 15); qr(1, 6, 11, 12); qr(2, 7, 8, 13); qr(3, 4, 9, 14)
        x += st
    return x.astype("<u4").tobytes()


def chacha20_xor(data: bytes, key: bytes, nonce: bytes, position: int, counter0: int = 1) -> bytes:
    if not data:
        return b""
    first = counter0 + position // 64
    skip = position % 64
    blocks = (skip + len(data) + 63) // 64
    out = bytearray()
    for b in range(0, blocks, 1 << 15):
        out += _chacha_blocks(key, nonce, first + b, min(1 << 15, blocks - b))
    stream = bytes(out[skip:skip + len(data)])
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(data), "little")


# ── Arşiv okuma ────────────────────────────────────────────────────────────
def _name(table: bytes, address: int, utf8: bool) -> Tuple[str, bytes]:
    """(özgün ad, anahtar için büyük harfli ad)."""
    packs = struct.unpack_from("<H", table, address)[0]
    upper = _cstr(table[address + 4:address + 4 + packs * 4])
    original = _cstr(table[address + 4 + packs * 4:address + 4 + packs * 8])
    return original.decode("utf-8" if utf8 else "cp932", errors="replace"), upper


class _Reader:
    """DXArchive sürüm 5/6/8 tablolarını gezer."""

    def __init__(self, version: int, table: bytes, file_off: int, dir_off: int, utf8: bool):
        self.v, self.t, self.fo, self.do, self.utf8 = version, table, file_off, dir_off, utf8
        if version >= 6:
            self.fh_size = 72 if version >= 8 else 64
            self.none = NONE64
        else:
            self.fh_size = 44 if version >= 2 else 40
            self.none = NONE32

    def dir(self, address: int) -> Tuple[int, int, int, int]:
        if self.v >= 6:
            return struct.unpack_from("<4Q", self.t, self.do + address)
        return struct.unpack_from("<4I", self.t, self.do + address)

    def file(self, address: int) -> Tuple[int, int, int, int, int, int]:
        """(ad adresi, öznitelik, veri adresi, boy, LZ boyu, Huffman boyu)"""
        p = self.fo + address
        if self.v >= 8:
            name, attr, _c, _a, _w, data, size, press, huff = struct.unpack_from("<9Q", self.t, p)
        elif self.v >= 6:
            name, attr, _c, _a, _w, data, size, press = struct.unpack_from("<8Q", self.t, p)
            huff = NONE64
        else:
            name, attr = struct.unpack_from("<II", self.t, p)
            data, size = struct.unpack_from("<II", self.t, p + 32)
            press = struct.unpack_from("<I", self.t, p + 40)[0] if self.v >= 2 else NONE32
            huff = NONE32
        return name, attr, data, size, press, huff

    def walk(self, dir_address: int, prefix: str, parents: List[bytes], visit) -> None:
        own, parent, count, heads = self.dir(dir_address)
        if count > 1_000_000:
            raise WolfArchiveError("dosya tablosu bozuk")
        for i in range(count):
            name_addr, attr, data, size, press, huff = self.file(heads + i * self.fh_size)
            name, upper = _name(self.t, name_addr, self.utf8)
            if not name or "/" in name or "\\" in name or name in (".", ".."):
                raise WolfArchiveError("geçersiz dosya adı")
            if attr & FILE_ATTRIBUTE_DIRECTORY:
                self.walk(data, f"{prefix}{name}/", [upper] + parents, visit)
            else:
                visit(f"{prefix}{name}", upper, parents, data, size, press, huff)


def _valid_head_v8(head: bytes, size: int) -> bool:
    _h, _v, head_size, data_start, names, files, dirs = struct.unpack_from("<HHIQQQQ", head, 0)
    return 0 < head_size < size * 64 and 64 <= data_start <= size and 64 <= names <= size and files < head_size \
        and dirs < head_size


def open_archive(path: Path) -> Archive:
    """Arşivin anahtarını bulur ve dosya listesini çıkarır. Desteklenmeyen arşivde WolfArchiveError."""
    path = Path(path)
    src = _Source(path, path.stat().st_size)
    raw = src.raw(0, 64)
    if len(raw) < 64:
        raise WolfArchiveError("arşiv çok kısa")
    if raw[:2] == b"DX":
        version = struct.unpack_from("<H", raw, 2)[0]
        if version != 8:
            raise WolfArchiveError(f"desteklenmeyen DXArchive sürümü ({version})")
        return _open_v8(path, src, raw)
    for label, version, _cv, key in KEYS:
        if version not in (5, 6):
            continue
        k = key_create_v6(key)
        head = _xor_repeat(raw[:48], k, 0)
        found = struct.unpack_from("<H", head, 2)[0]
        if head[:2] == b"DX" and (found == version or (version == 5 and 1 <= found < 5)):
            version = found
            try:
                return _open_v56(path, src, raw, label, version, k)
            except (WolfArchiveError, struct.error, IndexError, UnicodeDecodeError):
                continue
    raise WolfArchiveError("şifre çözülemedi (WOLF Pro ya da bilinmeyen anahtar)")


def _open_v56(path: Path, src: "_Source", raw: bytes, label: str, version: int, key: bytes) -> Archive:
    if version == 6:
        _h, _v, head_size, data_start, names, files, dirs, codepage = struct.unpack("<HHIQQQQQ", _xor_repeat(raw[:48], key, 0))
    else:
        _h, _v, head_size, data_start, names, files, dirs, codepage = struct.unpack("<HHIIIIII", _xor_repeat(raw[:28], key, 0))
        if version < 4:
            codepage = 932                       # sürüm 3 başlığında kod sayfası yok
    if not (0 < head_size and names + head_size <= src.size):
        raise WolfArchiveError("başlık tutmuyor")
    # DXArchive 5 öncesinde anahtar dosyadaki mutlak konumdan ilerler
    table = _xor_repeat(src.raw(names, head_size), key, 0 if version >= 5 else names)
    arc = Archive(path, label, version, 0, source=src)
    reader = _Reader(version, table, files, dirs, codepage == 65001)

    def visit(rel, _upper, _parents, data, size, press, huff):
        none = reader.none
        at = data_start + data
        arc.entries.append(Entry(rel, at, size, -1 if press == none else press, -1, key, -1 if version >= 5 else at))

    reader.walk(0, "", [], visit)
    return arc


def _open_v8(path: Path, src: "_Source", raw: bytes) -> Archive:
    head = bytearray(raw[:64])
    flags = struct.unpack_from("<I", head, 44)[0]
    cv = flags >> 16
    if cv >= 1000 or cv == 0xC8:
        raise WolfArchiveError("WOLF Pro arşivi (oyuna özel anahtar) desteklenmiyor")
    candidates = [k for k in KEYS if k[1] == 8 and k[2] == cv]
    if not candidates:
        raise WolfArchiveError(f"bilinmeyen WOLF şifre sürümü ({cv:#x})")
    last_error: Optional[Exception] = None
    for label, _version, _cv, key_string in candidates:
        try:
            return _open_v8_with(path, src, bytes(head), label, cv, _cstr(key_string)[:63])
        except (WolfArchiveError, struct.error, IndexError, ValueError) as exc:
            last_error = exc
    raise WolfArchiveError(f"şifre çözülemedi ({last_error})")


def _open_v8_with(path: Path, src0: "_Source", head0: bytes, label: str, cv: int, key_string: bytes) -> Archive:
    head = bytearray(head0)
    src = _Source(path, src0.size)
    arc = Archive(path, label, 8, cv, source=src)
    size = src.size
    if _new_crypt(cv):
        pw = bytes(head[49:64])
        crypt_addresses(head, pw, cv)
        if size - 64 < 0x400:
            raise WolfArchiveError("arşiv çok kısa")
        src.other = init_wolf_crypt(cv, pw, other=True, key_string=key_string)
        src.cv = cv
        rk, iv = init_aes128(pw, None, cv)
        body = 0x400
        if _is_v35(cv):
            seed = pw[2] * pw[4] + pw[12] or 1
            xs = _XorShift(seed)
            xs()
            if size >= xs() % 500 + 800:
                xs()
            body = size - 64
            if body >= xs() % 500 + 800:
                body = xs() % 500 + 800
        names = struct.unpack_from("<Q", head, 16)[0]
        if not 64 + body <= names <= size:
            raise WolfArchiveError("başlık tutmuyor")
        first = bytearray(src.read(64, body))           # "other" XOR uygulanmış
        aes_ctr(first, 0, body, rk, iv)
        last = bytearray(src.read(names, size - names))
        aes_ctr(last, 0, size - names, rk, iv)          # sayaç ilk bölgeden sürer
        src.patches = [(0, bytes(head) + bytes(first)), (names, bytes(last))]
        arc.special_key = init_wolf_crypt(cv, pw)
    arc.chacha = cv == 0x64
    _h, _v, head_size, data_start, names, files, dirs, charcode, flags, huff_kb = struct.unpack_from("<HHIQQQQIIB", head, 0)
    if not _valid_head_v8(bytes(head), size):
        raise WolfArchiveError("başlık tutmuyor")
    arc.huff_kb = huff_kb
    no_key = bool(flags & DXA_FLAG_NO_KEY)
    key = None if no_key else key_create_v8(key_string)
    conv = _Conv(arc, key_string)
    if flags & DXA_FLAG_NO_HEAD_PRESS:
        table = conv(src.read(64, head_size), key, 0)
    else:
        table = lz_decode(huffman_decode(conv(src.read(names, size - names), key, 0)))
    if len(table) != head_size:
        raise WolfArchiveError("başlık tablosu boyu tutmuyor")
    reader = _Reader(8, table, files, dirs, charcode == 65001)

    def visit(rel, upper, parents, addr, size, press, huff):
        file_key = None
        if not no_key:
            file_key = key_create_v8(key_string + upper + b"".join(parents))
        arc.entries.append(Entry(rel, data_start + addr, size, -1 if press == NONE64 else press,
                                 -1 if huff == NONE64 else huff, file_key))

    reader.walk(0, "", [], visit)
    return arc


class _Conv:
    """DXArchive::KeyConv — sürüme göre doğru XOR'u uygular."""

    def __init__(self, arc: Archive, key_string: bytes = b""):
        self.arc = arc
        self.cc_key = key_string[:32]
        self.cc_nonce = key_string[32:44]

    def __call__(self, data: bytes, key: Optional[bytes], position: int) -> bytes:
        if key is None:
            return bytes(data)
        if self.arc.special_key is not None:
            return wolf_crypt(self.arc.special_key, data, position, self.arc.crypt_version)
        if self.arc.chacha:
            return chacha20_xor(data, self.cc_key, self.cc_nonce, position)
        return _xor_repeat(data, key, position)


def read_entry(arc: Archive, entry: Entry) -> bytes:
    """Bir dosyayı açar (motorun yaptığı gibi; veritabanı dosyalarındaki çıkarma notu kaldırılır)."""
    src = arc.source or _Source(arc.path, arc.path.stat().st_size)
    if arc.version < 8:
        key = entry.key
        at = entry.size if entry.key_at < 0 else entry.key_at
        stored = src.read(entry.data_offset, entry.press if entry.press >= 0 else entry.size)
        out = lz_decode(_xor_repeat(stored, key, at)) if entry.press >= 0 else _xor_repeat(stored, key, at)
    else:
        out = _read_v8(arc, entry, src)
    if len(out) != entry.size:
        raise WolfArchiveError(f"{entry.path}: boy tutmuyor")
    if entry.path.lower().endswith(ANTI_UNPACK_FILES) and out.startswith(ANTI_UNPACK):
        out = out[len(ANTI_UNPACK):]
    return out


def _read_v8(arc: Archive, e: Entry, src: "_Source") -> bytes:
    conv = _Conv(arc, _key_string_for(arc))
    at = e.data_offset
    if e.size == 0:
        return b""
    body = e.press if e.press >= 0 else e.size
    kb = arc.huff_kb * 1024
    if e.huff >= 0:
        huff = huffman_decode(conv(src.read(at, e.huff), e.key, e.size))
        if arc.huff_kb != 0xFF and body > kb * 2:
            middle = conv(src.read(at + e.huff, body - kb * 2), e.key, e.size + e.huff)
            stored = huff[:kb] + middle + huff[kb:kb * 2]
        else:
            stored = huff
    else:
        stored = conv(src.read(at, body), e.key, e.size)
    if len(stored) != body:
        raise WolfArchiveError(f"{e.path}: sıkıştırılmış boy tutmuyor")
    return lz_decode(stored) if e.press >= 0 else stored


def _key_string_for(arc: Archive) -> bytes:
    for label, _v, _cv, key in KEYS:
        if label == arc.label:
            return _cstr(key)[:63]
    return b""


# ── Oyun klasörü ───────────────────────────────────────────────────────────
def find_archives(game_root: Path) -> List[Path]:
    root = Path(game_root)
    out = [p for p in root.glob("*.wolf") if p.is_file()]
    data = root / "Data"
    if data.is_dir():
        out += [p for p in data.glob("*.wolf") if p.is_file()]
    return sorted(out)


def _target_dir(root: Path, archive: Path) -> Path:
    return archive.parent / archive.stem


def _safe_target(base: Path, rel: str) -> Optional[Path]:
    target = (base / rel).resolve()
    return target if base.resolve() in target.parents else None


def probe(game_root: Path) -> Dict[str, object]:
    """Arşivlerin açılabilirliğini bildirir: {"archives": [...], "supported": bool, "reason": str, "label": str}."""
    archives = find_archives(game_root)
    labels, reason = [], ""
    for path in archives:
        try:
            arc = open_archive(path)
            labels.append(arc.label)
        except (WolfArchiveError, OSError) as exc:
            reason = f"{path.name}: {exc}"
            break
    return {"archives": [p.name for p in archives], "supported": bool(archives) and not reason,
            "reason": reason, "label": labels[0] if labels else ""}


def extract_data(game_root: Path, dest: Path, wanted=(".dat", ".project", ".mps")) -> int:
    """Yalnızca metin içeren dosyaları dest/Data altına açar (analiz önizlemesi için; oyuna dokunmaz)."""
    root = Path(game_root).resolve()
    dest = Path(dest).resolve()
    count = 0
    for path in find_archives(root):
        arc = open_archive(path)
        base = dest / _target_dir(root, path.resolve()).relative_to(root)
        for entry in arc.entries:
            if not entry.path.lower().endswith(wanted):
                continue
            target = _safe_target(base, entry.path)
            if target:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_entry(arc, entry))
                count += 1
    return count


def unpack(game_root: Path, log: LogFn = print, progress: Optional[ProgressFn] = None) -> Dict[str, object]:
    """Arşivleri oyun klasörüne açar, arşivleri yedeğe taşır ve geri alma manifesti yazar. Önce bütün arşivler
    okunabilir mi denetlenir; biri açılamazsa hiçbir şeye dokunulmaz."""
    root = Path(game_root).resolve()
    paths = [p.resolve() for p in find_archives(root)]
    if not paths:
        raise FileNotFoundError("Oyun klasöründe .wolf arşivi bulunamadı.")
    opened = [open_archive(p) for p in paths]
    total = sum(len(a.entries) for a in opened)
    backup = root / BACKUP_DIR
    backup.mkdir(parents=True, exist_ok=True)
    extracted: List[str] = []
    replaced: List[str] = []
    moved: List[str] = []
    done = 0
    try:
        for arc in opened:
            base = _target_dir(root, arc.path)
            for entry in arc.entries:
                target = _safe_target(base, entry.path)
                done += 1
                if not target:
                    log(f"Atlandı (güvensiz yol): {entry.path}")
                    continue
                data = read_entry(arc, entry)
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
                if progress and (done % 25 == 0 or done == total):
                    progress(done, total)
        for arc in opened:
            rel = arc.path.relative_to(root).as_posix()
            dest = backup / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(arc.path), str(dest))
            moved.append(rel)
    finally:
        manifest = {"archives": moved, "labels": [a.label for a in opened], "extracted": extracted,
                    "replaced": replaced}
        (root / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"WOLF arşivi açıldı ({opened[0].label}): {len(extracted)} dosya çıkarıldı, {len(moved)} arşiv yedeğe taşındı.")
    return manifest


def is_unpacked(game_root: Path) -> bool:
    return (Path(game_root) / MANIFEST).exists()


def restore(game_root: Path, log: LogFn = print) -> int:
    """unpack() işlemini geri alır: çıkarılan dosyaları siler, arşivleri ve değişen dosyaları geri koyar."""
    root = Path(game_root).resolve()
    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError("Bu oyunda Capri ile açılmış bir WOLF arşivi yok.")
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
    for rel in manifest["archives"]:
        src, target = backup / rel, _safe_target(root, rel)
        if target and src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
    for folder in sorted({(root / rel).parent for rel in manifest["extracted"]}, key=lambda p: len(p.parts), reverse=True):
        while folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    manifest_path.unlink()
    shutil.rmtree(backup, ignore_errors=True)
    log(f"WOLF arşivi geri yüklendi ({removed} çıkarılmış dosya silindi).")
    return removed


__all__ = ["open_archive", "read_entry", "find_archives", "probe", "extract_data", "unpack", "restore",
           "is_unpacked", "WolfArchiveError", "Archive", "Entry", "KEYS", "BACKUP_DIR", "MANIFEST"]
