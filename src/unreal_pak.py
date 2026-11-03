"""
Capri — Unreal Engine .pak desteği (repak)
==========================================
Metinleri .pak içinde duran oyunlar için açık kaynak `repak` aracı (github.com/trumank/repak)
kullanılır. Araç uygulamayla gelmez: ilk gerektiğinde kullanıcıya sorulup GitHub'dan indirilir ve
`tools/repak/` altına kurulur.

Akış: paketlerdeki .locres dosyaları önbelleğe çıkarılır → çevrilir → `Paks/~mods/` altına
`zzz_Capri_<dil>_P.pak` yama paketi olarak paketlenir. Oyunun kendi dosyalarına dokunulmaz;
yamayı kaldırmak için bu tek dosyayı silmek yeter.
UE5 IoStore oyunlarında da .locres dosyaları genellikle klasik .pak içinde durur.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from paths import APP_DIR

TOOLS_DIR = APP_DIR / "tools" / "repak"
REPAK_REPO = "trumank/repak"
ASSET_SUFFIX = "x86_64-pc-windows-msvc.zip"
MOD_PREFIX = "zzz_Capri_"
MANIFEST = "_capri_backups/unreal_pak.json"
LogFn = Callable[[str], None]


class NeedsAesKey(RuntimeError):
    """Paket AES ile şifreli ve anahtar verilmemiş / yanlış."""


def repak_path() -> Optional[Path]:
    exe = TOOLS_DIR / "repak.exe"
    return exe if exe.exists() else None


def latest_asset(timeout: float = 15) -> Dict[str, object]:
    resp = requests.get(f"https://api.github.com/repos/{REPAK_REPO}/releases/latest", timeout=timeout,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
    resp.raise_for_status()
    rel = resp.json()
    asset = next((a for a in rel.get("assets", []) if a["name"].endswith(ASSET_SUFFIX)), None)
    if not asset:
        raise RuntimeError("repak sürümünde Windows paketi bulunamadı.")
    return {"version": rel.get("tag_name", ""), "url": asset["browser_download_url"], "size": asset.get("size", 0)}


def install_repak(log: LogFn = print) -> Path:
    """repak'ı GitHub'dan indirip tools/repak/ altına kurar (yalnızca repak.exe çıkarılır)."""
    asset = latest_asset()
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    archive = TOOLS_DIR / "repak.zip"
    log(f"repak {asset['version']} indiriliyor…")
    with requests.get(str(asset["url"]), stream=True, timeout=60, headers={"User-Agent": "Capri"}) as resp:
        resp.raise_for_status()
        with archive.open("wb") as out:
            for chunk in resp.iter_content(1 << 16):
                out.write(chunk)
    with zipfile.ZipFile(archive) as zf:
        member = next((n for n in zf.namelist() if n.lower().endswith("repak.exe")), None)
        if not member:
            raise RuntimeError("İndirilen pakette repak.exe yok.")
        with zf.open(member) as src, (TOOLS_DIR / "repak.exe").open("wb") as out:
            shutil.copyfileobj(src, out)
    archive.unlink(missing_ok=True)
    (TOOLS_DIR / "VERSION.txt").write_text(str(asset["version"]), encoding="utf-8")
    log(f"repak kuruldu: {TOOLS_DIR / 'repak.exe'}")
    return TOOLS_DIR / "repak.exe"


def run(args: List[str], aes_key: str = "", timeout: float = 600) -> str:
    exe = repak_path()
    if not exe:
        raise FileNotFoundError("repak kurulu değil.")
    cmd = [str(exe)] + (["--aes-key", aes_key] if aes_key else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        if re.search(r"aes|encrypt|decrypt", message, re.IGNORECASE):
            raise NeedsAesKey(message)
        raise RuntimeError(f"repak hatası: {message[-400:]}")
    return proc.stdout


def pak_info(pak: Path, aes_key: str = "") -> Dict[str, str]:
    out = run(["info", str(pak)], aes_key)
    return {k.strip(): v.strip() for k, v in (line.split(":", 1) for line in out.splitlines() if ":" in line)}


def list_files(pak: Path, aes_key: str = "") -> List[str]:
    return [line.strip() for line in run(["list", str(pak)], aes_key).splitlines() if line.strip()]


def is_mod_pak(pak: Path) -> bool:
    return pak.name.startswith(MOD_PREFIX)


def game_paks(paks_dir: Path) -> List[Path]:
    return sorted(p for p in Path(paks_dir).rglob("*.pak") if not is_mod_pak(p))


def find_localization(paks: List[Path], source_lang: str, aes_key: str = "", log: LogFn = print) -> Dict[Path, List[str]]:
    """{pak: [kaynak dildeki .locres yolları]} — en yüksek öncelikli (sonradan yüklenen) paket kazanır."""
    found: Dict[Path, List[str]] = {}
    owner: Dict[str, Path] = {}
    encrypted = []
    for pak in paks:
        try:
            files = list_files(pak, aes_key)
        except NeedsAesKey:
            encrypted.append(pak.name)
            continue
        for path in files:
            parts = path.lower().split("/")
            if path.lower().endswith(".locres") and "localization" in parts and len(parts) >= 2 \
                    and parts[-2] in (source_lang.lower(), source_lang.lower().split("-")[0]):
                owner[path] = pak                       # sonraki paket öncekini ezer (yama paketleri)
    for path, pak in owner.items():
        found.setdefault(pak, []).append(path)
    if encrypted and not found:
        raise NeedsAesKey(", ".join(encrypted[:3]))
    return found


def extract(found: Dict[Path, List[str]], out_dir: Path, aes_key: str = "") -> List[Path]:
    """Seçilen .locres dosyalarını out_dir altına (paket içi yollarıyla) çıkarır."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for pak, paths in found.items():
        args = ["unpack", str(pak), "--output", str(out_dir), "--quiet", "--force"]
        for path in paths:
            args += ["--include", re.sub(r"([\[\]?*])", r"[\1]", path)]
        run(args, aes_key)
    return sorted(out_dir.rglob("*.locres"))


def pack_mod(staging: Path, paks_dir: Path, target_lang: str, version: str = "V11", log: LogFn = print) -> Path:
    """Çevrilmiş dosyaları Paks/~mods/zzz_Capri_<dil>_P.pak olarak paketler."""
    mods = Path(paks_dir) / "~mods"
    mods.mkdir(exist_ok=True)
    target = mods / f"{MOD_PREFIX}{target_lang.upper()}_P.pak"
    run(["pack", str(staging), str(target), "--mount-point", "../../../", "--version", version or "V11", "--quiet"])
    log(f"Yama paketi oluşturuldu: {target}")
    return target


def write_manifest(game_root: Path, pak: Path, files: List[str]) -> None:
    path = Path(game_root) / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pak": str(Path(pak).relative_to(game_root)), "files": files}, indent=1,
                               ensure_ascii=False), encoding="utf-8")


def remove_mod(game_root: Path, log: LogFn = print) -> bool:
    path = Path(game_root) / MANIFEST
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    pak = Path(game_root) / data["pak"]
    if pak.exists():
        pak.unlink()
        log(f"Yama paketi kaldırıldı: {pak.name}")
    path.unlink()
    return True
