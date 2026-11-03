"""
Capri — Ruby Marshal 4.8 okuyucu / yazıcı (RPG Maker XP / VX / VX Ace veri dosyaları)
========================================================================================
.rxdata / .rvdata / .rvdata2 dosyalarını, değiştirilmeyen her baytı aynen koruyacak şekilde
okur ve yazar: sembol tablosu, nesne bağlantıları (@), sayı/kayan nokta kodlamaları ve
kullanıcı tanımlı (_dump) türler (Table, Color, Tone) olduğu gibi kalır. Okuyup değiştirmeden
yazmak orijinal dosyayla bayt bayt aynı çıktıyı üretir.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional, Tuple


@dataclass
class Sym:
    name: bytes

    def __str__(self) -> str:
        return self.name.decode("utf-8", "replace")


@dataclass
class Link:
    """Daha önce okunan nesneye bağlantı ('@' + sıra numarası)."""
    index: int


@dataclass
class Node:
    ivars: Optional[List[Tuple[Any, Any]]] = field(default=None, kw_only=True)  # 'I' sarmalayıcı değişkenleri


@dataclass
class RString(Node):
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", "replace")

    @text.setter
    def text(self, value: str) -> None:
        self.data = value.encode("utf-8")


@dataclass
class RFloat(Node):
    raw: bytes


@dataclass
class RBignum(Node):
    sign: bytes
    raw: bytes


@dataclass
class RRegexp(Node):
    source: bytes
    options: int


@dataclass
class RArray(Node):
    items: list


@dataclass
class RHash(Node):
    pairs: list
    default: Any = None
    has_default: bool = False


@dataclass
class RObject(Node):
    cls: Any
    attrs: list  # [(Sym('@name'), değer), ...] — sıra korunur

    def get(self, name: str, default: Any = None) -> Any:
        key = name.encode()
        for k, v in self.attrs:
            if isinstance(k, Sym) and k.name == key:
                return v
        return default

    @property
    def class_name(self) -> str:
        return str(self.cls)


@dataclass
class RUserDef(Node):
    cls: Any
    data: bytes


@dataclass
class RUserMarshal(Node):
    cls: Any
    value: Any


@dataclass
class RStruct(Node):
    cls: Any
    members: list


@dataclass
class RExtended(Node):
    module: Any
    value: Any


@dataclass
class RUserClass(Node):
    cls: Any
    value: Any


@dataclass
class RClassRef(Node):
    kind: bytes  # b'c', b'm', b'M'
    name: bytes


class Reader:
    def __init__(self, data: bytes):
        self.f = io.BytesIO(data)
        major, minor = self.f.read(2)
        if (major, minor) != (4, 8):
            raise ValueError(f"Desteklenmeyen Marshal sürümü {major}.{minor}")
        self.symbols: List[Sym] = []

    def byte(self) -> int:
        b = self.f.read(1)
        if not b:
            raise EOFError("Beklenmeyen dosya sonu")
        return b[0]

    def long(self) -> int:
        c = self.byte()
        if c > 127:
            c -= 256
        if c == 0:
            return 0
        if 4 < c < 128:
            return c - 5
        if -129 < c < -4:
            return c + 5
        n = abs(c)
        value = int.from_bytes(self.f.read(n), "little")
        if c < 0:
            value -= 1 << (8 * n)
        return value

    def bytes_(self) -> bytes:
        return self.f.read(self.long())

    def symbol(self) -> Sym:
        t = self.f.read(1)
        if t == b":":
            sym = Sym(self.bytes_())
            self.symbols.append(sym)
            return sym
        if t == b";":
            return self.symbols[self.long()]
        if t == b"I":  # kodlamalı sembol
            sym = self.symbol_body_after_ivar()
            return sym
        raise ValueError(f"Sembol bekleniyordu, {t!r} bulundu")

    def symbol_body_after_ivar(self) -> Sym:
        if self.f.read(1) != b":":
            raise ValueError("Kodlamalı sembol hatalı")
        sym = Sym(self.bytes_())
        self.symbols.append(sym)
        for _ in range(self.long()):
            self.symbol()
            self.read()
        return sym

    def read(self) -> Any:
        t = self.f.read(1)
        if t == b"0":
            return None
        if t == b"T":
            return True
        if t == b"F":
            return False
        if t == b"i":
            return self.long()
        if t in (b":", b";"):
            self.f.seek(-1, 1)
            return self.symbol()
        if t == b"@":
            return Link(self.long())
        if t == b"I":
            node = self.read()
            node.ivars = [(self.symbol(), self.read()) for _ in range(self.long())]
            return node
        if t == b'"':
            return RString(self.bytes_())
        if t == b"f":
            return RFloat(self.bytes_())
        if t == b"l":
            sign = self.f.read(1)
            words = self.long()
            return RBignum(sign, self.f.read(words * 2))
        if t == b"/":
            source = self.bytes_()
            return RRegexp(source, self.byte())
        if t == b"[":
            node = RArray([])
            node.items = [self.read() for _ in range(self.long())]
            return node
        if t in (b"{", b"}"):
            node = RHash([])
            node.pairs = [(self.read(), self.read()) for _ in range(self.long())]
            if t == b"}":
                node.default, node.has_default = self.read(), True
            return node
        if t == b"o":
            cls = self.symbol()
            node = RObject(cls, [])
            node.attrs = [(self.symbol(), self.read()) for _ in range(self.long())]
            return node
        if t == b"u":
            cls = self.symbol()
            return RUserDef(cls, self.bytes_())
        if t == b"U":
            cls = self.symbol()
            node = RUserMarshal(cls, None)
            node.value = self.read()
            return node
        if t == b"S":
            cls = self.symbol()
            node = RStruct(cls, [])
            node.members = [(self.symbol(), self.read()) for _ in range(self.long())]
            return node
        if t == b"e":
            module = self.symbol()
            return RExtended(module, self.read())
        if t == b"C":
            cls = self.symbol()
            return RUserClass(cls, self.read())
        if t in (b"c", b"m", b"M"):
            return RClassRef(t, self.bytes_())
        raise ValueError(f"Desteklenmeyen Marshal türü {t!r} (konum {self.f.tell() - 1})")


class Writer:
    def __init__(self):
        self.out = io.BytesIO()
        self.out.write(b"\x04\x08")
        self.symbols: dict = {}

    def long(self, value: int) -> None:
        w = self.out.write
        if value == 0:
            w(b"\x00")
        elif 0 < value < 123:
            w(bytes([value + 5]))
        elif -124 < value < 0:
            w(bytes([(value - 5) & 0xFF]))
        else:
            for n in range(1, 5):
                if value > 0 and value < (1 << (8 * n)):
                    w(bytes([n]) + value.to_bytes(n, "little"))
                    return
                if value < 0 and value >= -(1 << (8 * n)):
                    w(bytes([256 - n]) + (value + (1 << (8 * n))).to_bytes(n, "little"))
                    return
            raise ValueError(f"Sayı Marshal long aralığı dışında: {value}")

    def bytes_(self, data: bytes) -> None:
        self.long(len(data))
        self.out.write(data)

    def symbol(self, sym: Sym) -> None:
        if sym.name in self.symbols:
            self.out.write(b";")
            self.long(self.symbols[sym.name])
        else:
            self.symbols[sym.name] = len(self.symbols)
            self.out.write(b":")
            self.bytes_(sym.name)

    def write(self, obj: Any) -> None:
        w = self.out.write
        if obj is None:
            w(b"0")
        elif obj is True:
            w(b"T")
        elif obj is False:
            w(b"F")
        elif isinstance(obj, int):
            if -(1 << 30) <= obj < (1 << 30):
                w(b"i")
                self.long(obj)
            else:
                raw = abs(obj).to_bytes((abs(obj).bit_length() + 15) // 16 * 2, "little")
                w(b"l" + (b"+" if obj >= 0 else b"-"))
                self.long(len(raw) // 2)
                w(raw)
        elif isinstance(obj, Sym):
            self.symbol(obj)
        elif isinstance(obj, Link):
            w(b"@")
            self.long(obj.index)
        elif isinstance(obj, Node):
            if obj.ivars is not None:
                w(b"I")
            self.node(obj)
            if obj.ivars is not None:
                self.long(len(obj.ivars))
                for key, value in obj.ivars:
                    self.symbol(key)
                    self.write(value)
        else:
            raise TypeError(f"Yazılamayan tür: {type(obj).__name__}")

    def node(self, n: Node) -> None:
        w = self.out.write
        if isinstance(n, RString):
            w(b'"')
            self.bytes_(n.data)
        elif isinstance(n, RFloat):
            w(b"f")
            self.bytes_(n.raw)
        elif isinstance(n, RBignum):
            w(b"l" + n.sign)
            self.long(len(n.raw) // 2)
            w(n.raw)
        elif isinstance(n, RRegexp):
            w(b"/")
            self.bytes_(n.source)
            w(bytes([n.options]))
        elif isinstance(n, RArray):
            w(b"[")
            self.long(len(n.items))
            for item in n.items:
                self.write(item)
        elif isinstance(n, RHash):
            w(b"}" if n.has_default else b"{")
            self.long(len(n.pairs))
            for key, value in n.pairs:
                self.write(key)
                self.write(value)
            if n.has_default:
                self.write(n.default)
        elif isinstance(n, RObject):
            w(b"o")
            self.symbol(n.cls)
            self.long(len(n.attrs))
            for key, value in n.attrs:
                self.symbol(key)
                self.write(value)
        elif isinstance(n, RUserDef):
            w(b"u")
            self.symbol(n.cls)
            self.bytes_(n.data)
        elif isinstance(n, RUserMarshal):
            w(b"U")
            self.symbol(n.cls)
            self.write(n.value)
        elif isinstance(n, RStruct):
            w(b"S")
            self.symbol(n.cls)
            self.long(len(n.members))
            for key, value in n.members:
                self.symbol(key)
                self.write(value)
        elif isinstance(n, RExtended):
            w(b"e")
            self.symbol(n.module)
            self.write(n.value)
        elif isinstance(n, RUserClass):
            w(b"C")
            self.symbol(n.cls)
            self.write(n.value)
        elif isinstance(n, RClassRef):
            w(n.kind)
            self.bytes_(n.name)


def loads(data: bytes) -> Any:
    reader = Reader(data)
    value = reader.read()
    rest = reader.f.read()
    if rest:
        raise ValueError(f"Marshal verisinin sonunda {len(rest)} fazla bayt var")
    return value


def dumps(obj: Any) -> bytes:
    writer = Writer()
    writer.write(obj)
    return writer.out.getvalue()


def walk_strings(obj: Any) -> Iterator[RString]:
    """Tüm iç içe RString düğümlerini dolaşır."""
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, RString):
            yield node
        elif isinstance(node, RArray):
            stack.extend(reversed(node.items))
        elif isinstance(node, RHash):
            for k, v in reversed(node.pairs):
                stack.extend((v, k))
        elif isinstance(node, (RObject, RStruct)):
            stack.extend(v for _, v in reversed(node.attrs if isinstance(node, RObject) else node.members))
        elif isinstance(node, (RUserMarshal, RExtended, RUserClass)):
            stack.append(node.value)
