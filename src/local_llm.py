"""
Dahili yerel çeviri modelleri: Ollama kurmadan, llama.cpp'nin taşınabilir sunucusu (llama-server) ve GGUF model dosyası.

- Çalışma ortamı ve modeller yalnızca kullanıcı "İndir" deyince, Capri klasörüne iner (tools/, models_llm/); kurulum yok,
  arka planda kalıcı servis yok. Her dosya yayımlanan SHA-256 özetiyle doğrulanır, sürümler sabitlenmiştir.
- Sunucu ilk çeviri isteğinde açılır, yalnızca 127.0.0.1'i dinler, Capri kapanınca (ya da bir süre kullanılmazsa) kapanır;
  Capri çökse bile Windows iş nesnesi (job object) sayesinde onunla birlikte kapanır. `--fit on` modeli ekran kartının
  belleğine sığdırır, sığmayan kısım işlemciye düşer (çökme yerine yavaşlama).
- Çeviri mantığı (resmi istem biçimleri, ardışık satırların blok çevirisi, kod koruma) engine_common'daki Ollama
  motoruyla aynıdır; yalnızca istek llama-server'a gider.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import APP_DIR

LLAMA_VERSION = "b12426"
_GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/"
# Çalışma ortamı: Vulkan her ekran kartında (NVIDIA/AMD/Intel) çalışır ve küçüktür (37 MB). Ölçüm (RTX 5070,
# MiLMMT 4B): Vulkan 8,5 satır/sn, CUDA 9,4 satır/sn — 630 MB'lık CUDA paketi %10 hız için sunulmuyor.
RUNTIMES: Dict[str, Dict[str, Any]] = {
    "vulkan": {"label": "Vulkan (tüm ekran kartları)", "files": [
        {"name": f"llama-{LLAMA_VERSION}-bin-win-vulkan-x64.zip", "size": 38287057,
         "sha256": "4607416aaa5d223598f54bf99fe081d87414c3a83f8c94ef820947049579fb0e"}]},
}
DEFAULT_RUNTIME = "vulkan"

_HF = "https://huggingface.co/{repo}/resolve/{rev}/{file}"
CATALOG: List[Dict[str, Any]] = [
    {"id": "translategemma-4b", "label": "TranslateGemma 4B", "family": "translategemma", "tier": "light",
     "repo": "mradermacher/translategemma-4b-it-GGUF", "rev": "d37868f759d2f817a43d28dd80cf9f982ffa62fd",
     "file": "translategemma-4b-it.Q4_K_M.gguf", "size": 2489909760,
     "sha256": "81200d03e843d2ec1ece6eeafe7d13cb6e5211e1fcd336ade55790b683a08330",
     "vram_gb": 4, "ram_gb": 8, "use": "Oyun çevirisi · çoğu bilgisayar için",
     "speed": "Ekran kartıyla ~10 satır/sn, ekran kartsız ~1 satır/sn"},
    {"id": "translategemma-12b", "label": "TranslateGemma 12B", "family": "translategemma", "tier": "heavy",
     "repo": "mradermacher/translategemma-12b-it-GGUF", "rev": "41d7c8aa650b26791225ad9d0597e674e680da96",
     "file": "translategemma-12b-it.Q4_K_M.gguf", "size": 7300794112,
     "sha256": "b7aac4b4be7ab0c49b6556c29c4467e74313df7f1e95d9f9676bb2adf0afa528",
     "vram_gb": 10, "ram_gb": 16, "use": "Oyun çevirisi · en iyi kalite",
     "speed": "Ekran kartıyla ~4 satır/sn, ekran kartsız ~0,4 satır/sn (önerilmez)"},
    {"id": "milmmt-4b", "label": "MiLMMT-46 4B", "family": "milmmt", "tier": "light",
     "repo": "mradermacher/MiLMMT-46-4B-v1.0-GGUF", "rev": "3d05b58ace3d89a89af0574cdc49c84567f33969",
     "file": "MiLMMT-46-4B-v1.0.Q4_K_M.gguf", "size": 2489893152,
     "sha256": "25424cbb5423afaa22b1b53bfb3d8aa116cfd84b5f8dcfa82363bfb3c4221ddf",
     "vram_gb": 4, "ram_gb": 8, "use": "Ekran çevirisi · tek satır, çok hızlı",
     "speed": "Tek satır ~0,1 sn, ekran kartsız ~0,5 sn"},
]
BY_ID = {m["id"]: m for m in CATALOG}
IDLE_SECONDS = 300          # bu kadar kullanılmazsa sunucu kapanır, ekran kartı belleği boşalır
CONTEXT = 8192


def tools_dir() -> Path:
    return APP_DIR / "tools" / "llama.cpp"


def models_dir() -> Path:
    return APP_DIR / "models_llm"


def runtime_path(flavor: str) -> Path:
    return tools_dir() / f"{LLAMA_VERSION}-{flavor}"


def server_exe(flavor: Optional[str] = None) -> Optional[Path]:
    """Kurulu llama-server (tercih: verilen tür, yoksa CUDA, yoksa Vulkan)."""
    for name in ([flavor] if flavor else []) + ["cuda", DEFAULT_RUNTIME]:
        exe = runtime_path(name) / "llama-server.exe"
        if exe.is_file():
            return exe
    return None


def model_path(model_id: str) -> Path:
    return models_dir() / BY_ID[model_id]["file"]


def installed_runtimes() -> List[str]:
    return [name for name in RUNTIMES if (runtime_path(name) / "llama-server.exe").is_file()]


def model_installed(model_id: str) -> bool:
    path = model_path(model_id)
    return path.is_file() and path.stat().st_size == BY_ID[model_id]["size"]


def recommend(vram_gb: Optional[float], nvidia: bool = False) -> Dict[str, str]:
    """Ekran kartına göre önerilen model ve çalışma ortamı."""
    model = "translategemma-12b" if (vram_gb or 0) >= 10 else "translategemma-4b"
    return {"model": model, "runtime": DEFAULT_RUNTIME}


def status(vram_gb: Optional[float] = None, nvidia: bool = False) -> Dict[str, Any]:
    rec = recommend(vram_gb, nvidia)
    return {
        "runtimes": [{"id": k, "label": v["label"], "installed": k in installed_runtimes(),
                      "size": sum(f["size"] for f in v["files"])} for k, v in RUNTIMES.items()],
        "models": [{**{k: m[k] for k in ("id", "label", "family", "tier", "size", "vram_gb", "ram_gb", "use", "speed")},
                    "installed": model_installed(m["id"]), "recommended": m["id"] == rec["model"]} for m in CATALOG],
        "recommended": rec, "running": SERVER.model_id,
    }


# ── İndirme ──────────────────────────────────────────────────────────────────
class DownloadCancelled(Exception):
    pass


def _download(url: str, target: Path, size: int, sha256: str, progress: Optional[Callable[[int, int], None]],
              cancel: Optional[threading.Event], opener=urllib.request.urlopen) -> None:
    """Parça dosyaya indirir, boyut ve SHA-256 tutarsa yerine koyar; tutmazsa siler ve hata verir."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    digest, done = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "Capri"})
    try:
        with opener(request, timeout=60) as response, open(part, "wb") as handle:
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > size:
                    raise ValueError("Beklenenden büyük dosya")
                if progress:
                    progress(done, size)
        if done != size or digest.hexdigest() != sha256:
            raise ValueError(f"{target.name} doğrulanamadı (boyut ya da SHA-256 tutmuyor); dosya silindi.")
        part.replace(target)
    finally:
        if part.exists():
            part.unlink()


def install_runtime(flavor: str, progress=None, cancel=None, log=print, opener=urllib.request.urlopen) -> Path:
    spec = RUNTIMES[flavor]
    total = sum(f["size"] for f in spec["files"])
    staging = tools_dir() / f".{LLAMA_VERSION}-{flavor}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    base = 0
    try:
        for item in spec["files"]:
            archive = staging / item["name"]
            _download(_GH + item["name"], archive, item["size"], item["sha256"],
                      (lambda d, t, b=base: progress(b + d, total)) if progress else None, cancel, opener)
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    name = Path(member.filename)
                    if name.is_absolute() or ".." in name.parts:      # zip içinden dışarı yazılamaz
                        raise ValueError(f"Güvensiz arşiv yolu: {member.filename}")
                zf.extractall(staging)
            archive.unlink()
            base += item["size"]
        if not (staging / "llama-server.exe").is_file():
            raise ValueError("Pakette llama-server.exe yok.")
        target = runtime_path(flavor)
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
        log(f"llama.cpp {LLAMA_VERSION} ({flavor}) kuruldu: {target}")
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install_model(model_id: str, progress=None, cancel=None, log=print, opener=urllib.request.urlopen) -> Path:
    spec = BY_ID[model_id]
    target = model_path(model_id)
    _download(_HF.format(**spec), target, spec["size"], spec["sha256"], progress, cancel, opener)
    log(f"{spec['label']} indirildi ve doğrulandı: {target}")
    return target


def remove_model(model_id: str) -> None:
    if SERVER.model_id == model_id:
        SERVER.stop()
    model_path(model_id).unlink(missing_ok=True)


def remove_runtime(flavor: str) -> None:
    SERVER.stop()
    shutil.rmtree(runtime_path(flavor), ignore_errors=True)


# ── Sunucu ───────────────────────────────────────────────────────────────────
def _kill_with_parent(process: subprocess.Popen) -> None:
    """Capri kapanır ya da çökerse sunucu da kapansın (Windows iş nesnesi, KILL_ON_JOB_CLOSE)."""
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("Basic", BasicLimits), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.OpenProcess.restype = ctypes.c_void_p
        job = kernel32.CreateJobObjectW(None, None)
        info = ExtendedLimits()
        info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        handle = kernel32.OpenProcess(0x0101, False, process.pid)   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        process._capri_job = job          # iş nesnesi Capri yaşadıkça açık kalır
    except Exception:
        pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LlamaServer:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.model_id: Optional[str] = None
        self.url = ""
        self.last_used = 0.0
        self._lock = threading.RLock()
        self._watch: Optional[threading.Thread] = None
        self.log_file = APP_DIR / "portable_cache" / "llama-server.log"
        self.flavor: Optional[str] = None       # None: kurulu en iyi ortam (CUDA > Vulkan)
        self.extra_args: List[str] = []         # ölçüm/test için (ör. ["-dev", "none"] = yalnız işlemci)

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def ensure(self, model_id: str, log: Callable[[str], None] = print, timeout: float = 180) -> str:
        """Sunucu bu modelle çalışmıyorsa başlatır, hazır olana (model belleğe yüklenene) kadar bekler."""
        with self._lock:
            self.last_used = time.time()
            if self.running() and self.model_id == model_id:
                return self.url
            self.stop()
            exe = server_exe(self.flavor)
            if exe is None:
                raise RuntimeError("Yerel model ortamı (llama.cpp) kurulu değil. Yerel Modeller sayfasından indir.")
            if not model_installed(model_id):
                raise RuntimeError(f"{BY_ID[model_id]['label']} indirilmemiş. Yerel Modeller sayfasından indir.")
            port = _free_port()
            args = [str(exe), "-m", str(model_path(model_id)), "--host", "127.0.0.1", "--port", str(port),
                    "-c", str(CONTEXT), "-np", "1", "--fit", "on", "--no-webui", *self.extra_args]
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            out = open(self.log_file, "w", encoding="utf-8", errors="replace")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(args, cwd=str(exe.parent), stdout=out, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, creationflags=flags)
            out.close()
            _kill_with_parent(self.process)
            self.url, self.model_id = f"http://127.0.0.1:{port}", model_id
            log(f"{BY_ID[model_id]['label']} yükleniyor ({exe.parent.name})…")
            started = time.time()
            while time.time() - started < timeout:
                if self.process.poll() is not None:
                    tail = self._log_tail()
                    self.process, self.model_id = None, None
                    raise RuntimeError(f"Yerel model sunucusu kapandı: {tail}")
                try:
                    with urllib.request.urlopen(f"{self.url}/health", timeout=2) as response:
                        if response.status == 200:
                            log(f"{BY_ID[model_id]['label']} hazır ({time.time() - started:.1f} sn)")
                            self._start_watch()
                            return self.url
                except Exception:
                    time.sleep(0.25)
            self.stop()
            raise RuntimeError("Yerel model zamanında yüklenemedi.")

    def _log_tail(self) -> str:
        try:
            lines = [l for l in self.log_file.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            return " | ".join(lines[-3:])[-400:]
        except OSError:
            return ""

    def _start_watch(self) -> None:
        if self._watch is not None and self._watch.is_alive():
            return

        def watch():
            while self.running():
                time.sleep(15)
                if time.time() - self.last_used > IDLE_SECONDS:
                    self.stop()
                    return
        self._watch = threading.Thread(target=watch, daemon=True, name="llama-idle")
        self._watch.start()

    def stop(self) -> None:
        with self._lock:
            process, self.process, self.model_id = self.process, None, None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()

    def complete(self, model_id: str, prompt: str, stop: List[str], temperature: float, n_predict: int,
                 timeout: float, log: Callable[[str], None] = print) -> str:
        url = self.ensure(model_id, log)
        body = json.dumps({"prompt": prompt, "temperature": temperature, "n_predict": n_predict, "stop": stop,
                           "cache_prompt": True}).encode("utf-8")
        request = urllib.request.Request(f"{url}/completion", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        self.last_used = time.time()
        return (data.get("content") or "").strip()


SERVER = LlamaServer()


def translate_one(model_id: str, text: str, source: str, target: str, temperature: float = 0.1,
                  timeout: float = 600, log: Callable[[str], None] = print) -> str:
    """Tek metin (TranslateGemma'da birden çok satır olabilir): modelin resmi istem biçimiyle."""
    from engine_common import milmmt_prompt, translategemma_prompt
    spec = BY_ID[model_id]
    budget = max(64, min(4096, int(len(text) * 1.5) + 64))
    if spec["family"] == "milmmt":
        return SERVER.complete(model_id, milmmt_prompt(text, source, target), ["\n"], 0.0, budget, timeout, log)
    prompt = f"<start_of_turn>user\n{translategemma_prompt(text, source, target)}<end_of_turn>\n<start_of_turn>model\n"
    return SERVER.complete(model_id, prompt, ["<end_of_turn>"], temperature, budget, timeout, log)


def transport(model_id: str, source: str, target: str, log: Callable[[str], None] = print):
    """OllamaTranslationEngine için istek fonksiyonu: (metin, sıcaklık, zaman aşımı) → çeviri."""
    return lambda text, temperature=0.1, timeout=600: translate_one(model_id, text, source, target, temperature,
                                                                     timeout, log)


def family(model_id: str) -> str:
    return BY_ID[model_id]["family"] if model_id in BY_ID else "chat"
