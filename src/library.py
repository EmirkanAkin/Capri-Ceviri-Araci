"""
Capri — Proje Kütüphanesi ve Oyun Kapak Görselleri
======================================================
Çevrilen / analiz edilen oyunları `portable_cache/projects.json` içinde tutar ve
arayüz için kapak (poster) ve vitrin (hero) görsellerini bulur:

1. Steam AppID (steam_appid.txt, steam_emu.ini, appmanifest, mağaza araması)
2. Yerel Steam kütüphane önbelleği (appcache/librarycache)
3. Steam CDN (indirilen görseller portable_cache/art altında önbelleğe alınır)
4. Oyunun kendi görselleri (Ren'Py ana menü, RPG Maker başlık, Unreal splash)
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import APP_DIR
DATA_DIR = APP_DIR / "portable_cache"
PROJECTS_FILE = DATA_DIR / "projects.json"
ART_DIR = DATA_DIR / "art"

STEAM_CDN = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/{name}"
STEAM_ASSET_BASE = "https://shared.akamai.steamstatic.com/store_item_assets/"
STEAM_ITEMS_API = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
POSTER_SIZE = (360, 540)
HERO_MAX_WIDTH = 1600


# ═══════════════════════════════════════════════════════════════════════════════
# Proje kütüphanesi
# ═══════════════════════════════════════════════════════════════════════════════

class ProjectLibrary:
    """Basit, iş parçacığı güvenli JSON proje deposu (anahtar: oyun kök yolu)."""

    def __init__(self, path: Path = PROJECTS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._items: Dict[str, Dict[str, Any]] = {}
        self._load()

    @staticmethod
    def key(path: str | Path) -> str:
        return str(Path(path)).lower()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._items = {self.key(p["path"]): p for p in raw if isinstance(p, dict) and p.get("path")}
        except (OSError, ValueError):
            self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.list(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self._items.values(), key=lambda p: p.get("updated", 0), reverse=True)

    def get(self, path: str | Path) -> Optional[Dict[str, Any]]:
        return self._items.get(self.key(path))

    def upsert(self, path: str | Path, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            item = self._items.setdefault(self.key(path), {"path": str(path), "created": time.time()})
            item.update({k: v for k, v in fields.items() if v is not None})
            item["updated"] = time.time()
            self._save()
            return dict(item)

    def remove(self, path: str | Path) -> None:
        with self._lock:
            self._items.pop(self.key(path), None)
            self._save()


# ═══════════════════════════════════════════════════════════════════════════════
# Steam AppID tespiti
# ═══════════════════════════════════════════════════════════════════════════════

def _steam_root() -> Optional[Path]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            path = Path(value)
            return path if path.is_dir() else None
    except (OSError, ImportError):
        return None


def _steam_libraries(steam: Path) -> List[Path]:
    libs = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    try:
        for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
            lib = Path(match.group(1).replace("\\\\", "\\"))
            if lib.is_dir() and lib not in libs:
                libs.append(lib)
    except OSError:
        pass
    return libs


def _appid_from_files(root: Path) -> Optional[str]:
    """steam_appid.txt / steam_emu.ini gibi dosyalardan AppID okur (en fazla 3 seviye)."""
    patterns = ("steam_appid.txt", "steam_emu.ini", "cream_api.ini")
    queue = [(root, 0)]
    while queue:
        folder, depth = queue.pop(0)
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name.lower()
            if entry.is_file() and name in patterns:
                try:
                    text = entry.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                match = re.search(r"^\s*(\d{3,9})\s*$", text, re.M) if name.endswith(".txt") else \
                    re.search(r"^\s*appid\s*=\s*(\d{3,9})", text, re.M | re.I)
                if match:
                    return match.group(1)
            elif entry.is_dir() and depth < 3 and not name.startswith((".", "_capri", "_omnitrans", "_turkish")):
                queue.append((entry, depth + 1))
    return None


def _appid_from_manifest(root: Path, steam: Optional[Path]) -> Optional[str]:
    if not steam:
        return None
    for lib in _steam_libraries(steam):
        common = lib / "steamapps" / "common"
        try:
            rel = root.resolve().relative_to(common.resolve())
        except (ValueError, OSError):
            continue
        installdir = rel.parts[0].lower() if rel.parts else ""
        for manifest in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = re.search(r'"installdir"\s+"([^"]+)"', text)
            if m and m.group(1).lower() == installdir:
                return manifest.stem.split("_", 1)[1]
    return None


def _normalize_title(title: str) -> str:
    title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", re.sub(r"[._]+", " ", title))
    title = re.sub(r"(?i)\b(season|s)\s*\d+\b|\bv?\d+(\.\d+)+\w*\b|\b(repack|build|final|pc|win64|igg)\b", " ", title)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", title)).strip().lower()


def _appid_from_store(title: str) -> Optional[str]:
    """Steam mağaza aramasıyla AppID bulur; ad benzerliği düşükse kabul etmez."""
    query = _normalize_title(title)
    if len(query) < 3:
        return None
    url = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode(
        {"term": query, "cc": "us", "l": "english"}
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Capri"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            items = json.loads(resp.read().decode("utf-8")).get("items", [])
    except Exception:
        return None
    best, best_ratio = None, 0.0
    for item in items[:8]:
        ratio = difflib.SequenceMatcher(None, query, _normalize_title(item.get("name", ""))).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return str(best["id"]) if best and best_ratio >= 0.72 else None


# ═══════════════════════════════════════════════════════════════════════════════
# Görsel kaynakları
# ═══════════════════════════════════════════════════════════════════════════════

def _steam_cache_images(steam: Optional[Path], appid: str) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    if not steam:
        return found
    cache = steam / "appcache" / "librarycache"
    names = {"poster": "library_600x900.jpg", "hero": "library_hero.jpg", "header": "header.jpg"}
    for kind, name in names.items():
        for candidate in (cache / f"{appid}_{name}", cache / appid / name):
            if candidate.is_file():
                found[kind] = candidate
                break
        else:
            folder = cache / appid
            if folder.is_dir():
                hit = next(folder.rglob(name), None)
                if hit:
                    found[kind] = hit
    return found


def _steam_store_item(appid: str) -> Dict[str, Any]:
    """Steam StoreBrowse API'sinden oyun adı ve görsel URL'lerini alır (sonuç önbelleklenir)."""
    meta_file = ART_DIR / f"steam_{appid}.json"
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    payload = {
        "ids": [{"appid": int(appid)}],
        "context": {"language": "english", "country_code": "US"},
        "data_request": {"include_assets": True},
    }
    url = STEAM_ITEMS_API + "?" + urllib.parse.urlencode({"input_json": json.dumps(payload)})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Capri"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            item = json.loads(resp.read().decode("utf-8"))["response"]["store_items"][0]
    except Exception:
        return {}
    assets = item.get("assets") or {}
    fmt = assets.get("asset_url_format", "")
    def asset(key: str) -> Optional[str]:
        return STEAM_ASSET_BASE + fmt.replace("${FILENAME}", assets[key]) if fmt and assets.get(key) else None
    meta = {
        "name": item.get("name"),
        "poster": asset("library_capsule_2x") or asset("library_capsule"),
        "hero": asset("library_hero") or asset("page_background"),
        "header": asset("header"),
    }
    if item.get("success") == 1:
        ART_DIR.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def _download(url: str, target: Path) -> Optional[Path]:
    if target.is_file() and target.stat().st_size > 0:
        return target
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Capri"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) < 2048:
            return None
        ART_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target
    except Exception:
        return None


def _local_game_images(root: Path, engine: str) -> Dict[str, Path]:
    """Oyunun kendi dosyalarından vitrin görseli adayı bulur."""
    candidates: List[Path] = []
    if engine == "renpy":
        for game_dir in (root / "game", root):
            candidates += [game_dir / "gui" / "main_menu.png", game_dir / "gui" / "main_menu.jpg",
                           game_dir / "gui" / "game_menu.png"]
    elif engine == "rpgmaker":
        for base in (root / "www" / "img" / "titles1", root / "img" / "titles1"):
            if base.is_dir():
                candidates += sorted(base.glob("*.png"))[:3]
    elif engine == "unreal":
        for project in [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []:
            candidates += [project / "Content" / "Splash" / "Splash.bmp", project / "Content" / "Splash" / "EdSplash.bmp"]
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 4096:
                return {"hero": path}
        except OSError:
            continue
    return {}


def _to_data_uri(path: Path, kind: str) -> Optional[str]:
    """Görseli küçültüp JPEG data URI olarak döndürür (sonuç diskte önbelleklenir)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    digest = hashlib.sha1(f"{path}|{stat.st_size}|{stat.st_mtime}|{kind}".encode("utf-8")).hexdigest()[:16]
    cached = ART_DIR / f"r_{digest}.jpg"
    if not cached.is_file():
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as img:
                img = img.convert("RGB")
                if kind == "poster":
                    img = ImageOps.fit(img, POSTER_SIZE, Image.LANCZOS)
                elif img.width > HERO_MAX_WIDTH:
                    img = img.resize((HERO_MAX_WIDTH, int(img.height * HERO_MAX_WIDTH / img.width)), Image.LANCZOS)
                buffer = io.BytesIO()
                img.save(buffer, "JPEG", quality=84, optimize=True)
            ART_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(buffer.getvalue())
        except Exception:
            # Pillow yoksa veya görsel okunamıyorsa: JPEG/PNG'yi olduğu gibi gönder
            if path.suffix.lower() not in (".jpg", ".jpeg", ".png") or stat.st_size > 3_000_000:
                return None
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/jpeg;base64," + base64.b64encode(cached.read_bytes()).decode("ascii")


def resolve_art(root: str | Path, engine: str, title: str, appid: Optional[str] = None,
                online: bool = True) -> Dict[str, Any]:
    """Oyun için {appid, poster, hero} döndürür; görseller data URI ya da None."""
    root = Path(root)
    steam = _steam_root()
    appid = appid or _appid_from_files(root) or _appid_from_manifest(root, steam)
    if not appid and online:
        appid = _appid_from_store(title)

    images: Dict[str, Path] = {}
    steam_name: Optional[str] = None
    if appid:
        images = _steam_cache_images(steam, appid)
        if online:
            meta = _steam_store_item(appid)
            steam_name = meta.get("name")
            legacy = {"poster": "library_600x900.jpg", "hero": "library_hero.jpg", "header": "header.jpg"}
            for kind in ("poster", "hero", "header"):
                if kind in images:
                    continue
                url = meta.get(kind) or STEAM_CDN.format(appid=appid, name=legacy[kind])
                downloaded = _download(url, ART_DIR / f"steam_{appid}_{kind}.jpg")
                if downloaded:
                    images[kind] = downloaded
        if "hero" not in images and "header" in images:
            images["hero"] = images["header"]
    for kind, path in _local_game_images(root, engine).items():
        images.setdefault(kind, path)
    if "poster" not in images and "hero" in images:
        images["poster"] = images["hero"]

    return {
        "appid": appid,
        "name": steam_name,
        "poster": _to_data_uri(images["poster"], "poster") if "poster" in images else None,
        "hero": _to_data_uri(images["hero"], "hero") if "hero" in images else None,
    }
