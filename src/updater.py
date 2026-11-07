"""
Capri — Güncelleme denetimi ve uygulama
===========================================
Sürümlerin yayımlandığı GitHub deposu derleme sırasında exe'ye yazılır (build_info.json; kaynak
koddan çalışırken .git/config'teki origin adresinden okunur). Kullanıcı yalnızca "kontrol et"e basar.
Güncelleme, sürümün .zip paketi indirilip ara klasöre açılarak hazırlanır; uygulama kapandıktan
sonra çalışan küçük bir betik dosyaları kopyalar ve uygulamayı yeniden başlatır.
Kullanıcı verileri (portable_cache, modeller, ayarlar, API anahtarları) asla üzerine yazılmaz.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from paths import APP_DIR, FROZEN, RES_DIR
STAGING_DIR = APP_DIR / "portable_cache" / "update"
# CAPRI_UPDATE_API: test sunucusu ya da kurum içi ayna için adres şablonu ({repo} yer tutucusuyla)
API = os.environ.get("CAPRI_UPDATE_API") or "https://api.github.com/repos/{repo}/releases/latest"
BUILD_INFO = RES_DIR / "build_info.json"
# Güncelleme paketinin asla dokunmayacağı yollar (kullanıcı verisi)
PROTECTED = ("portable_cache", "model", "model_nllb", "runtime", "tools", "data", "config_providers.json", "gemini_api_key.txt",
             "glossary.json", "glossary_rpgm.json", "glossary_nsfw.json", "terms.json")
LogFn = Callable[[str], None]


def parse_version(text: str) -> Tuple[int, ...]:
    numbers = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in numbers[:4]) or (0,)


def repo_from_git(root: Path) -> str:
    """.git/config içindeki origin adresinden "kullanici/depo" çıkarır (yalnızca GitHub)."""
    try:
        text = (Path(root) / ".git" / "config").read_text(encoding="utf-8")
    except OSError:
        return ""
    block = re.search(r'\[remote "origin"\][^\[]*', text)
    match = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?\s*$", block.group(0), re.MULTILINE) if block else None
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def default_repo() -> str:
    """Güncelleme deposu: exe'ye gömülü bilgi, yoksa (kaynak kodda) git origin adresi."""
    try:
        repo = json.loads(BUILD_INFO.read_text(encoding="utf-8")).get("repo", "")
        if repo:
            return repo
    except (OSError, ValueError):
        pass
    return "" if FROZEN else repo_from_git(APP_DIR)


def clean_notes(body: str, limit: int = 12) -> List[str]:
    """Sürüm açıklamasını düz madde listesine çevirir: başlıklar atılır, Markdown işaretleri temizlenir."""
    items: List[str] = []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ">", "```")):
            continue
        is_item = line.startswith(("- ", "* "))
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line.lstrip("-* ").strip())
        line = line.replace("**", "").replace("`", "").strip()
        if not line:
            continue
        if not is_item and items and raw[:1].isspace():    # alt satıra taşan madde
            items[-1] += " " + line
        else:
            items.append(line)
    return items[:limit]


def check(current: str, repo: str, timeout: float = 10) -> Dict[str, Any]:
    """{'available', 'latest', 'url', 'notes', 'asset'} döndürür."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        return {"available": False, "error": "Geçerli bir GitHub deposu girin (kullanici/depo)."}
    resp = requests.get(API.format(repo=repo), timeout=timeout,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
    if resp.status_code == 404:
        return {"available": False, "error": "Henüz yayımlanmış bir sürüm yok."}
    resp.raise_for_status()
    rel = resp.json()
    tag = rel.get("tag_name", "")
    zips = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")]
    asset = next((a for a in zips if "win" in a["name"].lower()), zips[0] if zips else None)
    return {
        "available": parse_version(tag) > parse_version(current),
        "latest": tag.lstrip("v"),
        "url": rel.get("html_url", ""),
        "notes": clean_notes(rel.get("body") or ""),
        "asset": asset["browser_download_url"] if asset else "",
        "asset_name": asset["name"] if asset else "",
        "asset_size": int(asset.get("size") or 0) if asset else 0,
        "published": (rel.get("published_at") or "")[:10],
    }


def _protected(rel: Path) -> bool:
    return bool(rel.parts) and rel.parts[0] in PROTECTED


def stage(asset_url: str, version: str, log: LogFn = print,
          progress: Optional[Callable[[int, int], None]] = None) -> Path:
    """Sürüm paketini indirir ve ara klasöre açar; paketteki tek üst klasörü otomatik soyar."""
    target = STAGING_DIR / version
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = STAGING_DIR / f"{version}.zip"
    log(f"Güncelleme indiriliyor: {asset_url}")
    with requests.get(asset_url, stream=True, timeout=120, headers={"User-Agent": "Capri"}) as resp:
        resp.raise_for_status()
        total, done = int(resp.headers.get("content-length") or 0), 0
        with archive.open("wb") as out:
            for chunk in resp.iter_content(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) == 1 and all("/" in n for n in names):
            prefix = tops.pop() + "/"
        root = target.resolve()
        for name in names:
            rel = Path(name[len(prefix):])
            dest = (root / rel).resolve()
            if root not in dest.parents or _protected(rel):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
    archive.unlink(missing_ok=True)
    if not any(target.glob("*.exe")) and not (target / "src" / "app_modern.py").exists():
        raise RuntimeError("İndirilen paket bir Capri sürümü gibi görünmüyor.")
    log(f"Güncelleme hazır: {target}")
    return target


def launch_command(app_dir: Path = APP_DIR) -> str:
    """Güncelleme sonrası uygulamayı yeniden açan komut (exe veya kaynak kod)."""
    if FROZEN:
        return f'start "" /D "{app_dir}" "{app_dir / Path(sys.executable).name}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'start "" /D "{app_dir}" "{pythonw if pythonw.exists() else sys.executable}" "{app_dir / "Capri.pyw"}"'


def write_apply_script(staged: Path, app_dir: Path = APP_DIR, pid: Optional[int] = None) -> Path:
    """Uygulama kapandıktan sonra dosyaları kopyalayıp yeniden başlatan betik (kullanıcı verisi hariç)."""
    excludes = " ".join(f'"{name}"' for name in PROTECTED)
    script = staged.parent / "apply_update.bat"
    wait = f'''
:bekle
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto bekle)''' if pid else "timeout /t 2 /nobreak >nul"
    script.write_text(f'''@echo off
chcp 65001 >nul
{wait}
robocopy "{staged}" "{app_dir}" /E /XD {excludes} /XF {excludes} /NFL /NDL /NJH /NJS >nul
{launch_command(app_dir)}
''', encoding="utf-8")
    return script
