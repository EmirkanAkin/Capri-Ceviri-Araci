"""
Capri — Evrensel Oyun Çeviri Stüdyosu
==============================================
pywebview (Microsoft Edge WebView2) arayüzü ile Python çeviri motorları
arasındaki köprü. Arayüz dosyaları `web/` klasöründedir.

Desteklenen motorlar: Ren'Py, Unity, Unreal Engine (.locres), RPG Maker MV/MZ ve JSON.
Çeviri sağlayıcıları: Gemini, OpenAI, Claude, DeepL, Ollama, OPUS-MT, NLLB-200.
"""
from __future__ import annotations

import base64
import collections
import ctypes
import getpass
import hashlib
import json
import os
import queue
import re
import socket
import shutil
import sys
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import paths
paths.harden_stdio()

import providers as prov
from backup_system import create_game_backup, list_game_backups, restore_game_backup
from engine_common import Glossary, TranslationCache, TranslationCancelled, cache_file_for
from languages import get_all_source_languages, get_all_target_languages
TARGET_CODES = {c for _l, c in get_all_target_languages()}
from library import ProjectLibrary, resolve_art
from progress import LiveEta, SpeedStore, estimate, estimate_cost, format_duration, format_rate
from languages import renpy_language_name
from fileio import atomic_write_text
import text_fit
import cloud_providers
from user_errors import describe_error

APP_VERSION = "1.0.9"
from paths import APP_DIR, FROZEN, GLOSSARY_DIR, ICON_FILE, RES_DIR, WEB_DIR, seed_user_files
SOUNDS_DIR = RES_DIR / "assets"
import gpu_runtime
gpu_runtime.activate()  # exe sürümünde sonradan kurulan PyTorch ortamı
DATA_DIR = APP_DIR / "portable_cache"
SETTINGS_FILE = DATA_DIR / "settings.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENGINE_LABELS = {
    "renpy": "Ren'Py",
    "unity": "Unity",
    "unreal": "Unreal Engine",
    "rpgmaker": "RPG Maker",
    "tyrano": "TyranoScript",
    "kirikiri": "KiriKiri",
    "godot": "Godot",
    "wolf": "WOLF RPG",
}
KAG_ENGINES = ("tyrano", "kirikiri")
MODEL_LABELS = {
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic Claude",
    "deepl": "DeepL",
    **{pid: meta["title"] for pid, meta in cloud_providers.ALL.items()},
    "local": "Yerel model (dahili)",
    "ollama": "Ollama (yerel LLM)",
    "opus": "OPUS-MT (çevrimdışı)",
    "nllb": "NLLB-200 (çevrimdışı)",
}
FULL_TRANSLATION_MODELS = tuple(MODEL_LABELS)
CLOUD_MODELS = ("openai", "anthropic", "deepl", *cloud_providers.ALL)
SPEAKER_MODELS = ("gemini", "openai", "anthropic", *cloud_providers.CHAT_PROVIDERS)   # konuşan karakteri bilen motorlar
LOCAL_MODELS = ("opus", "nllb")          # Ekran kartında çalışan çevrimdışı modeller
TURKISH_ONLY_MODELS = ("opus",)           # OPUS-MT yalnızca EN→TR; NLLB-200 çok dilli
GLOSSARY_FILES = {"general": "glossary.json", "rpgmaker": "glossary_rpgm.json", "nsfw": "glossary_nsfw.json"}
DEFAULT_SETTINGS = {
    "source": "en", "target": "tr", "model": "gemini", "nsfw": False, "backup": True, "quality_pass": False,
    "gpu_auto": True,
    "ocr_hotkey": "Ctrl+Shift+T", "pin_hotkey": "Ctrl+Shift+Y", "ocr_model": "",
    "ocr_interval": 350, "ocr_place": "below",
    "update_repo": "", "update_check": True, "ocr_speak": False, "tour_done": False, "game_tour_done": False, "tours_seen": [],
    "scan_on_start": True, "renpy_compile_check": True, "scan_folders": [], "scan_dismissed": [], "sound": True, "notify": True, "memory": True, "ui_language": None,
    "auto_names": True,        # ilk çeviride karakter adlarını tarayıp oyuna özel sözlüğe ekle
    "local_model": None,       # dahili yerel model (local_llm.CATALOG kimliği); None: ekran kartına göre önerilen
}
# Güncelleme penceresinde ve GitHub sürüm notunda gösterilir; ayrıntılar CHANGELOG.md'de. Her sürümde yenilenmeli:
# WHATS_NEW_VERSION, APP_VERSION'la aynı değilse sürüm derlemesi durur (build_exe.py --check-tag).
WHATS_NEW_VERSION = "1.0.9"
WHATS_NEW = [
    "Yeni motorlar: Godot, TyranoScript, KiriKiri ve WOLF RPG",
    "WOLF RPG: şifreli Data.wolf arşivleri ve veritabanı (eşya, beceri, karakter adları)",
    "Unity Localization tabloları ve Godot betiklerindeki metinler dosyadan çevrilir",
    "Yerel model kitaplığı: 12 model kaliteye göre sıralı; OPUS-MT ve NLLB artık PyTorch'suz",
    "Yeni bulut sağlayıcıları: DeepSeek, Mistral, Grok, Groq, OpenRouter, Qwen ve daha fazlası",
    "Toplu çeviri: oyunları sıraya ekle, teker teker çevrilsin",
    "Editör: kutuya sığmayan satırlar işaretlenir ve yapay zekâyla düzeltilir",
    "Elle yaptığın düzeltmeler ve karakter adları diğer oyunlarda da kullanılır",
    "Altyazı (.srt, .vtt, .ass) çevirisi ve ekran çevirisini sesli okuma",
    "Maskot Capri eşliğinde tanıtım turu ve her sayfa için kısa anlatım",
]
UI_PORT = 42001
QUEUE_ASK_TIMEOUT = 60      # toplu çeviride onay sorusu en çok bu kadar bekler
REVIEW_FIX_LIMIT = 400     # "İncelenmelileri düzelt" bir seferde en çok bu kadar satır gönderir
COST_CONFIRM_USD = 3.0     # ücretli API'de bu tutarın üstündeki çeviriler başlamadan onay ister
NOTO = "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/{0}/NotoSans{0}-Regular.otf"
NOTO_FONTS = {"ja": NOTO.format("JP"), "zh-CN": NOTO.format("SC"), "zh-TW": NOTO.format("TC"), "ko": NOTO.format("KR")}
FONT_MAGIC = (b"OTTO", b"\x00\x01\x00\x00", b"true", b"ttcf")


def _file_head(path: Path, size: int = 4) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def fetch_github_file(url: str, target: Path, log: Callable[[str], None] = print) -> Path:
    """github.com/<sahip>/<depo>/raw/<dal>/<yol> dosyasını indirir ve GitHub contents API'sinin verdiği boyut ve git
    blob özetiyle (SHA-1) doğrular; API'ye ulaşılamazsa (ör. saatlik sınır) en azından font imzası denetlenir.
    Dosya önce geçici ada yazılır, doğrulanınca yerine konur."""
    import requests
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/raw/([^/]+)/(.+)$", url)
    expected = None
    if match:
        owner, repo, ref, path = match.groups()
        try:
            meta = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", params={"ref": ref},
                                timeout=20, headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
            body = meta.json() if meta.status_code == 200 else None
            if isinstance(body, dict) and body.get("sha"):
                expected = (int(body.get("size") or 0), str(body["sha"]))
        except (requests.RequestException, ValueError):
            expected = None
    response = requests.get(url, timeout=120, headers={"User-Agent": "Capri"})
    response.raise_for_status()
    data = response.content
    if expected:
        blob = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        if len(data) != expected[0] or blob != expected[1]:
            raise UserError("İndirilen yazı tipi GitHub'daki dosyayla uyuşmuyor; eklenmedi. Tekrar dene.")
    else:
        log("Yazı tipi GitHub kaydıyla doğrulanamadı (API'ye ulaşılamadı); yalnızca dosya imzası denetlendi.")
    if data[:4] not in FONT_MAGIC:
        raise UserError("İndirilen dosya bir yazı tipi değil; eklenmedi.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    temp.write_bytes(data)
    temp.replace(target)
    return target
ANALYSIS_VERSION = 7     # analiz biçimi değişince eski kayıtlar yok sayılır (7: metin kutusu sınırları)
LEARN_MIN_LINES, LEARN_MIN_SECONDS = 20, 5.0
OCR_TITLES = {"select": "Capri OCR Seçim", "popup": "Capri OCR Sonuç", "pin": "Capri OCR Sabit"}
PATCH_SUFFIX = ".capripatch"


# ═══════════════════════════════════════════════════════════════════════════════
# Oyun motoru tespiti
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_here(p: Path) -> Tuple[Optional[str], Any]:
    """Tek bir klasörde motor tespiti (alt klasörlere inmez)."""
    try:
        if (p / "game").is_dir() or any(p.glob("*.rpy")) or any(p.glob("*.rpa")):
            from engine_renpy import analyze_game
            return "renpy", analyze_game(str(p), log=lambda s: None)
    except Exception:
        pass
    try:
        from engine_unity import detect_unity_game
        info = detect_unity_game(str(p))
        if info:
            return "unity", info
    except Exception:
        pass
    try:
        from engine_unreal import detect_unreal_game
        info = detect_unreal_game(str(p))
        if info:
            return "unreal", info
    except Exception:
        pass
    try:
        from engine_kag import detect_kag_game
        info = detect_kag_game(p)
        if info:
            return info.dialect, info
    except Exception:
        pass
    try:
        from engine_godot import detect_godot
        info = detect_godot(p)
        if info:
            return "godot", info
    except Exception:
        pass
    try:
        from engine_wolf import detect_wolf
        info = detect_wolf(p)
        if info:
            return "wolf", info
    except Exception:
        pass
    try:
        from engine_rpgmaker import detect_rpgmaker_game
        return "rpgmaker", detect_rpgmaker_game(str(p))
    except Exception:
        pass
    return None, None


def detect_any_game_type(path_str: str) -> Tuple[Optional[str], Any]:
    """
    Seçilen klasördeki oyun motorunu tespit eder. Klasörün kendisinde oyun
    yoksa (ör. indirme sarmalayıcısı) bir alt seviyedeki klasörlere bakar.
    """
    if not path_str:
        return None, None
    p = Path(path_str)
    if not p.is_dir():
        return None, None
    found = _detect_here(p)
    if found[0]:
        return found

    def children_of(folder: Path) -> List[Path]:
        try:
            items = [c for c in folder.iterdir() if c.is_dir() and not c.name.startswith((".", "_"))]
        except OSError:
            return []
        # Çalıştırılabilir dosya içeren alt klasörler önce denenir
        return sorted(items, key=lambda c: (not any(c.glob("*.exe")), c.name.lower()))[:12]

    # 1. kat: her alt klasör. 2. kat: yalnızca sarmalayıcıya benzeyen (en fazla 4 alt klasörlü) klasörlerin içi —
    # ör. "Oyun_v1.1.3_Windows\Oyun v1.1.3 Windows\PC\Oyun.exe". Tarama büyük klasörlerde yavaşlamaz.
    frontier = [p]
    for level in range(2):
        deeper: List[Path] = []
        for folder in frontier:
            children = children_of(folder)
            if level > 0 and len(children) > 4:
                continue
            for child in children:
                found = _detect_here(child)
                if found[0]:
                    return found
                deeper.append(child)
        frontier = deeper
    return None, None


_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯]")
_HAN = re.compile(r"[㐀-鿿]")


def detect_source_language(texts: List[str], default: str = "en") -> str:
    """Oyun metinlerinin dili (yalnızca alfabeye bakar): kana → ja, hangıl → ko, yalnızca Çince karakter → zh-CN."""
    sample = [t for t in texts[:3000] if t.strip()]
    if not sample:
        return default
    share = lambda rx: sum(1 for t in sample if rx.search(t)) / len(sample)   # noqa: E731
    if share(_KANA) > 0.2:
        return "ja"
    if share(_HANGUL) > 0.2:
        return "ko"
    if share(_HAN) > 0.3:
        return "zh-CN"
    return default


def game_root_of(game_type: str, info: Any, fallback: Path) -> Path:
    root = getattr(info, "root", None)
    return Path(root) if root else fallback


def parse_glossary_file(path: Path) -> List[List[str]]:
    import csv
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows = [r for r in csv.reader(text.splitlines()) if len(r) >= 2]
        if rows and rows[0][0].strip().lower() in ("kaynak", "source", "en", "english"):
            rows = rows[1:]
        return [[a.strip(), b.strip()] for a, b, *_ in rows if a.strip() and b.strip()]
    data = json.loads(text)
    items = data.items() if isinstance(data, dict) else (tuple(x[:2]) for x in data if isinstance(x, (list, tuple)) and len(x) >= 2)
    return [[str(a), str(b)] for a, b in items if not str(a).startswith("_") and str(a).strip() and str(b).strip()]


MEMORY_LIMIT = 20_000
_UI_TEXT = re.compile(r"[A-Za-z][A-Za-z'&\- ]*")


def is_ui_text(source: str) -> bool:
    """Oyunlar arası paylaşılabilecek kısa arayüz metni mi? ("Save", "Load Game", "Start Day")
    Cümle, noktalama, etiket ve değişken içerenler bağlama göre değişebileceğinden paylaşılmaz."""
    text = source.strip()
    return (text == source and 2 <= len(text) <= 24 and len(text.split()) <= 3
            and bool(_UI_TEXT.fullmatch(text)) and text[0].isupper())


def quick_line_count(game: Dict[str, Any]) -> Optional[int]:
    """Tarama önerileri için satır tahmini (salt okunur). Unity'de açık metin tabloları, Utage ve I2 okunur;
    Unreal'da yalnızca açık .locres dosyaları (paketli olanlar dış araç gerektirir, analizde sayılır)."""
    root = Path(game["path"])
    quiet = lambda s: None   # noqa: E731
    if game["engine"] == "renpy":
        game_dir = root / "game" if (root / "game").is_dir() else root
        return estimate_renpy_text(game_dir).get("unique") or None
    if game["engine"] == "rpgmaker":
        from engine_rpgmaker import detect_rpgmaker_game, extract_texts_mv_mz
        info = detect_rpgmaker_game(root)
        if info.engine_type in ("mv", "mz"):
            return len({t.original for t in extract_texts_mv_mz(info.data_dir, log=quiet)}) or None
    if game["engine"] == "unity":
        from engine_unity import detect_unity_game, extract_texts_unity
        info = detect_unity_game(root)
        if info is not None:
            return len({t.original for t in extract_texts_unity(info, log=quiet) if t.original.strip()}) or None
    if game["engine"] == "unreal":
        from engine_unreal import detect_unreal_game, extract_texts_unreal
        info = detect_unreal_game(root)
        if info is not None and info.locres_files:
            return len({t.original for t in extract_texts_unreal(info, log=quiet) if t.original.strip()}) or None
    if game["engine"] in KAG_ENGINES:
        from engine_kag import detect_kag_game, extract_texts
        info = detect_kag_game(root)
        if info is not None and not info.encrypted:
            return len({t.original for t in extract_texts(info, log=quiet)}) or None
    if game["engine"] == "godot":
        import engine_godot
        info = engine_godot.detect_godot(root)
        if info is not None and not info.encrypted:
            return len({t.original for t in engine_godot.extract_texts(info, log=quiet)}) or None
    if game["engine"] == "wolf":
        import engine_wolf
        info = engine_wolf.detect_wolf(root)
        if info is not None and not info.archived:
            return len({t.original for t in engine_wolf.extract_texts(info, log=quiet)}) or None
    return None


def readable_folder_name(root: Path) -> str:
    """Klasör adından oyun adı: game/ gibi genel adlarda üst klasör; 'Oyun.Adi.3' → 'Oyun Adi 3'."""
    root = Path(root)
    name = root.parent.name if root.name.lower() in ("game", "games", "data", "bin") and root.parent.name else root.name
    return re.sub(r"[._]+", " ", name).strip() if " " not in name else name


def game_title_of(game_type: str, info: Any, root: Path) -> str:
    if game_type == "unity" and getattr(info, "game_title", ""):
        return info.game_title
    if game_type == "rpgmaker":
        try:
            system = json.loads((info.data_dir / "System.json").read_text(encoding="utf-8-sig"))
            if system.get("gameTitle"):
                return str(system["gameTitle"])
        except Exception:
            pass
        try:  # XP / VX / VX Ace: System.r*data* (Ruby Marshal)
            import rgss_marshal
            from engine_rpgmaker import RGSS_EXT
            path = info.data_dir / f"System{RGSS_EXT.get(info.engine_type, '.rvdata2')}"
            title = rgss_marshal.loads(path.read_bytes()).get("@game_title")
            if title is not None and title.text.strip():
                return title.text.strip()
        except Exception:
            pass
        try:  # şifreli arşivli oyunlar: Game.ini → Title=
            raw = (Path(root) / "Game.ini").read_bytes()
            for enc in ("utf-8", "cp932", "cp1252"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            title = re.search(r"^\s*Title\s*=\s*(.+?)\s*$", text, re.MULTILINE)
            if title:
                return title.group(1)
        except Exception:
            pass
    return readable_folder_name(root)


def cache_path_for(root: Path, engine: str, model: str, target: str) -> Path:
    """
    Oyun + motor + model için önbellek dosyası. Eski arayüzle aynı adlandırma
    korunur, böylece daha önce yapılan (ücretli) çeviriler yeniden kullanılır.
    """
    base = cache_file_for(root, DATA_DIR)  # .../cache/<kimlik>.json
    lang = "" if target == "tr" else f"_{target}"
    if engine == "renpy":
        name = base.stem + ("" if model == "opus" else f"_{model}") + lang
    else:
        tag = "rpgm" if engine == "rpgmaker" else engine
        name = f"{base.stem}_{tag}_{model}{lang}"
        legacy = base.parent / f"{name}.json.json"  # eski sürümün çift uzantı hatası
        current = base.parent / f"{name}.json"
        if legacy.exists() and not current.exists():
            legacy.replace(current)
    return base.parent / f"{name}.json"


CHARACTER_DEFINE = re.compile(
    r"""^\s*define\s+([A-Za-z_]\w*)\s*=\s*(?:Dynamic)?Character\(\s*(?:_\(\s*)?(?:u|r)?(["'])(.+?)\2""", re.M)


def project_glossary_path(root: Path) -> Path:
    return DATA_DIR / "glossaries" / f"{cache_file_for(root, DATA_DIR).stem}.json"


def _renpy_script_texts(game_dir: Path) -> List[str]:
    """Açık .rpy dosyalarının ve RPA arşivlerindeki .rpy'lerin içeriği (tl/ hariç)."""
    from engine_renpy import read_rpa_index
    texts: List[str] = []
    for path in game_dir.rglob("*.rpy"):
        if "tl" not in {part.lower() for part in path.relative_to(game_dir).parts}:
            try:
                texts.append(path.read_text(encoding="utf-8-sig", errors="ignore"))
            except OSError:
                pass
    for archive in game_dir.glob("*.rpa"):
        try:
            _version, index = read_rpa_index(archive)
            with archive.open("rb") as handle:
                for name, chunks in index.items():
                    if not name.endswith(".rpy") or name.replace("\\", "/").startswith("tl/"):
                        continue
                    data = b""
                    for offset, length, prefix in chunks:
                        handle.seek(offset)
                        data += prefix + handle.read(length - len(prefix))
                    texts.append(data.decode("utf-8", errors="ignore"))
        except Exception:
            continue
    return texts


RENPY_SAY = re.compile(r'''^[ \t]*(?:[A-Za-z_]\w*[ \t]+)?"((?:[^"\\\n]|\\.)+)"''', re.MULTILINE)
RPYC_BYTES_PER_LINE = 150      # yalnızca derlenmiş betik varsa kaba ölçek


# tl dosyasındaki çeviri satırları: `e "..."`, `"..."`, `new "..."` — `old "..."` ve `# ...` (orijinal) hariç
RENPY_TL_SOURCE = re.compile(r'''^[ \t]*(?!old[ \t])(?:[A-Za-z_]\w*[ \t]+)?"((?:[^"\\\n]|\\.)+)"''', re.MULTILINE)
_MEDIA_FILE = re.compile(r"\.(?:ogg|mp3|wav|opus|flac|png|jpe?g|webp|webm|avi|mp4|ttf|otf)$", re.IGNORECASE)


def _is_renpy_text(value: str) -> bool:
    """Diyalog mu? Herhangi bir alfabede (Rusça, Japonca…) en az iki harf; dosya yolu değil."""
    return bool(re.search(r"[^\W\d_]{2}", value)) and not _MEDIA_FILE.search(value.strip())


def _renpy_english_lines(game_dir: Path) -> set:
    """Oyunun hazır İngilizce çevirisi (tl/english, açık ya da RPA içinde) varsa onun diyalog + arayüz metinleri."""
    from engine_renpy import language_reference
    lines: set = set()
    with language_reference(game_dir, "english", log=lambda _message: None) as folder:
        if folder is None:
            return lines
        for path in folder.rglob("*.rpy"):
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            lines.update(m.group(1) for m in RENPY_TL_SOURCE.finditer(text) if _is_renpy_text(m.group(1)))
    return lines


def estimate_renpy_text(game_dir: Path) -> Dict[str, Any]:
    """Ren'Py'de kesin liste çeviri başlarken üretilir; analizde süre tahmini için diyalog sayısı kestirilir."""
    lines: set = set()
    for text in _renpy_script_texts(game_dir):
        lines.update(m.group(1) for m in RENPY_SAY.finditer(text) if _is_renpy_text(m.group(1)))
    english = _renpy_english_lines(game_dir)
    if english and len(english) >= len(lines) * 0.5:
        lines = english   # oyun başka dilde yazılmış, hazır İngilizcesi var: çeviri o metinlerden yapılır
    if lines:
        chars = sum(len(line) for line in lines)
        return {"unique": len(lines), "chars": chars, "words": sum(len(line.split()) for line in lines), "exact": False}
    size = sum(p.stat().st_size for p in game_dir.rglob("*.rpyc") if "tl" not in {x.lower() for x in p.relative_to(game_dir).parts})
    approx = size // RPYC_BYTES_PER_LINE
    return {"unique": approx, "chars": approx * 45, "words": approx * 8, "exact": False} if approx else {}


def renpy_character_map(game_dir: Path) -> Dict[str, str]:
    """{karakter değişkeni: görünen ad} — define e = Character("Elena")."""
    found: Dict[str, str] = {}
    for text in _renpy_script_texts(game_dir):
        for match in CHARACTER_DEFINE.finditer(text):
            found.setdefault(match.group(1), match.group(3).strip())
    return found


def scan_renpy_characters(game_dir: Path) -> List[str]:
    """Ren'Py `define x = Character("Ad")` tanımlarını açık .rpy dosyalarından ve RPA arşivlerinden toplar."""
    names: List[str] = []
    for text in _renpy_script_texts(game_dir):
        for match in CHARACTER_DEFINE.finditer(text):
            name = match.group(3).strip()
            if name and "[" not in name and "{" not in name and name not in names and len(name) <= 40:
                names.append(name)
    return names


# Karakter tanımlarında sık geçen, çevrilmesi gereken genel sözcükler (özel ad değil)
ROLE_WORDS = {
    "mom", "mother", "dad", "father", "mum", "mama", "papa", "sister", "brother", "sis", "bro", "aunt", "uncle", "grandma",
    "grandpa", "grandmother", "grandfather", "son", "daughter", "wife", "husband", "girlfriend", "boyfriend", "friend",
    "guard", "soldier", "knight", "king", "queen", "prince", "princess", "lord", "lady", "sir", "madam", "master", "maid",
    "butler", "servant", "teacher", "student", "professor", "doctor", "nurse", "boss", "manager", "officer", "police",
    "policeman", "detective", "priest", "nun", "monk", "witch", "wizard", "mage", "hero", "heroine", "villain", "demon",
    "angel", "ghost", "monster", "man", "woman", "boy", "girl", "child", "kid", "baby", "old", "young", "stranger",
    "voice", "narrator", "announcer", "unknown", "someone", "everyone", "all", "both", "player", "you", "me", "crowd",
    "customer", "clerk", "waiter", "waitress", "bartender", "driver", "receptionist", "shopkeeper", "merchant", "villager",
    "townsperson", "guest", "host", "neighbor", "neighbour", "classmate", "roommate", "coworker", "colleague", "thug",
    "bandit", "thief", "assistant", "secretary", "scientist", "guy", "dude", "gentleman", "mysterious", "girls",
    "boys", "men", "women", "people", "group", "phone", "tv", "radio", "computer", "system", "note", "letter", "sign",
}
_NAME_WORD = r"[A-ZÀ-ÖØ-Þ](?:[a-zà-öø-ÿ]+|['’-][A-ZÀ-ÖØ-Þ]?[a-zà-öø-ÿ]+)+"
_NAME_SHAPE = re.compile(rf"{_NAME_WORD}(?: {_NAME_WORD})?")
LATIN_TARGETS = {"tr", "en", "es", "de", "fr", "it", "pt-BR", "pt", "pl", "nl", "id", "vi", "cs", "ro", "hu", "sv",
                 "da", "no", "fi"}


def looks_like_name(name: str) -> bool:
    """"Elena", "Mary Jane" gibi özel adlar; "Mom", "Old Man", "???" gibi çevrilmesi gerekenler değil."""
    name = str(name or "").strip()
    if len(name) < 2 or len(name) > 30 or not _NAME_SHAPE.fullmatch(name):
        return False
    return not any(part.casefold().strip("'’") in ROLE_WORDS for part in name.split())


def scan_rpgmaker_characters(data_dir: Path) -> List[str]:
    names: List[str] = []
    actors = _read_json(data_dir / "Actors.json", [])
    for actor in actors if isinstance(actors, list) else []:
        if isinstance(actor, dict):
            for key in ("name", "nickname"):
                value = str(actor.get(key) or "").strip()
                if value and value not in names:
                    names.append(value)
    return names


UNITY_LOCALIZATION_NOTE = ("Oyun, Unity'nin Localization paketini kullanıyor; dize tabloları dosyadan çevrilir. Veri "
                           "dosyası tablolarında Türkçe oyunun dil listesine eklenir; paketli tablolarda oyunda English'i "
                           "seçince Türkçe görünür.")
OUTDATED_NOTE = ("Oyun dosyaları çeviriden sonra değişmiş (oyun güncellenmiş olabilir); çeviri kaybolmuş ya da yeni satırlar "
                 "eklenmiş olabilir. Yeniden uygularken önbellekteki satırlar ücretsizdir, yalnızca yeni satırlar çevrilir.")


def game_files_stamp(root: str | Path, engine: str) -> Optional[str]:
    """Oyunun ana veri dosyalarının (ad, boyut, değişme zamanı) parmak izi. Capri'nin kendi yazdığı çeviri klasörleri,
    yedekler ve Ren'Py'nin her açılışta yeniden yazdığı .rpyc dosyaları dahil edilmez."""
    root = Path(root)
    if engine == "unity":
        files = [f for d in root.glob("*_Data") for f in list(d.glob("*.assets")) + list(d.glob("data.unity3d"))]
    elif engine == "rpgmaker":
        files = [f for pattern in ("www/data/*.json", "data/*.json", "www/js/plugins.js", "js/plugins.js", "Data/*.rvdata2", "Data/*.rvdata", "Data/*.rxdata",
                                   "Game.rgss3a", "Game.rgss2a", "Game.rgssad") for f in root.glob(pattern)]
    elif engine == "renpy":
        files = [f for f in list(root.glob("game/**/*.rpa")) + list(root.glob("game/**/*.rpy"))
                 if "tl" not in f.relative_to(root / "game").parts[:1] and not f.name.lower().startswith(("zz_", "turkish_support"))]
    elif engine == "unreal":
        files = [f for ext in ("pak", "utoc", "ucas") for f in root.glob(f"**/Content/Paks/*.{ext}") if "~mods" not in f.parts]
    elif engine in KAG_ENGINES:
        from engine_kag import files_stamp_paths
        files = files_stamp_paths(root)
    elif engine == "godot":
        from engine_godot import files_stamp_paths
        files = files_stamp_paths(root)
    elif engine == "wolf":
        from engine_wolf import files_stamp_paths
        files = files_stamp_paths(root)
    else:
        return None
    files = sorted({f for f in files if f.is_file() and "_capri_backups" not in f.parts})[:5000]
    if not files:
        return None
    digest = hashlib.sha1()
    for f in files:
        st = f.stat()
        digest.update(f"{f.relative_to(root).as_posix()}|{st.st_size}|{int(st.st_mtime)}\n".encode("utf-8"))
    return digest.hexdigest()



class TermRules:
    """Oyuna özel terim kuralları. Bütün terimler tek bir birleşik desenle önce elenir (satırların çoğunda hiçbir terim
    geçmez); yalnızca eşleşen satırlarda, metninde geçen terimlerin kendi kuralı denetlenir. Sonuç terim başına ayrı
    arayan eski yöntemle birebir aynıdır, ama satır × terim kadar regex araması yapılmaz."""

    def __init__(self, terms: Dict[str, str]):
        self.rules: List[Tuple["re.Pattern", str, str]] = []
        sources = set()
        for source, target in (terms or {}).items():
            source, target = str(source).strip(), str(target or "").strip()
            if len(source) < 3 or not target:
                continue
            flags = 0 if source[:1].isupper() else re.IGNORECASE
            self.rules.append((re.compile(r"(?<![\w])" + re.escape(source) + r"(?![\w])", flags), target.casefold(),
                               source.casefold()))
            sources.add(source)
        # Ön eleme özgün yazımla kurulur: "İ".casefold() iki karakterdir ve büyük/küçük harf duyarsız regex onu "İ" ile eşleştirmez
        alternatives = sorted((re.escape(x) for x in sources), key=len, reverse=True)
        self.any = re.compile(r"(?<![\w])(?:" + "|".join(alternatives) + r")(?![\w])", re.IGNORECASE) \
            if alternatives else None

    def __bool__(self) -> bool:
        return bool(self.rules)

    def lost(self, src: str, tr: str) -> bool:
        if not self.rules or not tr or tr == src or not self.any.search(src):
            return False
        lowered, folded = src.casefold(), tr.casefold()
        return any(key in lowered and target not in folded and rx.search(src) for rx, target, key in self.rules)


def term_rules(terms: Dict[str, str]) -> TermRules:
    return TermRules(terms)


def term_lost(src: str, tr: str, rules: Optional[TermRules]) -> bool:
    return bool(rules) and rules.lost(src, tr)


def term_inconsistencies(cache: Dict[str, str], terms: Dict[str, str], limit: int = 5000) -> List[str]:
    """Oyuna özel terimler (karakter adları, yer adları…) kaynakta geçip çeviride hiç geçmiyorsa o satırlar.
    Türkçe ekler sorun olmaz ("Elena'ya" içinde "Elena" var). Genel sözlük kullanılmaz: "Save" gibi sözcükler cümle
    içinde başka türlü çevrilebilir."""
    rules = term_rules(terms)
    if not rules:
        return []
    found = []
    for src, tr in cache.items():
        if term_lost(src, tr, rules):
            found.append(src)
            if len(found) >= limit:
                break
    return found


def _mtime_ns(path: Optional[Path]) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns if path else None
    except OSError:
        return None


def review_path_for(cache_path: Path) -> Path:
    return DATA_DIR / "reports" / f"{cache_path.stem}.review.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any, indent: Any = 2) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent))   # elektrik kesilirse yarım kalmaz


def _n(value: Any) -> str:
    """Türkçe binlik ayırıcı: 21529 → 21.529 (arayüz başka dildeyse i18n.js sayıyı o dilin biçimine çevirir)"""
    return f"{int(value or 0):,}".replace(",", ".")


def _resolve_shortcut(path: str) -> Optional[str]:
    """Windows .lnk kısayolunun hedefini çözer (PowerShell / WScript.Shell)."""
    import subprocess
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(New-Object -ComObject WScript.Shell).CreateShortcut('{path}').TargetPath"],
            capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip() or None
    except Exception:
        return None


def load_settings() -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings["model"] = prov.load_provider_config().active_provider or "gemini"
    first_run = not SETTINGS_FILE.exists()
    saved = _read_json(SETTINGS_FILE, {})
    settings.update(saved if isinstance(saved, dict) else {})
    if not settings.get("ui_language"):
        # Yeni kullanıcı: arayüz ve hedef dil Windows'un dilinden. Mevcut kullanıcı Türkçe kullanıyordu: değişmez.
        import i18n
        settings["ui_language"] = i18n.system_language() if first_run else "tr"
        if first_run and settings["ui_language"] in TARGET_CODES:
            settings["target"] = settings["ui_language"]
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


def free_ui_port(start: int = UI_PORT, tries: int = 50) -> int:
    """
    Arayüzü sunan yerel port. Sabit kalmalı (yerel veriler adrese bağlıdır), ama Windows aynı porta ikinci dinleyiciye
    izin verir: başka bir Capri açıksa yeni pencere onun eski arayüzünü yüklerdi. Dolu port sırası atlanır.
    """
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0    # pywebview kendi seçsin


def refresh_web_cache(web_dir: Path, storage: Path, version: str) -> bool:
    """
    Arayüz sabit bir yerel adresten sunulur ve WebView2 dosyaları önbellekler: güncellemeden sonra yeni kod eski
    index.html ile açılabilirdi. Arayüz dosyaları değişince tarayıcı önbelleği temizlenir (yerel veriler korunur).
    """
    import hashlib
    import shutil
    digest = hashlib.sha1(version.encode("utf-8"))
    for path in sorted(web_dir.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8"))
    stamp = storage / "web_version.txt"
    current = digest.hexdigest()
    try:
        if stamp.read_text(encoding="utf-8") == current:
            return False
    except OSError:
        pass
    for profile in storage.glob("**/Default"):
        for name in ("Cache", "Code Cache", "GPUCache"):
            shutil.rmtree(profile / name, ignore_errors=True)
    storage.mkdir(parents=True, exist_ok=True)
    stamp.write_text(current, encoding="utf-8")
    return True


class UserError(Exception):
    """Kullanıcıya olduğu gibi gösterilecek, beklenen hata."""


# ═══════════════════════════════════════════════════════════════════════════════
# Arayüz olay kanalı
# ═══════════════════════════════════════════════════════════════════════════════

class UiChannel:
    """
    Python → JavaScript olaylarını toplar ve tek çağrıda iletir. Boştayken uyur; olay gelince en geç 40 ms'de
    gönderir. Binlerce log satırı veya ilerleme güncellemesi arayüzü dondurmaz.
    """
    LOG_LIMIT = 1 << 20    # teknik günlük dosyası bu boyutu geçince bir öncekinin yerine taşınır

    def __init__(self):
        self.window = None
        self.log_file: Optional[Path] = None
        self._queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._progress: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="ui-channel").start()

    def emit(self, event: str, payload: Any = None) -> None:
        self._queue.put((event, payload))
        self._wake.set()

    def log(self, message: Any) -> None:
        text = str(message)
        try:  # günlük yazmak hiçbir koşulda işi düşürmemeli
            print(f"[Capri] {text}")
        except Exception:
            pass
        self._queue.put(("log", text))
        self._wake.set()

    def progress(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._progress = payload
        self._wake.set()

    def clear_progress(self) -> None:
        with self._lock:
            self._progress = None

    def _write_log_file(self, lines: List[str]) -> None:
        if not self.log_file or not lines:
            return
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            if self.log_file.exists() and self.log_file.stat().st_size > self.LOG_LIMIT:
                self.log_file.replace(self.log_file.with_suffix(".old.log"))
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with self.log_file.open("a", encoding="utf-8", errors="replace") as handle:
                handle.writelines(f"{stamp} {line}\n" for line in lines)
        except OSError:
            pass

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            time.sleep(0.04)   # aynı anda gelen olayları tek çağrıda topla
            self._wake.clear()
            events: List[Dict[str, Any]] = []
            logs: List[str] = []
            while True:
                try:
                    event, payload = self._queue.get_nowait()
                except queue.Empty:
                    break
                if event == "log":
                    logs.append(payload)
                    self._write_log_file([payload])
                    continue
                if logs:
                    events.append({"e": "log", "d": logs})
                    logs = []
                events.append({"e": event, "d": payload})
            if logs:
                events.append({"e": "log", "d": logs})
            with self._lock:
                if self._progress is not None:
                    events.append({"e": "progress", "d": self._progress})
                    self._progress = None
            if events and self.window is not None:
                script = f"window.OT && OT.receive({json.dumps(events, ensure_ascii=False)})"
                try:
                    runner = getattr(self.window, "run_js", None) or self.window.evaluate_js
                    runner(script)
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# JavaScript köprüsü
# ═══════════════════════════════════════════════════════════════════════════════

class CapriBridge:
    """
    `window.pywebview.api.<metot>()` ile çağrılır. pywebview, js_api nesnesinin
    herkese açık niteliklerini dışa aktardığı için iç durum `_` ile başlar.
    """

    def __init__(self):
        self._ui = UiChannel()
        self._ui.log_file = DATA_DIR / "capri.log"
        self._window = None
        self._library = ProjectLibrary()
        self._library.recover_interrupted()
        self._settings = load_settings()
        self._ui_dict: Dict[str, str] = {}      # arayüz dili sözlüğü (Windows bildirimleri de çevrilir)
        self._speeds = SpeedStore(DATA_DIR / "speeds_v2.json")   # v2: Gemini hızlandı, eski ölçümler geçersiz
        self._editor_cache: Optional[Tuple[Tuple[str, int], Dict[str, str], Dict[str, bool]]] = None
        self._editor_fold: Optional[Tuple[Dict[str, str], Dict[str, Tuple[str, str]]]] = None
        self._review_ctx: Optional[Tuple[Tuple[Any, ...], Any]] = None   # editör: incelenmeli satır bağlamı
        self._fit_missing: set = set()                 # çeviri klasörü olmayan Ren'Py oyunları (sınır hesaplanamaz)
        self._queue: List[Dict[str, Any]] = []      # toplu çeviri sırası (yerinde değişir, _queue_lock ile korunur)
        self._queue_lock = threading.Lock()
        self._queue_running = False
        self._queue_last_ask = ""
        self._analysis_thread: Optional[threading.Thread] = None
        self._scan_running = False
        self._scan_found: List[Dict[str, str]] = _read_json(DATA_DIR / "scan.json", [])
        self._translating = False
        self._game: Optional[Dict[str, Any]] = None
        self._busy = False
        self._busy_lock = threading.Lock()
        self._cancel = threading.Event()
        self._eta = LiveEta()
        self._eta_prior: Optional[float] = None    # saniye/satır: ilk parti bitene kadarki tahmin
        from taskbar import TaskbarProgress
        from ocr import own_window
        self._taskbar = TaskbarProgress(lambda: own_window("Capri"))   # görev çubuğu simgesindeki ilerleme
        self._progress_unit = "satır"
        self._confirms: Dict[str, Tuple[threading.Event, List[bool]]] = {}
        self._art: Dict[str, Dict[str, Any]] = {}
        self._gpu: Optional[Dict[str, Any]] = None
        self._stats_cache: Dict[str, Tuple[float, int]] = {}
        self._gpu_opt: Optional[Dict[str, Any]] = None
        self._gpu_lock = threading.Lock()
        # Ekran çevirisi (OCR)
        self._ocr_win: Dict[str, Any] = {}
        self._screen_scale = 1.0
        self._screen_size = (1920, 1080)
        self._ocr_shot = None
        self._ocr_mode = "once"
        self._ocr_selecting = False
        self._ocr_restore_main = False
        self._ocr_last_rect: Optional[Tuple[int, int, int, int]] = None
        self._ocr_anchor: Dict[str, Any] = {}
        self._ocr_cache: "collections.OrderedDict[Tuple[str, str, str], str]" = collections.OrderedDict()
        self._ocr_history: "collections.deque[Dict[str, Any]]" = collections.deque(maxlen=50)   # yalnızca bellekte
        self._pin_watcher = None
        self._pin_pending: Optional[Tuple[str, float]] = None
        self._pin_busy = False
        self._hotkeys = None

    def set_window(self, window) -> None:
        self._window = window
        self._ui.window = window

    # ── İç yardımcılar ───────────────────────────────────────────────────────
    def _log(self, message: Any) -> None:
        self._ui.log(message)

    def _status(self, text: str, tone: str = "info") -> None:
        self._ui.emit("status", {"text": text, "tone": tone})

    def _toast(self, text: str, tone: str = "info") -> None:
        self._ui.emit("toast", {"text": text, "tone": tone})

    def _notify(self, title: str, text: str = "", tone: str = "info", icon: str = "bell",
                action: Optional[Dict[str, str]] = None) -> None:
        """Bildirim merkezine kalıcı, okunabilir bir kayıt ekler (ve kısa bildirim gösterir)."""
        self._log(f"{'✔' if tone == 'ok' else '⚠' if tone in ('warn', 'error') else '•'} {title}"
                  + (f" — {text}" if text else ""))
        self._ui.emit("notify", {
            "id": uuid.uuid4().hex[:10], "title": title, "text": text, "tone": tone,
            "icon": icon, "time": time.time(), "action": action,
            "project": self._game["title"] if self._game else "",
        })

    def _progress(self, done: int, total: int) -> None:
        if self._cancel.is_set():
            raise TranslationCancelled()
        if total <= 0:
            return
        if done <= 0 or self._eta.total != max(total, 1) or done < self._eta.done:
            self._eta.start(total)
        self._eta.update(done)
        self._taskbar.value(done, total)
        eta = self._eta.eta_seconds(self._eta_prior)
        self._ui.progress({
            "done": done,
            "total": total,
            "pct": round(min(100.0, done * 100.0 / total), 1),
            "eta": format_duration(eta),
            "eta_s": None if eta is None else round(eta, 1),
            "elapsed_s": round(self._eta.elapsed(), 1),
            "rate": format_rate(self._eta.rate(), self._progress_unit),
            "unit": self._progress_unit,
        })

    def _stage(self, key: str, label: str) -> None:
        """Çevirinin hangi adımda olduğunu arayüze bildirir (Yedek · Hazırlık · Çeviri · Yazma)."""
        self._ui.clear_progress()
        self._taskbar.busy()
        self._ui.emit("stage", {"key": key, "label": label})
        self._log(label)

    def _attention(self, sound: str = "done", title: str = "", text: str = "") -> None:
        """Çeviri bitti/başarısız: Capri'nin ince bildirim sesi; uygulama arka plandaysa görev çubuğu yanıp söner
        ve (ayarlarda açıksa) Windows bildirimi gösterilir."""
        from ocr import attention, balloon, play_sound
        if self._settings.get("sound", True):
            play_sound(SOUNDS_DIR / f"{sound}.wav")
        if title and self._settings.get("notify", True):
            import i18n
            lang = self._settings.get("ui_language") or "tr"
            balloon(i18n.translate_text(title, self._ui_dict, lang), i18n.translate_text(text, self._ui_dict, lang), ICON_FILE)
        attention("Capri")

    def _notice(self, text: str) -> None:
        """İlerleme panelinin altındaki kısa durum notu (ör. sağlayıcı hız sınırı)."""
        self._ui.emit("notice", {"text": text})

    def _ask(self, title: str, text: str, timeout: float = 300.0) -> bool:
        """Arayüzde onay penceresi açar ve kullanıcının yanıtını bekler. Toplu çeviri sürerken (gözetimsiz çalışma)
        en çok QUEUE_ASK_TIMEOUT saniye beklenir; yanıt gelmezse "hayır" sayılır ve soru oyunun notuna yazılır."""
        if self._queue_running:
            timeout = min(timeout, QUEUE_ASK_TIMEOUT)
            self._queue_last_ask = title
        cid = uuid.uuid4().hex
        event, answer = threading.Event(), [False]
        self._confirms[cid] = (event, answer)
        self._ui.emit("confirm", {"id": cid, "title": title, "text": text})
        event.wait(timeout)
        self._confirms.pop(cid, None)
        return answer[0]

    def _project_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(item)
        art = self._art.get(ProjectLibrary.key(item["path"]))
        if art:
            data["poster"], data["hero"] = art.get("poster"), art.get("hero")
        data["engine_label"] = ENGINE_LABELS.get(item.get("engine", ""), "Bilinmiyor")
        data["active"] = bool(self._game and ProjectLibrary.key(self._game["root"]) == ProjectLibrary.key(item["path"]))
        return data

    def _emit_project(self, path: str | Path) -> None:
        item = self._library.get(path)
        if item:
            self._ui.emit("project", self._project_payload(item))

    def _load_art_async(self, item: Dict[str, Any]) -> None:
        key = ProjectLibrary.key(item["path"])
        if key in self._art:
            return
        self._art[key] = {}

        def work():
            try:
                art = resolve_art(item["path"], item.get("engine", ""), item.get("title", ""), item.get("appid"))
            except Exception as exc:
                print(f"[Capri] Kapak görseli bulunamadı: {exc}")
                return
            self._art[key] = art
            fields: Dict[str, Any] = {"appid": art.get("appid")}
            if art.get("name") and not item.get("title_locked"):
                fields["title"] = art["name"]
                if self._game and ProjectLibrary.key(self._game["root"]) == key:
                    self._game["title"] = art["name"]
            self._library.upsert(item["path"], touch=False, **fields)   # kapak yüklemek "işlem" sayılmaz
            self._emit_project(item["path"])

        threading.Thread(target=work, daemon=True, name="art").start()

    def _emit_stats(self) -> None:
        threading.Thread(target=lambda: self._ui.emit("stats", self.get_stats()), daemon=True, name="stats").start()

    def _run_task(self, label: str, fn: Callable[[], None]) -> bool:
        with self._busy_lock:
            if self._busy:
                self._toast("Devam eden bir işlem var, lütfen bitmesini bekleyin.", "warn")
                return False
            self._busy = True
        self._cancel.clear()
        self._translating = False
        self._progress_unit = "satır"
        self._eta_prior = None
        self._eta = LiveEta()
        self._ui.clear_progress()
        try:
            import engine_renpy
            engine_renpy.NOTICE = self._notice
        except Exception:
            pass
        self._ui.emit("busy", {"busy": True, "label": label})
        self._taskbar.busy()

        def work():
            outcome = self._taskbar.clear
            try:
                fn()
            except TranslationCancelled:
                outcome = self._taskbar.paused
                self._task_cancelled(label)
            except UserError as exc:
                outcome = self._taskbar.error
                self._task_failed(label, {"title": f"{label} yapılamadı", "hint": str(exc), "detail": "",
                                          "action": getattr(exc, "action", None)}, "warn")
            except Exception as exc:
                outcome = self._taskbar.error
                self._safely(lambda: self._log(traceback.format_exc()))
                self._task_failed(label, describe_error(exc), "error")
            finally:
                self._translating = False
                with self._busy_lock:
                    self._busy = False
                self._safely(outcome)
                self._ui.emit("busy", {"busy": False})

        threading.Thread(target=work, daemon=True, name=label).start()
        return True

    @staticmethod
    def _safely(fn: Callable[[], Any]) -> None:
        """Hata yolundaki adımlar birbirini engellememeli: biri düşse de diğerleri çalışır."""
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def _task_cancelled(self, label: str) -> None:
        game, done, total = self._game, self._eta.done, self._eta.total
        if self._translating and game:
            self._safely(lambda: self._library.upsert(
                game["root"], status="paused", last_action="Çeviri durduruldu", last_action_at=time.time(),
                paused_done=done, paused_total=total))
            self._safely(lambda: self._emit_project(game["root"]))
        self._safely(lambda: self._status("Durduruldu.", "warn"))
        self._safely(lambda: self._notify(f"{label} durduruldu",
                                          "Yapılan çeviriler kaydedildi; devam ettiğinde kaldığı yerden sürer.", "warn", "pause"))

    def _task_failed(self, label: str, info: Dict[str, Any], tone: str) -> None:
        """Hatayı açık bir biçimde bildirir; yalnızca başlamış bir çeviri projeyi 'hatalı' durumuna geçirir."""
        game = self._game
        if self._translating and game:
            self._safely(lambda: self._library.upsert(
                game["root"], status="error", last_error=info, last_action=info["title"], last_action_at=time.time()))
            self._safely(lambda: self._emit_project(game["root"]))
        self._safely(lambda: self._ui.emit("task_error", {"label": label, **info}))
        if self._translating:
            self._safely(lambda: self._attention("error", info["title"], info.get("hint", "")))
        self._safely(lambda: self._status(info["title"], tone))
        self._safely(lambda: self._notify(info["title"], info["hint"], tone, "alert", info.get("action")))

    def _select_game(self, chosen: str) -> Dict[str, Any]:
        game_type, info = detect_any_game_type(chosen)
        if not game_type:
            raise UserError("Seçilen klasörde desteklenen bir oyun bulunamadı (Ren'Py, Unity, Unreal, RPG Maker).")
        root = game_root_of(game_type, info, Path(chosen))
        existing = self._library.get(root) or {}
        title = existing.get("title") or game_title_of(game_type, info, root)
        self._game = {"root": str(root), "type": game_type, "info": info, "texts": None,
                      "analysis": None, "title": title}
        item = self._library.upsert(root, title=title, engine=game_type, status=existing.get("status") or "new")
        self._log(f"Proje açıldı: {title} · {ENGINE_LABELS[game_type]}")
        self._load_art_async(item)
        self._emit_stats()
        return self._project_payload(item)

    def _require_game(self) -> Dict[str, Any]:
        if not self._game:
            raise UserError("Önce bir oyun klasörü seçin.")
        return self._game

    def _cache_path(self, model: Optional[str] = None) -> Path:
        game = self._require_game()
        return cache_path_for(Path(game["root"]), game["type"], model or self._settings["model"], self._settings["target"])

    # ── Oyunlar arası ortak çeviri belleği (kısa arayüz metinleri) ─────────────────────────
    def _memory_file(self) -> Path:
        return DATA_DIR / "memory" / f"ui_{self._settings['target']}.json"

    def _fixes_file(self) -> Path:
        return DATA_DIR / "memory" / f"fixes_{self._settings['target']}.json"

    def _seed_memory(self, cache_path: Path) -> int:
        """Başka oyunlarda çevrilmiş arayüz metinlerini ve Çeviri Editörü'nde elle yapılmış düzeltmeleri bu oyunun
        önbelleğine ekler. Bu oyunda zaten çevrilmiş satırlara dokunmaz."""
        if not self._settings.get("memory", True):
            return 0
        memory = _read_json(self._memory_file(), {})
        fixes = _read_json(self._fixes_file(), {})
        memory = memory if isinstance(memory, dict) else {}
        fixes = fixes if isinstance(fixes, dict) else {}
        if not memory and not fixes:
            return 0
        cache = _read_json(cache_path, {})
        if not isinstance(cache, dict):
            return 0
        from_fixes = {s: t for s, t in fixes.items() if isinstance(s, str) and isinstance(t, str) and t and s not in cache}
        from_memory = {s: t for s, t in memory.items() if s not in cache and s not in from_fixes}
        if from_fixes or from_memory:
            cache.update(from_memory)
            cache.update(from_fixes)
            _write_json(cache_path, cache, indent=None)
        if from_memory:
            self._log(f"Ortak çeviri belleği: {_n(len(from_memory))} arayüz metni hazır (başka oyunlarda çevrilmişti)")
        if from_fixes:
            self._log(f"Düzeltme belleği: {_n(len(from_fixes))} satır başka oyunlarda elle düzelttiğin hâliyle geldi")
        return len(from_memory) + len(from_fixes)

    def _learn_fixes(self, fixes: Dict[str, str]) -> int:
        """Çeviri Editörü'nde elle düzeltilen satırlar: aynı cümle başka oyunda (ör. serinin devamında) geçerse
        makine çevirisi yerine bu hâli kullanılır. Kısa arayüz metinleri ortak bellekte de güncellenir."""
        fixes = {s: t for s, t in fixes.items() if isinstance(s, str) and isinstance(t, str) and s and t and t != s}
        if not fixes or not self._settings.get("memory", True):
            return 0
        stored = _read_json(self._fixes_file(), {})
        stored = stored if isinstance(stored, dict) else {}
        for source in fixes:
            stored.pop(source, None)            # yeniden düzeltilen satır en yeniler arasına geçer
        stored.update(fixes)
        if len(stored) > MEMORY_LIMIT:
            stored = dict(list(stored.items())[-MEMORY_LIMIT:])
        _write_json(self._fixes_file(), stored)
        ui = {s: t for s, t in fixes.items() if is_ui_text(s)}
        if ui:
            memory = _read_json(self._memory_file(), {})
            memory = memory if isinstance(memory, dict) else {}
            memory.update(ui)
            _write_json(self._memory_file(), memory)
        return len(fixes)

    def _learn_memory(self, cache_path: Path, cache: Optional[Dict[str, str]] = None) -> int:
        """Bu oyunda çevrilen kısa arayüz metinlerini ortak belleğe ekler. cache: zaten okunmuş önbellek."""
        if not self._settings.get("memory", True):
            return 0
        cache = _read_json(cache_path, {}) if cache is None else cache
        memory = _read_json(self._memory_file(), {})
        if not isinstance(cache, dict) or not isinstance(memory, dict):
            return 0
        new = {s: t for s, t in cache.items()
               if isinstance(t, str) and t and t != s and s not in memory and is_ui_text(s)}
        if new:
            memory.update(new)
            if len(memory) > MEMORY_LIMIT:            # en eskiler düşer
                memory = dict(list(memory.items())[-MEMORY_LIMIT:])
            _write_json(self._memory_file(), memory)
        return len(new)

    # ── Metin kutusuna sığma ────────────────────────────────────────────────
    def _fit_path(self, game: Dict[str, Any]) -> Path:
        return DATA_DIR / "reports" / f"{cache_file_for(Path(game['root']), DATA_DIR).stem}_{game['type']}.fit.json"

    def _save_fit(self, game: Dict[str, Any], limits: Dict[str, int]) -> None:
        text_fit.save_limits(self._fit_path(game), limits)

    def _fit_limits(self, game: Dict[str, Any]) -> Dict[str, int]:
        """Kaynak satır → metin kutusuna sığan en çok karakter. Ren'Py'de çeviri klasöründen hesaplanır (bir kez)."""
        path = self._fit_path(game)
        if game["type"] == "renpy" and not path.exists():
            if ProjectLibrary.key(game["root"]) in self._fit_missing:   # çeviri klasörü yok: analiz her seferinde yinelenmez
                return {}
            from engine_renpy import analyze_game
            info = analyze_game(game["root"], lambda s: None, language=renpy_language_name(self._settings["target"]))
            if not info.tl_dir.is_dir():
                self._fit_missing.add(ProjectLibrary.key(game["root"]))
                return {}
            self._save_fit(game, text_fit.renpy_limits(info.game_dir, info.tl_dir))
        return text_fit.load_limits(path)

    def _overflow_after_translate(self, game: Dict[str, Any], cache: Optional[Dict[str, str]] = None) -> List[str]:
        """Çeviriden sonra: metin kutusundan taşabilecek satırlar (yalnızca RPG Maker MV/MZ ve Ren'Py)."""
        if game["type"] not in text_fit.WIDTH_FUNCS:
            return []
        try:
            if game["type"] == "renpy":
                self._fit_path(game).unlink(missing_ok=True)     # çeviri klasörü yeniden üretildi
                self._fit_missing.discard(ProjectLibrary.key(game["root"]))
            limits = self._fit_limits(game)
            found = text_fit.overflowing(_read_json(self._cache_path(), {}) if cache is None else cache, limits,
                                         game["type"])
        except Exception as exc:
            self._log(f"Metin kutusu denetimi yapılamadı: {exc}")
            return []
        if found:
            self._log(f"Metin kutusu denetimi: {_n(len(found))} satır kutuya sığmayabilir (tahmin).")
            self._notify(f"{_n(len(found))} satır kutuya sığmayabilir",
                         "Çevirisi orijinalinden uzun olup metin kutusunu aşabilecek satırlar editörde turuncu görünür. "
                         "'İncelenmelileri düzelt' bunları yapay zekâyla kısaltır.", "warn", "edit",
                         {"label": "Editörde aç", "page": "editor"})
        return list(found)

    def _record_review(self, cache_path: Path, failed: set, terms: Optional[Dict[str, str]] = None,
                       forced: Any = (), cache: Optional[Dict[str, str]] = None) -> None:
        """Geçerli çeviri alınamayan, oyun terimini kaybeden ve derleme denetiminin orijinaline döndürdüğü (forced)
        satırları editörde incelenmek üzere kaydeder. cache: zaten okunmuş önbellek (verilmezse dosyadan okunur)."""
        path = review_path_for(cache_path)
        cache = _read_json(cache_path, {}) if cache is None else cache
        current = set(_read_json(path, [])) | set(failed)
        terms_lost = set(term_inconsistencies(cache, terms or {}))
        lost = terms_lost | set(forced or ())
        pending = sorted(s for s in current | lost if s not in cache or cache.get(s) == s or s in lost)
        if terms_lost:
            self._log(f"Terim denetimi: {_n(len(terms_lost))} satırda oyun terimi (karakter/yer adı) çeviride yok.")
            self._notify(f"{_n(len(terms_lost))} satırda terim kayıp",
                         "Oyuna özel bir ad ya da terim kaynakta var ama çeviride yok. Editörde turuncu görünürler.",
                         "warn", "edit", {"label": "Editörde aç", "page": "editor"})
        if pending:
            _write_json(path, pending)
        elif path.exists():
            path.unlink()
        if failed:
            self._notify(f"{_n(len(failed))} satır incelenmeli",
                         "Bu satırlar çevrilemedi ve İngilizce kaldı. Editörde düzeltebilir ya da çeviriyi yeniden başlatabilirsin.",
                         "warn", "edit", {"label": "Editörde aç", "page": "editor"})

    # ── Durum ────────────────────────────────────────────────────────────────
    def get_state(self) -> Dict[str, Any]:
        cfg = prov.load_provider_config()
        projects = self._library.list()
        for item in projects[:24]:
            self._load_art_async(item)
        if self._gpu is None:
            self._gpu = {"name": "Algılanıyor…", "detail": "", "cuda": False}
            threading.Thread(target=self._detect_gpu, daemon=True).start()
        self._emit_stats()
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        return {
            "version": APP_VERSION,
            "user": user,
            "settings": self._settings,
            "gpu": self._gpu,
            "providers": {
                "active": cfg.active_provider,
                "gemini_keys": cfg.gemini_keys,
                "gemini_model": cfg.gemini_model,
                "openai_key": cfg.openai_key,
                "openai_model": cfg.openai_model,
                "anthropic_key": cfg.anthropic_key,
                "anthropic_model": cfg.anthropic_model,
                "deepl_key": cfg.deepl_key,
                "ollama_host": cfg.ollama_host,
                "ollama_model": cfg.ollama_model,
                **self._extra_provider_fields(cfg),
            },
            "provider_catalog": self._provider_catalog(),
            "models": {k: prov.get_offline_model_status(k) for k in ("opus", "nllb")},
            "whats_new": WHATS_NEW,
            "ui": self._ui_payload(),
            "scan": self._scan_payload(),
            "model_labels": MODEL_LABELS,
            "full_models": list(FULL_TRANSLATION_MODELS),
            "engine_labels": ENGINE_LABELS,
            "source_languages": [{"code": c, "label": l} for l, c in get_all_source_languages()],
            "target_languages": [{"code": c, "label": l} for l, c in get_all_target_languages()],
            "projects": [self._project_payload(p) for p in projects],
            "busy": self._busy,
            "gpu_opt": self._gpu_opt,
            "ocr": self.ocr_status(),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Ana sayfa istatistikleri: proje sayısı, çevrilen proje, önbellekteki satır."""
        cache_dir = DATA_DIR / "cache"
        stats_file = DATA_DIR / "stats_cache.json"
        if not self._stats_cache:
            self._stats_cache = {k: tuple(v) for k, v in _read_json(stats_file, {}).items()}
        lines, size, changed = 0, 0, False
        for path in cache_dir.glob("*.json") if cache_dir.is_dir() else []:
            stat = path.stat()
            size += stat.st_size
            cached = self._stats_cache.get(path.name)
            if not cached or cached[0] != stat.st_mtime:
                data = _read_json(path, {})
                cached = (stat.st_mtime, len(data) if isinstance(data, dict) else 0)
                self._stats_cache[path.name] = cached
                changed = True
            lines += cached[1]
        if changed:
            _write_json(stats_file, self._stats_cache, indent=None)
        projects = self._library.list()
        return {
            "projects": len(projects),
            "translated": sum(1 for p in projects if p.get("status") == "translated"),
            "lines": lines,
            "cache_mb": round(size / 1048576, 1),
            "written": sum(int(p.get("written") or 0) for p in projects),
        }

    def _detect_gpu(self) -> None:
        card = gpu_runtime.nvidia_info()
        runtime = gpu_runtime.ready()
        if card:
            self._gpu = {"name": card["name"], "detail": card["memory"], "cuda": runtime,
                         "vram_gb": float(re.sub(r"[^\d.]", "", card["memory"]) or 0)}
        else:
            self._gpu = {"name": "Ekran kartı algılanmadı", "detail": "CPU", "cuda": False}
        self._gpu["runtime"] = runtime
        self._ui.emit("gpu", self._gpu)
        uses_local = self._ocr_model() in LOCAL_MODELS or self._settings["model"] in LOCAL_MODELS
        if self._gpu["cuda"] and self._settings.get("gpu_auto") and uses_local:
            self.optimize_gpu(preload=True, silent=True)

    # ── Arayüz dili ──────────────────────────────────────────────────────────
    def _ui_dictionaries(self):
        import i18n
        return i18n.Dictionaries(DATA_DIR / "ui_lang", RES_DIR / "data" / "ui_lang")   # üretilen + pakette hazır

    def _ui_payload(self) -> Dict[str, Any]:
        """Arayüz dili ve sözlüğü. Henüz üretilmemiş bir dilse İngilizce gönderilir ve "pending" işaretlenir."""
        import i18n
        code = self._settings.get("ui_language") or "tr"
        dictionaries = self._ui_dictionaries()
        dictionary = dictionaries.get(code)
        if dictionary is None and dictionaries.missing(code) <= 0.1 * len(i18n.EN) and self._ui_translator(code) is None:
            dictionary = dictionaries.with_fallback(code)   # hazır sözlükte birkaç yeni metin eksik, anahtar yok: uyarma
        self._ui_dict = dictionary if dictionary is not None else dict(i18n.EN)
        return {"language": code, "languages": i18n.ui_languages(), "dict": self._ui_dict, "pending": dictionary is None}

    def ui_dictionary(self) -> Dict[str, Any]:
        """Ekran çevirisi pencereleri ana pencereyle aynı arayüz dilini kullanır."""
        code = self._settings.get("ui_language") or "tr"
        return {"language": code, "dict": getattr(self, "_ui_dict", None) or {}}

    def _tr(self, text: str) -> str:
        """Python tarafında doğrudan ekrana yazılan (çeviriden muaf alanlardaki) metinler için arayüz dili."""
        import i18n
        return i18n.translate_text(text, getattr(self, "_ui_dict", None) or {}, self._settings.get("ui_language") or "tr")

    def _push_ui_language(self) -> None:
        """Açık ekran çevirisi pencerelerine yeni sözlüğü gönderir."""
        payload = json.dumps(self.ui_dictionary(), ensure_ascii=False)
        for win in (getattr(self, "_ocr_win", None) or {}).values():
            try:
                win.evaluate_js(f"(function(r){{ if (window.I18N) I18N.set(r.language, r.dict); }})({payload})")
            except Exception:
                pass

    def _ui_translator(self, code: str):
        """Arayüz metinlerini İngilizceden hedef dile çeviren bulut motoru (anahtarı olan ilk sağlayıcı)."""
        from engine_renpy import load_gemini_api_key, translate_with_gemini
        cfg = prov.load_provider_config()
        keys = {"gemini": bool(cfg.gemini_keys or load_gemini_api_key()), "openai": bool(cfg.openai_key),
                "anthropic": bool(cfg.anthropic_key), "deepl": bool(cfg.deepl_key),
                **{pid: cloud_providers.configured(cfg, pid) for pid in cloud_providers.ALL}}
        order = [self._settings["model"]] + ["gemini", "openai", "anthropic", "deepl", *cloud_providers.ALL]
        provider = next((p for p in order if keys.get(p)), None)
        if provider is None:
            return None
        cache_path = DATA_DIR / "ui_lang" / f"_{code}_cache.json"
        engine = "software user interface (buttons, menus, short messages)"

        def run(lines: List[str]) -> Dict[str, str]:
            cache: Dict[str, str] = {}
            if provider == "gemini":
                translate_with_gemini(lines, cache, cache_path, load_gemini_api_key(), log=self._log,
                                      target_lang=code, source_lang="en", game_engine=engine)
            else:
                prov.translate_with_cloud(provider, lines, cache, cache_path, log=self._log, game_engine=engine,
                                          target_lang=code, source_lang="en")
            return cache
        return run

    def set_ui_language(self, code: str) -> Dict[str, Any]:
        """Arayüz dilini değiştirir; hedef dil de (destekleniyorsa) aynı dile geçer: ENG → Almanca gibi."""
        import i18n
        code = i18n.normalize(code) or "en"
        self._settings["ui_language"] = code
        target_changed = code in TARGET_CODES and self._settings.get("target") != code
        if target_changed:
            self._settings["target"] = code
            if self._settings.get("source") == code:
                self._settings["source"] = "auto"
        save_settings(self._settings)
        error = None
        dictionaries = self._ui_dictionaries()
        dictionary = dictionaries.get(code)
        if dictionary is None:
            translator = self._ui_translator(code)
            if translator is None:
                error = ("Bu arayüz dili için bir bulut anahtarı gerekiyor (Gemini, OpenAI, Claude veya DeepL). Şimdilik İngilizce.")
            else:
                self._status("Arayüz çevriliyor…")
                try:
                    dictionary, failed = dictionaries.build(code, translator)
                    self._log(f"Arayüz dili {code}: {len(dictionary) - failed}/{len(dictionary)} metin çevrildi")
                except Exception as exc:
                    self._log(f"Arayüz çevrilemedi: {exc}")
                    error = describe_error(exc)["title"]
        self._ui_dict = dictionary if dictionary is not None else dict(i18n.EN)
        threading.Thread(target=self._push_ui_language, daemon=True, name="ui-lang").start()
        if target_changed and self._game and self._game.get("analysis"):
            game = self._game
            threading.Thread(target=lambda: self._emit_estimate(game), daemon=True, name="estimate").start()
        return {"ok": error is None, "error": error, "language": code, "dict": self._ui_dict,
                "settings": self._settings, "target_changed": target_changed}

    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        hotkeys_changed = any(k in patch and patch[k] != self._settings.get(k) for k in ("ocr_hotkey", "pin_hotkey"))
        for key in DEFAULT_SETTINGS:
            if key in patch:
                self._settings[key] = patch[key]
        save_settings(self._settings)
        if hotkeys_changed and self._hotkeys:
            self._setup_hotkeys()
        if self._pin_watcher and "ocr_interval" in patch:
            self._pin_watcher.interval = max(0.15, int(self._settings["ocr_interval"]) / 1000)
        if self._game and self._game.get("analysis") and {"model", "target", "source"} & set(patch):
            game = self._game
            threading.Thread(target=lambda: self._emit_estimate(game), daemon=True, name="estimate").start()
        return self._settings

    # ── Oyun / kütüphane ─────────────────────────────────────────────────────
    def pick_folder(self) -> Optional[Dict[str, Any]]:
        import webview
        if not self._window:
            return None
        if self._busy:
            self._toast("Devam eden işlem bitmeden yeni oyun eklenemez.", "warn")
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return None
        try:
            project = self._select_game(result[0])
        except UserError as exc:
            self._notify("Oyun bulunamadı", str(exc), "warn", "alert")
            return None
        self.analyze()
        return project

    def open_project(self, path: str) -> Optional[Dict[str, Any]]:
        if self._busy:
            self._toast("Devam eden işlem bitmeden proje değiştirilemez.", "warn")
            return None
        if self._game and ProjectLibrary.key(self._game["root"]) == ProjectLibrary.key(path):
            return self._project_payload(self._library.get(path))
        if not Path(path).is_dir():
            self._notify("Oyun klasörü bulunamadı", path, "error", "alert")
            return None
        try:
            project = self._select_game(path)
        except UserError as exc:
            self._notify("Proje açılamadı", str(exc), "warn", "alert")
            return None
        self.analyze()
        return project

    def open_dropped(self, path: str) -> Optional[Dict[str, Any]]:
        """Pencereye sürüklenip bırakılan klasör / .exe / kısayoldan oyunu açar."""
        target = Path(path)
        if target.suffix.lower() == ".lnk":
            target = Path(_resolve_shortcut(str(target)) or target)
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            self._notify("Bırakılan öğe açılamadı", path, "warn", "alert")
            return None
        if self._busy:
            self._toast("Devam eden işlem bitmeden yeni oyun eklenemez.", "warn")
            return None
        try:
            project = self._select_game(str(target))
        except UserError as exc:
            self._notify("Oyun bulunamadı", str(exc), "warn", "alert")
            return None
        self.analyze()
        return project

    def _bind_drop(self) -> None:
        """WebView2 bırakılan dosyaların tam yolunu yalnızca 'drop' dinleyicisi varsa verir."""
        from webview.dom import DOMEventHandler

        def on_drop(event: Dict[str, Any]) -> None:
            files = (event.get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                self._ui.emit("dropped", paths)

        document = self._window.dom.document
        document.events.dragover += DOMEventHandler(lambda e: None, True, False)
        document.events.drop += DOMEventHandler(on_drop, True, False)

    def remove_project(self, path: str) -> bool:
        self._library.remove(path)
        if self._game and ProjectLibrary.key(self._game["root"]) == ProjectLibrary.key(path):
            self._game = None
        self._emit_stats()
        return True

    def _game_executable(self, game: Dict[str, Any]) -> Optional[Path]:
        info, root = game.get("info"), Path(game["root"])
        for attr in ("executable", "exe_path"):
            path = getattr(info, attr, None)
            if path and Path(path).is_file():
                return Path(path)
        skip = ("unins", "crash", "unitycrash", "notification_helper", "updater", "setup", "vc_redist", "dxsetup")
        candidates = [p for p in root.glob("*.exe") if not p.name.lower().startswith(skip)]
        preferred = [p for p in candidates if p.stem.lower() in ("game", "nw")] or candidates
        return sorted(preferred, key=lambda p: -p.stat().st_size)[0] if preferred else None

    def _check_runtime_errors(self, game: Dict[str, Any], analysis: Dict[str, Any], current: Dict[str, Any]) -> None:
        """Ren'Py: çeviriden sonra oyun, bir çeviri satırı yüzünden hata verdiyse (traceback.txt) öneri olarak gösterir."""
        analysis.pop("runtime_errors", None)
        if game["type"] == "unity" and current.get("status") == "translated":
            self._check_unity_glyphs(game, analysis, current)
            return
        if game["type"] != "renpy" or current.get("status") != "translated":
            return
        from engine_renpy import runtime_translation_errors
        since = max(float(current.get("translated_at") or 0), float(current.get("runtime_fixed_at") or 0))
        errors = runtime_translation_errors(Path(game["root"]), renpy_language_name(self._settings["target"]), since)
        analysis["advice"] = [a for a in (analysis.get("advice") or []) if a.get("action") != "fix-runtime"]
        if not errors:
            return
        analysis["runtime_errors"] = errors
        first = errors[0]
        self._log(f"Oyun çeviri satırı yüzünden hata verdi: {first['file']}:{first['line']} {first['message']}")
        analysis["advice"].insert(0, {
            "tone": "warn", "action": "fix-runtime", "action_label": "Hatalı satırları düzelt",
            "text": f"Oyun bir çeviri satırı yüzünden hata verdi ({Path(first['file']).name}:{first['line']}). "
                    "Düzeltince bu satırlar orijinal metne döner ve editörde turuncu görünür."})

    def _check_unity_glyphs(self, game: Dict[str, Any], analysis: Dict[str, Any], current: Dict[str, Any]) -> None:
        """Unity: oyun çalışırken fontta bulunamayan harfler (Player.log) → öneri; bir sonraki yazımda en yakın harf."""
        from engine_unity import detect_unity_game, runtime_missing_glyphs
        info = game.get("info") or detect_unity_game(game["root"])
        if info is None:
            return
        missing = runtime_missing_glyphs(info, float(current.get("translated_at") or 0))
        # Yalnızca bizim çevirilerimizde geçen harfler: oyunun kendi yazıları (ör. dil listesindeki Arapça/Hintçe adlar)
        # da kayda düşer, onlar çeviriyle ilgili değildir
        used = set("".join(str(v) for v in _read_json(self._cache_path(), {}).values()))
        missing = {font: [c for c in chars if c in used] for font, chars in missing.items()}
        missing = {font: chars for font, chars in missing.items() if chars}
        chars = sorted({c for values in missing.values() for c in values})
        if not chars:
            return
        known = set(current.get("runtime_missing") or "")
        self._library.upsert(game["root"], touch=False, runtime_missing="".join(sorted(known | set(chars))))
        fonts = ", ".join(sorted(missing)[:3])
        self._log(f"Oyun kaydı: fontta bulunamayan harfler {' '.join(chars)} ({fonts})")
        analysis["advice"] = [{"tone": "warn", "text":
                               f"Oyunda şu harfler fontta bulunamadı ve kutu olarak görünüyor: {' '.join(chars)} ({fonts}). "
                               "'Baştan çevir' bu harfleri en yakın harfle yazar (ğ→g, ş→s)."}] + [
            a for a in (analysis.get("advice") or []) if not str(a.get("text", "")).startswith("Oyunda şu harfler fontta")]

    def repair_runtime_errors(self) -> bool:
        """Oyunu çökerten çeviri satırlarını orijinaline döndürür; oyunun hata kayıtlarına dokunmaz."""
        def task():
            from engine_renpy import revert_translation_line
            game = self._require_game()
            errors = (game.get("analysis") or {}).get("runtime_errors") or []
            sources, fixed = [], 0
            for error in errors:
                reverted = revert_translation_line(Path(game["root"]) / error["file"], int(error["line"]))
                if reverted:
                    fixed += 1
                    if isinstance(reverted, str):
                        sources.append(reverted)
                    self._log(f"Düzeltildi: {error['file']}:{error['line']} → orijinal metin")
            self._library.upsert(game["root"], touch=False, runtime_fixed_at=time.time())
            self._record_review(self._cache_path(), set(), None, sources)
            if game.get("analysis"):
                game["analysis"]["advice"] = [a for a in game["analysis"].get("advice", []) if a.get("action") != "fix-runtime"]
                game["analysis"].pop("runtime_errors", None)
                self._ui.emit("analysis", game["analysis"])
            self._notify("Hatalı satırlar düzeltildi", f"{_n(fixed)} satır orijinal metne döndü; oyunu yeniden deneyebilirsin.",
                         "ok", "check")

        return self._run_task("Düzeltme", task)

    def play_game(self) -> bool:
        """Oyunu Capri'den açar: çeviriyi hemen oyunda görmek için."""
        import subprocess
        game = self._game
        if not game:
            return False
        exe = self._game_executable(game)
        if not exe:
            self._toast("Oyunun çalıştırılabilir dosyası bulunamadı; oyun klasöründen açabilirsin.", "warn")
            return False
        subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self._log(f"Oyun başlatıldı: {exe}")
        return True

    # ── Sözlük içe / dışa aktarma ──
    def glossary_export(self, kind: str, rows: List[List[str]]) -> Optional[str]:
        import csv
        import io
        import webview
        if not self._window:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"capri_sozluk_{kind}.json",
                                                 file_types=("JSON (*.json)", "CSV (*.csv)"))
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        pairs = [(str(a), str(b)) for a, b in (r for r in rows if len(r) == 2) if str(a).strip()]
        if target.suffix.lower() == ".csv":
            buffer = io.StringIO()
            csv.writer(buffer).writerows([("kaynak", "çeviri"), *pairs])
            target.write_text(buffer.getvalue(), encoding="utf-8-sig")
        else:
            _write_json(target, dict(pairs))
        self._toast(f"{_n(len(pairs))} terim dışa aktarıldı.", "ok")
        return str(target)

    def glossary_import(self) -> Optional[List[List[str]]]:
        """JSON (sözlük ya da [kaynak, çeviri] listesi) veya iki sütunlu CSV okur; kaydetmek kullanıcıya kalır."""
        import webview
        if not self._window:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Sözlük (*.json;*.csv)",))
        return parse_glossary_file(Path(result[0])) if result else None

    def open_url(self, url: str) -> bool:
        """Bağlantıyı varsayılan tarayıcıda açar (yalnızca http/https)."""
        import webbrowser
        if not re.match(r"^https?://", str(url or "")):
            return False
        return webbrowser.open(url)

    def open_path(self, path: str) -> bool:
        target = Path(path)
        if target.exists():
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        return False

    def answer_confirm(self, cid: str, value: bool) -> None:
        entry = self._confirms.get(cid)
        if entry:
            entry[1][0] = bool(value)
            entry[0].set()

    def cancel(self) -> bool:
        """Süren çeviriyi bir sonraki parti sonunda durdurur."""
        if not self._busy:
            return False
        self._cancel.set()
        self._status("Durduruluyor… (geçerli parti bitince)", "warn")
        return True

    # ── Analiz ───────────────────────────────────────────────────────────────
    def analyze(self, force: bool = False) -> bool:
        """
        Arka planda çalışır ve işlem kilidi tutmaz: analiz sürerken başka projeye geçilebilir (eski sonuç yok sayılır).
        Değişmemiş oyunun sonucu diskten anında gelir; "Yeniden analiz" (force) bunu atlar.
        """
        game = self._game
        if not game:
            self._toast("Önce bir oyun klasörü seçin.", "warn")
            return False
        if game.get("analysis") and not force:
            self._ui.emit("analysis", game["analysis"])
            return True
        if self._busy:
            self._toast("Devam eden işlem bitmeden analiz yapılamaz.", "warn")
            return False

        def work():
            try:
                analysis = self._analyze_now(game, force)
                if self._game is game:
                    self._ui.emit("analysis", analysis)
                    self._emit_project(game["root"])
            except Exception as exc:
                self._safely(lambda: self._log(traceback.format_exc()))
                if self._game is game:
                    self._safely(lambda: self._ui.emit("task_error", {"label": "Analiz", **describe_error(exc)}))
            finally:
                if self._game is game:
                    self._ui.emit("analyzing", {"active": False, "path": game["root"]})
                if self._analysis_thread is threading.current_thread():
                    self._analysis_thread = None

        self._ui.emit("analyzing", {"active": True, "path": game["root"]})
        self._analysis_thread = threading.Thread(target=work, daemon=True, name="Analiz")
        self._analysis_thread.start()
        return True

    def _analyze_now(self, game: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """Analizi bu iş parçacığında yapar (değişmemiş oyunun sonucu diskten gelir) ve kütüphaneyi günceller."""
        analysis = None if force else self._load_analysis(game)
        if analysis is None:
            analysis = getattr(self, f"_analyze_{game['type']}")(game)
            self._prepare_analysis(game, analysis)
            self._save_analysis(game, analysis)
        game["analysis"] = analysis
        current = self._library.get(game["root"]) or {}
        stamp = current.get("files_stamp")
        if current.get("status") == "translated" and stamp and stamp != game_files_stamp(game["root"], game["type"]):
            # Oyun güncellendi: çeviri kaybolmuş olabilir; eski yedekler artık "orijinal" sayılmaz
            self._library.upsert(game["root"], touch=False, status="analyzed", files_changed_at=time.time(),
                                 last_action="Oyun güncellenmiş", last_action_at=time.time())
            self._log("Oyun dosyaları çeviriden sonra değişmiş: çeviri yeniden uygulanmalı.")
            current = self._library.get(game["root"]) or {}
        analysis["advice"] = [a for a in (analysis.get("advice") or []) if a.get("action") != "reapply"]
        if current.get("last_action") == "Oyun güncellenmiş" and current.get("status") != "translated":
            analysis["advice"].insert(0, {"tone": "warn", "text": OUTDATED_NOTE, "action": "reapply",
                                          "action_label": "Çeviriyi yeniden uygula"})
        self._check_runtime_errors(game, analysis, current)
        stats = analysis.get("stats") or {}
        self._library.upsert(game["root"], touch=False, lines=analysis.get("lines"), unique=stats.get("unique"),
                             status=None if current.get("status") in ("translated", "paused", "error") else "analyzed")
        analysis["estimate"] = self._estimate(game)
        return analysis

    def _wait_for_analysis(self) -> None:
        """Çeviri, aynı dosyaları okuyan analizin bitmesini bekler."""
        thread = self._analysis_thread
        if thread is not None and hasattr(thread, "join"):
            thread.join()

    def _analysis_file(self, game: Dict[str, Any]) -> Path:
        return DATA_DIR / "analysis" / (cache_file_for(Path(game["root"]), DATA_DIR).stem + ".json")

    def _fingerprint(self, game: Dict[str, Any]) -> List[Any]:
        """Analizi etkileyen dosyaların boyut + tarihi: değişmişse sonuç yeniden hesaplanır."""
        if game.get("info") is None:   # baştan çeviride orijinaller geri yüklenince sıfırlanır
            game["info"] = _detect_here(Path(game["root"]))[1]
        info, paths = game["info"], []
        kind = game["type"]
        if kind == "unity":
            paths = [info.resources_assets_path, Path(info.root) / "BepInEx", info.streaming_assets_dir]
            try:   # Utage/I2 tabloları sharedassets/level dosyalarında, bileşen metinleri data.unity3d'de olabilir
                import unity_typed
                from engine_unity import _table_asset_files
                paths += list(_table_asset_files(info)) + unity_typed.containers(info) + [unity_typed.reader_dir()]
            except Exception:
                pass
        elif kind == "unreal":
            import unreal_pak
            paths = [*info.pak_files, *info.locres_files, unreal_pak.repak_path()]
        elif kind == "rpgmaker":
            paths = [*Path(info.data_dir).glob("*"), info.archive_path]
        elif kind == "renpy":
            paths = [*Path(info.game_dir).glob("*")]
        elif kind in KAG_ENGINES:
            from engine_kag import files_stamp_paths
            paths = files_stamp_paths(Path(game["root"]))
        elif kind == "godot":
            from engine_godot import files_stamp_paths
            paths = files_stamp_paths(Path(game["root"]))
        elif kind == "wolf":
            from engine_wolf import files_stamp_paths
            paths = files_stamp_paths(Path(game["root"]))
        stamp = []
        for path in paths:
            try:
                st = Path(path).stat()
                stamp.append([Path(path).name, st.st_size, st.st_mtime_ns])
            except (OSError, TypeError):
                pass
        target = self._settings["target"] if kind == "renpy" else ""   # Ren'Py analizi hedef dilin fontuna bakar
        return [ANALYSIS_VERSION, self._settings["source"], target, self._project_glossary()["aes_key"], sorted(stamp)]

    def _load_analysis(self, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        stored = _read_json(self._analysis_file(game), None)
        if not isinstance(stored, dict) or stored.get("fingerprint") != json.loads(json.dumps(self._fingerprint(game))):
            return None
        game["uniques"] = stored.get("uniques")
        self._log(f"Analiz önbellekten geldi: {game['title']}")
        return stored["analysis"]

    def _save_analysis(self, game: Dict[str, Any], analysis: Dict[str, Any]) -> None:
        data = {k: v for k, v in analysis.items() if k != "estimate"}
        self._safely(lambda: _write_json(self._analysis_file(game), {
            "fingerprint": self._fingerprint(game), "analysis": data, "uniques": game.get("uniques")}, indent=None))

    def _prepare_analysis(self, game: Dict[str, Any], analysis: Dict[str, Any]) -> None:
        """Metin istatistikleri: kelime/karakter sayısı süre tahmininin temelidir."""
        analysis["path"] = game["root"]
        texts = game.get("texts")
        if texts is not None:
            uniques = list(dict.fromkeys(t.original for t in texts if t.original.strip()))
            if game["type"] == "rpgmaker":   # çeviriyle aynı birimler: konuşmacı adı ve satır ayrı
                from engine_rpgmaker import speaker_sources
                uniques = speaker_sources(uniques)
            game["uniques"] = uniques
            analysis["stats"] = {"unique": len(uniques), "chars": sum(len(u) for u in uniques),
                                 "words": sum(len(u.split()) for u in uniques), "exact": True}
        else:
            game["uniques"] = None
            analysis["stats"] = analysis.get("stats") or {}

    def _workers(self, model: str) -> int:
        if model != "gemini":
            return 1
        keys = prov.load_provider_config().gemini_keys or []
        return max(1, min(len(keys), 4))

    def _estimate(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """Seçili motor ve önbelleğe göre çevrilecek satır ve süre (önceki çevirilerde ölçülen hız varsa onunla)."""
        analysis = game.get("analysis") or {}
        stats = analysis.get("stats") or {}
        model, target = self._settings["model"], self._settings["target"]
        total = stats.get("unique") or 0
        if not total:
            return {"lines": 0, "cached": 0, "pending": 0, "chars": 0, "seconds": 0, "text": "", "basis": "prior",
                    "model": MODEL_LABELS.get(model, model), "exact": False}
        cache = _read_json(cache_path_for(Path(game["root"]), game["type"], model, target), {})
        uniques = game.get("uniques")
        if uniques:
            pending = [u for u in uniques if u not in cache]
            cached, chars = len(uniques) - len(pending), sum(len(u) for u in pending)
        else:   # Ren'Py: kesin liste yok, ortalamadan kestirilir
            cached = min(len(cache), total)
            chars = int(stats.get("chars", 0) * (total - cached) / total)
        workers = self._workers(model)
        gpu = bool(self._gpu and self._gpu.get("cuda"))
        result = estimate(model, chars, workers, gpu, self._speeds)
        cfg = prov.load_provider_config()
        cost = estimate_cost(model, {"openai": cfg.openai_model, "anthropic": cfg.anthropic_model}.get(model, ""), chars)
        return {**result, "cost": cost, "lines": total, "cached": cached, "pending": total - cached, "chars": chars, "workers": workers,
                "model": MODEL_LABELS.get(model, model), "exact": bool(stats.get("exact"))}

    def _emit_estimate(self, game: Dict[str, Any]) -> None:
        if game.get("analysis"):
            game["analysis"]["estimate"] = self._estimate(game)
            if self._game is game:
                self._ui.emit("estimate", game["analysis"]["estimate"])

    def _learn_speed(self, game: Dict[str, Any]) -> None:
        """Gerçek çeviri hızını kaydeder: bir sonraki tahmin bu bilgisayar ve hesaba göre olur."""
        lines, seconds = self._eta.worked()
        if lines < LEARN_MIN_LINES or seconds < LEARN_MIN_SECONDS:
            return
        stats = (game.get("analysis") or {}).get("stats") or {}
        per_line = stats.get("chars", 0) / stats["unique"] if stats.get("unique") else 45
        model = self._settings["model"]
        self._speeds.record(model, lines * per_line, seconds, self._workers(model))

    def _analyze_renpy(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_renpy import analyze_game, scan_game_fonts
        from languages import NO_FONT_FALLBACK, SUPPORTED_LANGUAGES
        target = self._settings["target"]
        native = SUPPORTED_LANGUAGES[target].name_native if target in SUPPORTED_LANGUAGES else target
        info = analyze_game(game["root"], self._log, language=renpy_language_name(target))
        game["info"] = info
        fonts = scan_game_fonts(info)
        bad_fonts = [f for f in fonts if f.get("missing_chars")]
        game["texts"] = None
        stats = estimate_renpy_text(Path(info.game_dir))
        scripts = info.loose_rpy + info.packed_rpy
        compiled = info.loose_rpyc + info.packed_rpyc
        notes = [
            f"{scripts} .rpy / {compiled} .rpyc betik dosyası, {len(info.archives)} RPA arşivi",
            f"Mevcut Türkçe çeviri dosyası: {info.existing_tl_files}",
            f"Font: {len(fonts) - len(bad_fonts)} uyumlu, {len(bad_fonts)} Türkçe karakter eksik"
            + (" (otomatik font yaması uygulanacak)" if bad_fonts else ""),
        ]
        for note in notes:
            self._log(note)
        return {
            "engine": "renpy", "lines": None, "unique": None, "files": scripts or compiled,
            "notes": notes, "sample": "", "stats": stats,
            "engine_detail": "Ren'Py",
            "font": {"ok": not bad_fonts, "text": "Uyumlu" if not bad_fonts
                     else ("Font gerekli" if target in NO_FONT_FALLBACK else "Otomatik düzeltilecek")},
            "advice": ([{"tone": "warn", "text": f"Oyunun fontlarında {native} karakterleri yok; uygun bir font "
                                                 "eklemezsen metinler görünmeyebilir."} if target in NO_FONT_FALLBACK else
                        {"tone": "info", "text": f"{len(bad_fonts)} fontta {native} harfleri eksik. Capri çeviride otomatik font yaması uygular."}]
                       if bad_fonts else [])
                      + ([{"tone": "info", "text": f"Oyunda daha önce yapılmış {native} çeviri dosyaları var; mevcut çalışmanın üzerine devam edilir."}]
                         if info.existing_tl_files else []),
            "summary": f"{scripts or compiled} betik dosyası bulundu.",
            "meta": f"{scripts or compiled} betik dosyası",
        }

    def _analyze_unity(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_unity import detect_unity_game, extract_texts_unity
        info = game["info"] or detect_unity_game(game["root"])
        game["info"] = info
        texts = extract_texts_unity(info, log=self._log)
        if info.typed_reader_missing and not game.get("reader_declined"):
            texts, info = self._offer_unity_reader(game, info, texts)
        game["texts"] = texts
        unique = len({t.original for t in texts if t.original.strip()})
        notes = [
            f"{info.game_title} · Unity {info.runtime}",
            f"Lokalizasyon varlığı: {len(info.localization_text_assets)}",
            "Font: Türkçe karakter uyumlu" if info.font_turkish_support
            else f"Font: eksik karakterler {''.join(info.missing_font_chars)}",
            f"Çevrilebilir metin: {_n(len(texts))} satır ({_n(unique)} benzersiz)",
        ]
        import bepinex_installer
        utage = sum(1 for t in texts if t.format_type == "utage")
        typed = info.typed_counts
        localized = sum(1 for t in texts if t.format_type in ("loc_file", "loc_bundle"))
        needed = not texts or (info.runtime == "IL2CPP" and not utage and not typed and not localized)
        installed = bepinex_installer.is_installed(info.root)
        if utage:
            notes.append(f"Utage senaryosu açık: {_n(utage)} satır. BepInEx gerekmez; oyunda English'i seç.")
        naninovel = typed.get("naninovel", 0) + typed.get("naninovel_ui", 0)
        if naninovel:
            notes.append(f"Naninovel senaryosu açık: {_n(typed.get('naninovel', 0))} satır, "
                         f"{_n(typed.get('naninovel_ui', 0))} arayüz metni. BepInEx gerekmez; oyunda English'i seç.")
        elif typed:
            notes.append(f"Bileşenlerde açık metin: {_n(typed.get('fsm', 0))} PlayMaker, {_n(typed.get('ui', 0))} arayüz, "
                         f"{_n(typed.get('xml', 0))} tablo satırı. BepInEx gerekmez; oyunda English'i seç.")
        # IL2CPP: metin derlenmiş kodda/tipsiz veride. Mono: veri açık ama Capri'nin okuyamadığı bir yapıda (PlayMaker,
        # Adventure Creator, tek paket data.unity3d…). İkisinde de oyunda görünen metni BepInEx + XUnity yakalar.
        bundled = (Path(info.data_dir) / "data.unity3d").is_file() if getattr(info, "data_dir", None) else False
        from engine_unity import localization_tables
        loc_tables = localization_tables(info)
        if loc_tables:
            notes.append(f"Unity Localization: {_n(len(loc_tables))} dize tablosu dosyası, {_n(localized)} metin.")
        if needed:
            notes.append(("Tüm veri tek pakette (data.unity3d)" if bundled and info.runtime != "IL2CPP"
                          else "Metinler dosyada açık değil")
                         + ": çeviri BepInEx + XUnity.AutoTranslator ile yapılır"
                         + (" (kurulu)." if installed else " — tek tıkla kurulur."))
        for note in notes:
            self._log(note)
        return {
            "engine": "unity", "lines": len(texts), "unique": unique, "notes": notes,
            "engine_detail": f"Unity · {info.runtime}",
            "font": {"ok": info.font_turkish_support,
                     "text": "Uyumlu" if info.font_turkish_support else "Eksik: " + " ".join(info.missing_font_chars[:8])},
            "advice": ([{"tone": "info", "text": (
                            ("Metinler dosyalarda açık değil; çeviri oyun içinde BepInEx ile gösterilir (BepInEx kurulu)."
                             if installed else
                             "Metinler dosyalarda açık değil; çeviri oyun içinde BepInEx ile gösterilir (kurulumda iznin istenir).")
                            if info.runtime == "IL2CPP" else
                            ("Bu oyunun metinleri dosyadan çevrilemiyor. Çeviri, oyun içinde BepInEx + XUnity.AutoTranslator "
                             "ile yapılır (BepInEx kurulu)." if installed else
                             "Bu oyunun metinleri dosyadan çevrilemiyor. Çeviri, oyun içinde BepInEx + XUnity.AutoTranslator "
                             "ile yapılır; kurulum için iznin istenir."))}]
                       if needed else [])
                      + ([{"tone": "info", "text": "Utage senaryosu: oyunda dil olarak English'i seçince Türkçe görünür."}] if utage else [])
                      + ([{"tone": "info", "text": "Metinler oyunun bileşenlerinden okundu. Oyunda dil olarak English'i seçince Türkçe görünür."}] if typed and not naninovel else [])
                      + ([{"tone": "info", "text": "Naninovel oyunu: oyunda dil olarak English'i seçince Türkçe görünür."}] if naninovel else [])
                      + ([{"tone": "info", "text": UNITY_LOCALIZATION_NOTE}] if loc_tables else [])
                      + ([{"tone": "warn", "text": (
                            f"Oyunun fontunda {' '.join(info.missing_font_chars)} yok; bu harfler en yakın harfle yazılır "
                            "(ğ→g, ş→s, ı→i)."
                            if info.tmp_glyphs else
                            "Oyunun fontunda bazı Türkçe harfler yok; bu harfler oyunda boş ya da farklı görünebilir.")}]
                         if not info.font_turkish_support else []),
            "bepinex": {"needed": needed, "installed": installed,
                        "managed": bepinex_installer.manifest_file(Path(info.root)) is not None},
            "sample": texts[0].original if texts else "",
            "summary": f"{_n(len(texts))} satır ({_n(unique)} benzersiz) bulundu.",
            "meta": f"{_n(unique)} satır",
        }

    def _analyze_unreal(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_unreal import detect_unreal_game, extract_texts_unreal
        info = game["info"] or detect_unreal_game(game["root"])
        game["info"] = info
        texts = extract_texts_unreal(info, source_lang_code=self._settings["source"], log=self._log)
        pak_note = ""
        if not texts and info.pak_files:
            import unreal_pak
            if unreal_pak.repak_path():
                try:
                    texts, _staging = self._unreal_pak_texts(game, info)
                    pak_note = "Metinler .pak içinden okundu; çeviri Paks/~mods altına yama paketi olarak yazılır."
                except unreal_pak.NeedsAesKey:
                    pak_note = ("Paketler AES ile şifreli. Oyunun AES anahtarını Sözlük → Bu oyun sekmesine girip "
                                "yeniden analiz et.")
                except unreal_pak.UnsupportedContainer:
                    pak_note = ("Bu oyunun paket biçimi çok yeni; açık kaynak araçlar henüz okuyamıyor. Bu oyunda ekran çevirisini (OCR) kullanabilirsin.")
            else:
                pak_note = ("Metinler .pak paketlerinde; çeviri başlarken repak aracı (~2 MB) için izin istenir.")
            if not texts and not pak_note.startswith(("Paketler", "Metinler .pak paketlerinde", "Bu oyunun paket")):
                pak_note = ("Metinler .pak içinde bulunamadı. IoStore kapsayıcılarında da yok." if unreal_pak.retoc_path() else
                            "Metinler .pak içinde yok; oyun IoStore kullanıyorsa retoc aracı (~3 MB) için izin istenir.") \
                    if info.has_iostore else "Paketlerde kaynak dilde metin bulunamadı."
        game["texts"] = texts
        unique = len({t.original for t in texts if t.original.strip()})
        notes = [
            f"Unreal {info.engine_version} · Proje: {info.game_project_name}",
            f"PAK: {len(info.pak_files)} · IoStore: {'var (.utoc/.ucas)' if info.has_iostore else 'yok'}",
            f".locres dosyası: {len(info.locres_files)}",
            f"Çevrilebilir metin: {_n(len(texts))} satır ({_n(unique)} benzersiz)",
        ]
        if pak_note:
            notes.append(pak_note)
        elif not texts:
            notes.append("Açıkta .locres bulunamadı.")
        for note in notes:
            self._log(note)
        return {
            "engine": "unreal", "lines": len(texts), "unique": unique, "notes": notes,
            "engine_detail": f"Unreal {info.engine_version}",
            "advice": [{"tone": "warn" if "AES" in pak_note or "OCR" in pak_note else "info", "text": pak_note}] if pak_note
                      else ([] if texts else [{"tone": "warn", "text": "Bu oyunda çevrilecek metin bulunamadı."}]),
            "sample": texts[0].original if texts else "",
            "summary": f"{_n(len(texts))} satır ({_n(unique)} benzersiz) bulundu.",
            "meta": f"{_n(unique)} satır",
        }

    @staticmethod
    def _rgss_loose(info: Any) -> bool:
        from engine_rpgmaker import RGSS_EXT
        return info.engine_type in RGSS_EXT and any(Path(info.data_dir).glob(f"*{RGSS_EXT[info.engine_type]}"))

    @staticmethod
    def _rgss_archive(info: Any) -> Optional[Path]:
        """Şifreli RGSS arşivi (varsa). Oyun arşivi klasördeki dosyalara tercih ettiği için önce açılmalıdır."""
        from engine_rpgmaker import RGSS_EXT
        if info.engine_type not in RGSS_EXT:
            return None
        import rgss_archive
        return rgss_archive.find_archive(Path(info.root))

    def _rpgm_extract(self, info: Any) -> list:
        from engine_rpgmaker import extract_texts_mv_mz, extract_texts_vxace
        if info.engine_type in ("mv", "mz"):
            return extract_texts_mv_mz(info.data_dir, log=self._log)
        archive = self._rgss_archive(info)
        if archive:  # analiz: yalnızca Data/ girdileri geçici klasöre açılır, oyuna dokunulmaz
            import shutil
            import rgss_archive
            preview = DATA_DIR / "rgss_preview"
            shutil.rmtree(preview, ignore_errors=True)
            rgss_archive.extract_data(archive, preview)
            try:
                return extract_texts_vxace(preview, log=self._log, engine_type=info.engine_type)
            finally:
                shutil.rmtree(preview, ignore_errors=True)
        if self._rgss_loose(info):
            return extract_texts_vxace(info.data_dir, log=self._log, engine_type=info.engine_type)
        return []

    def _rgss_unpack(self, game: Dict[str, Any], info: Any) -> Any:
        """Şifreli arşivi kullanıcıya sorarak oyun klasörüne açar; yeni oyun bilgisini döndürür."""
        import rgss_archive
        from engine_rpgmaker import detect_rpgmaker_game
        archive = self._rgss_archive(info)
        size_mb = max(1, archive.stat().st_size // (1 << 20))
        if not self._ask("Şifreli arşiv açılacak",
                         f"{info.version_label} oyununun dosyaları şifreli {archive.name} arşivinde. Capri arşivi oyun "
                         f"klasörüne açacak (~{size_mb} MB) ve orijinalini yedekleyecek; Yedekler'den geri alınabilir. "
                         "Devam edilsin mi?"):
            raise TranslationCancelled()
        self._stage("prepare", f"{archive.name} arşivi açılıyor")
        self._progress_unit = "dosya"
        rgss_archive.unpack(Path(info.root), log=self._log, progress=self._progress)
        self._progress_unit = "satır"
        self._notify("Arşiv açıldı", f"{archive.name} oyun klasörüne çıkarıldı; orijinali yedeklendi.", "ok", "archive")
        info = detect_rpgmaker_game(game["root"])
        game["info"] = info
        return info

    def _analyze_rpgmaker(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_rpgmaker import detect_rpgmaker_game
        info = game["info"] or detect_rpgmaker_game(game["root"])
        game["info"] = info
        texts = self._rpgm_extract(info)
        game["texts"] = texts
        self._safely(lambda: self._save_fit(game, text_fit.rpgm_limits(texts, info.data_dir, info.engine_type)))
        unique = len({t.original for t in texts if t.original.strip()})
        notes = [
            f"{info.version_label} · {info.map_count} harita · {len(info.json_files)} JSON",
            f"Çevrilebilir metin: {_n(len(texts))} satır ({_n(unique)} benzersiz)",
        ]
        archive = self._rgss_archive(info)
        if archive:
            notes.append(f"Veriler şifreli {archive.name} arşivinde; çeviri başlarken açılır (iznin istenir), "
                         "orijinali yedeklenir.")
        for note in notes:
            self._log(note)
        return {
            "engine": "rpgmaker", "lines": len(texts), "unique": unique, "notes": notes,
            "engine_detail": info.version_label,
            "advice": [{"tone": "info", "text": f"Veriler şifreli {archive.name} arşivinde; çeviri başlarken açılır, "
                                                "orijinali yedeklenir."}] if archive else [],
            "sample": texts[0].original if texts else "",
            "summary": f"{_n(len(texts))} satır ({_n(unique)} benzersiz) bulundu.",
            "meta": f"{_n(unique)} satır",
        }

    # ── Çeviri ───────────────────────────────────────────────────────────────
    def _check_model_ready(self, game_type: Optional[str]) -> None:
        s = self._settings
        model, target = s["model"], s["target"]
        if model in TURKISH_ONLY_MODELS and target != "tr":
            raise UserError(f"{MODEL_LABELS[model]} yalnızca İngilizce → Türkçe çeviri yapabilir.")
        cfg = prov.load_provider_config()
        if model == "gemini":
            from engine_renpy import load_gemini_api_key
            if not (cfg.gemini_keys or load_gemini_api_key()):
                raise UserError("Gemini API anahtarı yok. Sağlayıcılar sayfasından ekleyin.")
        elif model in cloud_providers.ALL:
            if not cloud_providers.configured(cfg, model):
                raise UserError(f"{MODEL_LABELS[model]} için " + ("sunucu adresi" if model == "custom" else "API anahtarı")
                                + " yok. Sağlayıcılar sayfasından ekleyin.")
        elif model in CLOUD_MODELS:
            if not getattr(cfg, f"{model}_key"):
                raise UserError(f"{MODEL_LABELS[model]} API anahtarı yok. Sağlayıcılar sayfasından ekleyin.")
        elif model == "ollama":
            ok, _models, msg = prov.test_ollama_service(cfg.ollama_host)
            if not ok:
                raise UserError(msg)
        elif model == "local":
            import local_llm
            model_id = self._local_model_id()
            if local_llm.server_exe() is None or not local_llm.model_installed(model_id):
                raise UserError(f"{local_llm.BY_ID[model_id]['label']} indirilmemiş. Yerel Modeller sayfasından tek "
                                "tıkla indirebilirsin (Ollama gerekmez).")
        else:
            status = prov.get_offline_model_status(model)
            if not status["is_ready"]:
                raise UserError(
                    f"{MODEL_LABELS[model]} modeli eksik ({status['present_count']}/{status['total_files']} dosya). "
                    "Yerel Modeller sayfasından indirin."
                )
            if status.get("backend") == "torch" and not gpu_runtime.ready():
                raise UserError(f"{MODEL_LABELS[model]} için PyTorch kurulu değil; Yerel Modeller sayfasından tek tıkla kur.")
            if status.get("backend") == "ct2" and not gpu_runtime.ct2_ready():
                raise UserError(f"{MODEL_LABELS[model]} için çalışma ortamı (≈40 MB) kurulu değil; Yerel Modeller "
                                "sayfasından modeli yeniden indir, ortam da kurulur.")
            prov.release_offline_engines()  # Önizleme modelini VRAM'den boşalt

    def translate(self) -> bool:
        return self._run_task("Çeviri", self._translate_game)

    def _translate_game(self) -> None:
        """Seçili oyunu çevirir (görev iş parçacığında; toplu çeviri de bunu kullanır)."""
        game = self._require_game()
        self._wait_for_analysis()
        self._check_model_ready(game["type"])
        s = self._settings
        current = self._library.get(game["root"]) or {}
        game["skip_backup"] = False
        analysis = game.get("analysis")
        plan = self._estimate(game) if analysis else None
        cost = (plan or {}).get("cost") or {}
        if s["model"] in CLOUD_MODELS and (cost.get("usd") or 0) >= COST_CONFIRM_USD and not self._ask(
                "Ücretli çeviri", f"Bu çeviri {MODEL_LABELS[s['model']]} hesabından yaklaşık {cost['usd']:.2f} $ tutabilir "
                f"({_n(plan['pending'])} satır). Devam edilsin mi?"):
            return
        if current.get("status") == "translated" and not self._prepare_retranslation(game):
            return
        self._library.upsert(game["root"], status="translating", model=s["model"], target=s["target"])
        self._translating = True
        self._emit_project(game["root"])
        self._log(f"Çeviri başladı: {game['title']} · {MODEL_LABELS[s['model']]} · {s['source']} → {s['target']}")
        if plan:
            self._eta_prior = plan["seconds"] / plan["pending"] if plan["pending"] else None
        started = time.monotonic()
        failed: set = set()
        self._safely(lambda: self._auto_character_names(game))
        self._seed_memory(self._cache_path())          # başka oyunlarda çevrilmiş arayüz metinleri
        written = getattr(self, f"_translate_{game['type']}")(game, failed)
        took = int(time.monotonic() - started)
        self._learn_speed(game)
        cache = _read_json(self._cache_path(), {})          # bir kez okunur, üç denetim paylaşır
        cache = cache if isinstance(cache, dict) else {}
        overflow = self._overflow_after_translate(game, cache)
        self._record_review(self._cache_path(), failed, self._project_glossary().get("terms") or {},
                            set((game.get("compile_check") or {}).get("reverted_sources") or ()) | set(overflow), cache)
        self._safely(lambda: self._learn_memory(self._cache_path(), cache))
        note = game.pop("result_note", None)
        if note and not written:     # köprü kuruldu ama henüz yazılacak satır yok: "tamamlandı" denmez
            self._library.upsert(game["root"], status="analyzed", last_action="BepInEx kuruldu", last_action_at=time.time())
            self._translating = False
            self._emit_project(game["root"])
            self._notify("BepInEx hazır", note, "ok", "download")
            return
        if not written and not failed and game["type"] != "renpy":
            raise UserError("Oyuna yazılacak satır bulunamadı; oyunda değişiklik yapılmadı. Ayrıntı Teknik günlükte.")
        if failed and not written:
            raise UserError(f"{_n(len(failed))} satırın hiçbiri çevrilemedi. API anahtarını ve kotanı kontrol edip "
                            "tekrar dene.")
        self._library.upsert(game["root"], status="translated", translated_at=time.time(), written=written,
                             last_action="Çeviri tamamlandı", last_action_at=time.time(),
                             last_result={"written": written, "failed": len(failed), "took": took},
                             files_stamp=game_files_stamp(game["root"], game["type"]) or "")
        self._translating = False
        if analysis:    # oyun dosyaları artık çevrili: yeniden okunursa Türkçe metin "kaynak" sanılır
            game["analysis"] = analysis
            self._save_analysis(game, analysis)
            self._emit_estimate(game)
        self._emit_project(game["root"])
        message = f"{_n(written)} satır oyuna yazıldı · {format_duration(max(took, 1))}"
        self._status(message, "ok")
        self._notify("Çeviri tamamlandı", f"{game['title']} · {message}", "ok", "check")
        self._safely(lambda: self._attention("done", "Çeviri tamamlandı", f"{game['title']} · {message}"))
        self._ui.emit("done", {"written": written, "failed": len(failed), "took": took})
        self._emit_stats()

    # ── Toplu çeviri ─────────────────────────────────────────────────────────
    def queue_state(self) -> Dict[str, Any]:
        with self._queue_lock:
            return {"items": [dict(item) for item in self._queue], "running": self._queue_running}

    def _queue_update(self, item: Dict[str, Any], **fields: Any) -> None:
        with self._queue_lock:
            item.update(fields)
        self._emit_queue()

    def _next_waiting(self) -> Optional[Dict[str, Any]]:
        """Sıradaki bekleyen oyun: her turda güncel listeden seçilir (çıkarılan oyun seçilmez, eklenen seçilir)."""
        with self._queue_lock:
            return next((i for i in self._queue if i["state"] == "waiting"), None)

    def _emit_queue(self) -> None:
        self._ui.emit("queue", self.queue_state())

    def queue_add(self, paths: List[str]) -> Dict[str, Any]:
        """Kütüphanedeki oyunları sıraya ekler (aynı oyun iki kez eklenmez)."""
        with self._queue_lock:
            queued = {ProjectLibrary.key(item["path"]) for item in self._queue}
            for path in paths or []:
                item = self._library.get(path)
                if not item or ProjectLibrary.key(item["path"]) in queued:
                    continue
                queued.add(ProjectLibrary.key(item["path"]))
                self._queue.append({"path": item["path"], "title": item.get("title") or Path(item["path"]).name,
                                    "state": "waiting", "note": ""})
        self._emit_queue()
        return self.queue_state()

    def queue_remove(self, path: str) -> Dict[str, Any]:
        key = ProjectLibrary.key(path)
        with self._queue_lock:
            self._queue[:] = [i for i in self._queue if ProjectLibrary.key(i["path"]) != key or i["state"] == "running"]
        self._emit_queue()
        return self.queue_state()

    def queue_clear(self) -> Dict[str, Any]:
        """Bitmiş ve bekleyen satırları temizler (çevrilmekte olan kalır)."""
        with self._queue_lock:
            self._queue[:] = [i for i in self._queue if i["state"] == "running"]
        self._emit_queue()
        return self.queue_state()

    def queue_start(self) -> bool:
        """Sıradaki oyunları teker teker çevirir. Bir oyunda hata olursa not düşülüp sonrakine geçilir; "Durdur"
        bütün sırayı durdurur (çevrilen satırlar kaybolmaz, kalan oyunlar sırada bekler)."""
        if self._next_waiting() is None:
            self._toast("Sırada bekleyen oyun yok.", "warn")
            return False

        def task():
            self._queue_running = True
            done = failed = skipped = 0
            try:
                while not self._cancel.is_set():
                    item = self._next_waiting()
                    if item is None:
                        break
                    outcome, note = self._queue_one(item)
                    self._queue_update(item, state=outcome, note=note)
                    done += outcome == "done"
                    failed += outcome == "failed"
                    skipped += outcome == "skipped"
                    if outcome == "waiting":          # kullanıcı durdurdu
                        raise TranslationCancelled()
            finally:
                self._queue_running = False
                self._emit_queue()
            parts = [f"{_n(done)} oyun çevrildi"] + ([f"{_n(failed)} hata"] if failed else []) + \
                    ([f"{_n(skipped)} atlandı"] if skipped else [])
            self._status("Toplu çeviri bitti", "ok" if not failed else "warn")
            self._notify("Toplu çeviri bitti", " · ".join(parts), "ok" if not failed else "warn", "check",
                         {"label": "Kütüphane", "page": "library"})
            self._safely(lambda: self._attention("done", "Toplu çeviri bitti", " · ".join(parts)))

        return self._run_task("Toplu çeviri", task)

    def _queue_one(self, item: Dict[str, Any]) -> Tuple[str, str]:
        """Sıradaki bir oyunu açar, analiz eder ve çevirir: (durum, not)."""
        path = item["path"]
        if not Path(path).is_dir():
            return "failed", "Oyun klasörü bulunamadı"
        current = self._library.get(path) or {}
        if current.get("status") == "translated":
            return "skipped", "Zaten çevrilmiş"
        self._queue_update(item, state="running", note="")
        self._queue_last_ask = ""
        self._eta, self._eta_prior, self._translating = LiveEta(), None, False
        self._ui.clear_progress()
        try:
            self._select_game(path)
            self._emit_project(self._game["root"])
            self._ui.emit("analyzing", {"active": True, "path": self._game["root"]})
            try:
                analysis = self._analyze_now(self._game)
            finally:
                self._ui.emit("analyzing", {"active": False, "path": self._game["root"]})
            self._ui.emit("analysis", analysis)
            self._translate_game()
        except TranslationCancelled:
            if self._cancel.is_set():
                if self._translating and self._game:
                    self._library.upsert(self._game["root"], status="paused", last_action="Çeviri durduruldu",
                                         last_action_at=time.time())
                    self._emit_project(self._game["root"])
                return "waiting", "Durduruldu"
            asked = self._queue_last_ask
            return "skipped", f"Onay verilmedi: {asked}" if asked else "Onay verilmedi"
        except UserError as exc:
            self._log(f"Toplu çeviri: {item['title']} — {exc}")
            self._library.upsert(path, status="error", last_action="Çeviri başarısız", last_action_at=time.time())
            return "failed", str(exc)
        except Exception as exc:
            self._safely(lambda: self._log(traceback.format_exc()))
            self._library.upsert(path, status="error", last_action="Çeviri başarısız", last_action_at=time.time())
            return "failed", describe_error(exc).get("title") or str(exc)
        finally:
            self._translating = False
            self._safely(lambda: self._emit_project(path))
        after = self._library.get(path) or {}
        if after.get("status") == "translated":
            return "done", ""
        if after.get("last_action") == "BepInEx kuruldu":
            return "skipped", "BepInEx kuruldu; oyunu bir kez açıp kapattıktan sonra yeniden çevir"
        return "skipped", "Yazılacak satır yok"

    def _prepare_retranslation(self, game: Dict[str, Any]) -> bool:
        """Zaten çevrilmiş oyun baştan çevrilirken dosyaları değişen motorlarda önce orijinaller geri yüklenir."""
        in_place = game["type"] in ("unity", "rpgmaker", "godot", "wolf", *KAG_ENGINES)
        if not self._ask("Baştan çevir", "Oyun orijinaline döndürülüp baştan çevrilecek; önbellekteki satırlar ücretsiz. "
                         "Devam edilsin mi?" if in_place else
                         "Oyun baştan çevrilecek; önbellekteki satırlar ücretsiz. Devam edilsin mi?"):
            return False
        if in_place:
            self._stage("backup", "Orijinal dosyalar geri yükleniyor")
            self._restore_originals(game)
            game.update(info=None, texts=None, skip_backup=True)
        return True

    def _cjk_font(self, target: str, info: Any) -> Optional[Path]:
        """Çince/Japonca/Korece: oyunun fontu desteklemiyorsa izin alıp açık kaynak Noto Sans indirir."""
        from engine_renpy import scan_game_fonts
        url = NOTO_FONTS.get(target)
        if not url or not any(f.get("missing_chars") for f in scan_game_fonts(info)):
            return None
        target_file = DATA_DIR / "fonts" / url.rsplit("/", 1)[1]
        if target_file.exists() and _file_head(target_file) in FONT_MAGIC:
            return target_file
        if not self._ask("Yazı tipi indirilecek", "Oyunun fontlarında bu dilin harfleri yok. Açık kaynak Noto Sans fontu (~5-8 MB, SIL OFL) GitHub'dan indirilip "
                                                   "eklensin mi?"):
            return None
        self._stage("write", "Yazı tipi indiriliyor")
        fetch_github_file(url, target_file, self._log)
        return target_file

    def _want_backup(self, game: Dict[str, Any]) -> bool:
        return bool(self._settings["backup"]) and not game.get("skip_backup")

    def _project_glossary(self) -> Dict[str, Any]:
        default = {"terms": {}, "address": "sen", "notes": "", "aes_key": "", "names_scanned": False}
        if not self._game:
            return default
        data = _read_json(project_glossary_path(Path(self._game["root"])), {})
        return {**default, **(data if isinstance(data, dict) else {})}

    def _glossary_path(self) -> Optional[Path]:
        """Ren'Py için: genel (veya NSFW) sözlük + oyuna özel terimler birleştirilmiş dosya."""
        nsfw = GLOSSARY_DIR / "glossary_nsfw.json"
        base = nsfw if self._settings["nsfw"] and nsfw.exists() else GLOSSARY_DIR / "glossary.json"
        terms = self._project_glossary()["terms"]
        turkish = self._settings["target"] == "tr"   # hazır sözlükler Türkçedir; başka dilde yalnızca oyunun terimleri
        if turkish and (not terms or not self._game):
            return base
        if not self._game:
            return None
        merged = {k: v for k, v in _read_json(base, {}).items() if not str(k).startswith("_")} if turkish else {}
        merged.update(terms)
        path = project_glossary_path(Path(self._game["root"])).with_suffix(".merged.json")
        _write_json(path, merged)
        return path

    def _glossary(self, base_file: str) -> Glossary:
        glossary = Glossary.from_file(GLOSSARY_DIR / base_file)
        if self._settings["nsfw"]:
            extra = _read_json(GLOSSARY_DIR / "glossary_nsfw.json", {})
            extra.pop("_aciklama", None)
            glossary.entries.update({str(k): str(v) for k, v in extra.items()})
        glossary.entries.update(self._project_glossary()["terms"])
        return glossary

    def _extra_instruction(self) -> str:
        """Oyuna özel bağlam: notlar, hitap ve terim karşılıkları (bulut modellerinin talimatına eklenir)."""
        pg = self._project_glossary()
        title = self._game["title"] if self._game else ""
        terms = list(pg["terms"].items())[:80]
        if self._settings["target"] == "tr":
            lines = [f"Oyuna özel bilgiler — {title}:"]
            if pg["notes"].strip():
                lines.append(f"- Bağlam: {pg['notes'].strip()}")
            lines.append("- Hitap: karakterler birbirine ve oyuncuya " +
                         ("'siz' diye (resmi) hitap etsin." if pg["address"] == "siz" else "'sen' diye (samimi) hitap etsin."))
            if terms:
                lines.append("- Şu isim ve terimleri tam olarak bu karşılıklarla kullan (karakter adlarını çevirme): "
                             + "; ".join(f"{k} → {v}" for k, v in terms))
        else:
            lines = [f"Game-specific information — {title}:"]
            if pg["notes"].strip():
                lines.append(f"- Context: {pg['notes'].strip()}")
            if terms:
                lines.append("- Use exactly these renderings for names and terms (do not translate character names): "
                             + "; ".join(f"{k} → {v}" for k, v in terms))
        return "\n".join(lines) if len(lines) > 1 else ""

    def project_glossary_load(self) -> Optional[Dict[str, Any]]:
        if not self._game:
            return None
        pg = self._project_glossary()
        return {"title": self._game["title"], "engine": self._game["type"], "rows": [[k, v] for k, v in pg["terms"].items()],
                "address": pg["address"], "notes": pg["notes"], "aes_key": pg["aes_key"]}

    def project_glossary_save(self, rows: List[List[str]], address: str = "sen", notes: str = "",
                              aes_key: Optional[str] = None) -> Dict[str, Any]:
        game = self._require_game()
        terms = {str(a).strip(): str(b).strip() for a, b in (r for r in rows if len(r) == 2) if str(a).strip() and str(b).strip()}
        key = self._project_glossary()["aes_key"] if aes_key is None else re.sub(r"\s+", "", aes_key)
        _write_json(project_glossary_path(Path(game["root"])),
                    {"terms": terms, "address": "siz" if address == "siz" else "sen", "notes": notes or "", "aes_key": key,
                     "names_scanned": bool(self._project_glossary().get("names_scanned"))})
        return {"ok": True, "count": len(terms)}

    @staticmethod
    def _character_names(game: Dict[str, Any]) -> Optional[List[str]]:
        """Oyunun karakter adları (motor desteklemiyorsa None)."""
        info = game["info"]
        if game["type"] == "renpy":
            return scan_renpy_characters(Path(info.game_dir))
        if game["type"] == "rpgmaker":
            return scan_rpgmaker_characters(Path(info.data_dir))
        if game["type"] in KAG_ENGINES:
            from engine_kag import character_names
            return character_names(info, lambda s: None)
        return None

    def _auto_character_names(self, game: Dict[str, Any]) -> List[str]:
        """İlk çeviriden önce oyunun karakter adlarını bir kez tarayıp proje sözlüğüne "olduğu gibi kalsın" diye ekler.
        Yalnızca özel ada benzeyenler alınır ("Mom", "Guard", "???" gibi çevrilmesi gerekenler alınmaz) ve yalnızca
        Latin alfabeli hedef dillerde yapılır (Rusça/Japonca'da adlar o alfabeye aktarılmalı)."""
        if not self._settings.get("auto_names", True) or self._settings["target"] not in LATIN_TARGETS:
            return []
        pg = self._project_glossary()
        if pg.get("names_scanned"):
            return []
        try:
            names = self._character_names(game)
        except Exception as exc:
            self._log(f"Karakter adları taranamadı: {exc}")
            return []
        if names is None:
            return []
        added = [n for n in names if looks_like_name(n) and n not in pg["terms"]][:200]
        pg["terms"].update({n: n for n in added})
        pg["names_scanned"] = True
        _write_json(project_glossary_path(Path(game["root"])), pg)
        if added:
            shown = ", ".join(added[:6]) + ("…" if len(added) > 6 else "")
            self._log(f"Karakter adları oyuna özel sözlüğe eklendi: {', '.join(added)}")
            self._notify(f"{_n(len(added))} karakter adı korunacak", f"{shown}. Oyuna özel sözlükten değiştirebilirsin.",
                         "info", "book", {"label": "Sözlük", "page": "glossary"})
        return added

    def project_scan_characters(self) -> Dict[str, Any]:
        """Karakter adlarını oyundan tarar ve proje sözlüğüne (adı aynen koruyacak şekilde) ekler."""
        game = self._require_game()
        names = self._character_names(game)
        if names is None:
            return {"ok": False, "msg": f"{ENGINE_LABELS[game['type']]} için karakter taraması desteklenmiyor.", "added": 0}
        pg = self._project_glossary()
        added = [n for n in names if n not in pg["terms"]]
        pg["terms"].update({n: n for n in added})
        _write_json(project_glossary_path(Path(game["root"])), pg)
        return {"ok": True, "found": len(names), "added": len(added), "names": names[:50]}

    def _translate_strings(self, unique: List[str], cache_path: Path, pattern: Any, glossary: Glossary,
                           game_engine: str, failed: set, extra: Optional[str] = None,
                           engine_tags: Any = None, speakers: Optional[Dict[str, str]] = None,
                           source_lang: Optional[str] = None) -> Dict[str, str]:
        """Motor bağımsız: benzersiz metinleri seçili sağlayıcıyla çevirir (önbellek + sözlük).
        engine_tags: bulut motorlarının etiket denetiminde kullanılacak motor kuralı (yoksa Ren'Py/genel kural).
        speakers: {kaynak: konuşan karakter} — Gemini/OpenAI/Claude'a hitap ve cinsiyet için bildirilir."""
        from engine_common import TranslationEngine, make_llm_engine
        from engine_renpy import load_gemini_api_key, translate_with_gemini
        s, cfg, model = self._settings, prov.load_provider_config(), self._settings["model"]
        cache = TranslationCache(cache_path)
        cache.load()
        translations: Dict[str, str] = {}
        for src in unique:
            hit = glossary.lookup(src)
            if hit is not None:
                translations[src] = hit
            elif not re.search(r"[^\W\d_]", src):   # harf yok (sayı/noktalama); Japonca/Çince satırlar çevrilir
                translations[src] = src
        # Önbellekte kendisiyle kayıtlı Çince/Japonca/Korece satır: eskiden "harf yok" sayılıp çevrilmeden bırakılmıştı
        foreign = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
        cjk_target = s["target"] in ("ja", "zh-CN", "zh-TW", "ko")

        def stale(src: str) -> bool:
            return not cjk_target and cache.get(src) == src and bool(foreign.search(src))
        missing = [src for src in unique if src not in translations and (src not in cache or stale(src))]
        self._log(f"Benzersiz: {_n(len(unique))} · Önbellekte: {_n(len(unique) - len(missing))} · Çevrilecek: {_n(len(missing))}")
        source = source_lang or ("en" if s["source"] == "auto" else s["source"])
        extra = self._extra_instruction() if extra is None else extra
        if missing:
            if model == "gemini":
                translate_with_gemini(missing, cache.data, cache_path, load_gemini_api_key(), log=self._log,
                                      progress=self._progress, target_lang=s["target"], source_lang=source,
                                      game_engine=game_engine, failed_out=failed, extra_instruction=extra,
                                      protected=engine_tags, speakers=speakers)
            elif model in CLOUD_MODELS:
                prov.translate_with_cloud(model, missing, cache.data, cache_path, cfg, log=self._log,
                                          progress=self._progress, target_lang=s["target"], source_lang=source,
                                          game_engine=game_engine, failed_out=failed, extra_instruction=extra,
                                          protected=engine_tags, speakers=speakers)
            else:
                if model in ("ollama", "local"):
                    engine = make_llm_engine(model, self._llm_model(cfg), cfg.ollama_host, cache, pattern, self._log,
                                             s["target"], source, glossary=glossary)
                else:
                    engine = TranslationEngine(
                        model_dir=prov.offline_model_dir(model),
                        model_kind=model, cache=cache, glossary=glossary, protected_pattern=pattern, log=self._log,
                        source_lang=source, target_lang=s["target"],
                    )
                try:
                    translations.update(engine.translate_batch(missing, progress=self._progress))
                finally:
                    if hasattr(engine, "unload_model") and getattr(engine, "_model", None) is not None:
                        engine.unload_model()
        for src in unique:
            if src not in translations and cache.get(src) is not None:
                translations[src] = cache.get(src)
        return translations

    def _translate_renpy(self, game: Dict[str, Any], failed: set) -> int:
        from engine_renpy import (
            analyze_game, augment_ui_string_templates, backup_translation, enable_turkish,
            generate_templates, language_reference, overlay_english_dialogue_sources, qa_translation,
            repair_safe_issues, repair_say_prefixes, restore_orphaned_translation_bytecode,
            translate_templates,
        )
        s, cfg = self._settings, prov.load_provider_config()
        info = analyze_game(game["root"], self._log, language=renpy_language_name(s["target"]))
        if self._want_backup(game):
            self._stage("backup", "Mevcut çeviri dosyaları yedekleniyor")
            backup_translation(info, self._log)
        self._stage("prepare", "Oyunun metinleri hazırlanıyor")
        tl_dir = generate_templates(info, self._log)
        restore_orphaned_translation_bytecode(info.game_dir, self._log)
        augment_ui_string_templates(info, tl_dir, self._log)
        with language_reference(info.game_dir, "english", self._log) as english:   # RPA içindeyse geçici çıkarılır
            if english is not None:
                overlay_english_dialogue_sources(tl_dir, english, False, self._log)
        self._stage("translate", f"{MODEL_LABELS[s['model']]} çeviriyor")
        written = translate_templates(
            tl_dir=tl_dir,
            model_dir=prov.offline_model_dir(s["model"]),
            cache_path=self._cache_path(),
            glossary_path=self._glossary_path(),
            log=self._log,
            progress=self._progress,
            model_kind=s["model"],
            ollama_model=self._llm_model(cfg),
            ollama_host=cfg.ollama_host,
            failed_out=failed,
            extra_instruction=self._extra_instruction(),
            target_lang=s["target"],
            source_lang="en" if s["source"] == "auto" else s["source"],
            character_names=renpy_character_map(info.game_dir) if s["model"] in SPEAKER_MODELS else None,
        )
        self._learn_speed(game)
        if s.get("quality_pass"):
            self._stage("translate", "Kalite editörü sorunlu satırları düzeltiyor")
            self._run_quality(tl_dir)
        self._stage("write", "Çeviri oyuna uygulanıyor")
        enable_turkish(info, True, self._log, fallback_font=self._cjk_font(s["target"], info))
        repair_say_prefixes(tl_dir, self._log)
        repair_safe_issues(tl_dir, self._log)
        qa = qa_translation(tl_dir)
        self._log(f"QA: {qa['checked']} hedef · etiket hatası {qa['token_errors']} · boş {qa['empty_errors']} · "
                  f"artık {qa['artifacts']}")
        if s.get("renpy_compile_check", True):
            from engine_renpy import compile_check
            self._stage("write", "Oyunun Ren'Py'siyle derleme denetimi")
            check = compile_check(info, tl_dir, self._log)
            game["compile_check"] = check
            if check["reverted"]:
                self._notify(f"{check['reverted']} satır orijinal bırakıldı",
                             "Bu çeviri satırları oyunun Ren'Py'sinde derleme hatası verdi; oyun bozulmasın diye orijinal "
                             "metin kullanıldı. Editörde turuncu görünürler.", "warn", "edit",
                             {"label": "Editörde aç", "page": "editor"})
            if check["errors"]:
                self._notify("Derleme uyarısı", f"{len(check['errors'])} çeviri satırında Ren'Py derleme hatası kaldı; "
                             "ayrıntı Teknik günlükte.", "warn", "alert")
        return written

    def _translate_unity(self, game: Dict[str, Any], failed: set) -> int:
        from engine_unity import detect_unity_game, extract_texts_unity, translate_texts_unity, write_translations_unity
        from unity_bepinex import generate_bepinex_autotranslator_config, is_bepinex_installed, sync_cache_to_bepinex
        s, cfg = self._settings, prov.load_provider_config()
        info = game["info"] or detect_unity_game(game["root"])
        game["info"] = info
        self._stage("prepare", "Oyunun metinleri hazırlanıyor")
        texts = game["texts"] if game["texts"] is not None else extract_texts_unity(info, self._log)
        unique = sorted({t.original for t in texts if t.original.strip()})
        # İzin çeviriden önce istenir: "hayır" denirse boşuna API harcanmaz
        use_bridge = False
        # Utage gibi senaryosu dosyada açık oyunlar IL2CPP olsa da köprüye ihtiyaç duymaz
        scenario_in_files = any(t.format_type in ("utage", "typed", "loc_file", "loc_bundle") for t in texts)
        if not texts or (info.runtime == "IL2CPP" and not scenario_in_files):
            import bepinex_installer
            installed = is_bepinex_installed(info.root)
            use_bridge = self._ask("BepInEx köprüsü", (
                ("Bu oyunun metinlerinin bir kısmı dosyalarda açık değil (IL2CPP / paketli).\n\n"
                 "Çeviriyi oyunda göstermek için XUnity.AutoTranslator dosyaları yazılsın mı?" if installed else
                 "Bu oyunun metinlerinin bir kısmı dosyalarda açık değil (IL2CPP / paketli).\n\n"
                 "Çeviriyi oyunda göstermek için BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip kurulsun mu? "
                 "Tek tıkla geri alınabilir.") if texts else
                ("Bu oyunun metinleri dosyalarda açık değil (IL2CPP / paketli).\n\n"
                 "Çeviriyi oyunda göstermek için XUnity.AutoTranslator dosyaları yazılsın mı?\n\n"
                 "Hayır dersen bu oyun çevrilemez." if installed else
                 "Bu oyunun metinleri dosyalarda açık değil (IL2CPP / paketli).\n\n"
                 "Çeviriyi oyunda göstermek için BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip kurulsun mu? "
                 "Tek tıkla geri alınabilir.\n\nHayır dersen bu oyun çevrilemez.")))
            if not use_bridge and not texts:
                raise UserError("Metinler dosyalarda açık değil; BepInEx olmadan çevrilemez. İstersen çeviriyi yeniden başlatıp izin ver.")
        if self._want_backup(game):
            from engine_unity import localization_outputs
            files = {info.root / t.source_file for t in texts if t.format_type == "tsv_file"}
            if info.resources_assets_path and any(t.source_file == "resources.assets" for t in texts):
                files.add(info.resources_assets_path)
            files |= {info.data_dir / t.source_file for t in texts if t.format_type in ("utage", "tsv_col", "i2", "typed")}
            loc_backup, loc_created = localization_outputs(info, texts, s["target"])
            files |= set(loc_backup)
            if files or loc_created:
                self._stage("backup", "Orijinal dosyalar yedekleniyor")
                create_game_backup(info.root, "unity", sorted(files), log=self._log, created=loc_created)
        self._stage("translate", f"{MODEL_LABELS[s['model']]} çeviriyor")
        translations = translate_texts_unity(
            unique_sources=unique,
            cache_path=self._cache_path(),
            target_lang=s["target"], source_lang=s["source"],
            glossary=self._glossary("glossary.json"),
            log=self._log, progress=self._progress, tracker=None,
            model_kind=s["model"],
            model_dir=prov.offline_model_dir(s["model"]),
            ollama_model=self._llm_model(cfg), ollama_host=cfg.ollama_host, failed_out=failed,
            extra_instruction=self._extra_instruction(),
        )
        self._learn_speed(game)
        if s.get("quality_pass") and texts:
            translations.update(self._quality_edits(unique, translations))
        self._stage("write", "Çeviri oyuna yazılıyor")
        info.runtime_missing = set((self._library.get(game["root"]) or {}).get("runtime_missing") or "")
        written = write_translations_unity(info, translations, texts, self._log, target_lang=s["target"]) if texts else 0
        game["texts"] = None  # Varlıklar değişti; bir sonraki analizde yeniden okunur
        game["analysis"] = None

        if use_bridge:
            import bepinex_installer
            if not is_bepinex_installed(info.root):
                self._status("BepInEx ve XUnity.AutoTranslator kuruluyor…")
                bepinex_installer.install(info.root, runtime=info.runtime, log=self._log)
            written += sync_cache_to_bepinex(info.root, translations, target_lang=s["target"], log=self._log)
            generate_bepinex_autotranslator_config(info.root, target_lang=s["target"], source_lang=s["source"], log=self._log)
            if not written:
                game["result_note"] = "BepInEx kuruldu. Oyunu açınca metinler yakalanır; çevrilecek satırlar oyunu oynadıkça oluşur."
        return written

    def _translate_unreal(self, game: Dict[str, Any], failed: set) -> int:
        from engine_unreal import detect_unreal_game, extract_texts_unreal, write_translations_unreal
        from unreal_modding import generate_ue4ss_translation_config, setup_unreal_mods_folder
        s = self._settings
        info = game["info"] or detect_unreal_game(game["root"])
        if not info.locres_files and info.pak_files:
            return self._translate_unreal_pak(game, info, failed)
        self._stage("prepare", "Oyunun metinleri hazırlanıyor")
        texts = game["texts"] if game["texts"] is not None else extract_texts_unreal(
            info, source_lang_code=s["source"], log=self._log)
        if not texts:
            raise UserError("Bu oyunda çevrilebilir .locres metni bulunamadı.")
        if self._want_backup(game):
            self._stage("backup", "Orijinal dosyalar yedekleniyor")
            create_game_backup(info.root, "unreal", info.locres_files, log=self._log)
        unique = sorted({t.original for t in texts if t.original.strip()})
        self._stage("translate", f"{MODEL_LABELS[s['model']]} çeviriyor")
        translations = self._unreal_translate(unique, failed)
        self._learn_speed(game)
        self._stage("write", "Çeviri oyuna yazılıyor")
        written = write_translations_unreal(info, translations, texts, target_lang_code=s["target"], log=self._log)
        if written and info.has_iostore:
            setup_unreal_mods_folder(info, log=self._log)
            generate_ue4ss_translation_config(info, log=self._log)
        return written

    def _unreal_translate(self, unique: List[str], failed: set) -> Dict[str, str]:
        from engine_unreal import translate_texts_unreal
        s, cfg = self._settings, prov.load_provider_config()
        return translate_texts_unreal(
            unique_sources=unique, cache_path=self._cache_path(), target_lang=s["target"], source_lang=s["source"],
            glossary=self._glossary("glossary.json"), log=self._log, progress=self._progress, tracker=None,
            model_kind=s["model"], model_dir=prov.offline_model_dir(s["model"]),
            ollama_model=self._llm_model(cfg), ollama_host=cfg.ollama_host, failed_out=failed,
            extra_instruction=self._extra_instruction(),
        )

    def _unreal_pak_texts(self, game: Dict[str, Any], info: Any) -> Tuple[list, Path]:
        """Paketlerdeki kaynak dil .locres dosyalarını önbelleğe çıkarır ve metinleri okur."""
        import dataclasses
        import unreal_pak
        from engine_unreal import extract_texts_unreal
        key = self._project_glossary()["aes_key"]
        source = self._settings["source"]
        found = unreal_pak.find_localization(unreal_pak.game_paks(info.paks_dir), source, key, self._log)
        base = cache_file_for(Path(game["root"]), DATA_DIR)   # portable_cache/cache/<kimlik>.json
        staging = base.parent.parent / "unreal" / base.stem
        files = unreal_pak.extract(found, staging, key) if found else []
        if not found and info.has_iostore and unreal_pak.retoc_path():
            files = unreal_pak.extract_iostore(unreal_pak.find_iostore_localization(info.paks_dir, source, key, self._log),
                                               staging, key)
        self._log(f".pak içinden {len(files)} .locres dosyası çıkarıldı.")
        texts = extract_texts_unreal(dataclasses.replace(info, locres_files=files), source_lang_code=self._settings["source"],
                                     log=self._log)
        game["pak_found"] = found
        return texts, staging

    def _translate_unreal_pak(self, game: Dict[str, Any], info: Any, failed: set) -> int:
        """Metinleri .pak içinde olan oyunlar: repak ile çıkar → çevir → Paks/~mods yama paketi."""
        import dataclasses
        import unreal_pak
        from engine_unreal import write_translations_unreal
        if not unreal_pak.repak_path():
            if not self._ask("Ek araç kurulacak",
                             "Metinler .pak paketlerinde. Açmak için açık kaynak repak aracı (github.com/trumank/repak, ~2 MB) indirilsin "
                             "mi? Oyun dosyalarına dokunulmaz; çeviri ayrı bir yama paketi olur."):
                raise TranslationCancelled()
            self._stage("prepare", "repak aracı indiriliyor")
            unreal_pak.install_repak(log=self._log)
            self._notify("repak kuruldu", "Unreal paketleri artık açılabiliyor.", "ok", "download")
        self._stage("prepare", "Metinler .pak paketlerinden çıkarılıyor")
        try:
            texts, staging = self._unreal_pak_texts(game, info)
            if not texts and info.has_iostore and not unreal_pak.retoc_path():
                if not self._ask("Ek araç kurulacak",
                                 "Metinler .pak içinde yok; oyun IoStore (.utoc) kullanıyor. Okumak için açık kaynak retoc aracı "
                                 "(github.com/trumank/retoc, ~3 MB) indirilsin mi? Oyun dosyalarına dokunulmaz."):
                    raise TranslationCancelled()
                self._stage("prepare", "retoc aracı indiriliyor")
                unreal_pak.install_retoc(log=self._log)
                self._notify("retoc kuruldu", "IoStore kapsayıcıları artık okunabiliyor.", "ok", "download")
                self._stage("prepare", "Metinler IoStore kapsayıcılarından çıkarılıyor")
                texts, staging = self._unreal_pak_texts(game, info)
        except unreal_pak.NeedsAesKey:
            raise UserError("Paketler AES ile şifreli. Anahtarı Sözlük → Bu oyun sekmesindeki 'AES anahtarı' alanına girip tekrar dene.")
        except unreal_pak.UnsupportedContainer:
            raise UserError("Bu oyunun paket biçimi çok yeni; açık kaynak araçlar henüz okuyamıyor. Bu oyunda ekran çevirisini (OCR) kullanabilirsin.")
        if not texts:
            raise UserError("Paketlerde kaynak dilde (.locres) metin bulunamadı.")
        unique = sorted({t.original for t in texts if t.original.strip()})
        self._stage("translate", f"{MODEL_LABELS[self._settings['model']]} çeviriyor")
        translations = self._unreal_translate(unique, failed)
        self._learn_speed(game)
        self._stage("write", "Yama paketi oluşturuluyor")
        files = sorted({t.locres_path for t in texts})
        written = write_translations_unreal(dataclasses.replace(info, locres_files=files), translations, texts,
                                            target_lang_code=self._settings["target"], create_lang_folder=False,
                                            log=self._log)
        if written:
            first = next(iter(game.get("pak_found") or {}), None) or next(iter(unreal_pak.game_paks(info.paks_dir)), None)
            try:
                version = unreal_pak.pak_info(first, self._project_glossary()["aes_key"]).get("version", "V11") if first else "V11"
            except Exception:
                version = "V11"
            pak = unreal_pak.pack_mod(staging, info.paks_dir, self._settings["target"], version, log=self._log)
            unreal_pak.write_manifest(Path(info.root), pak, [p.relative_to(staging).as_posix() for p in files])
            self._notify("Yama paketi eklendi", f"{pak.name} · Paks/~mods klasörüne yazıldı. Kaldırmak için bu dosyayı "
                         "silmen yeterli.", "ok", "archive")
        game["texts"] = None
        game["analysis"] = None
        return written

    def _translate_rpgmaker(self, game: Dict[str, Any], failed: set) -> int:
        from engine_rpgmaker import (PROTECTED_RPGM, RGSS_EXT, RPGM_EXTRA_INSTRUCTION, detect_rpgmaker_game,
                                     join_speaker, speaker_sources, split_speaker, write_translations_mv_mz,
                                     write_translations_vxace)
        info = game["info"] or detect_rpgmaker_game(game["root"])
        rgss = info.engine_type in RGSS_EXT
        if rgss and self._rgss_archive(info):
            info = self._rgss_unpack(game, info)
            game["texts"] = None
        if rgss and not self._rgss_loose(info):
            raise UserError(f"{info.version_label}: çevrilecek veri dosyası bulunamadı.")
        if self._want_backup(game):
            self._stage("backup", "Orijinal dosyalar yedekleniyor")
            pattern = f"*{RGSS_EXT[info.engine_type]}" if rgss else "*.json"
            files = sorted(info.data_dir.glob(pattern))
            if not rgss:
                from engine_rpgmaker import plugins_file
                files += [plugins_file(info.data_dir)] if plugins_file(info.data_dir).is_file() else []
            create_game_backup(info.root, "rpgmaker", files, log=self._log)
        self._stage("prepare", "Oyunun metinleri hazırlanıyor")
        texts = game["texts"] if game["texts"] is not None else self._rpgm_extract(info)
        self._safely(lambda: self._save_fit(game, text_fit.rpgm_limits(texts, info.data_dir, info.engine_type)))
        unique = list(dict.fromkeys(t.original for t in texts if t.original.strip()))
        sources = speaker_sources(unique)   # \name[勇者] satırları: ad ve gövde ayrı çevrilir
        self._stage("translate", f"{MODEL_LABELS[self._settings['model']]} çeviriyor")
        extra = "\n\n".join(x for x in (self._extra_instruction(), RPGM_EXTRA_INSTRUCTION) if x)
        speakers: Dict[str, str] = {}
        for t in texts:
            if t.context == "dialogue" and t.speaker.strip():
                speakers.setdefault(t.original, t.speaker.strip())
            name, body = split_speaker(t.original)
            if name and body.strip():
                speakers.setdefault(body, name)
        translations = self._translate_strings(sources, self._cache_path(), PROTECTED_RPGM,
                                               self._glossary("glossary_rpgm.json"), "RPG Maker Game", failed,
                                               extra=extra, engine_tags=PROTECTED_RPGM, speakers=speakers)
        self._learn_speed(game)
        if self._settings.get("quality_pass"):
            translations.update(self._quality_edits(sources, translations))
        translations = join_speaker(unique, translations)
        self._stage("write", "Çeviri oyuna yazılıyor")
        game["texts"] = None
        game["analysis"] = None
        if rgss:
            return write_translations_vxace(info.data_dir, translations, self._log, engine_type=info.engine_type)
        return write_translations_mv_mz(info.data_dir, translations, self._log, language=self._settings["target"])

    # ── Dosya tabanlı motorlar: TyranoScript, KiriKiri, Godot, WOLF RPG ───────
    # Dördü aynı yolu izler: algıla → metinleri çıkar → (yedekle) → çevir → yaz. Motora özgü olan yalnızca algılama,
    # çıkarma, yazma, etiket deseni ve ek talimattır; ortak adımlar aşağıdaki iki yardımcıdadır.
    def _unreadable_analysis(self, game: Dict[str, Any], info: Any, note: str, summary: str) -> Dict[str, Any]:
        """Şifreli / okunamayan oyun: satır yok, uyarı var."""
        game["texts"] = []
        self._log(note)
        return {"engine": game["type"], "lines": 0, "unique": 0, "notes": [info.label, note], "engine_detail": info.label,
                "advice": [{"tone": "warn", "text": note}], "sample": "", "summary": summary, "meta": "şifreli"}

    def _file_engine_analysis(self, game: Dict[str, Any], info: Any, texts: List[Any], notes: List[str],
                              advice: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        game["texts"] = texts
        unique = len({t.original for t in texts})
        for note in notes:
            self._log(note)
        return {"engine": game["type"], "lines": len(texts), "unique": unique, "notes": notes,
                "engine_detail": info.label, "advice": advice or [], "sample": texts[0].original if texts else "",
                "summary": f"{_n(len(texts))} satır ({_n(unique)} benzersiz) bulundu.", "meta": f"{_n(unique)} satır"}

    def _translate_file_engine(self, game: Dict[str, Any], failed: set, texts: List[Any], *, root: Path,
                               backup: Callable[[], Tuple[List[Path], List[Path]]], pattern: Any, instruction: str,
                               game_engine: str, write: Callable[[Dict[str, str]], int],
                               speakers: Optional[Dict[str, str]] = None, default_lang: str = "en",
                               write_label: str = "Çeviri oyuna yazılıyor") -> int:
        """Ortak çeviri yolu. Kaynak dil metinden algılanır; OPUS-MT yalnızca İngilizceden çevirdiği için başka dilde
        durdurulur. Türkçe hedefte ve İngilizce kaynakta genel sözlük, diğerlerinde yalnızca oyuna özel terimler."""
        sources = list(dict.fromkeys(t.original for t in texts))
        if not sources:
            raise UserError("Oyuna yazılacak satır bulunamadı; oyunda değişiklik yapılmadı.")
        source_lang = detect_source_language(sources, default_lang)
        if self._settings["model"] in TURKISH_ONLY_MODELS and source_lang != "en":
            raise UserError(f"{MODEL_LABELS[self._settings['model']]} yalnızca İngilizceden çevirir; bu oyunun dili "
                            f"{source_lang}. Gemini, OpenAI, Claude ya da NLLB seç.")
        if self._want_backup(game):
            self._stage("backup", "Orijinal dosyalar yedekleniyor")
            files, created = backup()
            create_game_backup(root, game["type"], files, log=self._log, created=created)
        self._stage("translate", f"{MODEL_LABELS[self._settings['model']]} çeviriyor")
        extra = "\n\n".join(x for x in (self._extra_instruction(), instruction) if x)
        glossary = self._glossary("glossary.json") if self._settings["target"] == "tr" and source_lang == "en" \
            else Glossary(self._project_glossary()["terms"])
        translations = self._translate_strings(sources, self._cache_path(), pattern, glossary, game_engine, failed,
                                               extra=extra, engine_tags=pattern, speakers=speakers,
                                               source_lang=source_lang)
        self._learn_speed(game)
        if self._settings.get("quality_pass"):
            translations.update(self._quality_edits(sources, translations))
        self._stage("write", write_label)
        game["texts"] = None
        game["analysis"] = None
        return write(translations)

    # TyranoScript / KiriKiri
    def _analyze_kag(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_kag import detect_kag_game, extract_texts
        info = game["info"] or detect_kag_game(game["root"])
        game["info"] = info
        if info.encrypted:
            return self._unreadable_analysis(game, info, (
                "Oyunun arşivi (xp3) oyuna özel bir şifreyle korunuyor; senaryo okunamıyor. Bu oyun ekran "
                "çevirisiyle (OCR) çevrilebilir."), "Arşiv şifreli; metin okunamadı.")
        texts = extract_texts(info, log=self._log)
        unique = len({t.original for t in texts})
        choices = sum(1 for t in texts if t.context == "choice")
        notes = [info.label, f"{_n(len(info.scenario))} senaryo dosyası",
                 f"Çevrilebilir metin: {_n(len(texts))} satır ({_n(unique)} benzersiz, {_n(choices)} seçenek)"]
        source = detect_source_language([t.original for t in texts])
        if source != "en":
            notes.append(f"Kaynak dil: {source} (otomatik algılandı)")
        return self._file_engine_analysis(game, info, texts, notes)

    _analyze_tyrano = _analyze_kirikiri = _analyze_kag

    def _translate_kag(self, game: Dict[str, Any], failed: set) -> int:
        from engine_kag import (KAG_EXTRA_INSTRUCTION, PROTECTED_KAG, detect_kag_game, extract_texts,
                                files_to_backup, write_translations)
        info = game["info"] or detect_kag_game(game["root"])
        if info is None:
            raise UserError("Oyunun senaryo dosyaları bulunamadı.")
        if info.encrypted:
            raise UserError("Oyunun arşivi şifreli; senaryo okunamıyor. Bu oyunu ekran çevirisiyle (OCR) çevirebilirsin.")
        texts = game["texts"] if game.get("texts") is not None else extract_texts(info, log=self._log)
        return self._translate_file_engine(
            game, failed, texts, root=info.root, backup=lambda: files_to_backup(info), pattern=PROTECTED_KAG,
            instruction=KAG_EXTRA_INSTRUCTION, game_engine="visual novel",
            speakers={t.original: t.speaker for t in texts if t.speaker},
            write=lambda translations: write_translations(info, translations, self._log))

    _translate_tyrano = _translate_kirikiri = _translate_kag

    def _apply_kag(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_kag import detect_kag_game, write_translations
        self._restore_originals(game)
        return write_translations(detect_kag_game(game["root"]), cache, self._log)

    _apply_tyrano = _apply_kirikiri = _apply_kag

    # Godot
    def _analyze_godot(self, game: Dict[str, Any]) -> Dict[str, Any]:
        import engine_godot
        info = game["info"] or engine_godot.detect_godot(game["root"])
        game["info"] = info
        if info.encrypted:
            return self._unreadable_analysis(
                game, info, "Oyunun Godot paketi şifreli; metinler okunamıyor. Bu oyun ekran çevirisiyle (OCR) çevrilebilir.",
                "Paket şifreli; metin okunamadı.")
        texts = engine_godot.extract_texts(info, log=self._log)
        tables = sum(1 for t in texts if t.kind != "ui")
        notes = [info.label, f"Kaynak dil: {info.source_locale}",
                 f"Çeviri tablosu metni: {_n(tables)} · sahnelerdeki arayüz yazısı: {_n(len(texts) - tables)}"]
        advice = [] if texts else [{"tone": "warn", "text": (
            "Bu oyunun metinleri çeviri tablolarında ya da sahnelerde değil, büyük olasılıkla betiklerin içinde. "
            "Ekran çevirisi (OCR) kullanılabilir.")}]
        return self._file_engine_analysis(game, info, texts, notes, advice)

    def _translate_godot(self, game: Dict[str, Any], failed: set) -> int:
        import engine_godot
        info = game["info"] or engine_godot.detect_godot(game["root"])
        if info is None or info.encrypted:
            raise UserError("Oyunun Godot paketi okunamıyor (şifreli olabilir). Ekran çevirisini (OCR) kullanabilirsin.")
        engine_godot.load_details(info)
        texts = game["texts"] if game.get("texts") is not None else engine_godot.extract_texts(info, log=self._log)
        return self._translate_file_engine(
            game, failed, texts, root=info.root, backup=lambda: engine_godot.files_to_backup(info),
            pattern=engine_godot.PROTECTED_GODOT, instruction=engine_godot.GODOT_EXTRA_INSTRUCTION,
            game_engine="video game", default_lang=info.source_locale.split("_")[0] or "en",
            write_label="Çeviri yaması yazılıyor",
            write=lambda translations: engine_godot.write_translations(info, translations, self._log, units=texts))

    def _apply_godot(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        import engine_godot
        self._restore_originals(game)
        return engine_godot.write_translations(engine_godot.detect_godot(game["root"]), cache, self._log)

    # WOLF RPG
    WOLF_ARCHIVE_NOTE = ("Oyunun verileri WOLF Pro ile oyuna özel anahtarla şifrelenmiş; Capri bu arşivi açamıyor. "
                         "Bu oyun için ekran çevirisini (OCR) kullanabilirsin.")
    WOLF_PACKED_NOTE = ("Veriler şifreli .wolf arşivinde ({label}). Çeviri başlarken arşiv oyun klasörüne açılır, "
                        "orijinali yedeklenir; Yedekler'den tek tıkla geri konabilir.")
    WOLF_SJIS_NOTE = ("Bu oyun eski WOLF RPG sürümüyle (Shift-JIS) yapılmış: ğ, ş, ı, ç, ö, ü gibi harfler oyunda "
                      "gösterilemediği için en yakın harfle (g, s, i…) yazılır.")

    def _analyze_wolf(self, game: Dict[str, Any]) -> Dict[str, Any]:
        import engine_wolf
        info = game["info"] or engine_wolf.detect_wolf(game["root"])
        game["info"] = info
        if info.archived and not info.archive_supported:
            self._log(f"WOLF arşivi açılamadı: {info.archive_error}")
            return self._unreadable_analysis(game, info, self.WOLF_ARCHIVE_NOTE, "Veriler şifreli arşivde; metin okunamadı.")
        texts = engine_wolf.extract_texts(info, log=self._log)
        unique = len({t.original for t in texts})
        notes = [info.label, f"{_n(len(info.files))} veri dosyası · {_n(len(texts))} satır ({_n(unique)} benzersiz)"]
        if info.archived:
            notes.append(self.WOLF_PACKED_NOTE.format(label=info.archive_label))
        if info.encrypted_files:
            notes.append(f"Şifreli dosyalar atlandı: {', '.join(info.encrypted_files[:5])}")
        advice = [{"tone": "warn", "text": self.WOLF_SJIS_NOTE}] \
            if info.utf8 is False and self._settings["target"] not in ("ja", "en") else []
        return self._file_engine_analysis(game, info, texts, notes, advice)

    def _translate_wolf(self, game: Dict[str, Any], failed: set) -> int:
        import engine_wolf
        info = game["info"] or engine_wolf.detect_wolf(game["root"])
        if info is not None and info.archived:
            info = self._wolf_unpack(game, info)
        if info is None or info.archived:
            raise UserError(self.WOLF_ARCHIVE_NOTE)
        texts = game["texts"] if game.get("texts") is not None else engine_wolf.extract_texts(info, log=self._log)
        return self._translate_file_engine(
            game, failed, texts, root=info.root, backup=lambda: (engine_wolf.files_to_backup(info), []),
            pattern=engine_wolf.PROTECTED_WOLF, instruction=engine_wolf.WOLF_EXTRA_INSTRUCTION, game_engine="RPG game",
            write=lambda translations: self._write_wolf(info, translations))

    def _write_wolf(self, info: Any, translations: Dict[str, str]) -> int:
        import engine_wolf
        written, lossy = engine_wolf.write_translations(info, translations, self._log)
        if lossy:
            self._notify(f"{_n(lossy)} satırda harfler sadeleşti", self.WOLF_SJIS_NOTE, "warn", "alert")
        return written

    def _apply_wolf(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        import engine_wolf
        info = engine_wolf.detect_wolf(game["root"])
        if info is not None and info.archived:
            info = self._wolf_unpack(game, info)
        self._restore_originals(game)
        return self._write_wolf(info, cache)

    def _wolf_unpack(self, game: Dict[str, Any], info: Any) -> Any:
        """Şifreli WOLF arşivini kullanıcıya sorarak oyun klasörüne açar; açık klasörlü oyun bilgisini döndürür."""
        import engine_wolf
        if not info.archive_supported:
            self._log(f"WOLF arşivi açılamadı: {info.archive_error}")
            raise UserError(self.WOLF_ARCHIVE_NOTE)
        size_mb = max(1, sum((Path(info.root) / a).stat().st_size for a in info.archives) // (1 << 20))
        names = ", ".join(Path(a).name for a in info.archives[:3]) + ("…" if len(info.archives) > 3 else "")
        if not self._ask("Şifreli arşiv açılacak",
                         f"Oyunun dosyaları şifreli {names} arşivinde ({info.archive_label}). Capri arşivi oyun "
                         f"klasörüne açacak (~{size_mb} MB) ve orijinalini yedekleyecek; Yedekler'den geri alınabilir. "
                         "Devam edilsin mi?"):
            raise TranslationCancelled()
        self._stage("prepare", "WOLF arşivi açılıyor")
        self._progress_unit = "dosya"
        try:
            info = engine_wolf.unpack_archives(info, log=self._log, progress=self._progress)
        finally:
            self._progress_unit = "satır"
        self._notify("Arşiv açıldı", f"{names} oyun klasörüne çıkarıldı; orijinali yedeklendi.", "ok", "archive")
        game["info"] = info
        return info

    # ── BepInEx (Unity) ──────────────────────────────────────────────────────
    def install_bepinex(self) -> bool:
        def task():
            import bepinex_installer
            game = self._require_game()
            if game["type"] != "unity":
                raise UserError("BepInEx yalnızca Unity oyunları içindir.")
            if bepinex_installer.is_installed(game["root"]):
                raise UserError("BepInEx bu oyunda zaten kurulu.")
            if not self._ask("BepInEx kurulumu", "BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip oyuna kurulacak. Tek tıkla kaldırılabilir."):
                return
            manifest = bepinex_installer.install(game["root"], log=self._log)
            from unity_bepinex import generate_bepinex_autotranslator_config
            generate_bepinex_autotranslator_config(Path(game["root"]), target_lang=self._settings["target"],
                                                   source_lang=self._settings["source"], log=self._log)
            game["analysis"] = None
            self._notify("BepInEx kuruldu", f"BepInEx {manifest['versions']['bepinex']} + XUnity.AutoTranslator "
                         f"{manifest['versions']['xunity']} · {manifest['runtime']} {manifest['arch']}", "ok", "download")

        return self._run_task("BepInEx kurulumu", task)

    def uninstall_bepinex(self) -> bool:
        def task():
            import bepinex_installer
            game = self._require_game()
            if not self._ask("BepInEx'i kaldır", "Capri'nin kurduğu BepInEx dosyaları silinecek, değişen dosyalar geri yüklenecek."):
                return
            removed = bepinex_installer.uninstall(game["root"], log=self._log)
            game["analysis"] = None
            self._notify("BepInEx kaldırıldı", f"{_n(removed)} dosya silindi; oyun klasörü kurulum öncesi hâline döndü.",
                         "ok", "undo")

        return self._run_task("BepInEx kaldırma", task)

    # ── Kalite editörü (Ren'Py) ──────────────────────────────────────────────
    def _quality_provider(self) -> str:
        import local_llm
        from engine_common import ollama_family
        model = self._settings["model"]
        if model == "local" and local_llm.family(self._local_model_id()) == "gemma4":
            return "local"                                          # dahili Gemma 4 sohbet modeli
        translation_only = model == "local" or (
            model == "ollama" and ollama_family(prov.load_provider_config().ollama_model) != "chat")
        if model in prov.LLM_PROVIDERS and not translation_only:   # TranslateGemma/MiLMMT düzeltme yazamaz
            return model
        if prov.load_provider_config().gemini_keys:
            return "gemini"
        raise UserError("Kalite editörü bir sohbet modeli ister: Gemini, OpenAI, Claude, Ollama ya da yerel Gemma 4 seçin.")

    def _completer(self, provider: str, cfg: Any) -> Callable[[str, str], str]:
        if provider != "local":
            return lambda system, user: prov.llm_complete(provider, system, user, cfg)
        local = self._local_model_id()
        return lambda system, user: prov.llm_complete(provider, system, user, cfg, local_model=local)

    def _quality_edits(self, sources: List[str], translations: Dict[str, str]) -> Dict[str, str]:
        """Ren'Py dışı motorlar: sorunlu taslakları düzeltir, önbelleğe yazar ve düzeltmeleri döndürür."""
        from engine_renpy import quality_edit_pairs
        provider = self._quality_provider()
        cfg = prov.load_provider_config()
        self._stage("translate", f"Kalite editörü sorunlu satırları düzeltiyor ({MODEL_LABELS[provider]})")
        edits = quality_edit_pairs(sources, translations, self._completer(provider, cfg),
                                   target_lang=self._settings["target"], log=self._log, progress=self._progress,
                                   extra_instruction=self._extra_instruction())
        if edits:
            cache = TranslationCache(self._cache_path())
            cache.load()
            cache.update(edits)
            cache.save()
            self._notify("Kalite editörü tamamlandı", f"{_n(len(edits))} satır düzeltildi ({MODEL_LABELS[provider]}).", "ok", "edit")
        return edits

    def _run_quality(self, tl_dir: Path) -> Dict[str, int]:
        from engine_renpy import quality_edit_with_llm
        provider = self._quality_provider()
        cfg = prov.load_provider_config()
        self._status(f"Kalite editörü çalışıyor ({MODEL_LABELS[provider]})…")
        result = quality_edit_with_llm(
            tl_dir, self._cache_path(), self._completer(provider, cfg),
            log=self._log, progress=self._progress, extra_instruction=self._extra_instruction(),
            target_lang=self._settings["target"],
        )
        self._notify("Kalite editörü tamamlandı",
                     f"{_n(result['candidates'])} sorunlu taslaktan {_n(result['edited'])} satır düzeltildi "
                     f"({MODEL_LABELS[provider]}).", "ok", "edit")
        return result

    def quality_pass(self) -> bool:
        """Mevcut Ren'Py çevirisinde yalnızca kalite editörünü çalıştırır."""
        def task():
            game = self._require_game()
            from engine_renpy import analyze_game
            if game["type"] != "renpy":
                uniques = game.get("uniques") or []
                cache = _read_json(self._cache_path(), {})
                if not uniques or not cache:
                    raise UserError("Önce çeviriyi başlat; düzeltilecek çeviri yok.")
                if self._quality_edits(uniques, {u: cache[u] for u in uniques if u in cache}):
                    written = getattr(self, f"_apply_{game['type']}")(game, _read_json(self._cache_path(), {}))
                    self._status(f"Düzeltmeler oyuna yazıldı: {_n(written)} satır.", "ok")
                return
            tl_dir = analyze_game(game["root"], self._log, language=renpy_language_name(self._settings["target"])).tl_dir
            if not tl_dir.is_dir():
                raise UserError("Önce çeviriyi başlatın; Türkçe çeviri klasörü yok.")
            self._run_quality(tl_dir)

        return self._run_task("Kalite editörü", task)

    # ── Çeviri editörü ───────────────────────────────────────────────────────
    def editor_sources(self) -> List[Dict[str, Any]]:
        """Etkin proje için mevcut önbellekler (model başına)."""
        if not self._game:
            return []
        out = []
        for model in MODEL_LABELS:
            path = self._cache_path(model)
            if path.exists() or review_path_for(path).exists():
                out.append({"model": model, "label": MODEL_LABELS[model],
                            "count": len(_read_json(path, {})), "review": len(_read_json(review_path_for(path), []))})
        return out

    def _line_issues(self, src: str, tr: str, review: set, terms: Any, limits: Dict[str, int],
                     engine: str) -> List[str]:
        """Editörde bir satırın neden incelenmesi gerektiği (arayüz metni olarak)."""
        issues = []
        if tr == src or not tr:
            if src in review or re.search(r"[A-Za-z]{3}", src):
                issues.append("Çevrilmedi")
        elif not prov.placeholders_valid(src, tr):
            issues.append("Etiket ya da değişken farklı")
        if term_lost(src, tr, terms if isinstance(terms, TermRules) else term_rules(terms)):
            issues.append("Oyun terimi çeviride yok")
        if text_fit.too_long(src, tr, limits.get(src), engine):
            issues.append(f"Kutuya sığmayabilir (en çok {limits[src]} karakter)")
        if src in review and not issues:
            issues.append("İncelenmeli")
        return issues

    def _review_context(self, path: Path) -> Tuple[set, Dict[str, str], Dict[str, int], str, Any]:
        """(incelenmeli satırlar, terimler, kutu sınırları, motor, terim kuralları). Editör her aramada bunu ister:
        ilgili dosyalar değişmedikçe bellekten gelir."""
        game = self._game or {}
        fit = self._fit_path(game) if game.get("type") in text_fit.WIDTH_FUNCS else None
        glossary = project_glossary_path(Path(game["root"])) if game.get("root") else None
        key = (str(path), game.get("root"), game.get("type"), _mtime_ns(review_path_for(path)), _mtime_ns(fit),
               _mtime_ns(glossary))
        held = self._review_ctx
        if held and held[0] == key:
            return held[1]
        value = self._compute_review_context(path, game)
        self._review_ctx = (key, value)
        return value

    def _compute_review_context(self, path: Path, game: Dict[str, Any]) -> Tuple[set, Dict[str, str], Dict[str, int], str, Any]:
        limits: Dict[str, int] = {}
        if game.get("type") in text_fit.WIDTH_FUNCS:
            try:
                limits = self._fit_limits(game)
            except Exception:
                limits = {}
        terms = self._project_glossary().get("terms") or {}
        return set(_read_json(review_path_for(path), [])), terms, limits, game.get("type") or "", term_rules(terms)

    def editor_load(self, model: str, query: str = "", only_review: bool = False,
                    offset: int = 0, limit: int = 80) -> Dict[str, Any]:
        path = self._cache_path(model)
        cache, flags = self._editor_data(path)
        review, _terms, limits, engine, rules = self._review_context(path)

        def flagged(src: str, tr: str) -> bool:
            if src in review:
                return True
            value = flags.get(src)
            if value is None:   # doğrulama pahalı: yalnızca gerektiğinde hesaplanır, sonucu saklanır
                value = (tr == src and bool(re.search(r"[A-Za-z]{3}", src))) or (bool(tr) and not prov.placeholders_valid(src, tr)) \
                    or text_fit.too_long(src, tr, limits.get(src), engine) or term_lost(src, tr, rules)
                flags[src] = value
            return value

        q = (query or "").casefold()
        folded = self._editor_folded(cache) if q else {}
        matches = []
        for src in list(cache) + [r for r in review if r not in cache]:
            tr = cache.get(src, "")
            if q:
                low_src, low_tr = folded.get(src) or (src.casefold(), "")
                if q not in low_src and q not in low_tr:
                    continue
            if only_review and not flagged(src, tr):
                continue
            matches.append(src)
        items = []
        for src in matches[offset:offset + limit]:
            tr = cache.get(src, "")
            flag = flagged(src, tr)
            items.append({"src": src, "tr": tr, "flag": flag,
                          "why": self._line_issues(src, tr, review, rules, limits, engine) if flag else []})
        return {"total": len(matches), "items": items, "offset": offset,
                "model": model, "label": MODEL_LABELS.get(model, model)}

    def _editor_data(self, path: Path) -> Tuple[Dict[str, str], Dict[str, bool]]:
        """Önbellek dosyası değişmedikçe bellekten gelir (büyük oyunlarda arama her tuşta dosya okumaz)."""
        try:
            stamp = (str(path), path.stat().st_mtime_ns)
        except OSError:
            return {}, {}
        held = self._editor_cache
        if held and held[0] == stamp:
            return held[1], held[2]
        data = _read_json(path, {})
        self._editor_cache = (stamp, data, {})
        self._editor_fold = None
        return data, self._editor_cache[2]

    def _editor_folded(self, cache: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
        """{kaynak: (kaynak, çeviri) küçük harfli} — arama her tuşta bütün satırları yeniden küçültmez. Önbellek
        dosyası değişince (_editor_data) sıfırlanır."""
        held = self._editor_fold
        if held is not None and held[0] is cache:
            return held[1]
        folded = {src: (src.casefold(), str(tr).casefold()) for src, tr in cache.items()}
        self._editor_fold = (cache, folded)
        return folded

    def editor_save(self, model: str, changes: Dict[str, str]) -> Dict[str, Any]:
        path = self._cache_path(model)
        cache: Dict[str, str] = _read_json(path, {})
        bad = [src for src, tr in changes.items() if tr and not prov.placeholders_valid(src, tr)]
        if bad:
            return {"ok": False, "msg": f"{len(bad)} satırda etiket/değişken eksik veya fazla: {bad[0][:60]}"}
        fixes = {src: tr for src, tr in changes.items() if tr and cache.get(src) != tr}
        cache.update({src: tr for src, tr in changes.items() if tr})
        _write_json(path, cache, indent=None)
        self._safely(lambda: self._learn_fixes(fixes))
        review_file = review_path_for(path)
        review = [r for r in _read_json(review_file, []) if r not in changes]
        if review:
            _write_json(review_file, review)
        elif review_file.exists():
            review_file.unlink()
        return {"ok": True, "msg": f"{len(changes)} satır kaydedildi."}

    def _review_sources(self, path: Path, cache: Dict[str, str]) -> Dict[str, List[str]]:
        """İncelenmesi gereken satırlar ve sorunları (editördeki turuncu satırlar), oyundaki sıralarıyla."""
        review, _terms, limits, engine, rules = self._review_context(path)
        found: Dict[str, List[str]] = {}
        for src in list(cache) + [r for r in review if r not in cache]:
            tr = cache.get(src, "")
            if src in review or tr == src or (tr and not prov.placeholders_valid(src, tr)) \
                    or text_fit.too_long(src, tr, limits.get(src), engine) or term_lost(src, tr, rules):
                issues = self._line_issues(src, tr, review, rules, limits, engine)
                if issues and re.search(r"[^\W\d_]", src):
                    found[src] = issues
        return found

    def editor_fix_review(self, model: str) -> bool:
        """İncelenmeli satırları (çevrilmemiş, etiketi bozuk, terimi kayıp, kutuya sığmayan) sorunlarıyla birlikte bir
        sohbet modeline düzelttirir. Düzeltmeler önbelleğe yazılır; oyuna uygulamak kullanıcının kararıdır."""
        def task():
            from engine_renpy import quality_edit_pairs
            game = self._require_game()
            path = self._cache_path(model)
            cache: Dict[str, str] = _read_json(path, {})
            found = self._review_sources(path, cache)
            if not found:
                raise UserError("İncelenecek satır yok.")
            sources = list(found)[:REVIEW_FIX_LIMIT]
            _review, terms, limits, engine, rules = self._review_context(path)
            issues = {src: self._issue_text(src, found[src], terms, limits, engine) for src in sources}
            provider = self._quality_provider()
            cfg = prov.load_provider_config()
            self._stage("translate", f"İncelenmeli satırlar düzeltiliyor ({MODEL_LABELS[provider]})")
            edits = quality_edit_pairs(sources, cache, self._completer(provider, cfg),
                                       target_lang=self._settings["target"], log=self._log, progress=self._progress,
                                       extra_instruction=self._extra_instruction(), issues=issues, order=list(cache))
            accepted = {}
            for src, candidate in edits.items():
                if not prov.placeholders_valid(src, candidate):
                    continue
                if text_fit.too_long(src, candidate, limits.get(src), engine) and \
                        text_fit.WIDTH_FUNCS[engine](candidate) >= text_fit.WIDTH_FUNCS[engine](cache.get(src) or src):
                    continue                     # kısaltılması istenip kısalmayan öneri alınmaz
                accepted[src] = candidate
            if accepted:
                cache = _read_json(path, {})
                cache.update(accepted)
                _write_json(path, cache, indent=None)
                fixed = {s for s, t in accepted.items() if not self._line_issues(s, t, set(), rules, limits, engine)}
                review_file = review_path_for(path)
                left = [r for r in _read_json(review_file, []) if r not in fixed]
                if left:
                    _write_json(review_file, left)
                elif review_file.exists():
                    review_file.unlink()
            self._editor_cache = None
            more = len(found) - len(sources)
            self._status(f"{_n(len(accepted))} satır düzeltildi.", "ok")
            self._notify(f"{_n(len(accepted))} / {_n(len(sources))} satır düzeltildi",
                         ("Değişiklikleri editörde gözden geçirip 'Oyuna uygula'ya bas."
                          + (f" {_n(more)} satır daha var; tekrar çalıştırabilirsin." if more > 0 else "")),
                         "ok" if accepted else "warn", "edit", {"label": "Editörde aç", "page": "editor"})

        return self._run_task("İncelenmelileri düzelt", task)

    @staticmethod
    def _issue_text(src: str, issues: List[str], terms: Dict[str, str], limits: Dict[str, int], engine: str) -> str:
        """Modele giden sorun açıklaması (İngilizce)."""
        out = []
        for issue in issues:
            if issue == "Çevrilmedi":
                out.append("still untranslated: translate it")
            elif issue == "Etiket ya da değişken farklı":
                out.append("tags/variables differ from the source: keep every tag and variable exactly once")
            elif issue == "Oyun terimi çeviride yok":
                pairs = [f"{k} → {v}" for k, v in terms.items() if k and k in src][:5]
                out.append("a game term is missing; use exactly: " + "; ".join(pairs))
            elif issue.startswith("Kutuya sığmayabilir") and limits.get(src):
                out.append(text_fit.describe(limits[src], engine))
            else:
                out.append("review and improve the translation")
        return "; ".join(out)

    def editor_apply(self, model: str) -> bool:
        """Önbellekteki (düzenlenmiş) çevirileri oyun dosyalarına yeniden yazar — API harcamaz."""
        def task():
            game = self._require_game()
            cache: Dict[str, str] = _read_json(self._cache_path(model), {})
            if not cache:
                raise UserError("Bu model için önbellekte çeviri yok.")
            written = getattr(self, f"_apply_{game['type']}")(game, cache)
            if (self._library.get(game["root"]) or {}).get("status") == "translated":
                self._library.upsert(game["root"], files_stamp=game_files_stamp(game["root"], game["type"]) or "")
            game["texts"] = None
            game["analysis"] = None
            self._status(f"Düzenlemeler uygulandı: {_n(written)} satır.", "ok")
            self._notify("Düzenlemeler oyuna uygulandı", f"{game['title']} · {_n(written)} satır güncellendi", "ok", "check")

        return self._run_task("Uygulama", task)

    def _apply_renpy(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_renpy import analyze_game, decode_literal, encode_literal, find_source_before, last_literal_match
        info = analyze_game(game["root"], self._log, language=renpy_language_name(self._settings["target"]))
        tl_dir = info.tl_dir
        if not tl_dir.is_dir():
            raise UserError("Oyunda bu dilin çeviri klasörü yok; önce çeviriyi başlatın.")
        changed = 0
        for path in sorted(tl_dir.rglob("*.rpy")):
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                lines = handle.readlines()
            file_changed = False
            for index, raw in enumerate(lines):
                if raw.lstrip().startswith(("#", "old ")):
                    continue
                ending = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
                body = raw[: -len(ending)] if ending else raw
                match = last_literal_match(body)
                if not match:
                    continue
                try:
                    current = decode_literal(match.group(1))
                except (SyntaxError, ValueError):
                    continue
                source = find_source_before(lines, index)
                wanted = cache.get(source) if source is not None else None
                if wanted and wanted != current:
                    lines[index] = body[: match.start()] + encode_literal(wanted) + body[match.end():] + ending
                    changed += 1
                    file_changed = True
            if file_changed:
                atomic_write_text(path, "".join(lines))
        if changed and self._settings.get("renpy_compile_check", True):
            from engine_renpy import compile_check
            self._stage("write", "Oyunun Ren'Py'siyle derleme denetimi")
            check = compile_check(info, tl_dir, self._log)
            if check["errors"]:
                self._notify("Derleme uyarısı", f"{len(check['errors'])} çeviri satırında Ren'Py derleme hatası kaldı; "
                             "ayrıntı Teknik günlükte.", "warn", "alert")
        return changed

    def _restore_originals(self, game: Dict[str, Any]) -> None:
        backups = [b for b in list_game_backups(Path(game["root"])) if b.engine == game["type"]]
        changed_at = (self._library.get(game["root"]) or {}).get("files_changed_at") or 0
        if changed_at:     # oyun güncellendi: önceki yedekler eski sürümün dosyaları, geri yüklenirse oyunu bozar
            backups = [b for b in backups if b.path.exists() and b.path.stat().st_mtime >= changed_at]
        if not backups:
            raise UserError("Orijinal yedek yok; düzenlemeler için 'Çeviriyi başlat'ı kullan (önbellekteki satırlar ücretsiz).")
        ok, _count, msg = restore_game_backup(backups[-1], Path(game["root"]), log=self._log)  # en eski = orijinal
        if not ok:
            raise (UserError if msg.startswith("Yedek doğrulanamadı") else RuntimeError)(msg)

    def _apply_unity(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_unity import detect_unity_game, extract_texts_unity, write_translations_unity
        self._restore_originals(game)
        info = detect_unity_game(game["root"])
        texts = extract_texts_unity(info, self._log)
        info.runtime_missing = set((self._library.get(game["root"]) or {}).get("runtime_missing") or "")
        return write_translations_unity(info, cache, texts, self._log, target_lang=self._settings["target"])

    def _offer_unity_reader(self, game: Dict[str, Any], info: Any, texts: List[Any]):
        """Bileşen okuyucusu gerekli ama kurulu değil: bir kez izin istenir, indirilip metinler yeniden okunur."""
        import unity_typed
        from engine_unity import detect_unity_game, extract_texts_unity
        if not self._ask("Unity bileşen okuyucusu", (
                "Bu oyunun metinleri Unity bileşenlerinde (PlayMaker, Naninovel, UI Text). Okumak için bileşen okuyucusu "
                f"({unity_typed.READER_SIZE_MB} MB, PyPI: TypeTreeGeneratorAPI {unity_typed.READER_VERSION}, SHA-256 "
                "doğrulamalı) bir kez indirilsin mi? Hayır dersen BepInEx ile çevrilebilir.")):
            game["reader_declined"] = True
            return texts, info
        self._status("Unity bileşen okuyucusu indiriliyor…")
        try:
            unity_typed.install_reader(log=self._log)
        except Exception as exc:
            self._log(f"Bileşen okuyucusu indirilemedi: {exc}")
            self._toast("Unity bileşen okuyucusu indirilemedi; çeviri BepInEx ile yapılabilir.", "warn")
            game["reader_declined"] = True
            return texts, info
        info = detect_unity_game(game["root"])
        game["info"] = info
        return extract_texts_unity(info, log=self._log), info

    def _apply_rpgmaker(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_rpgmaker import (RGSS_EXT, detect_rpgmaker_game, join_speaker, write_translations_mv_mz,
                                     write_translations_vxace)
        self._restore_originals(game)
        info = detect_rpgmaker_game(game["root"])
        originals = list(dict.fromkeys(t.original for t in self._rpgm_extract(info)))
        translations = {**cache, **join_speaker(originals, cache)}   # konuşmacı adı ve satır ayrı kayıtlı
        if info.engine_type in RGSS_EXT:
            return write_translations_vxace(info.data_dir, translations, self._log, engine_type=info.engine_type)
        return write_translations_mv_mz(info.data_dir, translations, self._log, language=self._settings["target"])

    def _apply_unreal(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_unreal import detect_unreal_game, extract_texts_unreal, write_translations_unreal
        info = detect_unreal_game(game["root"])
        texts = extract_texts_unreal(info, source_lang_code=self._settings["source"], log=self._log)
        return write_translations_unreal(info, cache, texts, target_lang_code=self._settings["target"], log=self._log)

    # ── Sözlük editörü ───────────────────────────────────────────────────────
    def glossary_load(self, kind: str) -> List[List[str]]:
        data = _read_json(GLOSSARY_DIR / GLOSSARY_FILES.get(kind, "glossary.json"), {})
        return [[str(k), str(v)] for k, v in data.items() if not str(k).startswith("_")]

    def glossary_save(self, kind: str, entries: List[List[str]]) -> Dict[str, Any]:
        path = GLOSSARY_DIR / GLOSSARY_FILES.get(kind, "glossary.json")
        meta = {k: v for k, v in _read_json(path, {}).items() if str(k).startswith("_")}
        data = dict(meta)
        for pair in entries:
            if len(pair) == 2 and str(pair[0]).strip() and str(pair[1]).strip():
                data[str(pair[0]).strip()] = str(pair[1]).strip()
        _write_json(path, data)
        return {"ok": True, "count": len(data) - len(meta)}

    # ── JSON çevirici ────────────────────────────────────────────────────────
    def json_pick(self, mode: str = "file") -> Optional[str]:
        import webview
        if not self._window:
            return None
        if mode == "folder":
            result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=(
                "JSON ve altyazı (*.json;*.srt;*.vtt;*.ass;*.ssa)", "JSON dosyası (*.json)",
                "Altyazı (*.srt;*.vtt;*.ass;*.ssa)"))
        return result[0] if result else None

    def json_translate(self, input_path: str, output_path: str = "") -> bool:
        def task():
            import subtitles
            from engine_json import PROTECTED_JSON, apply_translations, collect_strings
            src = Path(input_path)
            if not src.exists():
                raise UserError("Giriş dosyası/klasörü bulunamadı.")
            self._check_model_ready(None)
            target_lang = self._settings["target"]
            if src.is_dir():
                files = sorted(src.rglob("*.json"))
                subs = [f for f in subtitles.find_files(src) if not subtitles.is_output(f, target_lang)]
            else:
                is_sub = src.suffix.lower() in subtitles.SUBTITLE_EXTS
                files, subs = ([], [src]) if is_sub else ([src], [])
            if not files and not subs:
                raise UserError("Bu klasörde .json ya da altyazı (.srt, .vtt, .ass) dosyası yok.")
            if subs:
                self._translate_subtitles(src, subs, Path(output_path) if output_path else None)
            if not files:
                return
            out_root = Path(output_path) if output_path and (src.is_dir() or not subs) else (
                src.with_name(src.name + "_tr") if src.is_dir() else src.with_name(f"{src.stem}_tr{src.suffix}"))
            failed: set = set()
            total = 0
            for file in files:
                data = _read_json(file, None)
                if data is None:
                    self._log(f"Atlandı (geçersiz JSON): {file.name}")
                    continue
                unique = sorted({text for _, text in collect_strings(data) if text.strip()})
                self._status(f"{file.name}: {_n(len(unique))} metin çevriliyor…")
                cache_path = cache_file_for(file.resolve(), DATA_DIR, suffix=f"_json_{self._settings['model']}")
                translations = self._translate_strings(unique, cache_path, PROTECTED_JSON,
                                                       Glossary.from_file(GLOSSARY_DIR / "glossary.json"), "video game",
                                                       failed, extra="")
                target = out_root / file.relative_to(src) if src.is_dir() else out_root
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(apply_translations(data, translations), ensure_ascii=False, indent="\t"),
                                  encoding="utf-8")
                total += len(unique)
            self._status(f"JSON çevirisi tamamlandı: {_n(total)} metin → {out_root}", "ok")
            self._notify("JSON çevirisi tamamlandı", f"{len(files)} dosya · {_n(total)} metin", "ok", "check",
                         {"label": "Klasörü aç", "path": str(out_root if out_root.is_dir() else out_root.parent)})
            if failed:
                self._notify(f"{_n(len(failed))} metin çevrilemedi", "Kaynak metinle bırakıldı; tekrar çalıştırınca yeniden denenir.",
                             "warn", "alert")

        return self._run_task("JSON çevirisi", task)

    def _translate_subtitles(self, src: Path, files: List[Path], output: Optional[Path]) -> None:
        """Altyazı dosyalarını çevirir; her biri "ad.<dil>.uzantı" olarak (klasör seçildiyse çıkış klasörüne,
        tek dosya seçildiyse verilen çıkış yoluna) yazılır. Orijinallere dokunulmaz."""
        import subtitles
        target_lang = self._settings["target"]
        glossary = self._glossary("glossary.json") if target_lang == "tr" else Glossary(self._project_glossary()["terms"])
        failed: set = set()
        written: List[Path] = []
        total = 0
        for index, file in enumerate(files, 1):
            try:
                sub = subtitles.load(file)
            except (OSError, ValueError) as exc:
                self._log(f"Atlandı (okunamadı): {file.name}: {exc}")
                continue
            unique = list(dict.fromkeys(subtitles.texts(sub)))
            if not unique:
                self._log(f"Atlandı (çevrilecek metin yok): {file.name}")
                continue
            self._status(f"{file.name}: {_n(len(unique))} altyazı satırı çevriliyor ({index}/{len(files)})…")
            cache_path = cache_file_for(file.resolve(), DATA_DIR,
                                        suffix=f"_sub_{self._settings['model']}_{target_lang}")
            translations = self._translate_strings(unique, cache_path, subtitles.PROTECTED_SUB, glossary,
                                                   "film / video game subtitles", failed, extra="",
                                                   engine_tags=subtitles.PROTECTED_SUB)
            name = subtitles.output_path(file, target_lang)
            if output and src.is_dir():
                target = output / name.relative_to(src)
            elif output and len(files) == 1:
                target = output if output.suffix else output / name.name
            else:
                target = name
            written.append(subtitles.save(sub, translations, target))
            total += len(unique)
        if not written:
            raise UserError("Çevrilebilecek altyazı satırı bulunamadı.")
        folder = written[0].parent
        self._status(f"Altyazı çevirisi tamamlandı: {_n(len(written))} dosya · {_n(total)} satır", "ok")
        self._notify("Altyazı çevirisi tamamlandı", f"{_n(len(written))} dosya · {_n(total)} satır → {written[0].name}"
                     + ("…" if len(written) > 1 else ""), "ok", "check", {"label": "Klasörü aç", "path": str(folder)})
        if failed:
            self._notify(f"{_n(len(failed))} altyazı satırı çevrilemedi",
                         "Orijinal hâliyle bırakıldı; tekrar çalıştırınca yeniden denenir.", "warn", "alert")

    # ── Yama paylaşımı ───────────────────────────────────────────────────────
    def export_patch(self) -> Optional[str]:
        import webview
        game = self._require_game() if self._game else None
        if not game:
            self._toast("Önce bir proje aç.", "warn")
            return None
        cache_path = self._cache_path()
        cache = _read_json(cache_path, {})
        if not cache:
            self._notify("Dışa aktarılacak çeviri yok", f"{MODEL_LABELS[self._settings['model']]} önbelleği boş.", "warn", "alert")
            return None
        safe = re.sub(r"[^\w\- ]+", "", game["title"]).strip() or "oyun"
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}_{self._settings['target']}{PATCH_SUFFIX}",
                                                 file_types=("Capri yaması (*.capripatch)",)) if self._window else None
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        manifest = {"app": "Capri", "version": APP_VERSION, "title": game["title"], "engine": game["type"],
                    "model": self._settings["model"], "target": self._settings["target"], "lines": len(cache),
                    "created": time.strftime("%Y-%m-%d %H:%M")}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("translations.json", json.dumps(cache, ensure_ascii=False))
        self._notify("Yama dışa aktarıldı", f"{_n(len(cache))} satır · {target.name}", "ok", "archive",
                     {"label": "Klasörü aç", "path": str(target.parent)})
        return str(target)

    def editor_export_csv(self, model: str = "") -> Optional[str]:
        """Çevirileri tablo (CSV) olarak dışa aktarır: Excel / Google E-Tablolar'da düzeltilip geri alınabilir."""
        import webview
        import patch_safety
        if not self._game:
            self._toast("Önce bir proje aç.", "warn")
            return None
        model = model or self._settings["model"]
        path = self._cache_path(model)
        cache = _read_json(path, {})
        if not cache:
            self._notify("Dışa aktarılacak çeviri yok", f"{MODEL_LABELS.get(model, model)} önbelleği boş.", "warn", "alert")
            return None
        safe = re.sub(r"[^\w\- ]+", "", self._game["title"]).strip() or "oyun"
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}_{self._settings['target']}.csv",
                                                 file_types=("CSV tablosu (*.csv)",)) if self._window else None
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        target.write_text(patch_safety.csv_export(cache, _read_json(review_path_for(path), [])), encoding="utf-8", newline="")
        self._notify("Tablo dışa aktarıldı", f"{_n(len(cache))} satır · {target.name}", "ok", "archive",
                     {"label": "Klasörü aç", "path": str(target.parent)})
        return str(target)

    def editor_import_csv(self, model: str = "") -> bool:
        import webview
        if not self._game:
            self._toast("Önce bir proje aç.", "warn")
            return False
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("CSV tablosu (*.csv;*.tsv;*.txt)",))             if self._window else None
        if not result:
            return False
        return self._apply_csv_file(Path(result[0]), model or self._settings["model"])

    def _apply_csv_file(self, path: Path, model: str) -> bool:
        """Tablodaki düzeltmeleri önbelleğe alır (oyuna yazmak için "Oyuna uygula"). Yalnızca bu oyunun satırları."""
        import patch_safety
        cache_path = self._cache_path(model)
        cache: Dict[str, str] = _read_json(cache_path, {})
        review_file = review_path_for(cache_path)
        review = _read_json(review_file, [])
        try:
            raw = path.read_bytes()
            if len(raw) > patch_safety.MAX_CSV:
                raise ValueError("dosya çok büyük")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1254", errors="replace")      # Excel'in "CSV" kaydı (Türkçe Windows)
            result = patch_safety.csv_import(text, cache, set(cache) | set(review), self._game["type"])
        except (OSError, ValueError) as error:
            self._notify("Tablo okunamadı", str(error), "error", "alert")
            return False
        changes = result["changes"]
        if changes:
            cache.update(changes)
            _write_json(cache_path, cache, indent=None)
            remaining = [r for r in review if r not in changes]
            if remaining:
                _write_json(review_file, remaining)
            elif review_file.exists():
                review_file.unlink()
        self._notify("Tablo içe aktarıldı",
                     f"{_n(len(changes))} satır güncellendi · {_n(result['unchanged'])} değişmedi · "
                     f"{_n(result['unknown'])} bu oyunda yok. Oyuna yazmak için 'Oyuna uygula'.", "ok", "archive")
        if result["rejected"]:
            self._notify(f"{_n(result['rejected'])} satır alınmadı",
                         "Bu satırlar kaynakta olmayan etiket, kod ya da bağlantı ekliyordu; alınmadı.", "warn", "shield")
        return True

    def save_diagnostics(self) -> Optional[str]:
        """Hata bildirimi için tanı paketi (zip): günlüğün sonu, ayarlar (gizli alanlar çıkarılmış), sürüm/sistem bilgisi
        ve açık projenin analiz özeti. API anahtarları zaten ayarlarda değil, Windows Kimlik Bilgisi Yöneticisi'ndedir."""
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.SAVE,
                                                 save_filename=f"capri-tani-{time.strftime('%Y%m%d-%H%M')}.zip",
                                                 file_types=("Zip (*.zip)",)) if self._window else None
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        self._write_diagnostics(target)
        self._notify("Tanı paketi kaydedildi", "Hata bildirirken bu dosyayı ekle. API anahtarları içermez.", "ok", "archive",
                     {"label": "Klasörü aç", "path": str(target.parent)})
        return str(target)

    def _write_diagnostics(self, target: Path) -> Path:
        import platform
        secret = re.compile(r"key|token|secret|password", re.IGNORECASE)
        settings = {k: ("<gizli>" if secret.search(k) else v) for k, v in self._settings.items()}
        info = [f"Capri {APP_VERSION}", f"Windows: {platform.platform()}", f"Python: {platform.python_version()}",
                f"Exe: {'evet' if FROZEN else 'hayır (kaynak kod)'}",
                f"Ekran kartı: {(self._gpu or {}).get('name', '?')} {(self._gpu or {}).get('detail', '')}",
                f"Proje sayısı: {len(self._library.list())}"]
        game = self._game
        if game:
            analysis = game.get("analysis") or {}
            info += ["", f"Açık proje motoru: {game.get('type')}", f"Satır: {analysis.get('lines')}",
                     *[f"Not: {n}" for n in analysis.get("notes", [])[:20]],
                     *[f"Öneri: {a.get('text')}" for a in analysis.get("advice", [])[:10]],
                     *[f"Oyun içi hata: {e['file']}:{e['line']} {e['message']}" for e in analysis.get("runtime_errors", [])[:10]]]
            check = game.get("compile_check")
            if check:
                info += [f"Derleme denetimi: çalıştı={check.get('ran')} temiz={check.get('ok')} "
                         f"geri alınan={check.get('reverted')} kalan hata={len(check.get('errors') or [])}"]
            entry = self._library.get(game["root"]) or {}
            info += [f"Durum: {entry.get('status')} · son işlem: {entry.get('last_action')}",
                     f"Oyunda kutu görünen harfler: {entry.get('runtime_missing') or '-'}"]
        log_file = DATA_DIR / "capri.log"
        log_tail = b""
        if log_file.exists():
            with open(log_file, "rb") as handle:
                handle.seek(max(0, log_file.stat().st_size - 2_000_000))
                log_tail = handle.read()
        home = str(Path.home())
        for variant in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:   # kullanıcı adı pakete girmesin
            log_tail = log_tail.replace(variant.encode("utf-8"), b"%USERPROFILE%")
        settings = json.loads(json.dumps(settings, ensure_ascii=False).replace(json.dumps(home)[1:-1], "%USERPROFILE%"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bilgi.txt", "\n".join(str(line) for line in info))
            archive.writestr("ayarlar.json", json.dumps(settings, ensure_ascii=False, indent=2))
            archive.writestr("capri.log", log_tail)
        return target

    def import_patch(self) -> bool:
        import webview
        if not self._game:
            self._toast("Önce yamanın ait olduğu oyunu aç.", "warn")
            return False
        result = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                                 file_types=("Capri yaması (*.capripatch;*.omnipatch;*.zip)",)) if self._window else None
        if not result:
            return False
        return self._apply_patch_file(Path(result[0]))

    def _apply_patch_file(self, path: Path) -> bool:
        """
        Yama dosyasındaki çevirileri açık oyunun önbelleğine ekler (oyuna yazmak için çeviri başlatılır).
        Yama başkasından gelmiş olabilir: her satır motorun etiket kuralıyla kaynağa göre denetlenir; yeni etiket, kod,
        bağlantı ya da fazladan satır sonu ekleyen satırlar alınmaz (bkz. patch_safety).
        """
        import patch_safety
        try:
            manifest, translations = patch_safety.read_patch(path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self._notify("Yama okunamadı", "Dosya geçerli bir Capri yaması değil.", "error", "alert")
            return False
        if manifest.get("engine") != self._game["type"]:
            self._notify("Yama bu oyuna uymuyor",
                         f"Yama {ENGINE_LABELS.get(manifest.get('engine'), '?')} için, açık oyun {ENGINE_LABELS[self._game['type']]}.",
                         "error", "alert")
            return False
        safe, rejected = patch_safety.filter_translations(translations, self._game["type"])
        cache_path = self._cache_path()
        cache = _read_json(cache_path, {})
        cache.update(safe)
        _write_json(cache_path, cache)
        title = str(manifest.get("title", ""))[:120]
        self._notify("Yama içe aktarıldı",
                     f"{_n(len(safe))} satır ({title}). 'Çeviriyi başlat' ile oyuna uygula — "
                     "bu satırlar için API harcanmaz.", "ok", "archive")
        if rejected:
            self._notify(f"{_n(rejected)} satır alınmadı",
                         "Bu satırlar kaynakta olmayan etiket, kod ya da bağlantı ekliyordu; alınmadı.", "warn", "shield")
        self._ui.emit("stats", self.get_stats())
        return True

    # ── Canlı önizleme ───────────────────────────────────────────────────────
    def translate_text(self, text: str, source: str = "", target: str = "", model: str = "") -> Dict[str, Any]:
        """Uygulama içi metin çevirici (çok satırlı metin desteklenir)."""
        s = self._settings
        model, target, source = model or s["model"], target or s["target"], source or s["source"]
        label = MODEL_LABELS.get(model, model)
        if not (text or "").strip():
            return {"ok": False, "text": "", "latency": 0, "model": label}
        if model in TURKISH_ONLY_MODELS and target != "tr":
            return {"ok": False, "text": f"{label} yalnızca İngilizce → Türkçe çeviri yapabilir.", "latency": 0, "model": label}
        ok, result, latency = prov.translate_single_text(
            text=text, provider_id=model, target_lang=target, source_lang=source,
            nsfw_mode=bool(s["nsfw"]), log=self._log, max_tokens=4096, local_model=self._local_model_id(),
        )
        return {"ok": ok, "text": result, "latency": latency, "model": label}

    def preview(self, text: str) -> Dict[str, Any]:
        return self.translate_text(text)

    # ── GPU hızlandırma ──────────────────────────────────────────────────────
    def optimize_gpu(self, preload: bool = True, silent: bool = False) -> Dict[str, Any]:
        """
        CUDA'yı çeviriye hazırlar:
        1) Sürücü bağlamını ve cuBLAS çekirdeklerini önceden başlatır (ilk çevirideki 1-3 sn gecikme kalkar),
        2) TF32 ve cuDNN benchmark'ı açar (RTX 30/40/50 serisinde matris işlemleri hızlanır),
        3) Kullanılmayan VRAM önbelleğini boşaltır (bellek yetmedi hatalarını azaltır),
        4) Seçili yerel modeli (OPUS/NLLB) VRAM'e önceden yükler (önizleme ve OCR anında çevirir).
        """
        with self._gpu_lock:
            try:
                import torch
            except Exception:
                return {"ok": False, "msg": "PyTorch kurulu değil."}
            if not torch.cuda.is_available():
                result = {"ok": False, "msg": "CUDA bulunamadı; yerel modeller CPU'da çalışır."}
                self._ui.emit("gpu_opt", result)
                return result
            t0 = time.perf_counter()
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            torch.cuda.empty_cache()
            x = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
            (x @ x).sum().item()
            init_ms = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            for _ in range(20):
                y = x @ x
            torch.cuda.synchronize()
            warm_ms = (time.perf_counter() - t1) * 1000 / 20
            del x, y
            torch.cuda.empty_cache()
            free, total = torch.cuda.mem_get_info()
            result: Dict[str, Any] = {
                "ok": True, "name": torch.cuda.get_device_name(0), "time": time.time(),
                "init_ms": round(init_ms), "warm_ms": round(warm_ms, 2),
                "tflops": round(2 * 2048 ** 3 / (warm_ms / 1000) / 1e12, 1),
                "vram_total": round(total / 1024 ** 3, 1), "vram_free": round(free / 1024 ** 3, 1),
                "tf32": True, "preload": None,
            }
            model = self._ocr_model() if self._ocr_model() in LOCAL_MODELS else self._settings["model"]
            if preload and model in LOCAL_MODELS and prov.get_offline_model_status(model)["is_ready"]:
                t2 = time.perf_counter()
                prov.translate_single_text("Ready.", model, log=self._log)
                result["preload"] = MODEL_LABELS[model]
                result["preload_ms"] = round((time.perf_counter() - t2) * 1000)
                result["vram_free"] = round(torch.cuda.mem_get_info()[0] / 1024 ** 3, 1)
            self._gpu_opt = result
        self._ui.emit("gpu_opt", result)
        if not silent:
            extra = f" · {result['preload']} VRAM'e yüklendi" if result.get("preload") else ""
            self._notify("GPU hazırlandı", f"{result['name']} · {result['tflops']} TFLOPS (FP16) · "
                         f"{result['vram_free']}/{result['vram_total']} GB boş{extra}", "ok", "cpu")
        return result

    # ── Ekran çevirisi (OCR) ─────────────────────────────────────────────────
    def set_ocr_windows(self, windows: Dict[str, Any], screen_size: Tuple[int, int], scale: float) -> None:
        self._ocr_win = windows
        self._screen_size = screen_size
        self._screen_scale = scale or 1.0

    def _ocr_model(self) -> str:
        return self._settings.get("ocr_model") or self._settings["model"]

    # ── Dahili yerel modeller (llama.cpp, Ollama'sız) ────────────────────────
    def _local_model_id(self, ocr: bool = False) -> str:
        """Seçili dahili model; seçilmemişse kurulu en iyi model, o da yoksa ekran kartına göre önerilen. Ekran çevirisinde
        (tek satır) MiLMMT ya da Hy-MT2 1.8B kuruluysa o kullanılır: tek satırda ~0,1 sn."""
        import local_llm
        if ocr:   # tek satır: en hızlı küçük çeviri modelleri (MiLMMT ~0,1 sn, Hy-MT2 1.8B)
            fast = next((m for m in ("milmmt-4b", "hymt2-1.8b") if m in local_llm.BY_ID and local_llm.model_installed(m)), None)
            if fast:
                return fast
        chosen = self._settings.get("local_model")
        if chosen in local_llm.BY_ID:
            return chosen
        installed = sorted((m for m in local_llm.CATALOG if local_llm.model_installed(m["id"])), key=local_llm.score, reverse=True)
        return installed[0]["id"] if installed else local_llm.recommend((self._gpu or {}).get("vram_gb"))["model"]

    def _vram_gb(self) -> Optional[float]:
        """Ekran kartı belleği. Açılıştaki tespit arka planda sürüyorsa beklemeden doğrudan okunur (~50 ms); yoksa
        12 GB'lık karta hafif model önerilirdi."""
        vram = (self._gpu or {}).get("vram_gb")
        if vram is None and (self._gpu or {}).get("name") == "Algılanıyor…":
            card = gpu_runtime.nvidia_info()
            vram = float(re.sub(r"[^\d.]", "", card["memory"]) or 0) if card else None
        return vram

    def _llm_model(self, cfg: Any) -> str:
        """Ollama ya da dahili motor için model adı (motorlara ollama_model parametresiyle gider)."""
        return self._local_model_id() if self._settings["model"] == "local" else cfg.ollama_model

    def local_models(self) -> Dict[str, Any]:
        import local_llm
        vram = self._vram_gb()
        classic = {k: bool(prov.get_offline_model_status(k).get("is_ready")) for k in ("opus", "nllb")}
        data = local_llm.status(vram, classic_ready=classic)
        data["selected"] = self._local_model_id()
        data["vram_gb"] = vram
        return data

    def download_local_model(self, model_id: str) -> bool:
        """Dahili modeli (gerekirse önce 37 MB'lık llama.cpp çalışma ortamını) indirir ve SHA-256 ile doğrular."""
        import local_llm
        if model_id not in local_llm.BY_ID:
            return False
        spec = local_llm.BY_ID[model_id]

        def task():
            if local_llm.server_exe() is None:
                self._stage("download", "Yerel model ortamı (llama.cpp) indiriliyor")
                self._progress_unit = "MB"
                local_llm.install_runtime(local_llm.DEFAULT_RUNTIME, lambda d, t: self._progress(d >> 20, max(1, t >> 20)),
                                          self._cancel, self._log)
            self._stage("download", f"{spec['label']} indiriliyor")
            self._progress_unit = "MB"
            local_llm.install_model(model_id, lambda d, t: self._progress(d >> 20, max(1, t >> 20)), self._cancel, self._log)
            if not local_llm.model_installed(self._settings.get("local_model") or ""):
                self._settings["local_model"] = model_id
                save_settings(self._settings)
            self._ui.emit("models", self.model_status())
            self._notify("Yerel model hazır", f"{spec['label']} indirildi. Kullanmak için Sağlayıcılar → Yerel model.",
                         "ok", "cpu")
        return self._run_task("Model indirme", task)

    def remove_local_model(self, model_id: str) -> Dict[str, Any]:
        import local_llm
        if model_id in local_llm.BY_ID:
            local_llm.remove_model(model_id)
            if self._settings.get("local_model") == model_id:
                self._settings["local_model"] = None
                save_settings(self._settings)
        return self.local_models()

    def ocr_status(self) -> Dict[str, Any]:
        try:
            from ocr import OCR
            ok, msg = OCR.available()
        except Exception as exc:
            ok, msg = False, str(exc)
        return {
            "available": ok, "languages": msg if ok else "", "error": "" if ok else msg,
            "hotkeys": dict(self._hotkeys.registered) if self._hotkeys else {},
            "pin_active": bool(self._pin_watcher and self._pin_watcher.running),
            "windows": bool(self._ocr_win),
        }

    def _setup_hotkeys(self) -> None:
        from ocr import HotkeyManager
        if self._hotkeys is None:
            def failed(name: str, combo: str) -> None:
                self._notify("Kısayol kaydedilemedi", f"{combo} başka bir uygulama tarafından kullanılıyor. "
                             "Ekran Çevirisi sayfasından farklı bir kısayol seç.", "warn", "alert",
                             {"label": "Ayarla", "page": "ocr"})
            self._hotkeys = HotkeyManager(on_error=failed)
        self._hotkeys.set({
            "ocr": (self._settings["ocr_hotkey"], lambda: self.ocr_start("once")),
            "pin": (self._settings["pin_hotkey"], self._pin_hotkey),
        })
        self._ui.emit("ocr", self.ocr_status())

    def _pin_hotkey(self) -> None:
        if self._pin_watcher and self._pin_watcher.running:
            self.ocr_pin_stop()
        else:
            self.ocr_start("pin")

    def _monitors(self) -> List[Dict[str, Any]]:
        """
        Fiziksel monitörleri (mss, piksel) pywebview ekranlarıyla (mantıksal, DPI ölçekli) eşleştirir.
        Her monitörün kendi ölçeği vardır (ör. 4K %150 + 1080p %100).
        """
        from ocr import _sct
        physical = [dict(m) for m in _sct().monitors[1:]]
        try:
            import webview
            screens = [(s.x, s.y, s.width, s.height) for s in webview.screens]
        except Exception:
            screens = []
        if len(screens) != len(physical):
            screens = [(m["left"], m["top"], m["width"], m["height"]) for m in physical]
        out = []
        for m, (x, y, w, h) in zip(sorted(physical, key=lambda m: (m["left"], m["top"])), sorted(screens)):
            out.append({"phys": m, "x": x, "y": y, "w": w, "h": h, "scale": m["width"] / max(1, w)})
        return out

    def _monitor_at(self, px: float, py: float) -> Dict[str, Any]:
        monitors = self._monitors()
        for mon in monitors:
            m = mon["phys"]
            if m["left"] <= px < m["left"] + m["width"] and m["top"] <= py < m["top"] + m["height"]:
                return mon
        return monitors[0]

    def _to_logical(self, px: float, py: float) -> Tuple[int, int, Dict[str, Any]]:
        """Fiziksel ekran noktası → pencere koordinatı (noktanın bulunduğu monitörün ölçeğiyle)."""
        mon = self._monitor_at(px, py)
        m = mon["phys"]
        return int(mon["x"] + (px - m["left"]) / mon["scale"]), int(mon["y"] + (py - m["top"]) / mon["scale"]), mon

    def _logical(self, value: float, mon: Optional[Dict[str, Any]] = None) -> int:
        return int(value / (mon["scale"] if mon else self._screen_scale))

    def ocr_start(self, mode: str = "once", from_ui: bool = False) -> bool:
        """Ekranı dondurur ve alan seçimini açar (kısayol veya arayüz düğmesi)."""
        from ocr import OCR, capture, cursor_pos
        if not self._ocr_win or self._ocr_selecting:
            return False
        ok, msg = OCR.available()
        if not ok:
            self._notify("Ekran çevirisi kullanılamıyor", msg, "error", "alert")
            return False
        self._ocr_selecting = True
        try:
            self._ocr_win["popup"].hide()
            if from_ui and self._window:
                self._window.minimize()
                self._ocr_restore_main = True
                time.sleep(0.35)  # pencere küçülme animasyonu bitsin
            # Farenin bulunduğu monitör yakalanır; seçim ekranı o monitörü kaplar
            mon = self._monitor_at(*cursor_pos())
            m = mon["phys"]
            shot = capture(m["left"], m["top"], m["width"], m["height"])
            self._ocr_shot, self._ocr_mode = shot, mode
            uri = "data:image/jpeg;base64," + base64.b64encode(shot.to_jpeg(82)).decode("ascii")
            selector = self._ocr_win["select"]
            selector.move(mon["x"], mon["y"])
            selector.resize(mon["w"], mon["h"])
            selector.evaluate_js(f"OCRSEL.open({json.dumps(uri)}, {json.dumps(mode)})")
            selector.show()
            return True
        except Exception as exc:
            self._ocr_selecting = False
            self._notify("Ekran yakalanamadı", str(exc), "error", "alert")
            return False

    def ocr_start_ui(self, mode: str = "once") -> bool:
        return self.ocr_start(mode, from_ui=True)

    def _restore_main(self) -> None:
        if self._ocr_restore_main and self._window:
            self._ocr_restore_main = False
            try:
                self._window.restore()
            except Exception:
                pass

    def ocr_cancel(self) -> None:
        if self._ocr_win:
            self._ocr_win["select"].hide()
        self._ocr_selecting = False
        self._restore_main()

    def ocr_selected(self, fx0: float, fy0: float, fx1: float, fy1: float) -> None:
        self._ocr_win["select"].hide()
        self._ocr_win["select"].evaluate_js("OCRSEL.reset()")
        self._ocr_selecting = False
        shot = self._ocr_shot
        if shot is None:
            return
        x0, y0 = max(0, int(fx0 * shot.width)), max(0, int(fy0 * shot.height))
        x1, y1 = min(shot.width, int(fx1 * shot.width)), min(shot.height, int(fy1 * shot.height))
        rect = (shot.left + x0, shot.top + y0, x1 - x0, y1 - y0)
        self._ocr_last_rect = rect
        if self._ocr_mode == "pin":
            self._ocr_start_pin(rect)
        else:
            threading.Thread(target=self._ocr_once, args=(shot.crop(x0, y0, x1, y1), rect), daemon=True).start()

    def _ocr_translate(self, text: str) -> Tuple[bool, str, int, bool]:
        model, target, source = self._ocr_model(), self._settings["target"], self._settings["source"]
        key = (model, target, text)
        if key in self._ocr_cache:
            self._ocr_cache.move_to_end(key)
            self._remember_ocr(text, self._ocr_cache[key])
            return True, self._ocr_cache[key], 0, True
        if model in TURKISH_ONLY_MODELS and target != "tr":
            return False, f"{MODEL_LABELS[model]} yalnızca Türkçeye çevirebilir.", 0, False
        ok, result, latency = prov.translate_single_text(text, model, target_lang=target, source_lang=source,
                                                         nsfw_mode=bool(self._settings["nsfw"]), log=self._log,
                                                         max_tokens=1024, local_model=self._local_model_id(ocr=True))
        if ok:
            self._ocr_cache[key] = result
            while len(self._ocr_cache) > 400:
                self._ocr_cache.popitem(last=False)
            self._remember_ocr(text, result)
        return ok, result, latency, False

    def _remember_ocr(self, text: str, result: str) -> None:
        """Canlı altyazı hızla geçerse kaçırılan satır geri okunabilsin: son 50 ekran çevirisi (aynısı art arda yazılmaz)."""
        if self._ocr_history and self._ocr_history[-1]["src"] == text:
            return
        item = {"src": text, "tr": result, "time": time.time()}
        self._ocr_history.append(item)
        self._safely(lambda: self._ui.emit("ocr_history", item))

    def ocr_history(self) -> List[Dict[str, Any]]:
        return list(reversed(self._ocr_history))

    def ocr_history_clear(self) -> bool:
        self._ocr_history.clear()
        return True

    def _ocr_once(self, crop, rect: Tuple[int, int, int, int]) -> None:
        from ocr import OCR
        label = MODEL_LABELS.get(self._ocr_model(), self._ocr_model()).replace(" (çevrimdışı)", "").replace(" (yerel LLM)", "")
        try:
            result = OCR.recognize(crop, self._settings["source"])
        except Exception as exc:
            self._ocr_popup(rect, {"state": "error", "error": f"OCR hatası: {exc}", "engine": label})
            return
        text = result.text
        if not text:
            self._ocr_popup(rect, {"state": "empty", "engine": label, "meta": f"OCR {result.ms:.0f} ms"})
            return
        self._ocr_popup(rect, {"state": "loading", "original": text, "engine": label, "meta": f"OCR {result.ms:.0f} ms · çevriliyor…"})
        ok, translated, latency, cached = self._ocr_translate(text)
        meta = f"OCR {result.ms:.0f} ms · çeviri {'önbellekten' if cached else f'{latency} ms'}"
        self._ocr_popup(rect, {"state": "ok" if ok else "error", "original": text, "translation": translated if ok else "",
                               "error": "" if ok else translated, "engine": label, "meta": meta,
                               "lang": self._settings["target"], "speak": bool(self._settings.get("ocr_speak"))})
        self._log(f"OCR: {text[:80]!r} → {translated[:80]!r}")

    def _ocr_popup(self, rect: Tuple[int, int, int, int], payload: Dict[str, Any]) -> None:
        win = self._ocr_win["popup"]
        first = self._ocr_anchor.get("popup") != rect
        self._ocr_anchor["popup"] = rect
        win.evaluate_js(f"OCRPOP.show({json.dumps(payload, ensure_ascii=False)})")
        if first:
            self._place("popup", 460, 150)
            win.show()

    def _place(self, which: str, width: int, height: int) -> None:
        """Pencereyi seçilen alanın altına (sığmazsa üstüne) yerleştirir; ekran dışına taşırmaz."""
        rect = self._ocr_anchor.get(which)
        if not rect:
            return
        left, top, mon = self._to_logical(rect[0] + 1, rect[1] + 1)
        rw, rh = self._logical(rect[2], mon), self._logical(rect[3], mon)
        mx, my, mw, mh = mon["x"], mon["y"], mon["w"], mon["h"]
        if which == "pin" and self._settings.get("ocr_place") == "over":
            x, y = left, top
        else:
            y = top + rh + 10
            if y + height > my + mh - 8:
                y = max(my + 8, top - height - 10)
            x = left
        x = min(max(mx + 8, x), max(mx + 8, mx + mw - width - 8))
        self._ocr_win[which].resize(width, height)
        self._ocr_win[which].move(x, y)

    def ocr_resize(self, which: str, height: int) -> None:
        if which not in self._ocr_win:
            return
        width = self._ocr_anchor.get(f"{which}_width", 460)
        self._place(which, width, int(min(max(height, 70), 640)))

    def ocr_hide(self, which: str = "popup") -> None:
        if which in self._ocr_win:
            self._ocr_win[which].hide()
            self._ocr_anchor.pop(which, None)
        self._restore_main()

    def ocr_pin_last(self) -> None:
        self.ocr_hide("popup")
        if self._ocr_last_rect:
            self._ocr_start_pin(self._ocr_last_rect)

    def _ocr_start_pin(self, rect: Tuple[int, int, int, int]) -> None:
        from ocr import RegionWatcher
        self.ocr_pin_stop(silent=True)
        over = self._settings.get("ocr_place") == "over"
        width = max(260 if over else 340, self._logical(rect[2], self._monitor_at(rect[0] + 1, rect[1] + 1)))
        self._ocr_anchor["pin"] = rect
        self._ocr_anchor["pin_width"] = width
        win = self._ocr_win["pin"]
        win.evaluate_js("OCRPIN.update(%s)" % json.dumps({
            "place": "over" if over else "below", "lang": self._settings["target"],
            "speak": bool(self._settings.get("ocr_speak")), "translation": self._tr("Alan izleniyor…"),
            "placeholder": True, "state": "live", "meta": ""}))
        self._place("pin", width, 96)
        win.show()
        self._pin_watcher = RegionWatcher(rect, self._settings["source"], self._pin_on_text, self._pin_on_state,
                                          interval=int(self._settings.get("ocr_interval", 350)) / 1000)
        self._pin_watcher.start()
        self._notify("Canlı ekran çevirisi açık", f"{rect[2]}×{rect[3]} piksellik alan izleniyor. "
                     f"Kapatmak için {self._settings['pin_hotkey']} veya penceredeki ✕.", "info", "scan")
        self._ui.emit("ocr", self.ocr_status())

    def _pin_on_state(self, state: str) -> None:
        if state.startswith("error"):
            self._ocr_win["pin"].evaluate_js("OCRPIN.update(%s)" % json.dumps({"state": "error", "meta": state[6:80]}))

    def _pin_on_text(self, text: str, ocr_ms: float) -> None:
        self._pin_pending = (text, ocr_ms)
        if self._pin_busy:
            return  # çeviri sürerken gelen en son metin sırada bekler
        self._pin_busy = True
        try:
            while self._pin_pending and self._pin_watcher and self._pin_watcher.running:
                text, ocr_ms = self._pin_pending
                self._pin_pending = None
                self._ocr_win["pin"].evaluate_js("OCRPIN.update(%s)" % json.dumps({"state": "busy"}))
                ok, translated, latency, cached = self._ocr_translate(text)
                meta = f"OCR {ocr_ms:.0f} ms · {'önbellek' if cached else f'{latency} ms'}"
                self._ocr_win["pin"].evaluate_js("OCRPIN.update(%s)" % json.dumps({
                    "translation": translated, "state": "live" if ok else "error", "meta": meta}, ensure_ascii=False))
        finally:
            self._pin_busy = False

    def ocr_pin_toggle(self) -> None:
        if self._pin_watcher:
            self._pin_watcher.paused = not self._pin_watcher.paused
            self._ocr_win["pin"].evaluate_js("OCRPIN.update(%s)" % json.dumps(
                {"state": "paused" if self._pin_watcher.paused else "live"}))

    def ocr_pin_stop(self, silent: bool = False) -> None:
        if self._pin_watcher:
            self._pin_watcher.stop()
            self._pin_watcher = None
            if not silent:
                self._notify("Canlı ekran çevirisi kapatıldı", "", "info", "scan")
        if self._ocr_win:
            self._ocr_win["pin"].hide()
        self._ocr_anchor.pop("pin", None)
        self._ui.emit("ocr", self.ocr_status())

    # ── Oyun tarama ──────────────────────────────────────────────────────────
    def _scan_payload(self) -> Dict[str, Any]:
        dismissed = {ProjectLibrary.key(p) for p in self._settings.get("scan_dismissed", [])}
        found = [g for g in self._scan_found if ProjectLibrary.key(g["path"]) not in dismissed
                 and not self._library.get(g["path"])]
        for game in found:
            game["engine_label"] = ENGINE_LABELS.get(game["engine"], game["engine"])
        return {"running": self._scan_running, "found": found, "folders": self._settings.get("scan_folders", []),
                "on_start": bool(self._settings.get("scan_on_start"))}

    @staticmethod
    def _scan_line_count(game: Dict[str, Any], before: Optional[Dict[str, Any]]) -> None:
        """Önerinin yaklaşık satır sayısı. Oyunun ana dosyaları önceki taramadan beri değişmediyse (parmak izi aynı)
        oyun yeniden çözümlenmez, önceki sayı kullanılır."""
        stamp = game_files_stamp(game["path"], game["engine"]) or ""
        if stamp and before and before.get("stamp") == stamp and before.get("engine") == game["engine"] \
                and "lines" in before:
            game.update(lines=before["lines"], stamp=stamp)
            return
        game.update(lines=quick_line_count(game), stamp=stamp)

    def scan_games(self, manual: bool = True) -> bool:
        """Bilgisayardaki oyunları arka planda arar (salt okunur); bulunanlar öneri olarak listelenir."""
        if self._scan_running:
            return False
        self._scan_running = True
        self._ui.emit("scan", self._scan_payload())

        def work():
            import game_scanner
            earlier = {ProjectLibrary.key(g["path"]): g for g in self._scan_found if isinstance(g, dict) and g.get("path")}
            previous = set(earlier)
            try:
                parents, direct = game_scanner.scan_sources(self._settings.get("scan_folders", []))
                known = [p["path"] for p in self._library.list()]
                self._scan_found = game_scanner.scan(detect_any_game_type, game_root_of, game_title_of, parents, direct, known)
                for game in self._scan_found:
                    self._safely(lambda: self._scan_line_count(game, earlier.get(ProjectLibrary.key(game["path"]))))
                _write_json(DATA_DIR / "scan.json", self._scan_found, indent=None)
            except Exception:
                self._safely(lambda: self._log(traceback.format_exc()))
            finally:
                self._scan_running = False
            payload = self._scan_payload()
            self._ui.emit("scan", payload)
            new = [g for g in payload["found"] if ProjectLibrary.key(g["path"]) not in previous]
            self._log(f"Oyun taraması: {len(payload['found'])} oyun bulundu, {len(new)} yeni.")
            if new:
                self._notify(f"{_n(len(new))} yeni oyun bulundu", "Kütüphane sayfasından tek tıkla ekleyebilirsin.", "info", "search",
                             {"label": "Göster", "page": "library"})
            elif manual and not payload["found"]:
                self._toast("Yeni oyun bulunamadı. Oyunların başka bir yerdeyse klasör ekleyebilirsin.", "info")

        threading.Thread(target=work, daemon=True, name="oyun-tarama").start()
        return True

    def scan_add(self, path: str) -> Optional[Dict[str, Any]]:
        game = next((g for g in self._scan_found if ProjectLibrary.key(g["path"]) == ProjectLibrary.key(path)), None)
        if not game:
            return None
        item = self._library.upsert(game["path"], title=game["title"], engine=game["engine"], status="new")
        self._load_art_async(item)
        self._emit_stats()
        self._ui.emit("scan", self._scan_payload())
        return self._project_payload(item)

    def scan_dismiss(self, path: str) -> Dict[str, Any]:
        """Öneriyi gizler; sonraki taramalarda da gösterilmez."""
        self.update_settings({"scan_dismissed": [*self._settings.get("scan_dismissed", []), path]})
        return self._scan_payload()

    def scan_pick_folder(self) -> Optional[Dict[str, Any]]:
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER) if self._window else None
        if not result:
            return None
        folders = [*self._settings.get("scan_folders", [])]
        if result[0] not in folders:
            self.update_settings({"scan_folders": [*folders, result[0]]})
        self.scan_games(True)
        return self._scan_payload()

    def scan_remove_folder(self, folder: str) -> Dict[str, Any]:
        self.update_settings({"scan_folders": [f for f in self._settings.get("scan_folders", []) if f != folder]})
        return self._scan_payload()

    # ── Güncelleme ───────────────────────────────────────────────────────────
    def _update_repo(self) -> str:
        import updater
        return (self._settings.get("update_repo") or "").strip() or updater.default_repo()

    def check_update(self, manual: bool = False) -> Dict[str, Any]:
        """Son sürümü kontrol eder. manual=False: açılıştaki sessiz kontrol (yalnızca yeni sürüm varsa bildirir)."""
        import updater
        repo = self._update_repo()
        if not repo:
            info: Dict[str, Any] = {"available": False, "error": "Bu derlemede güncelleme kaynağı tanımlı değil."}
        else:
            try:
                info = updater.check(APP_VERSION, repo)
            except Exception as exc:
                info = {"available": False, "error": f"Sunucuya ulaşılamadı ({type(exc).__name__})."}
        info.update(current=APP_VERSION, can_apply=FROZEN and bool(info.get("asset")))
        self._update_info = info
        self._ui.emit("update", info)
        if info.get("available") and not manual:
            self._notify(f"Yeni sürüm hazır: {info['latest']}", "Değişiklikleri görmek ve tek tıkla kurmak için Güncelle'ye bas.",
                         "info", "download", {"label": "Güncelle", "update": True})
        return info

    def apply_update(self) -> bool:
        """Güncelleme penceresinden çağrılır: indir (ilerlemeli) → kapat → dosyaları değiştir → yeniden aç."""
        def task():
            try:
                install()
            except Exception:
                self._ui.emit("update_progress", None)   # pencere kilitli kalmasın
                raise

        def install():
            import subprocess
            import updater
            info = getattr(self, "_update_info", None) or self.check_update(manual=True)
            if not info.get("available") or not info.get("asset"):
                raise UserError("Kurulacak bir güncelleme yok.")
            if not FROZEN:
                raise UserError("Kaynak koddan çalışıyorsun; güncellemek için 'git pull' kullan.")
            self._status(f"Capri {info['latest']} indiriliyor…")
            sent = [0]

            def report(done: int, total: int) -> None:   # en fazla MB başına bir olay
                if done - sent[0] >= 1 << 20 or done == total:
                    sent[0] = done
                    self._ui.emit("update_progress", {"done": done, "total": total})

            try:
                staged = updater.stage(info["asset"], info["latest"], log=self._log, progress=report,
                                       expected_size=int(info.get("asset_size") or 0), digest=info.get("asset_digest", ""))
            except updater.DownloadError as error:
                raise UserError(str(error))
            helper = staged / Path(sys.executable).name
            if not helper.exists():
                raise UserError("İndirilen paket eksik; güncelleme uygulanmadı. Daha sonra tekrar dene.")
            self._ui.emit("update_progress", {"installing": True})
            # Yeni sürümün kendi exe'si dosyaları değiştirir: konsol penceresi açılmaz, hata olursa geri alınır
            subprocess.Popen([str(helper), "--apply-update", "--pid", str(os.getpid()), "--target", str(APP_DIR),
                              "--from", APP_VERSION, "--to", str(info["latest"])], cwd=str(staged), close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            time.sleep(1.5)
            self.win_close()
            threading.Timer(5.0, lambda: os._exit(0)).start()   # açık kalan bir iş parçacığı kapanışı geciktirmesin

        return self._run_task("Güncelleme", task)

    def _on_start(self) -> None:
        """Pencereler açıldıktan sonra: OCR pencerelerini hazırla, kısayolları kaydet."""
        from ocr import prepare_overlay_window, set_window_icon
        try:
            set_window_icon("Capri", ICON_FILE)
        except Exception as exc:
            self._log(f"Uygulama simgesi ayarlanamadı: {exc}")
        for _ in range(40):
            if all(prepare_overlay_window(title, rounded=(key != "select")) for key, title in OCR_TITLES.items()):
                break
            time.sleep(0.15)
        try:
            self._setup_hotkeys()
        except Exception as exc:
            self._log(f"Kısayollar kaydedilemedi: {exc}")
        try:
            self._bind_drop()
        except Exception as exc:
            self._log(f"Sürükle-bırak etkinleştirilemedi: {exc}")
        if self._settings.get("update_check") and self._update_repo():
            threading.Thread(target=self.check_update, daemon=True).start()
        threading.Thread(target=self._preload_engines, daemon=True, name="preload").start()
        threading.Thread(target=self._scan_on_start, daemon=True, name="scan-start").start()
        self._report_update_result()

    def _report_update_result(self) -> None:
        """Güncelleme yardımcısının bıraktığı sonucu bildirir; artıkları temizler."""
        import updater
        result = updater.take_result()
        if not result:
            return
        if result.get("ok"):
            self._notify(f"Capri {result.get('to', APP_VERSION)} sürümüne güncellendi",
                         "Yenilikleri görmek için güncelleme penceresini aç.", "ok", "download", {"label": "Yenilikler", "update": True})
        else:
            self._notify("Güncelleme uygulanamadı", f"Önceki sürüm olduğu gibi duruyor. Ayrıntı: {result.get('error', '')}",
                         "error", "alert", {"label": "Teknik günlük", "page": "log"})
            self._log(f"Güncelleme hatası: {result.get('error')}")
    @staticmethod
    def _preload_engines() -> None:
        """İlk oyun açılışı beklemesin: ağır motor modülleri arayüz açıldıktan sonra arka planda yüklenir."""
        time.sleep(1.5)
        for module in ("engine_unity", "engine_renpy", "engine_unreal", "engine_rpgmaker", "engine_kag", "engine_godot",
                       "engine_wolf"):
            try:
                __import__(module)
            except Exception:
                pass

    def _scan_on_start(self) -> None:
        time.sleep(3.0)    # açılış bitsin, arayüz yanıt versin
        self._safely(self._check_library_updates)
        if self._settings.get("scan_on_start") and not self._busy:
            self.scan_games(False)

    def _check_library_updates(self) -> List[str]:
        """Çevrilmiş oyunlardan dosyaları çeviriden sonra değişenler (ör. Steam güncellemesi): tek bildirimle haber
        verilir, durumları düzeltilir; böylece eski yedekler yeni dosyaların üzerine "orijinal" diye geri yüklenmez."""
        changed = []
        for item in self._library.list():
            path, stamp = item.get("path"), item.get("files_stamp")
            if item.get("status") != "translated" or not stamp or not path or not Path(path).is_dir():
                continue
            current = game_files_stamp(path, str(item.get("engine") or ""))
            if current and current != stamp:
                self._library.upsert(path, touch=False, status="analyzed", files_changed_at=time.time(),
                                     last_action="Oyun güncellenmiş", last_action_at=time.time())
                self._emit_project(path)
                changed.append(str(item.get("title") or Path(path).name))
        if changed:
            names = ", ".join(changed[:3]) + ("…" if len(changed) > 3 else "")
            self._log(f"Çeviriden sonra dosyaları değişen oyunlar: {', '.join(changed)}")
            self._notify(f"{_n(len(changed))} oyun güncellenmiş",
                         f"{names}: oyunu açıp 'Çeviriyi yeniden uygula'ya bas (önbellekteki satırlar ücretsiz, "
                         "yalnızca yeni satırlar çevrilir).", "warn", "alert",
                         {"label": "Kütüphane", "page": "library"})
        return changed

    # ── Sağlayıcılar ─────────────────────────────────────────────────────────
    EXTRA_FIELDS = ("key", "model", "base_url", "region")

    @staticmethod
    def _extra_provider_fields(cfg: Any) -> Dict[str, str]:
        """Ek sağlayıcıların alanları arayüzde düz adlarla: deepseek_key, deepseek_model, custom_base_url…"""
        out = {}
        for pid in cloud_providers.ALL:
            values = cloud_providers.extra(cfg, pid)
            for name in CapriBridge.EXTRA_FIELDS:
                out[f"{pid}_{name}"] = values.get(name, "")
        return out

    @staticmethod
    def _provider_catalog() -> List[Dict[str, Any]]:
        """Arayüzdeki sağlayıcı kartları (ek bulut sağlayıcıları; ilk dördü app.js'de)."""
        items = []
        for pid, meta in cloud_providers.ALL.items():
            if pid == "custom":
                fields = [["custom_base_url", "Sunucu adresi (…/v1)", "text", "full"], ["custom_key", "API anahtarı (isteğe bağlı)", "password", ""],
                          ["custom_model", "Model", "model", ""]]
                test = "custom_base_url"
            elif pid == "azure_translator":
                fields = [["azure_translator_key", "API anahtarı", "password", ""], ["azure_translator_region", "Bölge (isteğe bağlı)", "text", ""]]
                test = "azure_translator_key"
            elif pid in cloud_providers.MT_PROVIDERS:
                fields = [[f"{pid}_key", "API anahtarı", "password", "full"]]
                test = f"{pid}_key"
            else:
                fields = [[f"{pid}_key", "API anahtarı", "password", ""], [f"{pid}_model", "Model", "model", ""]]
                test = f"{pid}_key"
            items.append({"id": pid, "short": meta["short"], "group": "cloud", "title": meta["title"], "tag": meta["tag"],
                          "desc": meta["desc"], "fields": fields, "test": test, "key_url": meta.get("key_url", ""),
                          "default_model": meta.get("model", ""), "kind": "mt" if pid in cloud_providers.MT_PROVIDERS else "chat"})
        return items

    def save_providers(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cfg = prov.load_provider_config()
        for pid in cloud_providers.ALL:
            for name in self.EXTRA_FIELDS:
                value = data.get(f"{pid}_{name}")
                if isinstance(value, str):
                    cloud_providers.extra(cfg, pid)[name] = value.strip()
        keys = data.get("gemini_keys", cfg.gemini_keys)
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.splitlines() if k.strip()]
        cfg.gemini_keys = keys
        for field in ("gemini_model", "openai_key", "openai_model", "anthropic_key", "anthropic_model",
                      "deepl_key", "ollama_host", "ollama_model"):
            if field in data and isinstance(data[field], str):
                setattr(cfg, field, data[field].strip())
        if data.get("active") in MODEL_LABELS:
            cfg.active_provider = data["active"]
            self._settings["model"] = data["active"]
            save_settings(self._settings)
        prov.save_provider_config(cfg)
        return {"ok": True, "settings": self._settings}

    def ollama_models(self) -> Dict[str, Any]:
        """Ollama'da kurulu modeller + önerilen çeviri modelleri (ekran kartının belleğine göre öneri)."""
        from engine_common import OLLAMA_PRESETS, ollama_family, recommended_ollama_model
        cfg = prov.load_provider_config()
        running, installed, _msg = prov.test_ollama_service(cfg.ollama_host)
        names = set(installed)
        presets = [{**p, "installed": p["model"] in names or f"{p['model']}:latest" in names} for p in OLLAMA_PRESETS]
        return {"running": running, "installed": installed, "presets": presets, "current": cfg.ollama_model,
                "family": ollama_family(cfg.ollama_model),
                "recommended": recommended_ollama_model((self._gpu or {}).get("vram_gb"))}

    def ollama_pull(self, model: str) -> bool:
        """Ollama modelini Capri içinden indirir (ilerleme çubuğuyla); bitince varsayılan Ollama modeli yapar."""
        model = (model or "").strip()
        if not model:
            return False

        def task():
            import requests
            cfg = prov.load_provider_config()
            host = (cfg.ollama_host or "http://127.0.0.1:11434").rstrip("/")
            if not prov.test_ollama_service(host)[0]:
                raise UserError("Ollama çalışmıyor. Ollama'yı kurup açtıktan sonra tekrar dene (ollama.com).")
            self._stage("download", f"{model} indiriliyor")
            self._progress_unit = "MB"
            with requests.post(f"{host}/api/pull", json={"model": model, "stream": True}, stream=True, timeout=60) as resp:
                if resp.status_code != 200:
                    raise UserError(f"Ollama indirmeyi reddetti (HTTP {resp.status_code}).")
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    event = json.loads(raw)
                    if event.get("error"):
                        raise UserError(f"Ollama: {event['error']}")
                    if event.get("total") and event.get("completed") is not None:
                        self._progress(int(event["completed"]) >> 20, max(1, int(event["total"]) >> 20))
            cfg.ollama_model = model
            prov.save_provider_config(cfg)
            self._notify("Model indirildi", f"{model} hazır ve Ollama için seçildi.", "ok", "download")
        return self._run_task("Model indirme", task)

    def gemini_models(self) -> List[str]:
        """Anahtarın erişebildiği, çeviriye uygun Gemini modelleri (hız sırasıyla)."""
        try:
            return prov.gemini_models()
        except Exception:
            return list(prov.GEMINI_FALLBACK_MODELS)

    def test_provider(self, provider: str, value: str = "") -> Dict[str, Any]:
        cfg = prov.load_provider_config()
        value = (value or "").strip()
        if provider == "gemini":
            ok, _lat, msg = prov.test_gemini_connection(value or (cfg.gemini_keys[0] if cfg.gemini_keys else ""),
                                                        model=cfg.gemini_model)
        elif provider == "openai":
            ok, _lat, msg = prov.test_openai_connection(value or cfg.openai_key, model=cfg.openai_model)
        elif provider == "anthropic":
            ok, _lat, msg = prov.test_anthropic_connection(value or cfg.anthropic_key, model=cfg.anthropic_model)
        elif provider == "deepl":
            ok, _lat, msg = prov.test_deepl_connection(value or cfg.deepl_key)
        elif provider == "ollama":
            ok, models, msg = prov.test_ollama_service(value or cfg.ollama_host)
            if ok and models:
                msg += " · " + ", ".join(models[:6])
        elif provider == "local":
            import local_llm
            model_id = self._local_model_id()
            started = time.time()
            try:
                result = local_llm.translate_one(model_id, "Welcome back, traveler!", "en", self._settings["target"],
                                                 log=self._log)
                ok, msg = True, f"{local_llm.BY_ID[model_id]['label']} çalışıyor ({int((time.time() - started) * 1000)} ms): {result}"
            except Exception as error:
                ok, msg = False, str(error)
        elif provider in ("opus", "nllb"):
            status = prov.get_offline_model_status(provider)
            ok = status["is_ready"]
            msg = f"Kurulu ({status['size_mb']} MB)" if ok else f"Eksik: {', '.join(status['missing_files'][:3])}"
        elif provider in cloud_providers.ALL:
            ok, msg, models = cloud_providers.test(cfg, provider, value)
            return {"ok": ok, "msg": msg, "models": models[:200]}
        else:
            ok, msg = False, "Bilinmeyen sağlayıcı."
        return {"ok": ok, "msg": msg}

    # ── Yerel modeller ───────────────────────────────────────────────────────
    def model_status(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {k: prov.get_offline_model_status(k) for k in ("opus", "nllb")}
        data["runtime"] = {"ready": gpu_runtime.ready(), "missing": gpu_runtime.missing(),
                           "dir": str(gpu_runtime.SITE_DIR), "ct2_ready": gpu_runtime.ct2_ready()}
        data["llm"] = self.local_models()
        return data

    def _ensure_runtime(self) -> bool:
        """PyTorch ortamı yoksa kullanıcıya ne kurulacağını söyleyip onay ister ve kurar."""
        if gpu_runtime.ready():
            return True
        cuda = gpu_runtime.driver_cuda()
        size = gpu_runtime.estimate_mb(cuda)
        kind = (f"NVIDIA ekran kartın için CUDA destekli PyTorch" if cuda else "NVIDIA ekran kartı bulunamadığı için CPU sürümü PyTorch")
        if not self._ask("OPUS-MT ve NLLB için PyTorch kurulacak",
                         f"OPUS-MT ve NLLB için PyTorch ve Transformers gerekiyor. Capri, {kind} ile birlikte bunları "
                         f"resmi kaynaklardan (download.pytorch.org, pypi.org) indirip kuracak (~{_n(size)} MB, bir kez). "
                         "Devam edilsin mi?"):
            return False
        self._status("PyTorch kuruluyor…")
        torch = gpu_runtime.install(log=self._log, progress=self._progress)
        self._notify("PyTorch kuruldu",
                     f"PyTorch {torch['version']} ({torch['variant']})" if torch else "Eksik kütüphaneler kuruldu.", "ok", "cpu")
        self._detect_gpu()
        return True

    def install_runtime(self) -> bool:
        def task():
            if gpu_runtime.ready():
                self._notify("PyTorch hazır", "PyTorch ve Transformers zaten kurulu.", "ok", "cpu")
            self._ensure_runtime()
            self._ui.emit("models", self.model_status())

        return self._run_task("Ortam kurulumu", task)

    def download_model(self, kind: str) -> bool:
        if kind not in ("opus", "nllb"):
            return False

        def task():
            if not gpu_runtime.ct2_ready():           # PyTorch yerine ~40 MB'lık CTranslate2 ortamı
                self._status("Çalışma ortamı kuruluyor (≈40 MB)…")
                gpu_runtime.install_ct2(log=self._log, progress=self._progress)
            status = prov.get_offline_model_status(kind)
            if status["is_ready"]:
                self._notify(f"{status['label']} hazır", f"Tüm dosyalar yerinde ({status['size_mb']} MB).", "ok", "cpu")
            else:
                self._status(f"{status['label']} indiriliyor…")
                prov.download_offline_model(
                    kind, log=self._log,
                    progress_callback=lambda i, n, _msg: self._progress(i, n),
                )
                self._notify(f"{status['label']} indirildi", "Model kullanıma hazır.", "ok", "cpu")
            self._ui.emit("models", self.model_status())

        return self._run_task("Model indirme", task)

    def compact_model(self, kind: str) -> bool:
        """Yerel modeli fp16'ya küçültür (onay ister; eski dosya Geri Dönüşüm Kutusu'na gider)."""
        if kind not in LOCAL_MODELS:
            return False

        def task():
            status = prov.get_offline_model_status(kind)
            if status.get("compact"):
                raise UserError(f"{status['label']} zaten küçültülmüş.")
            if not self._ask("Modeli küçült", f"{status['label']} fp16'ya dönüştürülecek: boyut yarıya iner, kalite "
                             "değişmez. Eski dosya Geri Dönüşüm Kutusu'na taşınır."):
                return
            self._status(f"{status['label']} küçültülüyor…")
            result = prov.compact_offline_model(kind, log=self._log)
            if not result.get("ok"):
                raise RuntimeError(result.get("msg", "Dönüştürme başarısız."))
            self._notify(f"{status['label']} küçültüldü",
                         f"{_n(result['old_mb'])} MB → {_n(result['size_mb'])} MB · yükleme {result['load_before']} sn → "
                         f"{result['load_after']} sn · aynı çıktı {result['identical']}"
                         + ("" if result["recycled"] else " · eski dosya taşınamadı, elle silebilirsin"), "ok", "cpu")
            self._ui.emit("models", self.model_status())

        return self._run_task("Model küçültme", task)

    # ── Yedekler ─────────────────────────────────────────────────────────────
    def list_backups(self) -> List[Dict[str, Any]]:
        if not self._game:
            return []
        import rgss_archive
        import wolf_archive
        root = Path(self._game["root"])
        items = []
        if rgss_archive.is_unpacked(root):
            manifest = _read_json(root / rgss_archive.MANIFEST, {})
            archive = root / rgss_archive.BACKUP_DIR / manifest.get("archive", "")
            items.append({"path": str(archive.parent), "engine": "Şifreli arşiv", "archive": manifest.get("archive", ""),
                          "date": time.strftime("%d.%m.%Y %H:%M", time.localtime((root / rgss_archive.MANIFEST).stat().st_mtime)),
                          "files": len(manifest.get("extracted", [])), "size": archive.stat().st_size if archive.exists() else 0,
                          "zip": False})
        if wolf_archive.is_unpacked(root):
            manifest = _read_json(root / wolf_archive.MANIFEST, {})
            kept = [root / wolf_archive.BACKUP_DIR / rel for rel in manifest.get("archives", [])]
            items.append({"path": str(root / wolf_archive.BACKUP_DIR), "engine": "Şifreli arşiv",
                          "archive": ", ".join(Path(rel).name for rel in manifest.get("archives", [])),
                          "date": time.strftime("%d.%m.%Y %H:%M", time.localtime((root / wolf_archive.MANIFEST).stat().st_mtime)),
                          "files": len(manifest.get("extracted", [])),
                          "size": sum(p.stat().st_size for p in kept if p.exists()), "zip": False})
        return items + [
            {
                "path": str(b.path), "engine": b.engine, "date": b.date_str,
                "files": b.file_count, "size": b.size_bytes, "zip": b.is_zip,
            }
            for b in list_game_backups(root)
        ]

    def restore_archive(self) -> bool:
        def task():
            import rgss_archive
            game = self._require_game()
            if not self._ask("Şifreli arşivi geri koy",
                             "Açılan dosyalar silinip orijinal arşiv geri konacak. Devam edilsin mi?"):
                return
            import wolf_archive
            root = Path(game["root"])
            removed = 0
            if wolf_archive.is_unpacked(root):
                removed += wolf_archive.restore(root, log=self._log)
            if rgss_archive.is_unpacked(root):
                removed += rgss_archive.restore(root, log=self._log)
            game.update(info=None, texts=None, analysis=None)
            self._library.upsert(game["root"], status="restored", last_action="Orijinal arşiv geri konuldu", last_action_at=time.time())
            self._emit_project(game["root"])
            self._notify("Arşiv geri konuldu", f"{game['title']} · {_n(removed)} açılmış dosya kaldırıldı", "ok", "undo")
            self._ui.emit("backups", self.list_backups())

        return self._run_task("Arşivi geri koyma", task)

    def restore_backup(self, path: str = "") -> bool:
        def task():
            game = self._require_game()
            backups = list_game_backups(Path(game["root"]))
            if not backups:
                raise UserError("Bu oyun için kayıtlı yedek bulunamadı.")
            chosen = next((b for b in backups if str(b.path) == path), None) if path else backups[0]
            if not chosen:
                raise UserError("Seçilen yedek bulunamadı.")
            if not self._ask("Yedeği geri yükle",
                             f"{chosen.date_str} tarihli yedek ({chosen.file_count} dosya) oyun klasörüne geri "
                             "yüklenecek. Devam edilsin mi?"):
                return
            ok, count, msg = restore_game_backup(chosen, Path(game["root"]), log=self._log)
            if not ok:
                raise (UserError if msg.startswith("Yedek doğrulanamadı") else RuntimeError)(msg)
            game["texts"] = None
            game["analysis"] = None
            self._library.upsert(game["root"], status="restored", last_action="Orijinal dosyalara dönüldü", last_action_at=time.time())
            self._emit_project(game["root"])
            self._status(f"Yedek geri yüklendi: {count} dosya.", "ok")
            self._notify("Yedek geri yüklendi", f"{game['title']} · {count} dosya orijinal hâline döndü", "ok", "undo")
            self._ui.emit("backups", self.list_backups())

        return self._run_task("Geri yükleme", task)

    # ── Pencere ──────────────────────────────────────────────────────────────
    def win_minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def win_maximize(self) -> None:
        if not self._window:
            return
        maximized = getattr(self._window, "_omni_max", False)
        (self._window.restore if maximized else self._window.maximize)()
        self._window._omni_max = not maximized

    def win_close(self) -> None:
        self._ui.window = None     # kapanırken yok edilmiş pencereye JavaScript gönderilmesin
        self.ocr_pin_stop(silent=True)
        try:
            import local_llm
            local_llm.SERVER.stop()   # dahili model sunucusu ekran kartı belleğini bırakır
        except Exception:
            pass
        for win in list(self._ocr_win.values()):
            try:
                win.destroy()
            except Exception:
                pass
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass


def main() -> None:
    import single_instance
    if not single_instance.acquire(APP_DIR, DATA_DIR):   # aynı Capri zaten açık: onu öne getir, ikinciyi açma
        single_instance.focus_existing(DATA_DIR)
        return
    html_file = WEB_DIR / "index.html"
    import webview
    if os.environ.get("CAPRI_DEBUG_PORT"):   # geliştirme: exe'nin arayüzünü dışarıdan test etmek için
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["CAPRI_DEBUG_PORT"])
    seed_user_files()
    refresh_web_cache(WEB_DIR, DATA_DIR / "webview", APP_VERSION)
    try:  # görev çubuğunda python yerine Capri simgesiyle ayrı grup
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Capri.GameTranslator")
    except Exception:
        pass

    bridge = CapriBridge()
    window = webview.create_window(
        title="Capri",
        url=str(html_file),
        js_api=bridge,
        width=1440,
        height=900,
        min_size=(1100, 700),
        frameless=True,
        easy_drag=False,
        text_select=True,
        background_color="#0c0d0f",
        hidden=bool(os.environ.get("CAPRI_HIDDEN")),   # yalnızca otomatik testler: pencere ekranda görünmez
    )
    bridge.set_window(window)

    # Ekran çevirisi pencereleri: gizli oluşturulur, kısayolla anında (≈10 ms) gösterilir
    try:
        from ocr import monitor_rect
        screen = webview.screens[0]
        physical = monitor_rect(1)
        scale = physical["width"] / max(1, screen.width)
        ocr_windows = {
            "select": webview.create_window(OCR_TITLES["select"], url=str(WEB_DIR / "ocr_select.html"), js_api=bridge,
                                            x=0, y=0, width=screen.width, height=screen.height, frameless=True,
                                            on_top=True, hidden=True, resizable=False, easy_drag=False,
                                            background_color="#000000"),
            "popup": webview.create_window(OCR_TITLES["popup"], url=str(WEB_DIR / "ocr_popup.html"), js_api=bridge,
                                           width=460, height=180, frameless=True, on_top=True, hidden=True,
                                           easy_drag=False, text_select=True, background_color="#1b1c1f"),
            "pin": webview.create_window(OCR_TITLES["pin"], url=str(WEB_DIR / "ocr_pin.html"), js_api=bridge,
                                         width=420, height=110, frameless=True, on_top=True, hidden=True,
                                         easy_drag=False, text_select=True, background_color="#1b1c1f"),
        }
        bridge.set_ocr_windows(ocr_windows, (screen.width, screen.height), scale)
        window.events.closed += bridge.win_close
    except Exception as exc:
        print(f"[UYARI] Ekran çevirisi pencereleri oluşturulamadı: {exc}")

    webview.start(bridge._on_start, debug="--debug" in sys.argv, private_mode=False, http_port=free_ui_port() or None,
                  storage_path=str(DATA_DIR / "webview"))


if __name__ == "__main__":
    if "--apply-update" in sys.argv:          # güncelleme yardımcısı: pencere açmadan dosyaları değiştirir
        import updater
        sys.exit(updater.run_helper(sys.argv))
    if sys.argv[1:3] == ["-m", "rpycdec"]:   # exe'de sys.executable Capri.exe'dir: ikinci pencere açılmasın
        import runpy
        sys.argv = ["rpycdec", *sys.argv[3:]]
        runpy.run_module("rpycdec", run_name="__main__", alter_sys=True)
        sys.exit(0)
    main()
