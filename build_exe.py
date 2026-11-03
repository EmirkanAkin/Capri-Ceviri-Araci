"""
Capri — Taşınabilir (portable) Windows sürümü derleme betiği
============================================================
Kullanım:
    python build_exe.py                          # dist/Capri klasörünü üretir
    python build_exe.py --zip                    # + GitHub sürümüne eklenecek Capri-win64.zip
    python build_exe.py --zip --out D:/Surumler --repo kullanici/Capri

Çıktı kurulum gerektirmez: klasörü istediğin yere kopyalayıp Capri.exe'yi çalıştırırsın. Ayarlar,
önbellekler, modeller ve yerel model ortamı exe'nin yanında tutulur. PyTorch/Transformers pakete
girmez (≈3 GB); yerel model istendiğinde uygulama içinden kurulur (gpu_runtime.py).

Güncelleme kaynağı: --repo verilmezse git'in "origin" adresinden (github.com/kullanici/depo) okunur ve
exe'ye gömülür; kullanıcılar uygulamada yalnızca "Güncellemeleri kontrol et"e basar.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SRC = APP_DIR / "src"
DIST = APP_DIR / "dist"
NAME = "Capri"
sys.path.insert(0, str(SRC))
# Yerel model ortamı uygulama içinden kurulur; pakete girmez
EXCLUDES = ["torch", "torchvision", "torchaudio", "transformers", "tokenizers", "safetensors", "sentencepiece",
            "sacremoses", "huggingface_hub", "accelerate", "sympy", "networkx", "jinja2", "mpmath",
            "matplotlib", "scipy", "pandas", "cv2", "tkinter", "IPython", "pytest", "numpy.testing"]
HIDDEN = ["webview", "webview.platforms.edgechromium", "webview.platforms.winforms", "clr", "UnityPy", "pylocres",
          "mss", "rpycdec", "numpy", "requests"]
DATA = ["web", "assets", "data"]


def version() -> str:
    return re.search(r'APP_VERSION = "([^"]+)"', (SRC / "app_modern.py").read_text(encoding="utf-8")).group(1)


def build(repo: str) -> Path:
    build_dir = APP_DIR / "build"
    build_dir.mkdir(exist_ok=True)
    (build_dir / "build_info.json").write_text(json.dumps({"repo": repo, "version": version()}), encoding="utf-8")
    args = [sys.executable, "-m", "PyInstaller", f"--name={NAME}", "--onedir", "--windowed", "--noconfirm", "--clean",
            f"--icon={APP_DIR / 'assets' / 'capri.ico'}", f"--distpath={DIST}", f"--workpath={build_dir}",
            f"--specpath={build_dir}", f"--paths={SRC}", "--collect-submodules=winrt", "--collect-data=webview",
            "--copy-metadata=pywebview", f"--add-data={build_dir / 'build_info.json'};."]
    args += [f"--add-data={APP_DIR / item};{item}" for item in DATA]
    args += [f"--hidden-import={m}" for m in HIDDEN] + [f"--exclude-module={m}" for m in EXCLUDES]
    args.append(str(SRC / "app_modern.py"))
    print("PyInstaller çalışıyor…")
    subprocess.run(args, cwd=str(APP_DIR), check=True)
    out = DIST / NAME
    (out / "BENIOKU.txt").write_text(
        "Capri — taşınabilir sürüm\n\n"
        "Kurulum gerekmez: Capri.exe'yi çalıştır. Klasörü istediğin yere taşıyabilirsin.\n"
        "Ayarlar, sözlükler, önbellekler ve modeller bu klasörde (data, portable_cache, model, runtime) tutulur.\n"
        "Yerel modeller (OPUS-MT, NLLB) ilk kullanımda uygulama içinden indirilir.\n"
        "Güncellemeler: üst çubuktaki indirme simgesi → Güncellemeleri kontrol et.\n"
        "Gerekli: Windows 10/11 64 bit ve Microsoft Edge WebView2 (Windows 11'de yüklü gelir).\n", encoding="utf-8")
    print(f"Derleme tamam: {out} · güncelleme kaynağı: {repo or 'YOK (--repo ile ver)'}")
    return out


def make_zip(folder: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{NAME}-win64.zip"   # sabit ad: .../releases/latest/download/Capri-win64.zip
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, Path(NAME) / path.relative_to(folder))
    print(f"Sürüm paketi: {target} ({target.stat().st_size >> 20} MB)")
    return target


if __name__ == "__main__":
    import updater
    repo = sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv else updater.repo_from_git(APP_DIR)
    folder = build(repo)
    if "--zip" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else DIST
        make_zip(folder, out)
    shutil.rmtree(APP_DIR / "build", ignore_errors=True)
