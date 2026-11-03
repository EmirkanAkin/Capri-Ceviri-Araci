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
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import providers as prov
from backup_system import create_game_backup, list_game_backups, restore_game_backup
from engine_common import Glossary, ProgressTracker, TranslationCache, TranslationCancelled, cache_file_for
from languages import get_all_source_languages, get_all_target_languages
from library import ProjectLibrary, resolve_art

APP_VERSION = "1.0.0"
from paths import APP_DIR, FROZEN, GLOSSARY_DIR, ICON_FILE, WEB_DIR, seed_user_files
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
}
MODEL_LABELS = {
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic Claude",
    "deepl": "DeepL",
    "ollama": "Ollama (yerel LLM)",
    "opus": "OPUS-MT (çevrimdışı)",
    "nllb": "NLLB-200 (çevrimdışı)",
}
FULL_TRANSLATION_MODELS = tuple(MODEL_LABELS)
CLOUD_MODELS = ("openai", "anthropic", "deepl")
LOCAL_MODELS = ("opus", "nllb")          # Ekran kartında çalışan çevrimdışı modeller
TURKISH_ONLY_MODELS = ("opus",)           # OPUS-MT yalnızca EN→TR; NLLB-200 çok dilli
GLOSSARY_FILES = {"general": "glossary.json", "rpgmaker": "glossary_rpgm.json", "nsfw": "glossary_nsfw.json"}
DEFAULT_SETTINGS = {
    "source": "en", "target": "tr", "model": "gemini", "nsfw": False, "backup": True, "quality_pass": False,
    "gpu_auto": True,
    "ocr_hotkey": "Ctrl+Shift+T", "pin_hotkey": "Ctrl+Shift+Y", "ocr_model": "",
    "ocr_interval": 350, "ocr_place": "below",
    "update_repo": "", "update_check": True,
}
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
    try:
        children = [c for c in p.iterdir() if c.is_dir() and not c.name.startswith((".", "_"))]
    except OSError:
        return None, None
    # Çalıştırılabilir dosya içeren alt klasörler önce denenir
    children.sort(key=lambda c: (not any(c.glob("*.exe")), c.name.lower()))
    for child in children[:12]:
        found = _detect_here(child)
        if found[0]:
            return found
    return None, None


def game_root_of(game_type: str, info: Any, fallback: Path) -> Path:
    root = getattr(info, "root", None)
    return Path(root) if root else fallback


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
    return root.name


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


def scan_renpy_characters(game_dir: Path) -> List[str]:
    """Ren'Py `define x = Character("Ad")` tanımlarını açık .rpy dosyalarından ve RPA arşivlerinden toplar."""
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
    names: List[str] = []
    for text in texts:
        for match in CHARACTER_DEFINE.finditer(text):
            name = match.group(3).strip()
            if name and "[" not in name and "{" not in name and name not in names and len(name) <= 40:
                names.append(name)
    return names


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


def review_path_for(cache_path: Path) -> Path:
    return DATA_DIR / "reports" / f"{cache_path.stem}.review.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any, indent: Any = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def _n(value: Any) -> str:
    """Türkçe binlik ayırıcı: 21529 → 21.529"""
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


def estimate_duration(lines: int, model: str) -> str:
    speed = {"gemini": 150, "openai": 60, "anthropic": 50, "deepl": 120, "opus": 70, "nllb": 45, "ollama": 12}.get(model, 40)
    seconds = max(5, int(lines / speed))
    if seconds < 60:
        return f"~{seconds} sn"
    if seconds < 3600:
        return f"~{seconds // 60} dk {seconds % 60} sn"
    return f"~{seconds // 3600} sa {(seconds % 3600) // 60} dk"


def load_settings() -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings["model"] = prov.load_provider_config().active_provider or "gemini"
    settings.update(_read_json(SETTINGS_FILE, {}))
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


class UserError(Exception):
    """Kullanıcıya olduğu gibi gösterilecek, beklenen hata."""


# ═══════════════════════════════════════════════════════════════════════════════
# Arayüz olay kanalı
# ═══════════════════════════════════════════════════════════════════════════════

class UiChannel:
    """
    Python → JavaScript olaylarını toplar ve ~10 kez/sn tek çağrıda iletir.
    Binlerce log satırı veya ilerleme güncellemesi arayüzü dondurmaz.
    """

    def __init__(self):
        self.window = None
        self._queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._progress: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="ui-channel").start()

    def emit(self, event: str, payload: Any = None) -> None:
        self._queue.put((event, payload))

    def log(self, message: Any) -> None:
        text = str(message)
        print(f"[Capri] {text}")
        self._queue.put(("log", text))

    def progress(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._progress = payload

    def _loop(self) -> None:
        while True:
            time.sleep(0.1)
            events: List[Dict[str, Any]] = []
            logs: List[str] = []
            while True:
                try:
                    event, payload = self._queue.get_nowait()
                except queue.Empty:
                    break
                if event == "log":
                    logs.append(payload)
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
        self._window = None
        self._library = ProjectLibrary()
        self._settings = load_settings()
        self._game: Optional[Dict[str, Any]] = None
        self._busy = False
        self._busy_lock = threading.Lock()
        self._cancel = threading.Event()
        self._tracker = ProgressTracker()
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
        if done <= 0 or self._tracker.total != max(total, 1) or done < self._tracker.done:
            self._tracker.start(total)
        self._tracker.advance(max(0, done - self._tracker.done))
        self._ui.progress({
            "done": done,
            "total": total,
            "pct": round(min(100.0, done * 100.0 / total), 1),
            "eta": self._tracker.eta_str(),
            "rate": self._tracker.rate_str(),
        })

    def _ask(self, title: str, text: str, timeout: float = 300.0) -> bool:
        """Arayüzde onay penceresi açar ve kullanıcının yanıtını bekler."""
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
            self._library.upsert(item["path"], **fields)
            self._emit_project(item["path"])

        threading.Thread(target=work, daemon=True, name="art").start()

    def _run_task(self, label: str, fn: Callable[[], None]) -> bool:
        with self._busy_lock:
            if self._busy:
                self._toast("Devam eden bir işlem var, lütfen bitmesini bekleyin.", "warn")
                return False
            self._busy = True
        self._cancel.clear()
        self._ui.emit("busy", {"busy": True, "label": label})

        def work():
            try:
                fn()
            except TranslationCancelled:
                self._status("Durduruldu. Kaldığı yerden devam etmek için tekrar başlat.", "warn")
                self._notify(f"{label} durduruldu", "Yapılan çeviriler önbellekte; tekrar başlatınca kaldığı yerden devam eder.",
                             "warn", "pause")
                if self._game:
                    self._library.upsert(self._game["root"], status="paused")
                    self._emit_project(self._game["root"])
            except UserError as exc:
                self._status(str(exc), "warn")
                self._notify(f"{label} yapılamadı", str(exc), "warn", "alert")
            except Exception as exc:
                self._log(traceback.format_exc())
                self._status(f"Hata: {exc}", "error")
                self._notify(f"{label} başarısız", str(exc), "error", "alert", {"label": "Teknik günlük", "page": "log"})
                if self._game:
                    self._library.upsert(self._game["root"], status="error")
                    self._emit_project(self._game["root"])
            finally:
                with self._busy_lock:
                    self._busy = False
                self._ui.emit("busy", {"busy": False})

        threading.Thread(target=work, daemon=True, name=label).start()
        return True

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
        self._notify("Proje açıldı", f"{title} · {ENGINE_LABELS[game_type]}", "info", "folder")
        self._load_art_async(item)
        return self._project_payload(item)

    def _require_game(self) -> Dict[str, Any]:
        if not self._game:
            raise UserError("Önce bir oyun klasörü seçin.")
        return self._game

    def _cache_path(self, model: Optional[str] = None) -> Path:
        game = self._require_game()
        return cache_path_for(Path(game["root"]), game["type"], model or self._settings["model"], self._settings["target"])

    def _record_review(self, cache_path: Path, failed: set) -> None:
        """Geçerli çeviri alınamayan satırları editörde incelenmek üzere kaydeder."""
        path = review_path_for(cache_path)
        cache = _read_json(cache_path, {})
        current = set(_read_json(path, [])) | set(failed)
        pending = sorted(s for s in current if s not in cache or cache.get(s) == s)
        if pending:
            _write_json(path, pending)
        elif path.exists():
            path.unlink()
        if failed:
            self._notify(f"{_n(len(failed))} satır incelenmeli",
                         "Bu satırlar için geçerli çeviri alınamadı ve İngilizce bırakıldı. Editörde düzeltebilir "
                         "ya da çeviriyi tekrar başlatarak yeniden deneyebilirsin.",
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
        threading.Thread(target=lambda: self._ui.emit("stats", self.get_stats()), daemon=True).start()
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
            },
            "models": {k: prov.get_offline_model_status(k) for k in ("opus", "nllb")},
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
        lines, size = 0, 0
        for path in cache_dir.glob("*.json") if cache_dir.is_dir() else []:
            stat = path.stat()
            size += stat.st_size
            cached = self._stats_cache.get(str(path))
            if not cached or cached[0] != stat.st_mtime:
                data = _read_json(path, {})
                cached = (stat.st_mtime, len(data) if isinstance(data, dict) else 0)
                self._stats_cache[str(path)] = cached
            lines += cached[1]
        projects = self._library.list()
        return {
            "projects": len(projects),
            "translated": sum(1 for p in projects if p.get("status") == "translated"),
            "lines": lines,
            "cache_mb": round(size / 1048576, 1),
            "written": sum(int(p.get("written") or 0) for p in projects),
        }

    def _detect_gpu(self) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                self._gpu = {
                    "name": torch.cuda.get_device_name(0).replace("NVIDIA ", "").replace("GeForce ", ""),
                    "detail": f"{props.total_memory / 1024 ** 3:.0f} GB",
                    "cuda": True,
                }
            else:
                self._gpu = {"name": "CPU modu", "detail": "CUDA yok", "cuda": False}
        except Exception:
            self._gpu = {"name": "Yerel ortam kurulmadı", "detail": "", "cuda": False}
        self._gpu["runtime"] = gpu_runtime.ready()
        self._ui.emit("gpu", self._gpu)
        if self._gpu.get("cuda") and self._settings.get("gpu_auto"):
            self.optimize_gpu(preload=self._ocr_model() in LOCAL_MODELS or self._settings["model"] in LOCAL_MODELS,
                              silent=True)

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
        if self._game and self._game.get("analysis"):
            lines = self._game["analysis"].get("unique") or 0
            self._ui.emit("eta", {"text": estimate_duration(lines, self._settings["model"]) if lines else ""})
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
        return True

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
        game = self._game
        if game and game.get("analysis") and not force:
            self._ui.emit("analysis", game["analysis"])
            return True

        def task():
            game = self._require_game()
            self._status("Oyun analiz ediliyor…")
            analysis = getattr(self, f"_analyze_{game['type']}")(game)
            game["analysis"] = analysis
            unique = analysis.get("unique") or 0
            analysis["eta"] = estimate_duration(unique, self._settings["model"]) if unique else ""
            current = self._library.get(game["root"]) or {}
            self._library.upsert(
                game["root"], lines=analysis.get("lines"), unique=unique,
                status=None if current.get("status") in ("translated", "paused") else "analyzed",
            )
            self._ui.emit("analysis", analysis)
            self._emit_project(game["root"])
            self._status(analysis["summary"], "ok")
            self._notify("Analiz tamamlandı", f"{game['title']} · {analysis['summary']}", "ok", "scan")

        return self._run_task("Analiz", task)

    def _analyze_renpy(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_renpy import analyze_game, scan_game_fonts
        info = analyze_game(game["root"], self._log)
        game["info"] = info
        fonts = scan_game_fonts(info)
        bad_fonts = [f for f in fonts if f.get("missing_chars")]
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
            "notes": notes, "sample": "",
            "summary": f"{scripts or compiled} betik dosyası bulundu.",
            "meta": f"{scripts or compiled} betik dosyası",
        }

    def _analyze_unity(self, game: Dict[str, Any]) -> Dict[str, Any]:
        from engine_unity import detect_unity_game, extract_texts_unity
        info = game["info"] or detect_unity_game(game["root"])
        game["info"] = info
        texts = extract_texts_unity(info, log=self._log)
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
        needed = not texts or info.runtime == "IL2CPP"
        installed = bepinex_installer.is_installed(info.root)
        if needed:
            notes.append("Metinler dosyada açık değil: çeviri BepInEx + XUnity.AutoTranslator ile uygulanır"
                         + (" (kurulu)." if installed else " — tek tıkla kurulabilir."))
        for note in notes:
            self._log(note)
        return {
            "engine": "unity", "lines": len(texts), "unique": unique, "notes": notes,
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
            else:
                pak_note = ("Metinler .pak paketlerinde. Çeviri başlarken Capri, paketleri açmak için açık kaynak repak "
                            "aracını indirip kurmak üzere izin isteyecek (~2 MB).")
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
                         f"{info.version_label} oyununun dosyaları şifreli {archive.name} arşivinde. Çeviri için Capri "
                         f"arşivi oyun klasörüne açacak (yaklaşık {size_mb} MB dosya yazılır) ve orijinal arşivi "
                         "_capri_backups klasörüne taşıyacak; oyun açılan dosyalarla aynı şekilde çalışır. "
                         "Yedekler sayfasından tek tıkla geri alınabilir. Devam edilsin mi?"):
            raise TranslationCancelled()
        self._status(f"{archive.name} açılıyor…")
        rgss_archive.unpack(Path(info.root), log=self._log, progress=self._progress)
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
        unique = len({t.original for t in texts if t.original.strip()})
        notes = [
            f"{info.version_label} · {info.map_count} harita · {len(info.json_files)} JSON",
            f"Çevrilebilir metin: {_n(len(texts))} satır ({_n(unique)} benzersiz)",
        ]
        archive = self._rgss_archive(info)
        if archive:
            notes.append(f"Veri dosyaları şifreli {archive.name} arşivinde. Çeviri başlarken Capri arşivi oyun "
                         "klasörüne açar (sana sorulur); orijinal arşiv yedeklenir.")
        for note in notes:
            self._log(note)
        return {
            "engine": "rpgmaker", "lines": len(texts), "unique": unique, "notes": notes,
            "sample": texts[0].original if texts else "",
            "summary": f"{_n(len(texts))} satır ({_n(unique)} benzersiz) bulundu.",
            "meta": f"{_n(unique)} satır",
        }

    # ── Çeviri ───────────────────────────────────────────────────────────────
    def _check_model_ready(self, game_type: Optional[str]) -> None:
        s = self._settings
        model, target = s["model"], s["target"]
        if game_type == "renpy" and target != "tr":
            raise UserError("Ren'Py çevirisi şu an yalnızca Türkçe hedefini destekliyor.")
        if model in TURKISH_ONLY_MODELS and target != "tr":
            raise UserError(f"{MODEL_LABELS[model]} yalnızca İngilizce → Türkçe çeviri yapabilir.")
        cfg = prov.load_provider_config()
        if model == "gemini":
            from engine_renpy import load_gemini_api_key
            if not (cfg.gemini_keys or load_gemini_api_key()):
                raise UserError("Gemini API anahtarı yok. Sağlayıcılar sayfasından ekleyin.")
        elif model in CLOUD_MODELS:
            if not getattr(cfg, f"{model}_key"):
                raise UserError(f"{MODEL_LABELS[model]} API anahtarı yok. Sağlayıcılar sayfasından ekleyin.")
        elif model == "ollama":
            ok, _models, msg = prov.test_ollama_service(cfg.ollama_host)
            if not ok:
                raise UserError(msg)
        else:
            if not gpu_runtime.ready():
                raise UserError(f"{MODEL_LABELS[model]} için yerel model ortamı (PyTorch) kurulu değil. "
                                "Yerel Modeller sayfasından tek tıkla kurabilirsin.")
            status = prov.get_offline_model_status(model)
            if not status["is_ready"]:
                raise UserError(
                    f"{MODEL_LABELS[model]} modeli eksik ({status['present_count']}/{status['total_files']} dosya). "
                    "Yerel Modeller sayfasından indirin."
                )
            prov.release_offline_engines()  # Önizleme modelini VRAM'den boşalt

    def translate(self) -> bool:
        def task():
            game = self._require_game()
            self._check_model_ready(game["type"])
            s = self._settings
            self._library.upsert(game["root"], status="translating", model=s["model"], target=s["target"])
            self._emit_project(game["root"])
            self._tracker = ProgressTracker()
            self._notify("Çeviri başladı", f"{game['title']} · {MODEL_LABELS[s['model']]} · {s['source']} → {s['target']}",
                         "info", "play")
            self._status(f"Çeviri sürüyor ({MODEL_LABELS[s['model']]})…")
            started = time.monotonic()
            failed: set = set()
            written = getattr(self, f"_translate_{game['type']}")(game, failed)
            took = int(time.monotonic() - started)
            self._library.upsert(game["root"], status="translated", translated_at=time.time(), written=written)
            self._emit_project(game["root"])
            self._record_review(self._cache_path(), failed)
            message = f"{_n(written)} satır yazıldı · {took // 60} dk {took % 60} sn"
            self._status(f"Çeviri tamamlandı: {message}.", "ok")
            self._notify("Çeviri tamamlandı", f"{game['title']} · {message}", "ok", "check")
            self._ui.emit("done", {"written": written})
            self._ui.emit("stats", self.get_stats())

        return self._run_task("Çeviri", task)

    def _project_glossary(self) -> Dict[str, Any]:
        default = {"terms": {}, "address": "sen", "notes": "", "aes_key": ""}
        if not self._game:
            return default
        data = _read_json(project_glossary_path(Path(self._game["root"])), {})
        return {**default, **(data if isinstance(data, dict) else {})}

    def _glossary_path(self) -> Path:
        """Ren'Py için: genel (veya NSFW) sözlük + oyuna özel terimler birleştirilmiş dosya."""
        nsfw = GLOSSARY_DIR / "glossary_nsfw.json"
        base = nsfw if self._settings["nsfw"] and nsfw.exists() else GLOSSARY_DIR / "glossary.json"
        terms = self._project_glossary()["terms"]
        if not terms or not self._game:
            return base
        merged = {k: v for k, v in _read_json(base, {}).items() if not str(k).startswith("_")}
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
                    {"terms": terms, "address": "siz" if address == "siz" else "sen", "notes": notes or "", "aes_key": key})
        return {"ok": True, "count": len(terms)}

    def project_scan_characters(self) -> Dict[str, Any]:
        """Karakter adlarını oyundan tarar ve proje sözlüğüne (adı aynen koruyacak şekilde) ekler."""
        game = self._require_game()
        info = game["info"]
        if game["type"] == "renpy":
            names = scan_renpy_characters(Path(info.game_dir))
        elif game["type"] == "rpgmaker":
            names = scan_rpgmaker_characters(Path(info.data_dir))
        else:
            return {"ok": False, "msg": f"{ENGINE_LABELS[game['type']]} için karakter taraması desteklenmiyor.", "added": 0}
        pg = self._project_glossary()
        added = [n for n in names if n not in pg["terms"]]
        pg["terms"].update({n: n for n in added})
        _write_json(project_glossary_path(Path(game["root"])), pg)
        return {"ok": True, "found": len(names), "added": len(added), "names": names[:50]}

    def _translate_strings(self, unique: List[str], cache_path: Path, pattern: Any, glossary: Glossary,
                           game_engine: str, failed: set, extra: Optional[str] = None) -> Dict[str, str]:
        """Motor bağımsız: benzersiz metinleri seçili sağlayıcıyla çevirir (önbellek + sözlük)."""
        from engine_common import OllamaTranslationEngine, TranslationEngine
        from engine_renpy import load_gemini_api_key, translate_with_gemini
        s, cfg, model = self._settings, prov.load_provider_config(), self._settings["model"]
        cache = TranslationCache(cache_path)
        cache.load()
        translations: Dict[str, str] = {}
        for src in unique:
            hit = glossary.lookup(src)
            if hit is not None:
                translations[src] = hit
            elif not re.search(r"[A-Za-zÀ-ž]", src):
                translations[src] = src
        missing = [src for src in unique if src not in translations and src not in cache]
        self._log(f"Benzersiz: {_n(len(unique))} · Önbellekte: {_n(len(unique) - len(missing))} · Çevrilecek: {_n(len(missing))}")
        source = "en" if s["source"] == "auto" else s["source"]
        extra = self._extra_instruction() if extra is None else extra
        if missing:
            if model == "gemini":
                translate_with_gemini(missing, cache.data, cache_path, load_gemini_api_key(), log=self._log,
                                      progress=self._progress, target_lang=s["target"], source_lang=source,
                                      game_engine=game_engine, failed_out=failed, extra_instruction=extra)
            elif model in CLOUD_MODELS:
                prov.translate_with_cloud(model, missing, cache.data, cache_path, cfg, log=self._log,
                                          progress=self._progress, target_lang=s["target"], source_lang=source,
                                          game_engine=game_engine, failed_out=failed, extra_instruction=extra)
            else:
                if model == "ollama":
                    engine = OllamaTranslationEngine(model_name=cfg.ollama_model, host=cfg.ollama_host, cache=cache,
                                                     glossary=glossary, protected_pattern=pattern, log=self._log)
                else:
                    engine = TranslationEngine(
                        model_dir=prov.resolve_model_dir("model_nllb" if model == "nllb" else "model"),
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
            generate_templates, overlay_english_dialogue_sources, qa_translation,
            repair_safe_issues, repair_say_prefixes, restore_orphaned_translation_bytecode,
            translate_templates,
        )
        s, cfg = self._settings, prov.load_provider_config()
        info = analyze_game(game["root"], self._log)
        if s["backup"]:
            backup_translation(info, self._log)
        self._status("Çeviri şablonları oluşturuluyor…")
        tl_dir = generate_templates(info, self._log)
        restore_orphaned_translation_bytecode(info.game_dir, self._log)
        augment_ui_string_templates(info, tl_dir, self._log)
        overlay_english_dialogue_sources(tl_dir, info.game_dir / "tl" / "english", False, self._log)
        self._status(f"Çeviri sürüyor ({MODEL_LABELS[s['model']]})…")
        written = translate_templates(
            tl_dir=tl_dir,
            model_dir=prov.resolve_model_dir("model_nllb" if s["model"] == "nllb" else "model"),
            cache_path=self._cache_path(),
            glossary_path=self._glossary_path(),
            log=self._log,
            progress=self._progress,
            model_kind=s["model"],
            ollama_model=cfg.ollama_model,
            ollama_host=cfg.ollama_host,
            failed_out=failed,
            extra_instruction=self._extra_instruction(),
        )
        if s.get("quality_pass"):
            self._run_quality(tl_dir)
        enable_turkish(info, True, self._log)
        repair_say_prefixes(tl_dir, self._log)
        repair_safe_issues(tl_dir, self._log)
        qa = qa_translation(tl_dir)
        self._log(f"QA: {qa['checked']} hedef · etiket hatası {qa['token_errors']} · boş {qa['empty_errors']} · "
                  f"artık {qa['artifacts']}")
        return written

    def _translate_unity(self, game: Dict[str, Any], failed: set) -> int:
        from engine_unity import detect_unity_game, extract_texts_unity, translate_texts_unity, write_translations_unity
        from unity_bepinex import generate_bepinex_autotranslator_config, is_bepinex_installed, sync_cache_to_bepinex
        s, cfg = self._settings, prov.load_provider_config()
        info = game["info"] or detect_unity_game(game["root"])
        if s["backup"] and info.resources_assets_path:
            create_game_backup(info.root, "unity", [info.resources_assets_path], log=self._log)
        texts = game["texts"] if game["texts"] is not None else extract_texts_unity(info, self._log)
        unique = sorted({t.original for t in texts if t.original.strip()})
        translations = translate_texts_unity(
            unique_sources=unique,
            cache_path=self._cache_path(),
            target_lang=s["target"], source_lang=s["source"],
            glossary=self._glossary("glossary.json"),
            log=self._log, progress=self._progress, tracker=None,
            model_kind=s["model"],
            model_dir=prov.resolve_model_dir("model_nllb" if s["model"] == "nllb" else "model"),
            ollama_model=cfg.ollama_model, ollama_host=cfg.ollama_host, failed_out=failed,
            extra_instruction=self._extra_instruction(),
        )
        written = write_translations_unity(info, translations, texts, self._log) if texts else 0
        game["texts"] = None  # Varlıklar değişti; bir sonraki analizde yeniden okunur
        game["analysis"] = None

        if not texts or info.runtime == "IL2CPP":
            import bepinex_installer
            installed = is_bepinex_installed(info.root)
            question = (
                "Bu Unity oyununun metinleri dosyalarda açık değil (IL2CPP / paketli).\n\n"
                + ("Çevirileri oyun içinde göstermek için XUnity.AutoTranslator çeviri dosyaları yazılsın mı?"
                   if installed else
                   "Çevirilerin oyun içinde görünmesi için BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip "
                   "oyun klasörüne kurulsun ve çeviri dosyaları yazılsın mı?\n\nKurulum tek tıkla geri alınabilir.")
            )
            if self._ask("BepInEx köprüsü", question):
                if not installed:
                    self._status("BepInEx ve XUnity.AutoTranslator kuruluyor…")
                    bepinex_installer.install(info.root, runtime=info.runtime, log=self._log)
                written += sync_cache_to_bepinex(info.root, translations, target_lang=s["target"], log=self._log)
                generate_bepinex_autotranslator_config(info.root, target_lang=s["target"],
                                                       source_lang=s["source"], log=self._log)
            else:
                self._log("ℹ BepInEx köprüsü kullanıcı tercihiyle atlandı.")
        return written

    def _translate_unreal(self, game: Dict[str, Any], failed: set) -> int:
        from engine_unreal import detect_unreal_game, extract_texts_unreal, write_translations_unreal
        from unreal_modding import generate_ue4ss_translation_config, setup_unreal_mods_folder
        s = self._settings
        info = game["info"] or detect_unreal_game(game["root"])
        if not info.locres_files and info.pak_files:
            return self._translate_unreal_pak(game, info, failed)
        texts = game["texts"] if game["texts"] is not None else extract_texts_unreal(
            info, source_lang_code=s["source"], log=self._log)
        if not texts:
            raise UserError("Bu oyunda çevrilebilir .locres metni bulunamadı.")
        if s["backup"]:
            create_game_backup(info.root, "unreal", info.locres_files, log=self._log)
        unique = sorted({t.original for t in texts if t.original.strip()})
        translations = self._unreal_translate(unique, failed)
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
            model_kind=s["model"], model_dir=prov.resolve_model_dir("model_nllb" if s["model"] == "nllb" else "model"),
            ollama_model=cfg.ollama_model, ollama_host=cfg.ollama_host, failed_out=failed,
            extra_instruction=self._extra_instruction(),
        )

    def _unreal_pak_texts(self, game: Dict[str, Any], info: Any) -> Tuple[list, Path]:
        """Paketlerdeki kaynak dil .locres dosyalarını önbelleğe çıkarır ve metinleri okur."""
        import dataclasses
        import unreal_pak
        from engine_unreal import extract_texts_unreal
        key = self._project_glossary()["aes_key"]
        found = unreal_pak.find_localization(unreal_pak.game_paks(info.paks_dir), self._settings["source"], key, self._log)
        base = cache_file_for(Path(game["root"]), DATA_DIR)   # portable_cache/cache/<kimlik>.json
        staging = base.parent.parent / "unreal" / base.stem
        files = unreal_pak.extract(found, staging, key) if found else []
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
                             "Bu oyunun metinleri .pak paketlerinin içinde. Paketleri açabilmek için Capri, açık kaynak "
                             "repak aracını (github.com/trumank/repak, yaklaşık 2 MB) GitHub'dan indirip kendi tools "
                             "klasörüne kuracak. Oyun dosyalarına dokunulmaz; çeviri ayrı bir yama paketi olarak eklenir. "
                             "Devam edilsin mi?"):
                raise TranslationCancelled()
            self._status("repak indiriliyor…")
            unreal_pak.install_repak(log=self._log)
            self._notify("repak kuruldu", "Unreal paketleri artık açılabiliyor.", "ok", "download")
        try:
            texts, staging = self._unreal_pak_texts(game, info)
        except unreal_pak.NeedsAesKey:
            raise UserError("Bu oyunun paketleri AES ile şifreli. Oyunun AES anahtarını Sözlük → Bu oyun sekmesindeki "
                            "'AES anahtarı' alanına girip tekrar dene.")
        if not texts:
            raise UserError("Paketlerde kaynak dilde (.locres) metin bulunamadı.")
        unique = sorted({t.original for t in texts if t.original.strip()})
        translations = self._unreal_translate(unique, failed)
        files = sorted({t.locres_path for t in texts})
        written = write_translations_unreal(dataclasses.replace(info, locres_files=files), translations, texts,
                                            target_lang_code=self._settings["target"], create_lang_folder=False,
                                            log=self._log)
        if written:
            first = next(iter(game.get("pak_found") or {}), None)
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
        from engine_rpgmaker import (PROTECTED_RPGM, RGSS_EXT, detect_rpgmaker_game, write_translations_mv_mz,
                                     write_translations_vxace)
        info = game["info"] or detect_rpgmaker_game(game["root"])
        rgss = info.engine_type in RGSS_EXT
        if rgss and self._rgss_archive(info):
            info = self._rgss_unpack(game, info)
            game["texts"] = None
        if rgss and not self._rgss_loose(info):
            raise UserError(f"{info.version_label}: çevrilecek veri dosyası bulunamadı.")
        if self._settings["backup"]:
            pattern = f"*{RGSS_EXT[info.engine_type]}" if rgss else "*.json"
            create_game_backup(info.root, "rpgmaker", sorted(info.data_dir.glob(pattern)), log=self._log)
        texts = game["texts"] if game["texts"] is not None else self._rpgm_extract(info)
        unique = list(dict.fromkeys(t.original for t in texts if t.original.strip()))
        translations = self._translate_strings(unique, self._cache_path(), PROTECTED_RPGM,
                                               self._glossary("glossary_rpgm.json"), "RPG Maker Game", failed)
        game["texts"] = None
        game["analysis"] = None
        if rgss:
            return write_translations_vxace(info.data_dir, translations, self._log, engine_type=info.engine_type)
        return write_translations_mv_mz(info.data_dir, translations, self._log)

    # ── BepInEx (Unity) ──────────────────────────────────────────────────────
    def install_bepinex(self) -> bool:
        def task():
            import bepinex_installer
            game = self._require_game()
            if game["type"] != "unity":
                raise UserError("BepInEx yalnızca Unity oyunları içindir.")
            if bepinex_installer.is_installed(game["root"]):
                raise UserError("BepInEx bu oyunda zaten kurulu.")
            if not self._ask("BepInEx kurulumu", "BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip oyun klasörüne "
                             "kurulacak. Üzerine yazılan dosyalar yedeklenir ve kurulum tek tıkla kaldırılabilir."):
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
            if not self._ask("BepInEx'i kaldır", "Capri'nin kurduğu BepInEx ve XUnity.AutoTranslator dosyaları silinecek, "
                             "üzerine yazılan dosyalar geri yüklenecek."):
                return
            removed = bepinex_installer.uninstall(game["root"], log=self._log)
            game["analysis"] = None
            self._notify("BepInEx kaldırıldı", f"{_n(removed)} dosya silindi; oyun klasörü kurulum öncesi hâline döndü.",
                         "ok", "undo")

        return self._run_task("BepInEx kaldırma", task)

    # ── Kalite editörü (Ren'Py) ──────────────────────────────────────────────
    def _quality_provider(self) -> str:
        model = self._settings["model"]
        if model in prov.LLM_PROVIDERS:
            return model
        if prov.load_provider_config().gemini_keys:
            return "gemini"
        raise UserError("Kalite editörü bir sohbet modeli ister: Gemini, OpenAI, Claude veya Ollama seçin.")

    def _run_quality(self, tl_dir: Path) -> Dict[str, int]:
        from engine_renpy import quality_edit_with_llm
        provider = self._quality_provider()
        cfg = prov.load_provider_config()
        self._status(f"Kalite editörü çalışıyor ({MODEL_LABELS[provider]})…")
        result = quality_edit_with_llm(
            tl_dir, self._cache_path(), lambda system, user: prov.llm_complete(provider, system, user, cfg),
            log=self._log, progress=self._progress, extra_instruction=self._extra_instruction(),
        )
        self._notify("Kalite editörü tamamlandı",
                     f"{_n(result['candidates'])} sorunlu taslaktan {_n(result['edited'])} satır düzeltildi "
                     f"({MODEL_LABELS[provider]}).", "ok", "edit")
        return result

    def quality_pass(self) -> bool:
        """Mevcut Ren'Py çevirisinde yalnızca kalite editörünü çalıştırır."""
        def task():
            game = self._require_game()
            if game["type"] != "renpy":
                raise UserError("Kalite editörü şu an Ren'Py oyunları için.")
            from engine_renpy import analyze_game
            tl_dir = analyze_game(game["root"], self._log).game_dir / "tl" / "Turkish"
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

    def editor_load(self, model: str, query: str = "", only_review: bool = False,
                    offset: int = 0, limit: int = 80) -> Dict[str, Any]:
        path = self._cache_path(model)
        cache: Dict[str, str] = _read_json(path, {})
        review = set(_read_json(review_path_for(path), []))
        q = (query or "").casefold()
        items = []
        for src in list(cache) + [r for r in review if r not in cache]:
            tr = cache.get(src, "")
            flagged = src in review or (tr == src and bool(re.search(r"[A-Za-z]{3}", src))) \
                or (bool(tr) and not prov.placeholders_valid(src, tr))
            if only_review and not flagged:
                continue
            if q and q not in src.casefold() and q not in tr.casefold():
                continue
            items.append({"src": src, "tr": tr, "flag": flagged})
        return {"total": len(items), "items": items[offset:offset + limit], "offset": offset,
                "model": model, "label": MODEL_LABELS.get(model, model)}

    def editor_save(self, model: str, changes: Dict[str, str]) -> Dict[str, Any]:
        path = self._cache_path(model)
        cache: Dict[str, str] = _read_json(path, {})
        bad = [src for src, tr in changes.items() if tr and not prov.placeholders_valid(src, tr)]
        if bad:
            return {"ok": False, "msg": f"{len(bad)} satırda etiket/değişken eksik veya fazla: {bad[0][:60]}"}
        cache.update({src: tr for src, tr in changes.items() if tr})
        _write_json(path, cache)
        review_file = review_path_for(path)
        review = [r for r in _read_json(review_file, []) if r not in changes]
        if review:
            _write_json(review_file, review)
        elif review_file.exists():
            review_file.unlink()
        return {"ok": True, "msg": f"{len(changes)} satır kaydedildi."}

    def editor_apply(self, model: str) -> bool:
        """Önbellekteki (düzenlenmiş) çevirileri oyun dosyalarına yeniden yazar — API harcamaz."""
        def task():
            game = self._require_game()
            cache: Dict[str, str] = _read_json(self._cache_path(model), {})
            if not cache:
                raise UserError("Bu model için önbellekte çeviri yok.")
            written = getattr(self, f"_apply_{game['type']}")(game, cache)
            game["texts"] = None
            game["analysis"] = None
            self._status(f"Düzenlemeler uygulandı: {_n(written)} satır.", "ok")
            self._notify("Düzenlemeler oyuna uygulandı", f"{game['title']} · {_n(written)} satır güncellendi", "ok", "check")

        return self._run_task("Uygulama", task)

    def _apply_renpy(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_renpy import analyze_game, decode_literal, encode_literal, find_source_before, last_literal_match
        info = analyze_game(game["root"], self._log)
        tl_dir = info.game_dir / "tl" / "Turkish"
        if not tl_dir.is_dir():
            raise UserError("Oyunda Türkçe çeviri klasörü yok; önce çeviriyi başlatın.")
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
                tmp = path.with_suffix(path.suffix + ".tmp")
                with tmp.open("w", encoding="utf-8", newline="") as handle:
                    handle.writelines(lines)
                tmp.replace(path)
        return changed

    def _restore_originals(self, game: Dict[str, Any]) -> None:
        backups = [b for b in list_game_backups(Path(game["root"])) if b.engine == game["type"]]
        if not backups:
            raise UserError("Orijinal dosyaların yedeği yok. Düzenlemeleri uygulamak için 'Çeviriyi başlat' kullanın "
                            "(önbellekteki satırlar için API harcanmaz).")
        ok, _count, msg = restore_game_backup(backups[-1], Path(game["root"]), log=self._log)  # en eski = orijinal
        if not ok:
            raise RuntimeError(msg)

    def _apply_unity(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_unity import detect_unity_game, extract_texts_unity, write_translations_unity
        self._restore_originals(game)
        info = detect_unity_game(game["root"])
        return write_translations_unity(info, cache, extract_texts_unity(info, self._log), self._log)

    def _apply_rpgmaker(self, game: Dict[str, Any], cache: Dict[str, str]) -> int:
        from engine_rpgmaker import RGSS_EXT, detect_rpgmaker_game, write_translations_mv_mz, write_translations_vxace
        self._restore_originals(game)
        info = detect_rpgmaker_game(game["root"])
        if info.engine_type in RGSS_EXT:
            return write_translations_vxace(info.data_dir, cache, self._log, engine_type=info.engine_type)
        return write_translations_mv_mz(info.data_dir, cache, self._log)

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
            result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("JSON dosyası (*.json)",))
        return result[0] if result else None

    def json_translate(self, input_path: str, output_path: str = "") -> bool:
        def task():
            from engine_json import PROTECTED_JSON, apply_translations, collect_strings
            src = Path(input_path)
            if not src.exists():
                raise UserError("Giriş dosyası/klasörü bulunamadı.")
            self._check_model_ready(None)
            files = sorted(src.rglob("*.json")) if src.is_dir() else [src]
            out_root = Path(output_path) if output_path else (
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

    def import_patch(self) -> bool:
        import webview
        if not self._game:
            self._toast("Önce yamanın ait olduğu oyunu aç.", "warn")
            return False
        result = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                                 file_types=("Capri yaması (*.capripatch;*.omnipatch;*.zip)",)) if self._window else None
        if not result:
            return False
        try:
            with zipfile.ZipFile(result[0]) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                translations = json.loads(archive.read("translations.json"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self._notify("Yama okunamadı", "Dosya geçerli bir Capri yaması değil.", "error", "alert")
            return False
        if manifest.get("engine") != self._game["type"]:
            self._notify("Yama bu oyuna uymuyor",
                         f"Yama {ENGINE_LABELS.get(manifest.get('engine'), '?')} için, açık oyun {ENGINE_LABELS[self._game['type']]}.",
                         "error", "alert")
            return False
        cache_path = self._cache_path()
        cache = _read_json(cache_path, {})
        cache.update({str(k): str(v) for k, v in translations.items()})
        _write_json(cache_path, cache)
        self._notify("Yama içe aktarıldı",
                     f"{_n(len(translations))} satır ({manifest.get('title', '')}). 'Çeviriyi başlat' ile oyuna uygula — "
                     "bu satırlar için API harcanmaz.", "ok", "archive")
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
            nsfw_mode=bool(s["nsfw"]), log=self._log, max_tokens=4096,
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
            return True, self._ocr_cache[key], 0, True
        if model in TURKISH_ONLY_MODELS and target != "tr":
            return False, f"{MODEL_LABELS[model]} yalnızca Türkçeye çevirebilir.", 0, False
        ok, result, latency = prov.translate_single_text(text, model, target_lang=target, source_lang=source,
                                                         nsfw_mode=bool(self._settings["nsfw"]), log=self._log,
                                                         max_tokens=1024)
        if ok:
            self._ocr_cache[key] = result
            while len(self._ocr_cache) > 400:
                self._ocr_cache.popitem(last=False)
        return ok, result, latency, False

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
                               "error": "" if ok else translated, "engine": label, "meta": meta})
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
            "place": "over" if over else "below", "translation": "Alan izleniyor…", "state": "live", "meta": ""}))
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

            staged = updater.stage(info["asset"], info["latest"], log=self._log, progress=report)
            script = updater.write_apply_script(staged, pid=os.getpid())
            self._ui.emit("update_progress", {"installing": True})
            subprocess.Popen(["cmd", "/c", str(script)], cwd=str(APP_DIR),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
            time.sleep(1.5)
            self.win_close()

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

    # ── Sağlayıcılar ─────────────────────────────────────────────────────────
    def save_providers(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cfg = prov.load_provider_config()
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
        elif provider in ("opus", "nllb"):
            status = prov.get_offline_model_status(provider)
            ok = status["is_ready"]
            msg = f"Kurulu ({status['size_mb']} MB)" if ok else f"Eksik: {', '.join(status['missing_files'][:3])}"
        else:
            ok, msg = False, "Bilinmeyen sağlayıcı."
        return {"ok": ok, "msg": msg}

    # ── Yerel modeller ───────────────────────────────────────────────────────
    def model_status(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {k: prov.get_offline_model_status(k) for k in ("opus", "nllb")}
        data["runtime"] = {"ready": gpu_runtime.ready(), "missing": gpu_runtime.missing(),
                           "dir": str(gpu_runtime.SITE_DIR)}
        return data

    def _ensure_runtime(self) -> bool:
        """PyTorch ortamı yoksa kullanıcıya ne kurulacağını söyleyip onay ister ve kurar."""
        if gpu_runtime.ready():
            return True
        cuda = gpu_runtime.driver_cuda()
        size = gpu_runtime.estimate_mb(cuda)
        kind = (f"NVIDIA ekran kartın için CUDA destekli PyTorch" if cuda else "NVIDIA ekran kartı bulunamadığı için CPU sürümü PyTorch")
        if not self._ask("Yerel model ortamı kurulacak",
                         f"Yerel modeller (OPUS-MT, NLLB) PyTorch ve Transformers kütüphanelerine ihtiyaç duyar. Capri, {kind} "
                         f"ile birlikte bu kütüphaneleri resmi kaynaklardan (download.pytorch.org, pypi.org) indirip kendi "
                         f"klasörüne (runtime) kuracak. İndirme yaklaşık {_n(size)} MB; bir kez yapılır. Devam edilsin mi?"):
            return False
        self._status("Yerel model ortamı kuruluyor…")
        torch = gpu_runtime.install(log=self._log, progress=self._progress)
        self._notify("Yerel model ortamı kuruldu",
                     f"PyTorch {torch['version']} ({torch['variant']})" if torch else "Eksik kütüphaneler kuruldu.", "ok", "cpu")
        self._detect_gpu()
        return True

    def install_runtime(self) -> bool:
        def task():
            if gpu_runtime.ready():
                self._notify("Yerel model ortamı hazır", "PyTorch ve Transformers zaten kurulu.", "ok", "cpu")
            self._ensure_runtime()
            self._ui.emit("models", self.model_status())

        return self._run_task("Ortam kurulumu", task)

    def download_model(self, kind: str) -> bool:
        if kind not in ("opus", "nllb"):
            return False

        def task():
            if not self._ensure_runtime():
                return
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
            if not self._ask("Modeli küçült", f"{status['label']} fp16 biçimine dönüştürülecek: dosya boyutu yaklaşık "
                             "yarıya iner ve model daha hızlı yüklenir. Çeviri kalitesi pratikte değişmez.\n\n"
                             "Yeni model deneme çevirisiyle doğrulanır; eski dosya Geri Dönüşüm Kutusu'na taşınır."):
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
        root = Path(self._game["root"])
        items = []
        if rgss_archive.is_unpacked(root):
            manifest = _read_json(root / rgss_archive.MANIFEST, {})
            archive = root / rgss_archive.BACKUP_DIR / manifest.get("archive", "")
            items.append({"path": str(archive.parent), "engine": "Şifreli arşiv", "archive": manifest.get("archive", ""),
                          "date": time.strftime("%d.%m.%Y %H:%M", time.localtime((root / rgss_archive.MANIFEST).stat().st_mtime)),
                          "files": len(manifest.get("extracted", [])), "size": archive.stat().st_size if archive.exists() else 0,
                          "zip": False})
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
                             "Capri'nin açtığı dosyalar (çevrilmiş veri dosyaları dahil) silinecek ve orijinal arşiv "
                             "yerine konacak. Oyun ilk hâline döner. Devam edilsin mi?"):
                return
            removed = rgss_archive.restore(Path(game["root"]), log=self._log)
            game.update(info=None, texts=None, analysis=None)
            self._library.upsert(game["root"], status="restored")
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
                raise RuntimeError(msg)
            game["texts"] = None
            game["analysis"] = None
            self._library.upsert(game["root"], status="restored")
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
        self.ocr_pin_stop(silent=True)
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
    html_file = WEB_DIR / "index.html"
    import webview
    seed_user_files()
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

    webview.start(bridge._on_start, debug="--debug" in sys.argv, private_mode=False,
                  storage_path=str(DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
