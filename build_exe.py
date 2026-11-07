"""
Capri — Taşınabilir (portable) Windows sürümü derleme betiği
============================================================
Kullanım:
    python build_exe.py                          # dist/Capri klasörünü üretir
    python build_exe.py --zip                    # + GitHub sürümüne eklenecek Capri-win64.zip
    python build_exe.py --zip --out D:/Surumler --repo kullanici/Capri
    python build_exe.py --check-tag v1.0.1       # etiket APP_VERSION ile aynı mı (GitHub Actions)
    python build_exe.py --notes notlar.md        # CHANGELOG'daki bu sürümün notları

Kod imzalama: CAPRI_SIGN_PFX (.pfx yolu) ve CAPRI_SIGN_PASSWORD tanımlıysa Capri.exe imzalanır (signtool gerekir).

Çıktı kurulum gerektirmez: klasörü istediğin yere kopyalayıp Capri.exe'yi çalıştırırsın. Ayarlar,
önbellekler, modeller ve yerel model ortamı exe'nin yanında tutulur. PyTorch/Transformers pakete
girmez (≈3 GB); yerel model istendiğinde uygulama içinden kurulur (gpu_runtime.py).

Güncelleme kaynağı: --repo verilmezse git'in "origin" adresinden (github.com/kullanici/depo) okunur ve
exe'ye gömülür; kullanıcılar uygulamada yalnızca "Güncellemeleri kontrol et"e basar.
"""
from __future__ import annotations

import json
import os
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
TIMESTAMP_URL = "http://timestamp.digicert.com"


def version() -> str:
    return re.search(r'APP_VERSION = "([^"]+)"', (SRC / "app_modern.py").read_text(encoding="utf-8")).group(1)


def find_signtool() -> str:
    tool = shutil.which("signtool")
    if tool:
        return tool
    kits = sorted(Path(r"C:\Program Files (x86)\Windows Kits\10\bin").glob("*/x64/signtool.exe"))
    if kits:
        return str(kits[-1])
    raise RuntimeError("signtool bulunamadı (Windows SDK ile gelir).")


def sign(exe: Path) -> bool:
    """Sertifika tanımlıysa exe'yi imzalar; tanımlı değilse imzasız devam eder."""
    pfx = os.environ.get("CAPRI_SIGN_PFX")
    if not pfx:
        print("İmzalama atlandı (CAPRI_SIGN_PFX tanımlı değil).")
        return False
    subprocess.run([find_signtool(), "sign", "/fd", "SHA256", "/f", pfx, "/p", os.environ.get("CAPRI_SIGN_PASSWORD", ""),
                    "/tr", TIMESTAMP_URL, "/td", "SHA256", str(exe)], check=True)
    print(f"İmzalandı: {exe}")
    return True


def release_notes(ver: str) -> str:
    """CHANGELOG.md içinden bu sürümün bölümü."""
    text = (APP_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(ver)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match:
        raise RuntimeError(f"CHANGELOG.md içinde {ver} bölümü yok.")
    return match.group(1).strip() + "\n"


def build(repo: str) -> Path:
    build_dir = APP_DIR / "build"
    build_dir.mkdir(exist_ok=True)
    (build_dir / "build_info.json").write_text(json.dumps({"repo": repo, "version": version()}), encoding="utf-8")
    args = [sys.executable, "-m", "PyInstaller", f"--name={NAME}", "--onedir", "--windowed", "--noconfirm", "--clean",
            f"--icon={APP_DIR / 'assets' / 'capri.ico'}", f"--distpath={DIST}", f"--workpath={build_dir}",
            f"--specpath={build_dir}", f"--paths={SRC}", "--collect-submodules=winrt", "--collect-submodules=rpycdec", "--collect-data=webview",
            "--copy-metadata=pywebview", f"--add-data={build_dir / 'build_info.json'};."]
    args += [f"--add-data={APP_DIR / item};{item}" for item in DATA]
    args += [f"--hidden-import={m}" for m in HIDDEN] + [f"--exclude-module={m}" for m in EXCLUDES]
    args.append(str(SRC / "app_modern.py"))
    print("PyInstaller çalışıyor…")
    subprocess.run(args, cwd=str(APP_DIR), check=True)
    out = DIST / NAME
    sign(out / f"{NAME}.exe")
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
    if "--check-tag" in sys.argv:
        tag = sys.argv[sys.argv.index("--check-tag") + 1]
        if tag.lstrip("v") != version():
            sys.exit(f"Etiket {tag} ile APP_VERSION {version()} farklı.")
        sys.exit(0)
    if "--notes" in sys.argv:
        Path(sys.argv[sys.argv.index("--notes") + 1]).write_text(release_notes(version()), encoding="utf-8")
        sys.exit(0)
    import updater
    repo = sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv else updater.repo_from_git(APP_DIR)
    folder = build(repo)
    if "--zip" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else DIST
        make_zip(folder, out)
    shutil.rmtree(APP_DIR / "build", ignore_errors=True)
