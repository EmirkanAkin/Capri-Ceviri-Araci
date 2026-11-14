"""
Capri arayüz dili.

Arayüz Türkçe yazılmıştır; İngilizce sözlük (i18n_en.EN) elle hazırlanmıştır. Diğer diller ilk seçildiklerinde
kullanıcının bulut çeviri motoruyla İngilizceden bir kez çevrilir ve veri klasöründe saklanır. Sözlük anahtarı
Türkçe metindir; "{0}" gibi yer tutucular çeviride korunmalıdır (korunmayan satır İngilizce kalır).
"""
from __future__ import annotations

import json
import locale
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from i18n_en import EN
from languages import SUPPORTED_LANGUAGES

_PLACEHOLDER = re.compile(r"\{\d+\}")


def ui_languages() -> List[Dict[str, str]]:
    return [{"code": code, "label": lang.name_native} for code, lang in SUPPORTED_LANGUAGES.items()]


def normalize(code: str) -> Optional[str]:
    """'de_DE', 'pt-BR', 'zh_TW' gibi yerel ayar adlarını Capri'nin dil koduna çevirir."""
    if not code:
        return None
    code = code.replace("_", "-")
    lowered = code.casefold()
    for known in SUPPORTED_LANGUAGES:
        if lowered == known.casefold():
            return known
    if lowered.startswith("pt-br"):
        return "pt-BR"
    if lowered.startswith("zh"):
        return "zh-TW" if any(t in lowered for t in ("tw", "hk", "hant", "mo")) else "zh-CN"
    base = lowered.split("-")[0]
    return base if base in SUPPORTED_LANGUAGES else None


def system_language() -> str:
    """Windows'un arayüz dili; desteklenmiyorsa İngilizce."""
    try:
        import ctypes
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        name = locale.windows_locale.get(lcid, "")
    except Exception:
        name = (locale.getlocale()[0] or "")
    return normalize(name) or "en"


def placeholders_ok(source: str, translated: str) -> bool:
    return sorted(_PLACEHOLDER.findall(source)) == sorted(_PLACEHOLDER.findall(translated))


class Dictionaries:
    """Dil sözlüklerini sağlar ve eksik olanları üretir."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def path(self, code: str) -> Path:
        return self.folder / f"{code}.json"

    def get(self, code: str) -> Optional[Dict[str, str]]:
        """Türkçe → boş sözlük; İngilizce → hazır; diğerleri: tamamlanmış kayıt varsa o, yoksa None (üretilmeli)."""
        if code == "tr":
            return {}
        if code == "en":
            return dict(EN)
        try:
            data = json.loads(self.path(code).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or set(EN) - set(data):
            return None          # sürüm güncellenince yeni metinler eklenir: eksikler üretilmeli
        return data

    def build(self, code: str, translate: Callable[[List[str]], Dict[str, str]]) -> Tuple[Dict[str, str], int]:
        """İngilizce metinleri hedef dile çevirir. translate(liste) → {İngilizce: çeviri}. (sözlük, başarısız sayısı)"""
        try:
            existing = json.loads(self.path(code).read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, ValueError):
            existing = {}
        missing = sorted({EN[k] for k in EN if k not in existing})
        translated = translate(missing) if missing else {}
        failed = 0
        result = dict(existing)
        for key, english in EN.items():
            if key in result:
                continue
            value = translated.get(english)
            if value and value.strip() and placeholders_ok(english, value):
                result[key] = value
            else:
                result[key] = english        # çevrilemeyen ya da yer tutucusu bozulan satır İngilizce kalır
                failed += 1
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(code).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result, failed


# Python metinleri Türkçe binlik ayırıcıyla yazar (2.575); çeviride sayı hedef dilin biçimine geçer (i18n.js ile aynı)
_THOUSANDS = {"tr": ".", "es": ".", "de": ".", "it": ".", "pt-BR": ".", "pt": ".", "nl": ".",
              "ru": " ", "uk": " ", "pl": " ", "fr": " "}
_TR_NUMBER = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def _local_number(value: str, language: str) -> Optional[str]:
    if not _TR_NUMBER.match(value):
        return None
    return f"{int(value.replace('.', '')):,}".replace(",", _THOUSANDS.get(language, ","))


def _lookup(text: str, dictionary: Dict[str, str], depth: int = 0, language: str = "en") -> Optional[str]:
    """i18n.js'teki lookup ile aynı: birebir, {0} kalıbı (değişkenler bir seviye daha çevrilir), sondaki nokta."""
    if text in dictionary:
        return dictionary[text]
    if depth > 1:
        return None
    for key, value in dictionary.items():
        if "{" not in key:
            continue
        pattern = "^" + re.sub(r"\\\{(\d+)\\\}", r"(?P<p\1>.+?)", re.escape(key)) + "$"
        match = re.match(pattern, text)
        if not match or any(" · " in v or " — " in v for v in match.groups()):
            continue
        values = {name[1:]: _local_number(v, language) or _lookup(v.strip(), dictionary, depth + 1, language) or v
                  for name, v in match.groupdict().items()}
        return re.sub(r"\{(\d+)\}", lambda m: values.get(m.group(1), ""), value)
    end = re.match(r"^(.*?[^.…])(…|\.\.\.|\.)$", text)
    inner = _lookup(end.group(1).strip(), dictionary, depth, language) if end else None   # içteki metin noktayla bitmez
    return None if inner is None else inner.rstrip(".…") + end.group(2)


def translate_text(text: str, dictionary: Dict[str, str], language: str = "en") -> str:
    """Python tarafında (ör. Windows bildirimi) arayüzle (i18n.js) aynı kurallarla çeviri: birebir, {0} kalıbı,
    sondaki nokta ve " · " ile birleşmiş parçalar."""
    if not dictionary or not text:
        return text
    key = re.sub(r"\s+", " ", text).strip()
    hit = _lookup(key, dictionary, 0, language)
    if hit is not None:
        return hit
    for sep in (" · ", " — "):
        parts = key.split(sep)
        if len(parts) < 2 or len(parts) > 12:
            continue
        out, changed, i = [], False, 0
        while i < len(parts):
            for j in range(len(parts), i, -1):
                if j - i == len(parts):
                    continue
                piece = _lookup(sep.join(parts[i:j]), dictionary, 0, language)
                if piece is not None:
                    out.append(piece)
                    changed, i = True, j
                    break
            else:
                out.append(parts[i])
                i += 1
        if changed:
            return sep.join(out)
    return text
