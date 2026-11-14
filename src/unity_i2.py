"""
I2 Localization (Unity'de yaygın yerelleştirme eklentisi) dil kaynakları: "I2Languages" LanguageSourceAsset.

IL2CPP oyunlarda tip bilgisi olmadığından ham veri okunur. Terim listesi düzeni (sürüme göre "Description"
alanı olabilir ya da olmayabilir; ikisi de denenir ve tüm terimler tutarlıysa kabul edilir):

    int terim_sayısı, sonra her terim için:
        string Term, int TermType, [string Description], string[] Languages, byte[] Flags, string[] Languages_Touch

Terimlerden sonra dil listesi gelir (string Name, string Code, byte Flags). Yazarken yalnızca değişen dil
hücrelerinin baytları değişir (unity_utage.rewrite ile aynı yöntem).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from unity_utage import UtageCell, UtageFormatError, _read_int, _read_string

MAX_TERMS = 500_000
TEXT_TERM = 0      # eTermType.Text; 2 Texture, 3 AudioClip, 5 Sprite, 9 TMP fontu… (değerleri varlık adıdır)
MAX_LANGUAGES = 200


@dataclass
class I2Source:
    languages: list[str]                                   # dil adları (bulunamazsa boş)
    terms: list[str] = field(default_factory=list)
    cells: list[list[UtageCell]] = field(default_factory=list)   # terim → dil hücreleri
    types: list[int] = field(default_factory=list)               # I2 eTermType: 0 metin, 5 resim (Sprite)…

    def is_text(self, index: int) -> bool:
        """Yalnızca metin terimleri çevrilir; diğerlerinin değeri resim/ses/font dosya adıdır."""
        return self.types[index] == TEXT_TERM

    def column(self, *names: str) -> int | None:
        lowered = [n.casefold() for n in self.languages]
        for name in names:
            for index, language in enumerate(lowered):
                if language == name.casefold() or language.startswith(name.casefold() + " "):
                    return index
        return None


def _skip_bytes_array(raw: bytes, pos: int) -> int:
    count = _read_int(raw, pos)
    if not 0 <= count <= MAX_LANGUAGES:
        raise UtageFormatError("bayrak dizisi geçersiz")
    end = pos + 4 + count
    return end + (-end) % 4


def _parse_terms(raw: bytes, pos: int, with_description: bool) -> tuple[I2Source, int]:
    count = _read_int(raw, pos)
    if not 1 <= count <= MAX_TERMS:
        raise UtageFormatError("terim sayısı geçersiz")
    pos += 4
    source = I2Source([])
    widths = set()
    for index in range(count):
        term, pos = _read_string(raw, pos)
        term_type = _read_int(raw, pos)
        pos += 4
        if not term or not 0 <= term_type <= 64:
            raise UtageFormatError("terim düzeni bozuk")
        if with_description:
            _description, pos = _read_string(raw, pos)
        languages = _read_int(raw, pos)
        if not 0 <= languages <= MAX_LANGUAGES:
            raise UtageFormatError("dil sayısı geçersiz")
        pos += 4
        cells = []
        for column in range(languages):
            text, end = _read_string(raw, pos)
            cells.append(UtageCell(index, column, pos, end, text))
            pos = end
        pos = _skip_bytes_array(raw, pos)                 # Flags
        touch = _read_int(raw, pos)                       # Languages_Touch (eski sürümler)
        if not 0 <= touch <= MAX_LANGUAGES:
            raise UtageFormatError("Languages_Touch geçersiz")
        pos += 4
        for _ in range(touch):
            _text, pos = _read_string(raw, pos)
        widths.add(languages)
        source.terms.append(term)
        source.cells.append(cells)
        source.types.append(term_type)
    if len(widths - {0}) > 1:
        raise UtageFormatError("terimlerin dil sayısı tutarsız")
    return source, pos


def _find_languages(raw: bytes, pos: int, count: int) -> list[str]:
    """Terim listesinden sonraki ilk 256 baytta "count" uzunluğunda (Name, Code, Flags) listesi arar."""
    for start in range(pos, min(pos + 256, len(raw) - 4), 4):
        try:
            if _read_int(raw, start) != count:
                continue
            names, at = [], start + 4
            for _ in range(count):
                name, at = _read_string(raw, at)
                _code, at = _read_string(raw, at)
                at += 4                                     # Flags (byte + hizalama)
                if not name or len(name) > 64:
                    raise UtageFormatError("dil adı geçersiz")
                names.append(name)
            return names
        except UtageFormatError:
            continue
    return []


def parse_source(raw: bytes) -> I2Source:
    """Ham veride I2 terim listesini bulur. Bulamazsa UtageFormatError."""
    if b"I2Languages" not in raw[:256] and b"Languages" not in raw[:256]:
        raise UtageFormatError("I2 kaynağı değil")
    name_length = _read_int(raw, 28)
    start = 28 + 4 + name_length
    start += (-start) % 4
    for offset in range(start, min(start + 64, len(raw) - 4), 4):
        for with_description in (False, True):
            try:
                source, end = _parse_terms(raw, offset, with_description)
            except UtageFormatError:
                continue
            width = max((len(c) for c in source.cells), default=0)
            source.languages = _find_languages(raw, end, width) if width else []
            return source
    raise UtageFormatError("I2 terim listesi bulunamadı")


def looks_like_source(name: str, raw_head: bytes) -> bool:
    return "i2languages" in name.casefold() or b"I2Languages" in raw_head
