"""
Capri — Altyazı dosyaları (.srt, .vtt, .ass / .ssa)
==================================================
Yalnızca konuşma metinleri çevrilir; sıra numaraları, zaman kodları, konum/stil ayarları ve biçim etiketleri
(<i>, {\\an8}, {\\i1}…) aynen kalır. Çıktı orijinalin yanına "ad.<dil>.uzantı" olarak yazılır (oynatıcılar bu adla
dili tanır); orijinal dosyaya dokunulmaz.

Bir altyazı satırı (cue) birden çok satırdan oluşabilir: çeviri tek birim olarak yapılır (cümle bölünmez), satır
sonları "\\n" olarak korunur. ASS'deki \\N satır sonu da aynı yoldan geçer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SUBTITLE_EXTS = (".srt", ".vtt", ".ass", ".ssa")

# Çeviride birebir korunacak parçalar: HTML biçimi (<i>, <font color=...>), ASS geçersiz kılma etiketleri ({\an8})
PROTECTED_SUB = re.compile(r"<\s*/?\s*[A-Za-z][^<>]{0,80}>|\{\\[^{}]{0,200}\}|\\[hn]")

_SRT_TIME = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")
_VTT_TIME = re.compile(r"^\s*(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3}\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3}")


@dataclass
class Cue:
    """Çevrilecek bir birim: dosyadaki satır aralığı [start, end) ve metni."""
    start: int
    end: int
    text: str


@dataclass
class SubtitleFile:
    path: Path
    kind: str                       # srt | vtt | ass
    lines: List[str]                # satır sonları olmadan
    newline: str
    encoding: str
    bom: bool
    cues: List[Cue] = field(default_factory=list)
    ass_text_field: int = -1        # ASS: Dialogue satırında Text alanının sırası


def _read(path: Path) -> Tuple[str, str, bool]:
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8", True
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16", False
    for enc in ("utf-8", "cp1254", "cp1252"):
        try:
            return raw.decode(enc), enc, False
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1", False


def _has_letters(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", PROTECTED_SUB.sub("", text)))


def load(path: Path) -> SubtitleFile:
    path = Path(path)
    text, encoding, bom = _read(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ext = path.suffix.lower()
    kind = "ass" if ext in (".ass", ".ssa") else "vtt" if ext == ".vtt" or (lines and lines[0].lstrip("﻿").startswith("WEBVTT")) else "srt"
    sub = SubtitleFile(path, kind, lines, newline, encoding, bom)
    if kind == "ass":
        _parse_ass(sub)
    else:
        _parse_blocks(sub, _VTT_TIME if kind == "vtt" else _SRT_TIME)
    return sub


def _parse_blocks(sub: SubtitleFile, timing: "re.Pattern") -> None:
    """SRT / WebVTT: zaman satırından sonraki boş olmayan satırlar o altyazının metnidir."""
    lines = sub.lines
    i = 0
    while i < len(lines):
        if timing.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j].strip() and not timing.match(lines[j]):
                j += 1
            body = lines[i + 1:j]
            if body and _has_letters("\n".join(body)):
                sub.cues.append(Cue(i + 1, j, "\n".join(body)))
            i = j
        elif sub.kind == "vtt" and lines[i].startswith(("NOTE", "STYLE", "REGION")):
            while i < len(lines) and lines[i].strip():      # yorum / stil blokları çevrilmez
                i += 1
        else:
            i += 1


def _parse_ass(sub: SubtitleFile) -> None:
    section = ""
    fields: List[str] = []
    for index, line in enumerate(sub.lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            continue
        if section != "[events]":
            continue
        if stripped.lower().startswith("format:"):
            fields = [f.strip().lower() for f in stripped.split(":", 1)[1].split(",")]
            sub.ass_text_field = fields.index("text") if "text" in fields else len(fields) - 1
            continue
        if not stripped.lower().startswith("dialogue:") or sub.ass_text_field < 0:
            continue                                         # Comment: satırları çevrilmez
        head, rest = line.split(":", 1)
        parts = rest.split(",", sub.ass_text_field)
        if len(parts) <= sub.ass_text_field:
            continue
        text = parts[sub.ass_text_field].replace("\\N", "\n")
        if _has_letters(text):
            sub.cues.append(Cue(index, index + 1, text))


def texts(sub: SubtitleFile) -> List[str]:
    return [c.text for c in sub.cues]


def render(sub: SubtitleFile, translations: Dict[str, str]) -> str:
    """Çevrilmiş dosya içeriği. Çevirisi olmayan birim orijinal hâliyle kalır."""
    lines = list(sub.lines)
    for cue in reversed(sub.cues):           # satır sayısı değişebilir: sondan başa
        target = translations.get(cue.text)
        if not target or target == cue.text:
            continue
        target = target.replace("\r\n", "\n").replace("\r", "\n")
        if sub.kind == "ass":
            line = lines[cue.start]
            head, rest = line.split(":", 1)
            parts = rest.split(",", sub.ass_text_field)
            parts[sub.ass_text_field] = target.replace("\n", "\\N")
            lines[cue.start] = head + ":" + ",".join(parts)
        else:
            body = [l for l in target.split("\n") if l.strip()] or [target.strip()]
            lines[cue.start:cue.end] = body
    return sub.newline.join(lines)


LANGUAGE_TAGS = {"en", "eng", "english", "tr", "tur", "turkish", "de", "ger", "deu", "fr", "fre", "fra", "es", "spa", "it",
                 "ita", "pt", "por", "pt-br", "ru", "rus", "ja", "jpn", "ko", "kor", "zh", "chi", "zho", "zh-cn",
                 "zh-tw", "pl", "pol", "ar", "ara", "nl", "dut", "nld", "uk", "ukr"}


def output_path(path: Path, target_lang: str) -> Path:
    """film.srt → film.tr.srt; dil eki varsa değiştirilir: film.en.srt → film.tr.srt."""
    path = Path(path)
    stem = path.stem
    head, _, tag = stem.rpartition(".")
    if head and tag.lower() in LANGUAGE_TAGS:
        stem = head
    return path.with_name(f"{stem}.{target_lang}{path.suffix}")


def save(sub: SubtitleFile, translations: Dict[str, str], target: Path) -> Path:
    data = render(sub, translations)
    target = Path(target)
    if target.resolve() == sub.path.resolve():
        raise ValueError("Çıktı orijinal dosyanın üzerine yazılamaz.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if sub.encoding == "utf-16":
        payload = data.encode("utf-16")
    else:
        # Eski kod sayfalı (cp1252…) dosyalar UTF-8 olarak yazılır: hedef dilin harfleri o sayfaya sığmayabilir.
        # ASCII dışı harf varsa BOM eklenir: eski oynatıcılar ve televizyonlar UTF-8'i ancak böyle tanır.
        payload = data.encode("utf-8")
        if sub.bom or not data.isascii():
            payload = b"\xef\xbb\xbf" + payload
    from fileio import atomic_write
    atomic_write(target, payload)
    return target


def find_files(folder: Path) -> List[Path]:
    """Klasördeki altyazılar; Capri'nin daha önce ürettiği "ad.<dil>.srt" çıktıları da kaynak olabilir, bu yüzden
    yalnızca çağıran tarafın verdiği hedef dil ekli olanlar dışarıda bırakılır (bkz. is_output)."""
    return sorted(p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() in SUBTITLE_EXTS)


def is_output(path: Path, target_lang: str) -> bool:
    return Path(path).stem.lower().endswith("." + target_lang.lower())


__all__ = ["SUBTITLE_EXTS", "PROTECTED_SUB", "Cue", "SubtitleFile", "load", "texts", "render", "output_path", "save",
           "find_files", "is_output"]
