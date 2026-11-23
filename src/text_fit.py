"""
Capri — Metin kutusuna sığma denetimi
====================================
Türkçe (ve çoğu dil) İngilizceden %20-30 uzun olabilir. Bazı motorlar uzun satırı kesip atar:

* **RPG Maker MV/MZ:** her "Metin göster" (401) satırı mesaj penceresinde tek satırdır; sığmayan kısım görünmez.
  Varsayılan yazı tipi (M+ 1m) eş aralıklıdır, yani genişlik karakter sayısıyla iyi kestirilir. Pencere genişliği
  System.json (MZ) ve Community_Basic eklentisinden (MV), yüz görseli olan mesajlarda yüzün kapladığı yer düşülerek
  hesaplanır.
* **Ren'Py:** satırlar kendiliğinden kaydırılır; taşma dikeydir (metin kutusuna sığmayan satır sayısı). gui.rpy'deki
  yazı boyu, diyalog genişliği ve metin kutusu yüksekliği okunur.

Sonuç bir tahmindir: yalnızca çevirisi sınırı aşan ve orijinali sınırın içinde kalan satırlar işaretlenir (oyunun
zaten kaydırma eklentisi kullandığı satırlar böylece yanlış alarm vermez).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# ── Görünür genişlik ("yarım genişlik karakter" birimi) ──────────────────────────
_RPGM_WIDE_CODES = {"N": 8, "P": 8, "V": 4, "G": 2, "I": 3}          # ad, değişken, para birimi, simge
_RPGM_CODE = re.compile(r"\\([A-Za-z]+)(\[[^\]\r\n]*\])?|\\[{}.|!><^$\\]")
_RPGM_PLUGIN_TAG = re.compile(r"<[^<>\r\n]{1,40}>")
_RENPY_TAG = re.compile(r"\{[^{}\r\n]*\}")
_RENPY_VAR = re.compile(r"\[[^\[\]\r\n]*\]")
WRAP_TAGS = re.compile(r"<\s*(?:wordwrap|wrap)\s*>", re.IGNORECASE)


def char_units(text: str) -> int:
    """Doğu Asya tam genişlik karakterleri 2, diğerleri 1 birim."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text if ch not in "\r\n")


def rpgm_width(text: str) -> int:
    def code(match: re.Match) -> str:
        name = (match.group(1) or "").upper()
        return "x" * _RPGM_WIDE_CODES.get(name, 0)
    plain = _RPGM_CODE.sub(code, text)
    plain = _RPGM_PLUGIN_TAG.sub("", plain)
    return max((char_units(part) for part in plain.split("\n")), default=0)


def renpy_width(text: str) -> int:
    plain = _RENPY_TAG.sub("", text)
    plain = _RENPY_VAR.sub("xxxxxx", plain)
    return char_units(plain.replace("\\n", "\n"))


WIDTH_FUNCS = {"rpgmaker": rpgm_width, "renpy": renpy_width}


# ── RPG Maker MV/MZ ─────────────────────────────────────────────────────────
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _mv_screen_width(data_dir: Path) -> int:
    """MV: ekran genişliği Community_Basic eklentisinde (yoksa 816)."""
    path = Path(data_dir).parent / "js" / "plugins.js"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return 816
    for line in text.split("\n"):
        body = line.strip().rstrip(",")
        if '"Community_Basic"' not in body or not body.startswith("{"):
            continue
        try:
            plugin = json.loads(body)
        except ValueError:
            continue
        if plugin.get("status") is not False:
            try:
                return max(320, int(str(plugin.get("parameters", {}).get("screenWidth", "816")).strip()))
            except ValueError:
                return 816
    return 816


def rpgm_message_units(data_dir: Path, engine_type: str) -> Dict[str, int]:
    """Mesaj penceresine bir satırda sığan yarım genişlik karakter sayısı: {"plain": yüzsüz, "face": yüzlü}."""
    system = _read_json(Path(data_dir) / "System.json") or {}
    if engine_type == "mz":
        advanced = system.get("advanced") if isinstance(system.get("advanced"), dict) else {}
        box = int(advanced.get("uiAreaWidth") or advanced.get("screenWidth") or 808)
        font = int(advanced.get("fontSize") or 26)
        inner = box - 2 * 12                       # windowPadding
        plain, face = inner - 4, inner - (144 + 20)
    else:
        box = _mv_screen_width(data_dir)
        font = 28
        inner = box - 2 * 18                       # standardPadding
        plain, face = inner, inner - 168
    half = max(6.0, font / 2)
    return {"plain": max(10, int(plain // half)), "face": max(8, int(face // half))}


def rpgm_limits(texts: Iterable[Any], data_dir: Path, engine_type: str) -> Dict[str, int]:
    """{kaynak metin: en çok birim}. Yalnızca konuşma satırları (401); aynı metin birden çok yerde geçiyorsa en dar
    olanı. Konuşmacı adıyla başlayan satırların gövdesi ayrı çevrildiği için gövde de ayrıca sınır alır."""
    if engine_type not in ("mv", "mz"):
        return {}
    from engine_rpgmaker import split_speaker
    units = rpgm_message_units(data_dir, engine_type)
    limits: Dict[str, int] = {}

    def put(key: str, value: int) -> None:
        if key.strip() and value > 0:
            limits[key] = min(value, limits.get(key, value))

    for item in texts:
        if getattr(item, "context", "") != "dialogue" or WRAP_TAGS.search(item.original):
            continue
        limit = units["face"] if getattr(item, "face", False) else units["plain"]
        put(item.original, limit)
        name, body = split_speaker(item.original)
        if name is not None and body.strip():
            put(body, limit - max(0, rpgm_width(item.original) - rpgm_width(body)))
    return limits


# ── Ren'Py ──────────────────────────────────────────────────────────────────
_GUI_DEFINE = re.compile(r"^\s*define\s+gui\.(text_size|dialogue_width|textbox_height|dialogue_ypos)\s*=\s*"
                         r"(?:gui\.scale\()?\s*(\d+)", re.MULTILINE)
_SAY = re.compile(r"""^\s*#\s*(?:[A-Za-z_]\w*\s+)*(?:"|')""")


def renpy_box(game_dir: Path) -> Dict[str, int]:
    """gui.rpy'den metin kutusu ölçüleri (bulunamayanlar 1920x1080 varsayılan arayüzün değerleri)."""
    values = {"text_size": 33, "dialogue_width": 1116, "textbox_height": 278, "dialogue_ypos": 50}
    path = Path(game_dir) / "gui.rpy"
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        text = ""
    if text:
        found = {k: int(v) for k, v in _GUI_DEFINE.findall(text)}
        if "gui.init(1280" in text.replace(" ", "") and not found:
            values = {"text_size": 22, "dialogue_width": 744, "textbox_height": 185, "dialogue_ypos": 33}
        values.update(found)
    return values


def renpy_dialogue_units(game_dir: Path) -> int:
    box = renpy_box(game_dir)
    size = max(8, box["text_size"])
    per_line = box["dialogue_width"] / (size * 0.5)
    lines = max(2, math.floor((box["textbox_height"] - box["dialogue_ypos"]) / (size * 1.25)))
    return int(per_line * lines)


def renpy_limits(game_dir: Path, tl_dir: Path) -> Dict[str, int]:
    """Çeviri dosyalarındaki diyalog satırlarının (old/new arayüz metinleri değil) sınırı."""
    from engine_renpy import source_from_line
    limit = renpy_dialogue_units(game_dir)
    limits: Dict[str, int] = {}
    for path in sorted(Path(tl_dir).rglob("*.rpy")) if Path(tl_dir).is_dir() else []:
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        in_strings = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("translate ") and stripped.endswith(":"):
                in_strings = stripped.split()[-1].rstrip(":") == "strings"
                continue
            if in_strings or not _SAY.match(line):
                continue
            source = source_from_line(line)
            if source and source.strip():
                limits[source] = limit
    return limits


# ── Denetim ─────────────────────────────────────────────────────────────────
def overflowing(cache: Dict[str, str], limits: Dict[str, int], engine: str) -> Dict[str, int]:
    """{kaynak: sınır} — çevirisi sınırı aşan ve orijinali sınıra sığan satırlar."""
    width = WIDTH_FUNCS.get(engine)
    if not width or not limits:
        return {}
    found: Dict[str, int] = {}
    for source, limit in limits.items():
        target = cache.get(source)
        if not target or target == source:
            continue
        if width(target) > limit and width(source) <= limit:
            found[source] = limit
    return found


def too_long(source: str, target: str, limit: Optional[int], engine: str) -> bool:
    width = WIDTH_FUNCS.get(engine)
    return bool(width and limit and target and width(target) > limit and width(source) <= limit)


def describe(limit: int, engine: str) -> str:
    """Kalite editörüne giden açıklama (İngilizce: model talimatı İngilizce/Türkçe karışık olsa da anlaşılır)."""
    if engine == "rpgmaker":
        return f"too long for the message window: keep it to at most {limit} characters on one line"
    return f"too long for the text box: keep it to at most {limit} characters"


def save_limits(path: Path, limits: Dict[str, int]) -> None:
    from fileio import atomic_write_text
    atomic_write_text(path, json.dumps(limits, ensure_ascii=False))


def load_limits(path: Path) -> Dict[str, int]:
    data = _read_json(path)
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int)} if isinstance(data, dict) else {}


__all__ = ["char_units", "rpgm_width", "renpy_width", "rpgm_message_units", "rpgm_limits", "renpy_box",
           "renpy_dialogue_units", "renpy_limits", "overflowing", "too_long", "describe",
           "save_limits", "load_limits", "WRAP_TAGS"]
