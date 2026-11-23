"""
Capri — GDScript betiklerindeki metinler
=======================================
Dışa aktarılmış Godot oyunlarında betikler üç biçimde bulunur:

* ``.gd``  — düz metin (Godot 4.0–4.2 ve "metin" kipinde dışa aktarılan oyunlar)
* ``.gdc`` — Godot 3.x derlenmiş belirteçler (GDSC sürüm 10–13)
* ``.gdc`` — Godot 4.3+ ikili belirteçler (GDSC sürüm 100/101), çoğunlukla zstd ile sıkıştırılmış

Biçimler Godot'nun kaynağından (MIT) alınmıştır: modules/gdscript/gdscript_tokenizer(_buffer).cpp ve
core/io/marshalls.cpp. Betiklere dokunulmaz: betikteki doğal dil metinleri yalnızca okunur, çevirileri Capri'nin
çeviri tablosuna eklenir. Godot, Label/Button/RichTextLabel gibi arayüz öğelerine atanan yazıları gösterirken bu
tablodan geçirdiği için betikte ``label.text = "Kapı kilitli."`` gibi yazılan metinler oyunda çevrilmiş görünür; aynı
dize oyun mantığında (karşılaştırma, sözlük anahtarı, dosya yolu) kullanılıyorsa davranış değişmez.

Şifreli betikler (.gde) okunmaz.
"""
from __future__ import annotations

import re
import struct
from typing import List

XOR = 0xB6


class GodotScriptError(ValueError):
    pass


# ── Metin betikleri (.gd) ───────────────────────────────────────────────────
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\", '"': '"',
            "'": "'", "0": "\0"}


def text_strings(source: str) -> List[str]:
    """Düz metin betikteki dize sabitleri (StringName &"…", NodePath ^"…", $"…" ve %"…" hariç)."""
    out: List[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c == "#":
            j = source.find("\n", i)
            i = n if j < 0 else j
            continue
        if c not in "\"'":
            i += 1
            continue
        prefix = source[i - 1] if i > 0 else ""
        raw = prefix == "r" and (i < 2 or not (source[i - 2].isalnum() or source[i - 2] == "_"))
        skip = prefix in "&^$%"
        quote = source[i:i + 3] if source[i:i + 3] in ('"""', "'''") else c
        i += len(quote)
        buf = []
        while i < n:
            if source.startswith(quote, i):
                i += len(quote)
                break
            ch = source[i]
            if ch == "\\" and not raw and i + 1 < n:
                nxt = source[i + 1]
                if nxt == "u" and re.match(r"[0-9a-fA-F]{4}", source[i + 2:i + 6]):
                    buf.append(chr(int(source[i + 2:i + 6], 16)))
                    i += 6
                    continue
                if nxt == "U" and re.match(r"[0-9a-fA-F]{6}", source[i + 2:i + 8]):
                    buf.append(chr(int(source[i + 2:i + 8], 16)))
                    i += 8
                    continue
                if nxt == "\n":                       # satır devamı
                    i += 2
                    continue
                buf.append(_ESCAPES.get(nxt, "\\" + nxt))
                i += 2
                continue
            if ch == "\\" and raw and i + 1 < n and source[i + 1] in "\"'\\":
                buf.append(source[i:i + 2])
                i += 2
                continue
            if ch == "\n" and len(quote) == 1:        # kapanmamış dize: satır sonunda biter
                break
            buf.append(ch)
            i += 1
        if not skip:
            out.append("".join(buf))
    return out


# ── İkili belirteçler (.gdc) ────────────────────────────────────────────────
def _pad(n: int) -> int:
    return n + (-n % 4)


def _variant(d: bytes, p: int, major: int) -> tuple:
    """(değer ya da None, yeni konum). Yalnızca betik sabitlerinde görülen türler çözülür."""
    header = struct.unpack_from("<I", d, p)[0]
    t, wide = header & 0xFFFF, bool(header & (1 << 16))
    p += 4
    if major == 3:
        nil, boolean, integer, real, string, node_path, string_name = 0, 1, 2, 3, 4, 15, -1
    else:
        nil, boolean, integer, real, string, node_path, string_name = 0, 1, 2, 3, 4, 22, 21
    if t == nil:
        return None, p
    if t == boolean:
        return None, p + 4
    if t in (integer, real):
        return None, p + (8 if wide else 4)
    if t in (string, string_name):
        length = struct.unpack_from("<I", d, p)[0]
        text = d[p + 4:p + 4 + length].decode("utf-8", errors="replace")
        return (text if t == string else None), p + 4 + _pad(length)
    if t == node_path:
        count = struct.unpack_from("<I", d, p)[0]
        if not count & 0x80000000:                    # eski biçim: tek dize
            return None, p + 4 + _pad(count)
        names = count & 0x7FFFFFFF
        subnames = struct.unpack_from("<I", d, p + 4)[0]
        if major == 3:
            subnames &= 0x7FFFFFFF
        p += 12
        for _ in range(names + subnames):
            length = struct.unpack_from("<I", d, p)[0]
            p += 4 + _pad(length)
        return None, p
    raise GodotScriptError(f"betik sabiti türü desteklenmiyor ({t})")


def _zstd(data: bytes, size: int) -> bytes:
    try:
        import zstandard
    except ImportError as exc:                        # pragma: no cover - exe ile gelir
        raise GodotScriptError("sıkıştırılmış betik için zstandard gerekli") from exc
    out = zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
    if len(out) != size:
        raise GodotScriptError("açılan betik boyu tutmuyor")
    return out


def binary_strings(data: bytes) -> List[str]:
    """Derlenmiş betiğin sabit tablosundaki dizeler."""
    if data[:4] != b"GDSC" or len(data) < 12:
        raise GodotScriptError("derlenmiş GDScript değil")
    version = struct.unpack_from("<I", data, 4)[0]
    try:
        if version >= 100:                             # Godot 4.3+
            size = struct.unpack_from("<I", data, 8)[0]
            body = _zstd(data[12:], size) if size else data[12:]
            fields = 5 if version == 100 else 4
            counts = struct.unpack_from(f"<{fields}I", body, 0)
            identifiers, constants = counts[0], counts[1]
            p = fields * 4
            for _ in range(identifiers):
                length = struct.unpack_from("<I", body, p)[0]
                p += 4 + length * 4
            major = 4
        elif 10 <= version <= 13:                      # Godot 3.x
            identifiers, constants = struct.unpack_from("<II", data, 8)
            body = data
            p = 24
            for _ in range(identifiers):
                length = struct.unpack_from("<I", body, p)[0]
                p += 4 + length
            major = 3
        else:
            raise GodotScriptError(f"GDScript belirteç sürümü desteklenmiyor ({version})")
        out = []
        for _ in range(constants):
            value, p = _variant(body, p, major)
            if value is not None:
                out.append(value)
        return out
    except struct.error as exc:
        raise GodotScriptError("derlenmiş betik bozuk") from exc


def script_strings(data: bytes) -> List[str]:
    if data[:4] == b"GDSC":
        return binary_strings(data)
    return text_strings(data.decode("utf-8", errors="replace"))


# ── Hangi dizeler metin? ────────────────────────────────────────────────────
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PATH = re.compile(r"^(res|user|uid|https?)://|^[A-Za-z]:[\\/]|^[\w.\-/\\]+\.[A-Za-z0-9]{2,5}$|^/?\w+(/\w+)+/?$")
_NO_LETTERS = re.compile(r"^[\W\d_]*$")
_FORMAT_ONLY = re.compile(r"^(\s|%[-+ #0]*\d*(\.\d+)?[sdifxXoc]|\{\w*\}|[\W\d_])*$")
_COLOR = re.compile(r"^#?[0-9A-Fa-f]{3,8}$")


def is_display_text(text: str) -> bool:
    """Betikteki bir dizenin oyuncuya gösterilen metin olma olasılığı: yollar, tanımlayıcılar (snake_case,
    camelCase, giriş eylemleri), renkler ve yalnızca biçim kodundan oluşan dizeler elenir."""
    t = text.strip()
    if len(t) < 2 or len(t) > 4000 or _NO_LETTERS.match(t) or _FORMAT_ONLY.match(t) or _COLOR.match(t):
        return False
    if _PATH.search(t):
        return False
    if _IDENT.fullmatch(t):
        # Tek kelime: yalnızca baş harfi büyük düz sözcükler (Start, Options, OK) arayüz yazısı sayılır
        if "_" in t or t.islower() or any(ch.isdigit() for ch in t):
            return False
        if any(ch.isupper() for ch in t[1:]) and not t.isupper():
            return False                               # PlayerController, getHealth
        return not (t.isupper() and len(t) > 4)        # ITEM_KEY gibi sabit adları
    if " " not in t and any(sym in t for sym in ("::", "=>", "()", "->")):
        return False
    letters = [ch for ch in t if ch.isalpha()]
    if all(ch.isupper() for ch in letters) and len(letters) >= 5 and any(sym in t for sym in "_=:"):
        return False                                   # "SCORE_KEY=", "DEBUG: X" gibi kayıt/anahtar dizeleri
    return True


__all__ = ["text_strings", "binary_strings", "script_strings", "is_display_text", "GodotScriptError"]
