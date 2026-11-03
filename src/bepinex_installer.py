"""
Capri — BepInEx + XUnity.AutoTranslator otomatik kurulumu
=============================================================
Metinleri dosyada açık olmayan (IL2CPP / paketli) Unity oyunlarında çevirinin oyun içinde
görünmesi için gereken eklentileri GitHub sürümlerinden indirip oyun klasörüne kurar.

- Mono   → BepInEx 5 (BepInEx_win_<arch>_5.x) + XUnity.AutoTranslator-BepInEx
- IL2CPP → BepInEx 6 (BepInEx-Unity.IL2CPP-win-<arch>-6.x) + XUnity.AutoTranslator-BepInEx-IL2CPP

Kurulan her dosya `_capri_backups/bepinex_install.json` manifestine yazılır; üzerine yazılan
dosyalar önce yedeklenir. `uninstall()` her şeyi kurulum öncesi hâline döndürür.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from unity_bepinex import detect_unity_architecture

from paths import APP_DIR
DOWNLOAD_DIR = APP_DIR / "portable_cache" / "downloads"
GITHUB_API = "https://api.github.com/repos/{repo}/releases"
MANIFEST = "_capri_backups/bepinex_install.json"
LEGACY_MANIFEST = "_omnitrans_backups/bepinex_install.json"
LogFn = Callable[[str], None]


def _releases(repo: str) -> List[Dict[str, Any]]:
    resp = requests.get(GITHUB_API.format(repo=repo), params={"per_page": 20}, timeout=15,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
    resp.raise_for_status()
    return resp.json()


def choose_assets(runtime: str, arch: str) -> Dict[str, Tuple[str, str, str]]:
    """{'bepinex': (ad, url, sürüm), 'xunity': (...)} — oyunun çalışma zamanına ve mimarisine uygun paketler."""
    il2cpp = runtime.upper() == "IL2CPP"
    if il2cpp:
        pattern = re.compile(rf"^BepInEx-Unity\.IL2CPP-win-{arch}-6.*\.zip$", re.I)
        xpattern = re.compile(r"^XUnity\.AutoTranslator-BepInEx-IL2CPP-[\d.]+\.zip$", re.I)
    else:
        pattern = re.compile(rf"^BepInEx_win_{arch}_5[\d.]*\.zip$", re.I)
        xpattern = re.compile(r"^XUnity\.AutoTranslator-BepInEx-[\d.]+\.zip$", re.I)
    chosen: Dict[str, Tuple[str, str, str]] = {}
    for key, repo, regex in (("bepinex", "BepInEx/BepInEx", pattern), ("xunity", "bbepis/XUnity.AutoTranslator", xpattern)):
        for rel in _releases(repo):
            if rel.get("draft") or (rel.get("prerelease") and not (il2cpp and key == "bepinex")):
                continue
            asset = next((a for a in rel.get("assets", []) if regex.match(a["name"])), None)
            if asset:
                chosen[key] = (asset["name"], asset["browser_download_url"], rel["tag_name"])
                break
        if key not in chosen:
            raise RuntimeError(f"{repo} için uygun paket bulunamadı ({runtime}, {arch}).")
    return chosen


def _download(name: str, url: str, log: LogFn) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_DIR / name
    if target.is_file() and zipfile.is_zipfile(target):
        return target
    log(f"İndiriliyor: {name}")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Capri"}) as resp:
        resp.raise_for_status()
        part = target.with_suffix(".part")
        with part.open("wb") as out:
            for chunk in resp.iter_content(1 << 16):
                out.write(chunk)
    part.replace(target)
    if not zipfile.is_zipfile(target):
        target.unlink(missing_ok=True)
        raise RuntimeError(f"{name} geçerli bir zip değil.")
    return target


def is_installed(game_root: Path) -> bool:
    root = Path(game_root)
    return (root / "BepInEx").is_dir() and ((root / "winhttp.dll").exists() or (root / "doorstop_config.ini").exists())


def install(game_root: Path, runtime: Optional[str] = None, arch: Optional[str] = None,
            log: LogFn = print) -> Dict[str, Any]:
    root = Path(game_root).resolve()
    detected_arch, detected_runtime = detect_unity_architecture(root)
    runtime, arch = runtime or detected_runtime, arch or detected_arch
    assets = choose_assets(runtime, arch)
    log(f"BepInEx kurulumu: {runtime} · {arch} · BepInEx {assets['bepinex'][2]} · XUnity {assets['xunity'][2]}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "_capri_backups" / f"bepinex_replaced_{stamp}"
    created: List[str] = []
    replaced: List[str] = []
    for key in ("bepinex", "xunity"):
        name, url, _tag = assets[key]
        archive = _download(name, url, log)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                rel = member.filename.replace("\\", "/")
                dest = (root / rel).resolve()
                if root not in dest.parents:
                    log(f"Atlandı (güvensiz yol): {rel}")
                    continue
                if dest.exists():
                    if rel not in created:
                        backup = backup_dir / rel
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(dest, backup)
                        replaced.append(rel)
                else:
                    created.append(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
    manifest = {"runtime": runtime, "arch": arch, "created": created, "replaced": replaced,
                "backup_dir": str(backup_dir.relative_to(root)) if replaced else "", "time": stamp,
                "versions": {k: v[2] for k, v in assets.items()}}
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"BepInEx kuruldu: {len(created)} yeni dosya, {len(replaced)} dosya yedeklenip güncellendi.")
    return manifest


def manifest_file(game_root: Path):
    """Kurulum manifesti (eski OmniTrans sürümlerinin yazdığı konum da tanınır); yoksa None."""
    for rel in (MANIFEST, LEGACY_MANIFEST):
        if (Path(game_root) / rel).exists():
            return Path(game_root) / rel
    return None


def uninstall(game_root: Path, log: LogFn = print) -> int:
    """Manifestteki dosyaları siler, üzerine yazılanları geri yükler, boş kalan klasörleri temizler."""
    root = Path(game_root).resolve()
    manifest_path = manifest_file(root)
    if not manifest_path:
        raise RuntimeError("Bu oyunda Capri ile yapılmış bir BepInEx kurulumu bulunamadı.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = 0
    for rel in manifest.get("created", []):
        path = root / rel
        if path.is_file():
            path.unlink()
            removed += 1
    backup_dir = root / manifest["backup_dir"] if manifest.get("backup_dir") else None
    for rel in manifest.get("replaced", []):
        if backup_dir and (backup_dir / rel).is_file():
            shutil.copy2(backup_dir / rel, root / rel)
    dirs = sorted({(root / rel).parent for rel in manifest.get("created", [])}, key=lambda p: len(p.parts), reverse=True)
    for folder in dirs:
        while folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    manifest_path.unlink()
    log(f"BepInEx kaldırıldı: {removed} dosya silindi, {len(manifest.get('replaced', []))} dosya geri yüklendi.")
    return removed
