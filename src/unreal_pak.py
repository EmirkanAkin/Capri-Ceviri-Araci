"""
Capri — Unreal Engine .pak desteği (repak)
==========================================
Metinleri .pak içinde duran oyunlar için açık kaynak `repak` aracı (github.com/trumank/repak)
kullanılır. Araç uygulamayla gelmez: ilk gerektiğinde kullanıcıya sorulup GitHub'dan indirilir ve
`tools/repak/` altına kurulur.

Akış: paketlerdeki .locres dosyaları önbelleğe çıkarılır → çevrilir → `Paks/~mods/` altına
`zzz_Capri_<dil>_P.pak` yama paketi olarak paketlenir. Oyunun kendi dosyalarına dokunulmaz;
yamayı kaldırmak için bu tek dosyayı silmek yeter.
UE5 IoStore oyunlarında da .locres dosyaları genellikle klasik .pak içinde durur; orada yoksa .utoc
kapsayıcıları `retoc` (github.com/trumank/retoc) ile aranır. Yama yine klasik .pak olarak paketlenir.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from paths import APP_DIR

TOOLS_DIR = APP_DIR / "tools" / "repak"
RETOC_DIR = APP_DIR / "tools" / "retoc"
RETOC_REPO = "trumank/retoc"
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


def retoc_path() -> Optional[Path]:
    exe = RETOC_DIR / "retoc.exe"
    return exe if exe.exists() else None


def latest_asset(timeout: float = 15, repo: str = REPAK_REPO) -> Dict[str, object]:
    resp = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=timeout,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "Capri"})
    resp.raise_for_status()
    rel = resp.json()
    asset = next((a for a in rel.get("assets", []) if a["name"].endswith(ASSET_SUFFIX)), None)
    if not asset:
        raise RuntimeError(f"{repo} sürümünde Windows paketi bulunamadı.")
    return {"version": rel.get("tag_name", ""), "url": asset["browser_download_url"], "size": asset.get("size", 0)}


def install_repak(log: LogFn = print) -> Path:
    """repak'ı GitHub'dan indirip tools/repak/ altına kurar (yalnızca repak.exe çıkarılır)."""
    return _install_tool("repak", REPAK_REPO, TOOLS_DIR, log)


def install_retoc(log: LogFn = print) -> Path:
    """retoc'u GitHub'dan indirip tools/retoc/ altına kurar (yalnızca retoc.exe çıkarılır)."""
    return _install_tool("retoc", RETOC_REPO, RETOC_DIR, log)


def _install_tool(tool: str, repo: str, folder: Path, log: LogFn) -> Path:
    asset = latest_asset(repo=repo)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{tool}.zip"
    log(f"{tool} {asset['version']} indiriliyor…")
    with requests.get(str(asset["url"]), stream=True, timeout=60, headers={"User-Agent": "Capri"}) as resp:
        resp.raise_for_status()
        with archive.open("wb") as out:
            for chunk in resp.iter_content(1 << 16):
                out.write(chunk)
    with zipfile.ZipFile(archive) as zf:
        member = next((n for n in zf.namelist() if n.lower().endswith(f"{tool}.exe")), None)
        if not member:
            raise RuntimeError(f"İndirilen pakette {tool}.exe yok.")
        with zf.open(member) as src, (folder / f"{tool}.exe").open("wb") as out:
            shutil.copyfileobj(src, out)
    archive.unlink(missing_ok=True)
    (folder / "VERSION.txt").write_text(str(asset["version"]), encoding="utf-8")
    log(f"{tool} kuruldu: {folder / f'{tool}.exe'}")
    return folder / f"{tool}.exe"


def run(args: List[str], aes_key: str = "", timeout: float = 600) -> str:
    exe = repak_path()
    if not exe:
        raise FileNotFoundError("repak kurulu değil.")
    return _execute(exe, args, aes_key, timeout)


def run_retoc(args: List[str], aes_key: str = "", timeout: float = 600) -> str:
    exe = retoc_path()
    if not exe:
        raise FileNotFoundError("retoc kurulu değil.")
    return _execute(exe, args, aes_key, timeout)


def _execute(exe: Path, args: List[str], aes_key: str, timeout: float) -> str:
    cmd = [str(exe)] + (["--aes-key", aes_key] if aes_key else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        if re.search(r"aes|encrypt|decrypt", message, re.IGNORECASE):
            raise NeedsAesKey(message)
        raise RuntimeError(f"{exe.stem} hatası: {message[-400:]}")
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


# retoc list --path: <kapsayıcı> <24 hane parça kimliği> <tür> <yol>
RETOC_LINE = re.compile(r"\b([0-9a-fA-F]{24})\s+\S+\s+(.+?)\s*$")


def _is_source_locres(path: str, source_lang: str) -> bool:
    parts = path.lower().split("/")
    return path.lower().endswith(".locres") and "localization" in parts and len(parts) >= 2 \
        and parts[-2] in (source_lang.lower(), source_lang.lower().split("-")[0])


def find_iostore_localization(paks_dir: Path, source_lang: str, aes_key: str = "") -> Dict[Path, List[Tuple[str, str]]]:
    """{.utoc: [(parça kimliği, yol)]}: kaynak dildeki .locres dosyaları; sonraki kapsayıcı öncekini ezer."""
    owner: Dict[str, Tuple[Path, str]] = {}
    encrypted = []
    for utoc in sorted(Path(paks_dir).rglob("*.utoc")):
        try:
            output = run_retoc(["list", str(utoc), "--path"], aes_key)
        except NeedsAesKey:
            encrypted.append(utoc.name)
            continue
        for line in output.splitlines():
            match = RETOC_LINE.search(line)
            if match and _is_source_locres(match.group(2), source_lang):
                owner[re.sub(r"^(\.\./)+", "", match.group(2))] = (utoc, match.group(1))
    found: Dict[Path, List[Tuple[str, str]]] = {}
    for path, (utoc, chunk) in owner.items():
        found.setdefault(utoc, []).append((chunk, path))
    if encrypted and not found:
        raise NeedsAesKey(", ".join(encrypted[:3]))
    return found


def extract_iostore(found: Dict[Path, List[Tuple[str, str]]], out_dir: Path, aes_key: str = "") -> List[Path]:
    """Yalnızca .locres parçalarını çıkarır (büyük oyunda tüm kapsayıcıyı açmak gigabaytlar tutar)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    root = out_dir.resolve()
    for utoc, entries in found.items():
        for chunk, path in entries:
            target = (root / path).resolve()
            if root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            run_retoc(["get", str(utoc), chunk, str(target)], aes_key)
    return sorted(out_dir.rglob("*.locres"))


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
