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
# Kalite: Capri'nin kendi testi (WMT24++ İngilizce → 14 dil chrF++, Türkçe 60 cümle; 24 oyun satırında etiket
# koruma; açgözlü çözüm, llama.cpp b12426 Vulkan, RTX 5070 12 GB). Dosyalar sabit sürüm ve SHA-256 ile doğrulanır.
CATALOG: List[Dict[str, Any]] = [
    {"id": "hymt2-1.8b", "label": "Hy-MT2 1.8B", "family": "hymt", "tier": "light", "repo": "tencent/Hy-MT2-1.8B-GGUF", "rev": "a0c709d9fac510f2c807aa3af52872340dc37a4a", "file": "Hy-MT2-1.8B-Q4_K_M.gguf", "size": 1133080448, "sha256": "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699", "vram_gb": 2, "ram_gb": 4, "license": "Apache-2.0", "use": "En küçük model (1,1 GB) ve ekran kartıyla en hızlısı. Belleği az, ekran kartsız bilgisayarlarda da akıcı çalışır; kalitesi grubunun altında ama ekran çevirisi ve hızlı ön çeviri için ideal.", "short": "En küçük ve en hızlı model", "speed": "RTX 5070 ile ~3,5 cümle/sn, ekran kartsız ~0,6 cümle/sn", "rate": 3.47, "quality": {"tr": 50.3, "avg": 46.7, "tags": 1.0}},
    {"id": "gemma4-e2b", "label": "Gemma 4 E2B", "family": "gemma4", "tier": "light", "repo": "google/gemma-4-E2B-it-qat-q4_0-gguf", "rev": "675cff42a74c774d6cb76f76d8eacb49b48c9b93", "file": "gemma-4-E2B_q4_0-it.gguf", "size": 3349516256, "sha256": "fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634", "vram_gb": 4, "ram_gb": 6, "license": "Apache-2.0", "use": "Google'ın küçük genel modeli. Boyutuna göre doğal Türkçe yazar, oyun etiketlerini hiç bozmadı; Avrupa dillerinde bu grubun en iyisi. Kalite editörü olarak da kullanılabilir.", "short": "Zayıf bilgisayarlarda doğal ve akıcı Türkçe", "speed": "RTX 5070 ile ~2,0 cümle/sn, ekran kartsız ~0,7 cümle/sn", "rate": 1.96, "quality": {"tr": 52.91, "avg": 49.2, "tags": 1.0}},
    {"id": "milmmt-4b", "label": "MiLMMT-46 4B", "family": "milmmt", "tier": "light", "repo": "mradermacher/MiLMMT-46-4B-v1.0-GGUF", "rev": "3d05b58ace3d89a89af0574cdc49c84567f33969", "file": "MiLMMT-46-4B-v1.0.Q4_K_M.gguf", "size": 2489893152, "sha256": "25424cbb5423afaa22b1b53bfb3d8aa116cfd84b5f8dcfa82363bfb3c4221ddf", "vram_gb": 4, "ram_gb": 8, "license": "Gemma", "use": "46 dile özel çeviri modeli. Hafif grupta en iyi Türkçe puanı ve etiketleri hiç bozmadı; kısa satırlarda çok hızlı olduğu için ekran çevirisinde de varsayılan.", "short": "Hızlı ve isabetli; ekran çevirisi için de ideal", "speed": "RTX 5070 ile ~2,4 cümle/sn, ekran kartsız ~0,4 cümle/sn", "rate": 2.42, "quality": {"tr": 53.43, "avg": 46.9, "tags": 1.0}},
    {"id": "translategemma-4b", "label": "TranslateGemma 4B", "family": "translategemma", "tier": "light", "repo": "mradermacher/translategemma-4b-it-GGUF", "rev": "d37868f759d2f817a43d28dd80cf9f982ffa62fd", "file": "translategemma-4b-it.Q4_K_M.gguf", "size": 2489909760, "sha256": "81200d03e843d2ec1ece6eeafe7d13cb6e5211e1fcd336ade55790b683a08330", "vram_gb": 4, "ram_gb": 8, "license": "Gemma", "use": "Google'ın ilk çeviri modeli. Testte zaman zaman metne olmayan şeyler ekledi ve sayıları değiştirdi; bu gruptaki diğer modeller daha iyi sonuç verdi.", "short": "Eski model; bu gruptaki diğerleri daha iyi", "speed": "RTX 5070 ile ~2,3 cümle/sn, ekran kartsız ~0,3 cümle/sn", "rate": 2.31, "quality": {"tr": 45.83, "avg": 44.9, "tags": 0.958}},
    {"id": "hymt2-7b", "label": "Hy-MT2 7B", "family": "hymt", "tier": "medium", "repo": "tencent/Hy-MT2-7B-GGUF", "rev": "ab8472660ac61fac25f1af43fac2599d52a8a775", "file": "Hy-MT2-7B-Q4_K_M.gguf", "size": 4624648896, "sha256": "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b", "vram_gb": 6, "ram_gb": 10, "license": "Apache-2.0", "use": "Tencent'in çeviri modeli. Testteki en iyi Türkçe puanlarından biri: anlama sadık, temiz ve doğal cümleler. 6 GB ekran kartında hızlı; çoğu kişi için en iyi seçim.", "short": "Anlama sadık, temiz Türkçe; çoğu kişi için en iyisi", "speed": "RTX 5070 ile ~1,3 cümle/sn, ekran kartsız ~0,2 cümle/sn", "rate": 1.33, "quality": {"tr": 55.68, "avg": 50.8, "tags": 1.0}},
    {"id": "gemma4-e4b", "label": "Gemma 4 E4B", "family": "gemma4", "tier": "medium", "repo": "google/gemma-4-E4B-it-qat-q4_0-gguf", "rev": "4b4a2c1d584be7264f87aac328a1bc739ce81b6c", "file": "gemma-4-E4B_q4_0-it.gguf", "size": 5154941280, "sha256": "676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee", "vram_gb": 6, "ram_gb": 10, "license": "Apache-2.0", "use": "Google'ın orta boy genel modeli. Konuşma diline yakın, akıcı Türkçe; diyalog ağırlıklı oyunlar için iyi, etiketleri hiç bozmadı. Kalite editörü olarak da kullanılabilir.", "short": "Akıcı, konuşma diline yakın Türkçe", "speed": "RTX 5070 ile ~2,1 cümle/sn, ekran kartsız ~0,3 cümle/sn", "rate": 2.14, "quality": {"tr": 54.65, "avg": 49.9, "tags": 1.0}},
    {"id": "gemma4-12b", "label": "Gemma 4 12B", "family": "gemma4", "tier": "heavy", "repo": "google/gemma-4-12B-it-qat-q4_0-gguf", "rev": "29d097773436b69ff9feafd636ab4cf873786537", "file": "gemma-4-12b-it-qat-q4_0.gguf", "size": 6975879296, "sha256": "93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b", "vram_gb": 9, "ram_gb": 16, "license": "Apache-2.0", "use": "Google'ın 12B genel modeli. Avrupa dillerinde güçlü ve etiketleri hiç bozmadı, ama Türkçede seyrek de olsa bozuk kelime üretti; Türkçe için 26B ya da MiLMMT 12B daha iyi.", "short": "Avrupa dillerinde güçlü, Türkçede ara sıra hata", "speed": "RTX 5070 ile ~1,1 cümle/sn", "rate": 1.08, "quality": {"tr": 54.51, "avg": 51.3, "tags": 1.0}},
    {"id": "milmmt-12b", "label": "MiLMMT-46 12B", "family": "milmmt", "tier": "heavy", "repo": "mradermacher/MiLMMT-46-12B-v1.0-GGUF", "rev": "67b6e43ad31a3aad46bafc4f899a9c0d5eec898d", "file": "MiLMMT-46-12B-v1.0.Q4_K_M.gguf", "size": 7300777440, "sha256": "8c2d878d8daf8722faf1a42eef02ce046411ede17bf3115fb8b2cce491d5fb03", "vram_gb": 10, "ram_gb": 16, "license": "Gemma", "use": "46 dile özel büyük çeviri modeli. Testte en yüksek Türkçe puanlarından birini aldı ve oyun etiketlerini hiç bozmadı; 10-12 GB ekran kartında hikâye ağırlıklı oyunlar için çok iyi.", "short": "En yüksek Türkçe puanı, etiketlere çok sadık", "speed": "RTX 5070 ile ~1,0 cümle/sn", "rate": 1.02, "quality": {"tr": 56.35, "avg": 48.3, "tags": 1.0}},
    {"id": "translategemma-12b", "label": "TranslateGemma 12B", "family": "translategemma", "tier": "heavy", "repo": "mradermacher/translategemma-12b-it-GGUF", "rev": "41d7c8aa650b26791225ad9d0597e674e680da96", "file": "translategemma-12b-it.Q4_K_M.gguf", "size": 7300794112, "sha256": "b7aac4b4be7ab0c49b6556c29c4467e74313df7f1e95d9f9676bb2adf0afa528", "vram_gb": 10, "ram_gb": 16, "license": "Gemma", "use": "Google'ın çeviri modeli. Güvenilir ve resmî bir dil kullanır ama Türkçe puanı aynı boydaki modellerin gerisinde kaldı; çok dilli oyunlarda dengeli.", "short": "Resmî dil; Türkçede diğerlerinin gerisinde", "speed": "RTX 5070 ile ~0,9 cümle/sn", "rate": 0.94, "quality": {"tr": 50.06, "avg": 48.4, "tags": 0.958}},
    {"id": "gemma4-26b-a4b", "label": "Gemma 4 26B-A4B", "family": "gemma4", "tier": "heavy", "repo": "google/gemma-4-26B-A4B-it-qat-q4_0-gguf", "rev": "d1c082be9cf3c8a514acf63b8761f4b41935842e", "file": "gemma-4-26B_q4_0-it.gguf", "size": 14439363584, "sha256": "3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d", "vram_gb": 16, "ram_gb": 24, "license": "Apache-2.0", "use": "Google'ın büyük genel modeli (uzmanlar karışımı: her kelimede yalnızca 4B çalışır). Ağır grupta en doğal ve akıcı Türkçe, etiketleri hiç bozmadı; 12 GB kartta kısmen işlemciye taşar ama hızlı kalır. Kalite editörü olarak da en iyi yerel seçenek.", "short": "En doğal Türkçe; kalite editörü olarak da en iyisi", "speed": "RTX 5070 ile ~0,5 cümle/sn", "rate": 0.49, "quality": {"tr": 55.88, "avg": 51.7, "tags": 1.0}},
    {"id": "hymt2-30b-a3b", "label": "Hy-MT2 30B-A3B", "family": "hymt", "tier": "heavy", "repo": "tencent/Hy-MT2-30B-A3B-GGUF", "rev": "fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3", "file": "Hy-MT2-30B-A3B-Q4_K_M.gguf", "size": 18236702880, "sha256": "bb44b11bb0f7cd3d1321645b41e911cd3de2e473731227fc6bf37aa18b543f88", "vram_gb": 20, "ram_gb": 32, "license": "Apache-2.0", "use": "Tencent'in en büyük çeviri modeli. Kalitesi çok iyi ama testte 7B kardeşini geçemedi ve 18 GB yer kaplar; 16 GB+ ekran kartı ve 32 GB RAM'li bilgisayarlar için.", "short": "Çok iyi ama büyük ve yavaş", "speed": "RTX 5070 ile ~0,2 cümle/sn", "rate": 0.25, "quality": {"tr": 54.36, "avg": 50.7, "tags": 1.0}},
    {"id": "translategemma-27b", "label": "TranslateGemma 27B", "family": "translategemma", "tier": "heavy", "repo": "mradermacher/translategemma-27b-it-GGUF", "rev": "22fb50537007ccd41c41a0f0f0482e0fdb3335ab", "file": "translategemma-27b-it.Q4_K_M.gguf", "size": 16546704480, "sha256": "7f1e67c4ecfec676b38c1ea2ef85c46fafe2f02d3c050fb9540e51787405d8a3", "vram_gb": 18, "ram_gb": 32, "license": "Gemma", "use": "Google'ın en büyük çeviri modeli. Resmî ve dikkatli çeviri yapar ama 16 GB+ ekran kartı ister; daha küçük kartlarda çok yavaş çalışır.", "short": "Çok büyük; 16 GB+ ekran kartı ister", "speed": "RTX 5070 ile ~0,05 cümle/sn", "rate": 0.05, "quality": {"tr": 54.12, "avg": 47.9, "tags": 0.917}},
]
BY_ID = {m["id"]: m for m in CATALOG}
# PyTorch ile çalışan klasik çeviri modelleri (Capri'nin eski yerel motorları; indirme ve kullanım providers'ta). Aynı
# testten geçirildi; kitaplıkta llama.cpp modelleriyle birlikte, kalitelerine göre sıralanır.
CLASSIC: List[Dict[str, Any]] = [
    {"id": "opus", "label": "OPUS-MT", "family": "classic", "tier": "light", "size": 474_500_000, "vram_gb": 0,
     "ram_gb": 2, "license": "CC-BY-4.0", "rate": 4.6,
     "short": "Yalnızca İngilizce → Türkçe; ekran kartı gerekmez, çok hızlı",
     "use": "Helsinki Üniversitesi'nin İngilizce → Türkçe çeviri modeli. İşlemcide çalışır (≈40 MB'lık ortamla, PyTorch "
            "gerekmez); ekran kartı olmayan bilgisayarlarda en hızlı model. Kalitesi hafif grubun ortasında; başka dil "
            "çiftlerini çeviremez.",
     "speed": "İşlemcide ~4,6 cümle/sn",
     "quality": {"tr": 52.36, "avg": None, "tags": 0.917}},
    {"id": "nllb", "label": "NLLB-200 600M", "family": "classic", "tier": "light", "size": 630_000_000, "vram_gb": 0,
     "ram_gb": 3, "license": "CC-BY-NC-4.0", "rate": 1.6,
     "short": "200 dil ama zayıf kalite; yalnızca ticari olmayan kullanım",
     "use": "Meta'nın 200 dilli modeli. İşlemcide çalışır (≈40 MB'lık ortamla, PyTorch gerekmez). Çok dil bilir ama "
            "testte Türkçede ve diğer dillerde en zayıf sonucu verdi; lisansı yalnızca ticari olmayan kullanıma izin verir.",
     "speed": "İşlemcide ~1,6 cümle/sn",
     "quality": {"tr": 37.76, "avg": 37.3, "tags": 0.917}},
]
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


TIERS = ("light", "medium", "heavy")


def score(spec: Dict[str, Any]) -> float:
    """Sıralama puanı: Türkçe chrF++ iki kat, 14 dilin ortalaması bir kat ağırlıklı; oyun etiketlerini koruyamayan
    model etiket oranıyla cezalandırılır (bozuk etiket oyunda hata demektir)."""
    q = spec.get("quality") or {}
    avg = q.get("avg") if q.get("avg") is not None else q.get("tr", 0)   # tek dil çiftli model (OPUS-MT)
    base = (2 * q.get("tr", 0) + avg) / 3
    return base * (0.5 + 0.5 * (q.get("tags") if q.get("tags") is not None else 1))


def ordered() -> List[Dict[str, Any]]:
    """Katalog arayüzdeki sırasıyla: önce hafif → orta → ağır, her grupta iyiden kötüye."""
    return sorted(CATALOG, key=lambda m: (TIERS.index(m["tier"]), -score(m)))


def recommend(vram_gb: Optional[float], nvidia: bool = False) -> Dict[str, str]:
    """Ekran kartına göre önerilen model: belleğe tamamen sığan en iyi model. 10 GB+ kartta ağır grubun, 6 GB+ kartta
    orta grubun, daha küçük kartta ya da kartsız bilgisayarda hafif grubun en iyisi."""
    vram = vram_gb or 0
    tier = "heavy" if vram >= 10 else "medium" if vram >= 6 else "light"
    pool = [m for m in ordered() if m["tier"] == tier and (vram == 0 or m["vram_gb"] <= vram)] or \
        [m for m in ordered() if m["tier"] == "light"]
    return {"model": pool[0]["id"], "runtime": DEFAULT_RUNTIME}


def status(vram_gb: Optional[float] = None, nvidia: bool = False,
           classic_ready: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """classic_ready: OPUS-MT / NLLB kurulu mu (verilirse kitaplığa sıralı olarak eklenirler)."""
    rec = recommend(vram_gb, nvidia)
    models, rank = [], {}
    pool = CATALOG + ([m for m in CLASSIC if m["id"] in classic_ready] if classic_ready is not None else [])
    for m in sorted(pool, key=lambda m: (TIERS.index(m["tier"]), -score(m))):
        rank[m["tier"]] = rank.get(m["tier"], 0) + 1
        classic = m["family"] == "classic"
        models.append({**{k: m[k] for k in ("id", "label", "family", "tier", "size", "vram_gb", "ram_gb", "use", "speed")},
                       "quality": m.get("quality") or {}, "license": m.get("license", ""), "rank": rank[m["tier"]],
                       "short": m.get("short", ""), "rate": m.get("rate"), "score": round(score(m), 1),
                       "best_in_tier": rank[m["tier"]] == 1, "game": True, "kind": "classic" if classic else "llm",
                       "installed": bool(classic_ready.get(m["id"])) if classic else model_installed(m["id"]),
                       "recommended": m["id"] == rec["model"]})
    return {
        "runtimes": [{"id": k, "label": v["label"], "installed": k in installed_runtimes(),
                      "size": sum(f["size"] for f in v["files"])} for k, v in RUNTIMES.items()],
        "models": models, "recommended": rec, "running": SERVER.model_id,
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
                    "-c", str(CONTEXT), "-np", "1", "--fit", "on", "--no-webui", "--jinja", *self.extra_args]
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

    def chat(self, model_id: str, content: str, temperature: float, n_predict: int, timeout: float,
             log: Callable[[str], None] = print, **extra: Any) -> str:
        """Modelin kendi sohbet şablonuyla tek mesaj (Hy-MT2, Gemma 4)."""
        url = self.ensure(model_id, log)
        body = json.dumps({"messages": [{"role": "user", "content": content}], "temperature": temperature,
                           "max_tokens": n_predict, "cache_prompt": True, **extra}).encode("utf-8")
        request = urllib.request.Request(f"{url}/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        self.last_used = time.time()
        message = (data.get("choices") or [{}])[0].get("message") or {}
        return (message.get("content") or "").strip()


SERVER = LlamaServer()


def translate_one(model_id: str, text: str, source: str, target: str, temperature: float = 0.1,
                  timeout: float = 600, log: Callable[[str], None] = print) -> str:
    """Tek metin (TranslateGemma'da birden çok satır olabilir): modelin resmi istem biçimiyle."""
    from engine_common import chat_translate_prompt, hymt_prompt, milmmt_prompt, translategemma_prompt
    spec = BY_ID[model_id]
    budget = max(64, min(4096, int(len(text) * 1.5) + 64))
    if spec["family"] in ("milmmt", "hymt") and "\n" in text.strip():
        # MiLMMT'nin istemi satır sonunda biter, Hy-MT2 satırları birleştirebiliyor (ölçüldü): satırlar ayrı çevrilir
        return "\n".join(translate_one(model_id, line, source, target, temperature, timeout, log)
                         if line.strip() else line for line in text.split("\n"))
    if spec["family"] == "milmmt":
        return SERVER.complete(model_id, milmmt_prompt(text, source, target), ["\n"], 0.0, budget, timeout, log)
    if spec["family"] == "hymt":
        return SERVER.chat(model_id, hymt_prompt(text, source, target), 0.0, budget * 2, timeout, log,
                           repeat_penalty=1.05)
    if spec["family"] == "gemma4":
        return SERVER.chat(model_id, chat_translate_prompt(text, source, target), 0.0, budget * 2, timeout, log,
                           chat_template_kwargs={"enable_thinking": False})
    prompt = f"<start_of_turn>user\n{translategemma_prompt(text, source, target)}<end_of_turn>\n<start_of_turn>model\n"
    return SERVER.complete(model_id, prompt, ["<end_of_turn>"], temperature, budget, timeout, log)


def transport(model_id: str, source: str, target: str, log: Callable[[str], None] = print):
    """OllamaTranslationEngine için istek fonksiyonu: (metin, sıcaklık, zaman aşımı) → çeviri."""
    return lambda text, temperature=0.1, timeout=600: translate_one(model_id, text, source, target, temperature,
                                                                     timeout, log)


def family(model_id: str) -> str:
    return BY_ID[model_id]["family"] if model_id in BY_ID else "chat"
