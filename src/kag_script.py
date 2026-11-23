"""
Capri — KAG senaryo dili (TyranoScript ve KiriKiri)
==================================================
Her iki motor da senaryoyu .ks dosyalarında KAG sözdizimiyle tutar:

    *etiket             etiket satırı
    ;yorum              yorum
    @tag a=1 b="x"      satır başı etiketi
    [tag a=1]metin[p]   satır içi etiketler ve oyuncunun gördüğü metin
    #Ad                 (TyranoScript) konuşan karakter
    [iscript] … [endscript]   JavaScript / TJS bloğu (çevrilmez)

Çeviri birimi bir metin satırıdır; satır içi etiketler ([r], [l], [p], [font …], [emb …]) çeviride aynen korunur.
Ruby (okunuş) etiketleri hedef dilde anlamsız olduğundan çeviriden önce çıkarılır. Seçenek düğmeleri ve isim
alanları gibi metin taşıyan etiket parametreleri (glink text=…, chara_new jname=…) ayrıca çevrilir.

Yazarken çevirinin sözdizimini bozmaması sağlanır: etiket dışındaki köşeli parantezler tam genişlik karşılığına
çevrilir, satır başındaki * # ; @ işaretleri kaçırılır, satır sonu tek satıra indirgenir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

# Metin taşıyan etiket parametreleri (etiket → parametreler)
TEXT_ATTRS = {
    "glink": ("text",), "ptext": ("text",), "mtext": ("text",), "dialog": ("text", "label_ok", "label_cancel"),
    "chara_new": ("jname",), "seladd": ("text",), "button": ("hint",), "link": ("hint",), "notice": ("text",),
    "selopt": ("text",), "exlink": ("text",),
}
SCRIPT_BLOCKS = {"iscript": "endscript", "html": "endhtml"}
RUBY = re.compile(r"\[ruby\s+text\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\]\s]*)\s*\]", re.IGNORECASE)
# Çeviride korunacak parçalar: etiketler ([...] ama [[ kaçışı değil)
PROTECTED_KAG = re.compile(r"(?<!\[)\[(?!\[)(?:[^\[\]\"']|\"[^\"]*\"|'[^']*')*\]")
_LETTER = re.compile(r"[^\W\d_]")
_IDENT = re.compile(r"[A-Za-z_][\w]*")


@dataclass
class KagText:
    file: str                   # kap içindeki dosya adı
    line: int                   # 0'dan başlayan satır
    start: int                  # satır içindeki başlangıç (dahil)
    end: int                    # bitiş (hariç)
    original: str               # çevrilecek metin (ruby çıkarılmış)
    context: str                # dialogue | choice | name | ui
    speaker: str = ""
    quoted: str = ""            # parametre ise özgün tırnak (", ' ya da boş)
    attr: str = ""              # parametre adı (parametre birimlerinde)


@dataclass
class _Tag:
    start: int
    end: int
    name: str
    attrs: List[Tuple[str, int, int, str, str]] = field(default_factory=list)   # (ad, değer başı, sonu, değer, tırnak)


def _scan_tag(line: str, i: int) -> int:
    """line[i] == '[' için etiketin bitişi (']' sonrası); kapanmıyorsa -1."""
    j = i + 1
    quote = ""
    while j < len(line):
        ch = line[j]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "]":
            return j + 1
        elif ch == "[":
            return -1
        j += 1
    return -1


def _parse_attrs(body: str, offset: int) -> Tuple[str, List[Tuple[str, int, int, str, str]]]:
    """'tag a=1 b="x y"' → (ad, [(parametre, değer başı, değer sonu, değer, tırnak)]); konumlar satıra göredir."""
    m = re.match(r"\s*([^\s=\]]+)", body)
    if not m:
        return "", []
    name = m.group(1).lower()
    attrs = []
    pos = m.end()
    pattern = re.compile(r"\s*([^\s=\]]+)\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s\]]*))")
    while pos < len(body):
        a = pattern.match(body, pos)
        if not a:
            nxt = re.match(r"\s*\S+", body[pos:])
            if not nxt:
                break
            pos += nxt.end()
            continue
        quote = '"' if a.group(3) is not None else "'" if a.group(4) is not None else ""
        value = a.group(3) if a.group(3) is not None else a.group(4) if a.group(4) is not None else a.group(5) or ""
        vstart = a.start(2) + (1 if quote else 0)
        attrs.append((a.group(1).lower(), offset + vstart, offset + vstart + len(value), value, quote))
        pos = a.end()
    return name, attrs


def _tags(line: str, from_col: int = 0) -> Tuple[List[_Tag], List[Tuple[int, int]]]:
    """Satırdaki etiketler ve aralarındaki düz metin parçaları."""
    tags: List[_Tag] = []
    plain: List[Tuple[int, int]] = []
    i, text_start = from_col, from_col
    while i < len(line):
        if line.startswith("[[", i):
            i += 2
            continue
        if line[i] == "[":
            end = _scan_tag(line, i)
            if end < 0:
                i += 1
                continue
            if i > text_start:
                plain.append((text_start, i))
            name, attrs = _parse_attrs(line[i + 1:end - 1], i + 1)
            tags.append(_Tag(i, end, name, attrs))
            i = text_start = end
            continue
        i += 1
    if text_start < len(line):
        plain.append((text_start, len(line)))
    return tags, plain


def _attr_value_is_text(value: str) -> bool:
    v = value.strip()
    return bool(v) and v[0] not in "&%*" and bool(_LETTER.search(v)) and not re.search(r"\.(png|jpe?g|webp|ks|ogg|mp3|m4a|wav|gif|tjs|js)$", v, re.I)


def extract(text: str, file: str = "", dialect: str = "tyrano", character_ids: Optional[Dict[str, str]] = None
            ) -> List[KagText]:
    """Senaryo metnindeki çevrilecek birimler. character_ids: {chara_new name: jname} (TyranoScript #ad)."""
    names = dict(character_ids or {})
    out: List[KagText] = []
    lines = text.split("\n")
    block_end = ""
    in_comment = False
    speaker = ""
    for n, raw in enumerate(lines):
        line = raw.rstrip("\r")
        stripped = line.strip()
        lowered = stripped.lower()
        if in_comment:
            if "*/" in stripped:
                in_comment = False
            continue
        if block_end:
            if re.match(rf"^(?:\[\s*{block_end}\s*\]|@\s*{block_end}\b)", lowered):
                block_end = ""
            continue
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("/*"):
            in_comment = "*/" not in stripped[2:]
            continue
        if stripped.startswith("*"):
            continue
        opener = re.match(r"^(?:\[\s*|@\s*)(iscript|html)\b", lowered)
        if opener:
            closer = SCRIPT_BLOCKS[opener.group(1)]
            if not re.search(rf"(?:\[\s*{closer}\s*\]|@\s*{closer}\b)", lowered[opener.end():]):
                block_end = closer
            continue
        indent = len(line) - len(line.lstrip())
        if dialect == "tyrano" and stripped.startswith("#"):
            label = stripped[1:].split(":")[0].strip()
            speaker = names.get(label, label) if _LETTER.search(label) else ""
            if label and _LETTER.search(label) and not (_IDENT.fullmatch(label) and (label in names or label.isascii())):
                start = indent + 1 + (len(line[indent + 1:]) - len(line[indent + 1:].lstrip()))
                out.append(KagText(file, n, start, start + len(label), label, "name"))
            continue
        if stripped.startswith("@"):
            name, attrs = _parse_attrs(line[indent + 1:], indent + 1)
            out += _attr_units(file, n, name, attrs, names)
            continue
        if dialect == "kirikiri" and re.fullmatch(r"【[^【】]+】", stripped):
            label = stripped[1:-1]
            speaker = label
            out.append(KagText(file, n, indent + 1, indent + 1 + len(label), label, "name"))
            continue
        tags, plain = _tags(line, indent)
        for tag in tags:
            out += _attr_units(file, n, tag.name, tag.attrs, names)
            if tag.name == "chara_new":
                ident = next((v for a, _s, _e, v, _q in tag.attrs if a == "name"), "")
                jname = next((v for a, _s, _e, v, _q in tag.attrs if a == "jname"), "")
                if ident:
                    names[ident] = jname or ident
        visible = "".join(line[a:b] for a, b in plain).replace("[[", "[")
        if not _LETTER.search(visible):
            continue
        end = len(line.rstrip())
        source = RUBY.sub("", line[indent:end])
        out.append(KagText(file, n, indent, end, source, "dialogue", speaker))
    return out


def _attr_units(file: str, n: int, tag: str, attrs, names: Dict[str, str]) -> List[KagText]:
    wanted = TEXT_ATTRS.get(tag, ())
    units = []
    for attr, start, end, value, quote in attrs:
        if attr in wanted and _attr_value_is_text(value):
            units.append(KagText(file, n, start, end, value, "name" if attr == "jname" else "choice",
                                 quoted=quote, attr=attr))
    return units


def character_ids(texts: Iterable[str]) -> Dict[str, str]:
    """TyranoScript: [chara_new name=akane jname=あかね] tanımları (bütün dosyalardan, #akane için)."""
    found: Dict[str, str] = {}
    for text in texts:
        for line in text.split("\n"):
            if "chara_new" not in line:
                continue
            tags, _ = _tags(line)
            for tag in tags + ([] if not line.lstrip().startswith("@") else
                               [_Tag(0, 0, *_parse_attrs(line.lstrip()[1:], 0))]):
                if tag.name == "chara_new":
                    ident = next((v for a, _s, _e, v, _q in tag.attrs if a == "name"), "")
                    jname = next((v for a, _s, _e, v, _q in tag.attrs if a == "jname"), "")
                    if ident:
                        found[ident] = jname or ident
    return found


def _escape_text(value: str, source: str = "") -> str:
    """Çevirideki köşeli parantezleri tam genişliğe çevirir; yalnızca kaynakta da olan etiketler (aynı sayıda)
    etiket olarak kalır — çeviri yeni bir etiket ([yapalım] gibi) üretemez."""
    value = re.sub(r"[\r\n]+", " ", value).strip()
    allowed: Dict[str, int] = {}
    for m in PROTECTED_KAG.finditer(source):
        allowed[m.group(0)] = allowed.get(m.group(0), 0) + 1
    out, pos = [], 0
    for m in PROTECTED_KAG.finditer(value):
        out.append(value[pos:m.start()].replace("[", "［").replace("]", "］"))
        tag = m.group(0)
        if allowed.get(tag):
            allowed[tag] -= 1
            out.append(tag)
        else:
            out.append(tag.replace("[", "［").replace("]", "］"))
        pos = m.end()
    out.append(value[pos:].replace("[", "［").replace("]", "］"))
    text = "".join(out)
    if text[:1] in "*#;@":
        text = {"*": "＊", "#": "＃", ";": "；", "@": "＠"}[text[0]] + text[1:]
    if text.startswith("/*"):
        text = "／" + text[1:]
    return text


def _escape_attr(value: str, quote: str) -> str:
    value = re.sub(r"[\r\n]+", " ", value).strip().replace("[", "［").replace("]", "］")
    return value.replace('"', "”").replace("'", "’")


def apply(text: str, units: List[KagText], translations: Dict[str, str]) -> Tuple[str, int]:
    """Çevirileri senaryoya yazar; (yeni metin, değişen birim sayısı). Birimler extract() ile aynı metinden gelmeli."""
    lines = text.split("\n")
    by_line: Dict[int, List[KagText]] = {}
    for unit in units:
        target = translations.get(unit.original)
        if target and target != unit.original:
            by_line.setdefault(unit.line, []).append(unit)
    changed = 0
    for n, items in by_line.items():
        line = lines[n]
        cr = "\r" if line.endswith("\r") else ""
        body = line[:-1] if cr else line
        for unit in sorted(items, key=lambda u: u.start, reverse=True):
            target = translations[unit.original]
            if unit.attr:
                new = _escape_attr(target, unit.quoted)
                if not unit.quoted:            # tırnaksız değer boşluk içerebilir: tırnağa alınır
                    body = body[:unit.start] + f'"{new}"' + body[unit.end:]
                else:
                    body = body[:unit.start] + new + body[unit.end:]
            else:
                new = _escape_text(target, unit.original)
                if unit.context == "name":
                    new = new.replace(":", "：")
                body = body[:unit.start] + new + body[unit.end:]
            changed += 1
        lines[n] = body + cr
    return "\n".join(lines), changed


# ── Kodlama ─────────────────────────────────────────────────────────────────
def decode(raw: bytes) -> Tuple[str, str]:
    """(metin, kodlama). KiriKiri senaryoları çoğunlukla Shift-JIS ya da UTF-16LE (BOM'lu) olur."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le"), "utf-16-le-bom"
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be"), "utf-16-be-bom"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp932"), "cp932"
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8"


def encode(text: str, encoding: str, dialect: str) -> bytes:
    """Özgün kodlamayla yazar; Shift-JIS'e sığmayan harf varsa KiriKiri'nin okuyabildiği UTF-16LE (BOM) kullanılır."""
    if encoding == "utf-8-sig":
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    if encoding == "utf-16-le-bom":
        return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding == "utf-16-be-bom":
        return b"\xfe\xff" + text.encode("utf-16-be")
    if encoding == "cp932":
        try:
            return text.encode("cp932")
        except UnicodeEncodeError:
            return b"\xff\xfe" + text.encode("utf-16-le") if dialect == "kirikiri" else text.encode("utf-8")
    return text.encode("utf-8")


__all__ = ["KagText", "TEXT_ATTRS", "PROTECTED_KAG", "RUBY", "extract", "apply", "character_ids", "decode", "encode"]
