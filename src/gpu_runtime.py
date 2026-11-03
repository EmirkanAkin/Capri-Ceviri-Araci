"""
Capri — Yerel model çalışma ortamı (PyTorch + Transformers)
===========================================================
Paketlenmiş exe bu kütüphaneleri içermez (PyTorch tek başına ~3 GB; GitHub'ın 2 GB dosya sınırını
aşar ve bulut motorlarını kullananlar için gereksizdir). Kullanıcı bir yerel model (OPUS-MT / NLLB)
istediğinde ortam, ekran kartına uygun resmi PyTorch sürümüyle birlikte exe'nin yanındaki
`runtime/site-packages` klasörüne kurulur (pip gerekmez; wheel dosyaları doğrudan açılır).
Kaynak koddan çalışırken kurulu kütüphaneler varsa hiçbir şey indirilmez.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from paths import APP_DIR

RUNTIME_DIR = APP_DIR / "runtime"
SITE_DIR = RUNTIME_DIR / "site-packages"
TORCH_INDEX = "https://download.pytorch.org/whl/torch/"
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
# Test edilmiş sürümler (paket, sürüm, içe aktarma adı) — bağımlılıklar önce
PACKAGES: List[Tuple[str, str, str]] = [
    ("typing-extensions", "4.16.0", "typing_extensions"), ("filelock", "4.0.1", "filelock"),
    ("fsspec", "2026.9.0", "fsspec"), ("mpmath", "1.3.0", "mpmath"), ("sympy", "1.14.0", "sympy"),
    ("networkx", "3.6.1", "networkx"), ("markupsafe", "3.0.3", "markupsafe"), ("jinja2", "3.1.6", "jinja2"),
    ("numpy", "2.4.6", "numpy"), ("packaging", "26.3", "packaging"), ("pyyaml", "6.0.3", "yaml"),
    ("regex", "2026.9.10", "regex"), ("tqdm", "4.70.1", "tqdm"), ("colorama", "0.4.6", "colorama"),
    ("huggingface-hub", "0.36.2", "huggingface_hub"), ("tokenizers", "0.22.2", "tokenizers"),
    ("safetensors", "0.8.0", "safetensors"), ("sentencepiece", "0.2.2", "sentencepiece"),
    ("transformers", "4.57.6", "transformers"),
]
LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


def activate() -> None:
    """Kurulu ortamı içe aktarma yoluna ekler (uygulama açılışında, torch'tan önce çağrılır)."""
    if SITE_DIR.is_dir() and str(SITE_DIR) not in sys.path:
        sys.path.append(str(SITE_DIR))
        importlib.invalidate_caches()
        torch_lib = SITE_DIR / "torch" / "lib"
        if torch_lib.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(torch_lib))


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing() -> List[str]:
    return [name for name, _v, module in PACKAGES if not _has(module)] + ([] if _has("torch") else ["torch"])


def ready() -> bool:
    return not missing()


def driver_cuda() -> Optional[Tuple[int, int]]:
    """NVIDIA sürücüsünün desteklediği en yüksek CUDA sürümü; NVIDIA kart yoksa None."""
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        out = subprocess.run([exe], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _version_key(text: str) -> Tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text))


def pick_torch_wheel(index_html: str, cuda: Optional[Tuple[int, int]]) -> Dict[str, str]:
    """Sürücüye uyan en yeni kararlı torch sürümünü seçer (CUDA yoksa CPU sürümü)."""
    pattern = re.compile(rf'href="([^"]*/(torch-(\d+\.\d+\.\d+)(?:\+|%2B)(cpu|cu\d+)-{PY_TAG}-{PY_TAG}-win_amd64\.whl))[^"]*"')
    best = None
    for url, name, version, variant in pattern.findall(index_html):
        if variant == "cpu":
            if cuda:
                continue
        else:
            if not cuda:
                continue
            code = int(variant[2:])
            need = (code // 10, code % 10)
            if need > cuda:
                continue
        key = (_version_key(version), variant != "cpu" and int(variant[2:]))
        if best is None or key > best[0]:
            best = (key, url, name.replace("%2B", "+"), version, variant)
    if not best:
        raise RuntimeError("Bu sisteme uygun PyTorch sürümü bulunamadı.")
    _key, url, name, version, variant = best
    if url.startswith("/"):
        url = "https://download.pytorch.org" + url
    elif not url.startswith("http"):
        url = TORCH_INDEX + url
    return {"url": url.split("#")[0], "name": name, "version": version, "variant": variant}


def pick_pypi_wheel(files: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    ok = []
    for f in files:
        name = str(f.get("filename", ""))
        if not name.endswith(".whl"):
            continue
        if name.endswith("-none-any.whl") or (("-" + PY_TAG + "-") in name and name.endswith("win_amd64.whl")) \
                or ("-abi3-" in name and name.endswith("win_amd64.whl")):
            ok.append(f)
    ok.sort(key=lambda f: str(f["filename"]).endswith("-none-any.whl"))  # derlenmiş sürüm önce
    return ok[0] if ok else None


def _download(url: str, target: Path, log: LogFn, progress: Optional[ProgressFn], label: str) -> None:
    part = target.with_suffix(target.suffix + ".part")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Capri"}) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with part.open("wb") as out:
            for chunk in resp.iter_content(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done >> 20, max(1, total >> 20))
    part.replace(target)
    log(f"{label} indirildi ({target.stat().st_size >> 20} MB).")


def _install_wheel(wheel: Path) -> None:
    """Wheel'i site-packages'a açar (.data/purelib|platlib içeriği köke taşınır)."""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    root = SITE_DIR.resolve()
    with zipfile.ZipFile(wheel) as zf:
        for member in zf.infolist():
            name = member.filename
            parts = name.split("/")
            if len(parts) > 2 and parts[0].endswith(".data"):
                if parts[1] not in ("purelib", "platlib"):
                    continue
                name = "/".join(parts[2:])
            target = (root / name).resolve()
            if root not in target.parents or member.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def estimate_mb(cuda: Optional[Tuple[int, int]]) -> int:
    return 2900 if cuda else 260


def install(log: LogFn = print, progress: Optional[ProgressFn] = None) -> Dict[str, str]:
    """Eksik paketleri kurar; seçilen torch sürüm bilgisini döndürür."""
    downloads = RUNTIME_DIR / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    result: Dict[str, str] = {}
    for name, version, module in PACKAGES:
        if _has(module):
            continue
        meta = requests.get(PYPI_JSON.format(name=name, version=version), timeout=30,
                            headers={"User-Agent": "Capri"}).json()
        wheel = pick_pypi_wheel(meta.get("urls", []))
        if not wheel:
            raise RuntimeError(f"{name} {version} için Windows paketi bulunamadı.")
        target = downloads / str(wheel["filename"])
        if not target.exists():
            _download(str(wheel["url"]), target, log, None, f"{name} {version}")
        _install_wheel(target)
        target.unlink(missing_ok=True)
    if not _has("torch"):
        cuda = driver_cuda()
        log("NVIDIA ekran kartı: " + (f"CUDA {cuda[0]}.{cuda[1]} destekli sürücü" if cuda else "bulunamadı (CPU sürümü kurulacak)"))
        html = requests.get(TORCH_INDEX, timeout=60, headers={"User-Agent": "Capri"}).text
        torch = pick_torch_wheel(html, cuda)
        log(f"PyTorch {torch['version']} ({torch['variant']}) indiriliyor…")
        target = downloads / torch["name"]
        if not target.exists():
            _download(torch["url"], target, log, progress, f"PyTorch {torch['version']}")
        log("PyTorch kuruluyor (dosyalar açılıyor)…")
        _install_wheel(target)
        target.unlink(missing_ok=True)
        result = torch
    shutil.rmtree(downloads, ignore_errors=True)
    activate()
    importlib.invalidate_caches()
    return result
