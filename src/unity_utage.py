"""
Utage (Unity görsel roman motoru) senaryo kitapları.

Utage senaryoyu Excel'den "AdvImportBook" adlı ScriptableObject'lere aktarır. IL2CPP oyunlarda bu nesnelerin
tip bilgisi olmadığından UnityPy alanlarını çözemez; ama Unity serileştirmesi düzenli olduğu için ham veri
güvenle okunabilir:

    satır listesi = int satır_sayısı, sonra her satır için:
        int satır_no, int hücre_sayısı, hücre_sayısı × string (int uzunluk + UTF-8 + 4 bayta hizalama), int, int

Her tablonun ilk satırı başlıktır ("Command", "Arg1"… "Text", "English", "Korean"…). Yazarken yalnızca değişen
metin hücrelerinin baytları değiştirilir; geri kalan her bayt aynen korunur. Hücreler 4 bayta hizalı olduğu için
sonraki verilerin hizası bozulmaz.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

COMMAND = "Command".encode("utf-8")
_HEADER_MARK = struct.pack("<i", len(COMMAND)) + COMMAND
MAX_CELLS = 4096
MAX_STRING = 1 << 20


class UtageFormatError(ValueError):
    """Ham veri beklenen Utage düzenine uymuyor; bu kitaba dokunulmaz."""


@dataclass
class UtageCell:
    row: int          # Utage satır numarası (rowIndex)
    column: int       # başlıktaki sütun sırası
    start: int        # uzunluk önekinin bayt konumu
    end: int          # hizalama dahil bitiş konumu
    text: str


@dataclass
class UtageGrid:
    header: list[str]
    rows: list[list[UtageCell]] = field(default_factory=list)   # başlık hariç

    def column(self, *names: str) -> int | None:
        lowered = [h.strip().casefold() for h in self.header]
        for name in names:
            if name.casefold() in lowered:
                return lowered.index(name.casefold())
        return None


def _read_int(raw: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(raw):
        raise UtageFormatError("veri beklenenden kısa")
    return struct.unpack_from("<i", raw, pos)[0]


def _read_string(raw: bytes, pos: int) -> tuple[str, int]:
    length = _read_int(raw, pos)
    if length < 0 or length > MAX_STRING or pos + 4 + length > len(raw):
        raise UtageFormatError("geçersiz metin uzunluğu")
    try:
        text = raw[pos + 4:pos + 4 + length].decode("utf-8")
    except UnicodeDecodeError as error:
        raise UtageFormatError("metin UTF-8 değil") from error
    end = pos + 4 + length
    return text, end + (-end) % 4


def encode_string(text: str, pos: int = 0) -> bytes:
    """Unity string'i: uzunluk + UTF-8 + 4 bayta hizalama (konum hep 4'ün katı olduğundan dolgu sabittir)."""
    data = text.encode("utf-8")
    padding = (-(pos + 4 + len(data))) % 4
    return struct.pack("<i", len(data)) + data + b"\0" * padding


def _parse_grid(raw: bytes, header_at: int) -> tuple[UtageGrid, int]:
    """header_at: başlık satırındaki "Command" hücresinin konumu."""
    cells_at = header_at - 4
    row_at = cells_at - 4
    count_at = row_at - 4
    row_count = _read_int(raw, count_at)
    if not 1 <= row_count <= 1_000_000:
        raise UtageFormatError("satır sayısı geçersiz")
    pos = row_at
    grid: UtageGrid | None = None
    previous = -1
    for _ in range(row_count):
        row_index = _read_int(raw, pos)
        cell_count = _read_int(raw, pos + 4)
        if row_index <= previous or not 0 <= cell_count <= MAX_CELLS:
            raise UtageFormatError("satır düzeni bozuk")
        previous = row_index
        pos += 8
        cells = []
        for column in range(cell_count):
            text, end = _read_string(raw, pos)
            cells.append(UtageCell(row_index, column, pos, end, text))
            pos = end
        pos += 8                       # satır sonundaki iki alan
        if grid is None:
            if not cells or cells[0].text != "Command":
                raise UtageFormatError("başlık satırı yok")
            grid = UtageGrid([c.text for c in cells])
        else:
            grid.rows.append(cells)
    if pos > len(raw):
        raise UtageFormatError("veri beklenenden kısa")
    return grid, pos


def parse_book(raw: bytes) -> list[UtageGrid]:
    """Kitaptaki tüm senaryo tablolarını bulur. Utage kitabı değilse boş liste; bozuksa UtageFormatError."""
    grids: list[UtageGrid] = []
    search = 0
    while True:
        at = raw.find(_HEADER_MARK, search)
        if at < 0:
            break
        search = at + 1
        if at % 4 or at < 12:
            continue
        try:
            grid, end = _parse_grid(raw, at)
        except UtageFormatError:
            if grids:          # ilk tablo okunduysa sonradan gelen eşleşme hücre içi bir "Command" olabilir
                continue
            raise
        grids.append(grid)
        search = end
    return grids


def looks_like_book(raw: bytes) -> bool:
    return _HEADER_MARK in raw


def rewrite(raw: bytes, replacements: dict[int, str], cells: dict[int, UtageCell]) -> bytes:
    """replacements: hücre başlangıç konumu → yeni metin. Diğer baytlar aynen kalır."""
    out = bytearray()
    cursor = 0
    for start in sorted(replacements):
        cell = cells[start]
        out += raw[cursor:cell.start]
        out += encode_string(replacements[start], len(out))
        cursor = cell.end
    out += raw[cursor:]
    return bytes(out)


def text_column(grid: UtageGrid) -> int | None:
    """Oyuncunun gördüğü yazılabilir sütun: varsa "English", yoksa varsayılan "Text"."""
    return grid.column("English", "Text")
