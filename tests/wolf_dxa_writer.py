"""
Testler için DXArchive yazıcısı (WOLF .wolf arşivleri). DxLib'in arşivleyicisiyle aynı yerleşimi üretir: sürüm 3/6
(12 baytlık döngüsel anahtar), sürüm 8 (dosya başına CRC32 anahtarı, LZ + Huffman) ve WOLF 3.31+ ek şifrelemesi
(adres karıştırma, AES-CTR, 768 baytlık XOR). Çözücü gerçek oyun arşivleriyle ayrıca doğrulandı; bu yazıcı yalnızca
depoya oyun verisi koymadan aynı yolları sınamak içindir.
"""
import heapq
import struct
from collections import Counter

import wolf_archive as wa

NONE64 = 0xFFFFFFFFFFFFFFFF
NONE32 = 0xFFFFFFFF


# ── Sıkıştırıcılar ─────────────────────────────────────────────────────────
def lz_encode(data: bytes) -> bytes:
    counts = Counter(data)
    key = min(range(256), key=lambda b: (counts.get(b, 0), b))
    out = bytearray()
    last = {}
    i = 0
    while i < len(data):
        best_len, best_off = 0, 0
        if i + 4 <= len(data):
            for j in last.get(data[i:i + 4], [])[-8:]:
                n = 0
                while i + n < len(data) and data[j + n] == data[i + n] and n < 2000:
                    n += 1
                if n > best_len:
                    best_len, best_off = n, i - j
        if best_len >= 4:
            ln = best_len - 4
            index = best_off - 1
            size = 0 if index < 0x100 else 1 if index < 0x10000 else 2
            code = ((ln & 0x1F) << 3) | (4 if ln > 0x1F else 0) | size
            out += bytes([key, code + 1 if code >= key else code])
            if ln > 0x1F:
                out.append(ln >> 5)
            out += index.to_bytes(size + 1, "little")
            for k in range(i, i + best_len):
                last.setdefault(data[k:k + 4], []).append(k)
            i += best_len
            continue
        b = data[i]
        out += bytes([key, key]) if b == key else bytes([b])
        last.setdefault(data[i:i + 4], []).append(i)
        i += 1
    return struct.pack("<II", len(data), len(out) + 9) + bytes([key]) + bytes(out)


class _BitsOut:
    def __init__(self):
        self.out = bytearray()
        self.n = 0

    def msb(self, value: int, bits: int) -> None:
        for k in range(bits - 1, -1, -1):
            if self.n % 8 == 0:
                self.out.append(0)
            self.out[-1] |= ((value >> k) & 1) << (7 - self.n % 8)
            self.n += 1


def huffman_encode(data: bytes) -> bytes:
    counts = Counter(data)
    weights = [min(counts.get(b, 0), 0xFFFF) for b in range(256)]
    heap = [(w, i) for i, w in enumerate(weights)]
    heapq.heapify(heap)
    child = {}
    node = 256
    while len(heap) > 1:
        w1, a = heapq.heappop(heap)
        w2, b = heapq.heappop(heap)
        child[node] = (a, b)
        heapq.heappush(heap, (w1 + w2, node))
        node += 1
    codes = {}
    stack = [(node - 1, [])]
    while stack:
        n, path = stack.pop()
        if n < 256:
            codes[n] = path
        else:
            stack.append((child[n][0], path + [0]))
            stack.append((child[n][1], path + [1]))
    body = bytearray()
    acc = nbits = 0
    for b in data:
        for bit in codes[b]:
            acc |= bit << nbits
            nbits += 1
            if nbits == 8:
                body.append(acc)
                acc = nbits = 0
    if nbits:
        body.append(acc)
    head = _BitsOut()
    for value in (len(data), len(body)):
        bits = max(1, value.bit_length())
        head.msb(bits - 1, 6)
        head.msb(value, bits)
    prev = 0
    for i, w in enumerate(weights):
        diff = w if i == 0 else w - prev
        mag = abs(diff)
        bits = max(2, mag.bit_length() + (mag.bit_length() & 1))
        head.msb(bits // 2 - 1, 3)
        head.msb(1 if diff < 0 else 0, 1)
        head.msb(mag, bits)
        prev = w
    return bytes(head.out) + bytes(body)


# ── Tablolar ───────────────────────────────────────────────────────────────
def _name_entry(name: str, codec: str = "cp932") -> bytes:
    raw = name.encode(codec)
    packs = len(raw) // 4 + 1
    upper = raw.upper().ljust(packs * 4, b"\0")
    return struct.pack("<HH", packs, sum(upper) & 0xFFFF) + upper + raw.ljust(packs * 4, b"\0")


def _tree(files):
    """{"a/b.txt": data} → iç içe sözlük."""
    root = {}
    for path, data in files.items():
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = data
    return root


def build_tables(files, version, add_data):
    """Ad, dosya ve klasör tablolarını kurar. add_data(path, upper_chain, data) → (adres, boy, lz, huff)."""
    names = bytearray()
    file_tab = bytearray()
    dir_tab = bytearray()
    q = "Q" if version >= 6 else "I"
    none = NONE64 if version >= 6 else NONE32
    fh_size = 72 if version >= 8 else 64 if version >= 6 else 44
    dir_size = 32 if version >= 6 else 16

    def add_name(name):
        at = len(names)
        names.extend(_name_entry(name))
        return at

    def filehead(name_at, attr, data_at, size, press, huff):
        if version >= 8:
            return struct.pack("<9Q", name_at, attr, 0, 0, 0, data_at, size, press, huff)
        if version >= 6:
            return struct.pack("<8Q", name_at, attr, 0, 0, 0, data_at, size, press)
        return struct.pack("<II3QIII", name_at, attr, 0, 0, 0, data_at, size, press)

    def emit_dir(node, own_at, parent_at, chain, prefix):
        my_at = len(dir_tab)
        dir_tab.extend(bytes(dir_size))
        heads_at = len(file_tab)
        items = sorted(node.items())
        file_tab.extend(bytes(fh_size * len(items)))
        struct.pack_into(f"<4{q}", dir_tab, my_at, own_at, parent_at, len(items), heads_at)
        for k, (name, value) in enumerate(items):
            name_at = add_name(name)
            slot = heads_at + k * fh_size
            if isinstance(value, dict):
                sub_at = emit_dir(value, slot, my_at, [name.encode("cp932").upper()] + chain, f"{prefix}{name}/")
                file_tab[slot:slot + fh_size] = filehead(name_at, 0x10, sub_at, 0, none, none)
            else:
                at, size, press, huff = add_data(f"{prefix}{name}", [name.encode("cp932").upper()] + chain, value)
                file_tab[slot:slot + fh_size] = filehead(name_at, 0x20, at, size, press, huff)
        return my_at

    emit_dir(_tree(files), none, none, [], "")
    return bytes(names), bytes(file_tab), bytes(dir_tab)


# ── Arşivler ───────────────────────────────────────────────────────────────
def _label_key(label):
    return next((v, cv, key) for name, v, cv, key in wa.KEYS if name == label)


def build_v8(files, label="WOLF 2.225", mode="mixed", huff_kb=1, pw=bytes(range(3, 18))):
    """mode: raw | lz | huff | mixed (dosyaya göre sırayla)."""
    _v, cv, key_string = _label_key(label)
    key_string = wa._cstr(key_string)[:63]
    new_crypt = wa._new_crypt(cv)
    special = wa.init_wolf_crypt(cv, pw) if new_crypt else None
    data_region = bytearray()
    order = ["raw", "lz", "huff", "lzhuff"]
    counter = [0]

    def conv(blob, key, pos):
        if special is not None:
            return wa.wolf_crypt(special, blob, pos, cv)
        if cv == 0x64:
            return wa.chacha20_xor(blob, key_string[:32], key_string[32:44], pos)
        return wa._xor_repeat(blob, key, pos)

    def add_data(path, chain, data):
        kind = order[counter[0] % 4] if mode == "mixed" else mode
        counter[0] += 1
        key = wa.key_create_v8(key_string + b"".join(chain))
        at = len(data_region)
        size = len(data)
        press = huff = NONE64
        stored = data
        if kind in ("lz", "lzhuff"):
            stored = lz_encode(data)
            press = len(stored)
        if kind in ("huff", "lzhuff"):
            kb = huff_kb * 1024
            part = stored[:kb] + stored[-kb:] if huff_kb != 0xFF and len(stored) > kb * 2 else stored
            encoded = huffman_encode(part)
            huff = len(encoded)
            blob = conv(encoded, key, size)
            if huff_kb != 0xFF and len(stored) > kb * 2:
                blob += conv(stored[kb:-kb], key, size + huff)
        else:
            blob = conv(stored, key, size)
        data_region.extend(blob)
        return at, size, press, huff

    names, file_tab, dir_tab = build_tables(files, 8, add_data)
    table = names + file_tab + dir_tab
    packed = conv(huffman_encode(lz_encode(table)), wa.key_create_v8(key_string), 0)
    data_start = 64
    names_at = data_start + len(data_region)
    head = bytearray(struct.pack("<HHIQQQQIIB", 0x5844, 8, len(table), data_start, names_at, len(names),
                                 len(names) + len(file_tab), 932, cv << 16, huff_kb) + pw)
    out = bytearray(head + data_region + packed)
    if new_crypt:
        size = len(out)
        assert size - 64 >= 0x400, "yeni şifreleme en az 1 KB veri ister"
        rk, iv = wa.init_aes128(pw, None, cv)
        body = 0x400
        if wa._is_v35(cv):
            xs = wa._XorShift(pw[2] * pw[4] + pw[12] or 1)
            xs()
            if size >= xs() % 500 + 800:
                xs()
            body = size - 64
            if body >= xs() % 500 + 800:
                body = xs() % 500 + 800
        wa.aes_ctr(out, 64, body, rk, iv)
        wa.aes_ctr(out, names_at, size - names_at, rk, iv)
        other = wa.init_wolf_crypt(cv, pw, other=True, key_string=key_string)
        out[64:size - 64] = wa.wolf_crypt(other, bytes(out[64:size - 64]), 64, cv)
        scrambled = bytearray(out[:64])
        wa.crypt_addresses(scrambled, pw, cv)
        out[:64] = scrambled
    return bytes(out)


def build_v56(files, label="WOLF 2.20", version=None, compress=True):
    dxa, _cv, key_string = _label_key(label)
    version = version or dxa
    key = wa.key_create_v6(key_string)
    head_size = 48 if version >= 6 else 28
    data_region = bytearray()
    none = NONE64 if version >= 6 else NONE32

    def add_data(path, chain, data):
        at = len(data_region)
        stored = lz_encode(data) if compress and len(data) > 8 else data
        file_at = head_size + at
        pos = len(data) if version >= 5 else file_at
        data_region.extend(wa._xor_repeat(stored, key, pos))
        return at, len(data), len(stored) if stored is not data else none, none

    names, file_tab, dir_tab = build_tables(files, version, add_data)
    table = names + file_tab + dir_tab
    names_at = head_size + len(data_region)
    if version >= 6:
        head = struct.pack("<HHIQQQQQ", 0x5844, version, len(table), head_size, names_at, len(names),
                           len(names) + len(file_tab), 932)
    else:
        head = struct.pack("<HHIIIIII", 0x5844, version, len(table), head_size, names_at, len(names),
                           len(names) + len(file_tab), 932)
    return (wa._xor_repeat(head, key, 0) + bytes(data_region)
            + wa._xor_repeat(table, key, 0 if version >= 5 else names_at))
