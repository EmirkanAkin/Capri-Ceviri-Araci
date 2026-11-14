"""
Capri Çoklu Yapay Zeka Çeviri Sağlayıcıları ve API Yöneticisi
================================================================
Gemini, OpenAI, Anthropic (Claude), DeepL, Ollama (Yerel),
Helsinki-NLP OPUS (Çevrimdışı) ve Meta NLLB-200 (Çevrimdışı)
için bağlantı testleri, tekli/canlı test çevirisi, model indirme ve ayar yönetimi.
"""
from __future__ import annotations

import collections
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from paths import APP_DIR
CONFIG_FILE = APP_DIR / "portable_cache" / "providers.json"
LEGACY_CONFIG_FILE = APP_DIR / "config_providers.json"
GEMINI_LEGACY_FILE = APP_DIR / "gemini_api_key.txt"

# Hugging Face Model Dosyaları ve Boyutları
OPUS_MODEL_FILES = {
    "config.json": 1_137,
    "generation_config.json": 301,
    "pytorch_model.bin": 469_780_741,
    "source.spm": 796_953,
    "target.spm": 833_391,
    "special_tokens_map.json": 65,
    "tokenizer_config.json": 337,
    "vocab.json": 1_501_287,
}

NLLB_MODEL_FILES = {
    "config.json": 846,
    "generation_config.json": 189,
    "pytorch_model.bin": 2_460_457_927,
    "sentencepiece.bpe.model": 4_852_054,
    "special_tokens_map.json": 3_548,
    "tokenizer.json": 17_331_176,
    "tokenizer_config.json": 564,
}

OPUS_BASE_URL = "https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr/resolve/main"
NLLB_BASE_URL = "https://huggingface.co/facebook/nllb-200-distilled-600M/resolve/main"


@dataclass
class ProviderConfig:
    active_provider: str = "gemini"
    # Google Gemini
    gemini_keys: List[str] = field(default_factory=list)
    gemini_model: str = "auto"  # "auto": erişilebilen tüm modelleri hız sırasıyla dene
    # OpenAI
    openai_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Anthropic Claude
    anthropic_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    # DeepL
    deepl_key: str = ""
    # Ollama (Yerel LLM)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    # Çevrimdışı Modeller
    opus_dir: str = "model"
    nllb_dir: str = "model_nllb"


PROVIDER_DISPLAY_INFO = {
    "gemini": {
        "title": "Google Gemini",
        "badge": "⚡ Ultra Hızlı Bulut",
        "badge_color": "#38bdf8",
        "category": "Bulut Yapay Zeka",
        "description": "Google'ın en yeni ve en hızlı çok dilli yapay zekası (Gemini 2.5 / 1.5 Flash). Binlerce satırı dakikalar içinde yüksek edebi akıcılıkla çevirir. Çoklu API anahtarı rotasyonunu tam destekler.",
        "requires_key": True,
        "is_offline": False,
    },
    "openai": {
        "title": "OpenAI (ChatGPT)",
        "badge": "🤖 Gelişmiş LLM",
        "badge_color": "#10a37f",
        "category": "Bulut Yapay Zeka",
        "description": "OpenAI GPT-4o ve GPT-4o-mini modelleri. Oyun içi nüansları, kelime oyunlarını ve diyalog tonunu yüksek sadakatle aktarır.",
        "requires_key": True,
        "is_offline": False,
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "badge": "🧠 Yüksek Edebi Akıcılık",
        "badge_color": "#d97706",
        "category": "Bulut Yapay Zeka",
        "description": "Claude 3.5 Sonnet ve Claude 3.5 Haiku modelleri. Roman dili, diyalog akıcılığı ve karmaşık anlatılarda sektör standartlarında edebi çeviri sağlar.",
        "requires_key": True,
        "is_offline": False,
    },
    "deepl": {
        "title": "DeepL Çeviri",
        "badge": "🌐 Makine Çevirisi Lideri",
        "badge_color": "#0ea5e9",
        "category": "Bulut Çeviri",
        "description": "DeepL Pro / Free API desteği. Dilbilgisi kurallarına sıkı sıkıya bağlı profesyonel çeviri. Ücretsiz hesaplarda ayda 500.000 karakter kotası sunar.",
        "requires_key": True,
        "is_offline": False,
    },
    "ollama": {
        "title": "Ollama (Yerel LLM)",
        "badge": "💻 Tamamen Yerel / Ücretsiz",
        "badge_color": "#a855f7",
        "category": "Yerel Yapay Zeka",
        "description": "Bilgisayarınızda yerel olarak çalışan açık kaynaklı LLM'ler (Qwen 2.5, Llama 3, Mistral). İnternet bağlantısı veya API anahtarı gerektirmez; tamamen gizli ve sınırsızdır.",
        "requires_key": False,
        "is_offline": True,
    },
    "opus": {
        "title": "Helsinki-NLP OPUS (Çevrimdışı)",
        "badge": "⚡ Kompakt Yerel Model (~470 MB)",
        "badge_color": "#30d158",
        "category": "Yerel Çevrimdışı Model",
        "description": "Helsinki-NLP Opus-MT nöral çeviri modeli. Bilgisayarınızda (GPU/CPU) tamamen internetsiz çalışır. Hafiftir, hızlıdır ve sıfır kota derdiyle sınırsız çeviri yapar.",
        "requires_key": False,
        "is_offline": True,
    },
    "nllb": {
        "title": "Meta NLLB-200 (Çevrimdışı)",
        "badge": "🌍 200 Dil Yüksek Kalite (~2.4 GB)",
        "badge_color": "#6366f1",
        "category": "Yerel Çevrimdışı Model",
        "description": "Meta AI (Facebook) NLLB-200 modeli. 200 dil arasında yüksek doğruluklu yerel nöral çeviri sağlar. Güçlü GPU'lar (CUDA) ile mükemmel performans gösterir.",
        "requires_key": False,
        "is_offline": True,
    },
}


SECRET_FIELDS = ("gemini_keys", "openai_key", "anthropic_key", "deepl_key")


def _secret_value(cfg: ProviderConfig, field_name: str) -> str:
    value = getattr(cfg, field_name)
    return "\n".join(value) if isinstance(value, list) else (value or "")


def load_provider_config() -> ProviderConfig:
    """
    Yapılandırmayı yükler. API anahtarları Windows Kimlik Bilgisi Yöneticisi'nden okunur;
    eski sürümlerin düz metin anahtarları bulunursa oraya taşınır ve dosyadan silinir.
    """
    cfg = ProviderConfig()

    # Legacy gemini_api_key.txt oku
    if GEMINI_LEGACY_FILE.exists():
        try:
            lines = [l.strip() for l in GEMINI_LEGACY_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            if lines:
                cfg.gemini_keys = lines
        except Exception:
            pass

    if not CONFIG_FILE.exists() and LEGACY_CONFIG_FILE.exists():  # eski konum (kök klasör)
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LEGACY_CONFIG_FILE.replace(CONFIG_FILE)
        except OSError:
            pass
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.active_provider = data.get("active_provider", cfg.active_provider)
            cfg.gemini_keys = data.get("gemini_keys", cfg.gemini_keys)
            cfg.gemini_model = data.get("gemini_model", cfg.gemini_model) or "auto"
            cfg.openai_key = data.get("openai_key", "")
            cfg.openai_model = data.get("openai_model", "gpt-4o-mini")
            cfg.anthropic_key = data.get("anthropic_key", "")
            cfg.anthropic_model = data.get("anthropic_model", "claude-3-5-haiku-20241022")
            cfg.deepl_key = data.get("deepl_key", "")
            cfg.ollama_host = data.get("ollama_host", "http://localhost:11434")
            cfg.ollama_model = data.get("ollama_model", "qwen2.5:7b")
            cfg.opus_dir = data.get("opus_dir", "model")
            cfg.nllb_dir = data.get("nllb_dir", "model_nllb")
        except Exception:
            pass

    import secrets_store
    if secrets_store.available():
        migrate = False
        for name in SECRET_FIELDS:
            stored = secrets_store.get(name)
            if stored is not None:
                setattr(cfg, name, [k for k in stored.splitlines() if k.strip()] if name == "gemini_keys" else stored)
            elif _secret_value(cfg, name):
                migrate = True  # düz metin anahtar bulundu → güvenli depoya taşı
        if migrate:
            save_provider_config(cfg)
    return cfg


GEMINI_MODELS_FILE = APP_DIR / "portable_cache" / "gemini_models.json"
GEMINI_FALLBACK_MODELS = [
    "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest",
    "gemini-2.5-flash", "gemini-pro-latest", "gemini-2.5-pro",
]
# Metin çevirisine uygun olmayan modeller (ses, görsel, müzik, ajan, araştırma…)
_GEMINI_EXCLUDE = re.compile(
    r"tts|image|banana|lyria|transcribe|robotics|computer-use|antigravity|deep-research|embedding|"
    r"customtools|live|audio|veo|imagen|aqa|learnlm", re.I)


def _gemini_rank(name: str) -> Tuple[int, float, int, str]:
    """Hız sırası: flash-lite → flash → diğer → pro → gemma; aynı sınıfta yeni sürüm önce."""
    n = name.lower()
    if "gemma" in n:
        tier = 4
    elif "lite" in n:
        tier = 0
    elif "flash" in n:
        tier = 1
    elif "pro" in n:
        tier = 3
    else:
        tier = 2
    version = re.search(r"(\d+(?:\.\d+)?)", n)
    ver = 99.0 if "latest" in n else float(version.group(1)) if version else 0.0
    return tier, -ver, ("preview" in n or "exp" in n), n


def gemini_models(api_key: str = "", refresh: bool = False) -> List[str]:
    """Anahtarın erişebildiği, metin üretebilen Gemini/Gemma modelleri (12 saat önbellekli)."""
    try:
        cached = json.loads(GEMINI_MODELS_FILE.read_text(encoding="utf-8"))
        if not refresh and time.time() - cached.get("time", 0) < 12 * 3600 and cached.get("models"):
            return cached["models"]
    except (OSError, ValueError):
        cached = {}
    key = api_key or next(iter(load_provider_config().gemini_keys), "")
    if not key:
        return cached.get("models") or list(GEMINI_FALLBACK_MODELS)
    try:
        resp = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                            params={"pageSize": 300}, headers={"x-goog-api-key": key}, timeout=8)
        resp.raise_for_status()
        names = [
            m["name"].split("/", 1)[-1] for m in resp.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and m["name"].split("/", 1)[-1].startswith(("gemini", "gemma"))
            and not _GEMINI_EXCLUDE.search(m["name"])
        ]
    except Exception:
        return cached.get("models") or list(GEMINI_FALLBACK_MODELS)
    models = sorted(set(names), key=_gemini_rank)
    GEMINI_MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEMINI_MODELS_FILE.write_text(json.dumps({"time": time.time(), "models": models}), encoding="utf-8")
    return models


_GEMINI_LAST_GOOD: List[str] = []  # bu oturumda en son hızlı yanıt veren model(ler)


def note_gemini_success(name: str) -> None:
    """Yanıt veren modeli bir sonraki istekte öne al (sunucu yoğunluğu modele göre değişebilir)."""
    if name in _GEMINI_LAST_GOOD:
        _GEMINI_LAST_GOOD.remove(name)
    _GEMINI_LAST_GOOD.insert(0, name)
    del _GEMINI_LAST_GOOD[3:]


def gemini_model_order(preferred: str = "auto", api_key: str = "") -> List[str]:
    """Denenecek model sırası: (seçilen model) + son başarılı + keşfedilen tüm modeller + yedek liste."""
    order: List[str] = []
    head = [preferred] if preferred and preferred != "auto" else []
    for name in head + list(_GEMINI_LAST_GOOD) + gemini_models(api_key) + GEMINI_FALLBACK_MODELS:
        if name and name not in order:
            order.append(name)
    return order


def save_provider_config(cfg: ProviderConfig) -> None:
    """
    Yapılandırmayı kaydeder. Anahtarlar Windows Kimlik Bilgisi Yöneticisi'ne yazılır ve geri
    okunarak doğrulanır; doğrulanırsa JSON'da düz metin tutulmaz. Depo kullanılamazsa eski davranış.
    """
    import secrets_store
    secure = secrets_store.available()
    if secure:
        for name in SECRET_FIELDS:
            value = _secret_value(cfg, name)
            if not secrets_store.set(name, value) or (secrets_store.get(name) or "") != value:
                secure = False
                break
    data = {
        "active_provider": cfg.active_provider,
        "gemini_keys": cfg.gemini_keys,
        "gemini_model": cfg.gemini_model,
        "openai_key": cfg.openai_key,
        "openai_model": cfg.openai_model,
        "anthropic_key": cfg.anthropic_key,
        "anthropic_model": cfg.anthropic_model,
        "deepl_key": cfg.deepl_key,
        "ollama_host": cfg.ollama_host,
        "ollama_model": cfg.ollama_model,
        "opus_dir": cfg.opus_dir,
        "nllb_dir": cfg.nllb_dir,
    }
    if secure:
        data.update({"gemini_keys": [], "openai_key": "", "anthropic_key": "", "deepl_key": "",
                     "secrets": "windows-credential-manager"})
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    if secure:
        if GEMINI_LEGACY_FILE.exists():
            send_to_recycle_bin(GEMINI_LEGACY_FILE)  # eski düz metin anahtar dosyası
    elif cfg.gemini_keys:
        GEMINI_LEGACY_FILE.write_text("\n".join(cfg.gemini_keys) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# BAĞLANTI TESTLERİ
# ─────────────────────────────────────────────────────────────

def test_gemini_connection(api_key: str, model: str = "auto") -> Tuple[bool, int, str]:
    """Gemini API anahtarını test eder; çalışan ilk modeli bulana kadar sırayla dener."""
    if not api_key:
        return False, 0, "API anahtarı girilmedi."
    payload = {"contents": [{"parts": [{"text": "Translate 'Hello' to Turkish. Reply with one word."}]}]}
    last = ""
    models = gemini_model_order(model, api_key)
    for name in models[:8]:
        t0 = time.monotonic()
        try:
            resp = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent",
                                 headers={"x-goog-api-key": api_key}, json=payload, timeout=10)
        except Exception as e:
            last = f"Bağlantı hatası: {e}"
            continue
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 200:
            return True, latency, f"Bağlantı başarılı ({latency} ms) · {name} · {len(models)} model erişilebilir"
        if resp.status_code in (400, 401, 403) and "API key" in resp.text:
            return False, latency, f"Geçersiz API anahtarı ({resp.status_code})."
        last = f"{name}: HTTP {resp.status_code}"
    return False, 0, f"Hiçbir model yanıt vermedi ({last})."


def test_openai_connection(api_key: str, model: str = "gpt-4o-mini") -> Tuple[bool, int, str]:
    """OpenAI API bağlantısını test eder."""
    if not api_key:
        return False, 0, "OpenAI API anahtarı girilmedi."

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }
    t0 = time.monotonic()
    try:
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=8)
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 200:
            return True, latency, f"Bağlantı Başarılı ({latency} ms) — {model} Hazır"
        else:
            return False, latency, f"OpenAI Hatası {resp.status_code}: {resp.json().get('error', {}).get('message', resp.text[:100])}"
    except Exception as e:
        return False, 0, f"Bağlantı hatası: {e}"


def test_anthropic_connection(api_key: str, model: str = "claude-3-5-haiku-20241022") -> Tuple[bool, int, str]:
    """Anthropic (Claude) API bağlantısını test eder."""
    if not api_key:
        return False, 0, "Anthropic API anahtarı girilmedi."

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "ping"}],
    }
    t0 = time.monotonic()
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=8)
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 200:
            return True, latency, f"Bağlantı Başarılı ({latency} ms) — Claude Hazır"
        else:
            return False, latency, f"Claude Hatası {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, 0, f"Bağlantı hatası: {e}"


def test_deepl_connection(api_key: str) -> Tuple[bool, int, str]:
    """DeepL API bağlantısını ve kalan kotayı test eder."""
    if not api_key:
        return False, 0, "DeepL API anahtarı girilmedi."

    endpoint = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    t0 = time.monotonic()
    try:
        resp = requests.get(f"{endpoint}/v2/usage", headers=headers, timeout=8)
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 200:
            data = resp.json()
            used = data.get("character_count", 0)
            limit = data.get("character_limit", 0)
            return True, latency, f"Bağlantı Başarılı ({latency} ms) — Kota: {used:,} / {limit:,} karakter"
        else:
            return False, latency, f"DeepL Hatası {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, 0, f"Bağlantı hatası: {e}"


def test_ollama_service(host: str = "http://localhost:11434") -> Tuple[bool, List[str], str]:
    """
    Ollama yerel servisinin çalışıp çalışmadığını denetler ve
    yüklü modellerin listesini döndürür.
    """
    clean_host = (host or "http://localhost:11434").rstrip("/")
    t0 = time.monotonic()
    try:
        resp = requests.get(f"{clean_host}/api/tags", timeout=4)
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            if models:
                return True, models, f"Ollama Servisi Aktif ({latency} ms) — {len(models)} model yüklü"
            else:
                return True, [], f"Ollama Aktif ama hiç model yüklenmemiş. 'ollama pull qwen2.5:7b' çalıştırın."
        else:
            return False, [], f"Ollama HTTP {resp.status_code} yanıtı verdi."
    except Exception:
        return False, [], "Ollama servisi çalışmıyor! Lütfen Ollama uygulamasını başlatın veya komut satırından 'ollama serve' yazın."


# ─────────────────────────────────────────────────────────────
# ÇEVRİMDIŞI MODELLER (OPUS & NLLB) KONTROL VE İNDİRME
# ─────────────────────────────────────────────────────────────

def resolve_model_dir(folder_name: str) -> Path:
    """Model klasörünü mevcut uygulama veya kök dizinlerden bulur."""
    candidates = [
        APP_DIR / folder_name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return APP_DIR / folder_name


def get_offline_model_status(kind: str, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Çevrimdışı modelin (OPUS veya NLLB) disk durumunu analiz eder:
    - Kurulmuş mu?
    - Kaç dosya mevcut / eksik?
    - Toplam disk boyutu nedir?
    """
    if kind == "nllb":
        m_dir = resolve_model_dir("model_nllb")
        expected = NLLB_MODEL_FILES
        base_url = NLLB_BASE_URL
        label = "Meta NLLB-200"
    else:
        m_dir = resolve_model_dir("model")
        expected = OPUS_MODEL_FILES
        base_url = OPUS_BASE_URL
        label = "Helsinki-NLP OPUS"

    missing = []
    total_bytes = 0
    present_count = 0

    compact = (m_dir / "model.safetensors").is_file() and not (m_dir / "pytorch_model.bin").is_file()
    if m_dir.exists():
        for fname, exp_sz in expected.items():
            fpath = m_dir / fname
            if fname == "pytorch_model.bin" and compact:
                fpath, exp_sz = m_dir / "model.safetensors", exp_sz // 2 - 1_000_000
            if fpath.exists() and fpath.stat().st_size >= max(1, exp_sz - 16):
                present_count += 1
                total_bytes += fpath.stat().st_size
            else:
                missing.append(fname)
    else:
        missing = list(expected.keys())

    is_ready = len(missing) == 0 and present_count == len(expected)
    total_expected_bytes = sum(expected.values())

    return {
        "kind": kind,
        "label": label,
        "dir": str(m_dir),
        "is_ready": is_ready,
        "present_count": present_count,
        "total_files": len(expected),
        "missing_files": missing,
        "size_mb": round(total_bytes / (1024 * 1024), 1),
        "expected_mb": round((total_expected_bytes - expected["pytorch_model.bin"]
                              + (m_dir / "model.safetensors").stat().st_size if compact else total_expected_bytes) / (1024 * 1024), 1),
        "compact": compact,
        "base_url": base_url,
    }


def download_offline_model(
    kind: str,
    base_dir: Optional[Path] = None,
    log: Callable[[str], None] = print,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> bool:
    """
    OPUS veya NLLB çevrimdışı modelini Hugging Face üzerinden indirir.
    Gerektiğinde curl fallback desteği sunar.
    """
    base = base_dir or APP_DIR
    if kind == "nllb":
        m_dir = base / "model_nllb"
        expected = NLLB_MODEL_FILES
        base_url = NLLB_BASE_URL
        label = "Meta NLLB-200"
    else:
        m_dir = base / "model"
        expected = OPUS_MODEL_FILES
        base_url = OPUS_BASE_URL
        label = "Helsinki-NLP OPUS"

    m_dir.mkdir(parents=True, exist_ok=True)
    log(f"📥 {label} modeli indirme işlemi başlatılıyor -> {m_dir}")

    total_files = len(expected)
    compact = (m_dir / "model.safetensors").is_file()
    for idx, (name, exp_size) in enumerate(expected.items(), 1):
        target = m_dir / name
        if name == "pytorch_model.bin" and compact:
            log(f"✔ [{idx}/{total_files}] fp16 model mevcut: model.safetensors")
            continue
        if target.exists() and target.stat().st_size >= max(1, exp_size - 16):
            log(f"✔ [{idx}/{total_files}] Zaten mevcut: {name}")
            continue

        url = f"{base_url}/{name}"
        temp_file = target.with_suffix(target.suffix + ".part")
        log(f"⬇ [{idx}/{total_files}] İndiriliyor: {name} ({exp_size / (1024*1024):.1f} MB)...")

        if progress_callback:
            progress_callback(idx, total_files, f"İndiriliyor: {name}")

        download_success = False
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Capri-Downloader/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, temp_file.open("wb") as out:
                shutil.copyfileobj(resp, out, length=1024 * 1024)
            download_success = True
        except Exception as err:
            log(f"Standart indirme hatası: {err}. curl ile deneniyor...")
            curl = shutil.which("curl.exe") or shutil.which("curl")
            if curl:
                res = subprocess.run(
                    [curl, "-k", "-fL", "--retry", "3", "-o", str(temp_file), url],
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                )
                if res.returncode == 0:
                    download_success = True

        if download_success and temp_file.exists():
            if target.exists():
                target.unlink()
            temp_file.rename(target)
            log(f"✔ Dosya tamamlandı: {name}")
        else:
            if temp_file.exists():
                temp_file.unlink()
            raise RuntimeError(f"{name} indirilemedi! İnternet bağlantınızı kontrol edin: {url}")

    log(f"🎉 {label} modeli tamamen indirildi ve kullanıma hazır!")
    return True


def send_to_recycle_bin(path: Path) -> bool:
    """Dosyayı kalıcı silmek yerine Geri Dönüşüm Kutusu'na taşır (geri alınabilir)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW(None, 3, str(Path(path).resolve()) + "\0\0", None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not Path(path).exists()


LLM_PROVIDERS = ("gemini", "openai", "anthropic", "ollama")


def llm_complete(provider: str, system: str, user: str, cfg: Optional[ProviderConfig] = None,
                 max_tokens: int = 8192) -> str:
    """Sohbet modelinden ham metin yanıtı alır (kalite editörü gibi serbest biçimli işler için)."""
    cfg = cfg or load_provider_config()
    if provider == "gemini":
        key = next(iter(cfg.gemini_keys), "")
        if not key:
            raise RuntimeError("Gemini API anahtarı yok.")
        payload = {
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
            "safetySettings": [{"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")],
        }
        ok, text = _gemini_hedged(gemini_model_order(cfg.gemini_model, key), key, payload, raw=True)
        if not ok:
            raise RuntimeError(f"Gemini: {text}")
        return text
    if provider == "openai":
        resp = requests.post(OPENAI_URL, timeout=180, headers={"Authorization": f"Bearer {cfg.openai_key}"}, json={
            "model": cfg.openai_model or "gpt-4o-mini", "temperature": 0.2, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system + '\nYanıtı {"items": [...]} nesnesi olarak ver.'},
                         {"role": "user", "content": user}]})
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI HTTP {resp.status_code}: {resp.text[:160]}")
        return resp.json()["choices"][0]["message"]["content"]
    if provider == "anthropic":
        resp = requests.post(ANTHROPIC_URL, timeout=180, headers={
            "x-api-key": cfg.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": cfg.anthropic_model or "claude-3-5-haiku-20241022", "max_tokens": max_tokens,
                  "temperature": 0.2, "system": system, "messages": [{"role": "user", "content": user}]})
        if resp.status_code != 200:
            raise RuntimeError(f"Claude HTTP {resp.status_code}: {resp.text[:160]}")
        return "".join(part.get("text", "") for part in resp.json().get("content", []))
    if provider == "ollama":
        resp = requests.post(f"{(cfg.ollama_host or 'http://localhost:11434').rstrip('/')}/api/chat", timeout=600, json={
            "model": cfg.ollama_model or "qwen2.5:7b", "stream": False, "format": "json",
            "options": {"temperature": 0.2, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status_code}")
        return resp.json()["message"]["content"]
    raise RuntimeError(f"{provider} serbest metin üretemez (kalite editörü için Gemini, OpenAI, Claude veya Ollama gerekir).")


def compact_offline_model(kind: str, log: Callable[[str], None] = print) -> Dict[str, Any]:
    """
    Yerel modeli fp16 safetensors biçimine dönüştürür (boyut yarıya iner, yükleme hızlanır).
    Yeni dosya deneme çevirisiyle doğrulanır; eski pytorch_model.bin Geri Dönüşüm Kutusu'na taşınır.
    """
    import tempfile
    import torch
    m_dir = resolve_model_dir("model_nllb" if kind == "nllb" else "model")
    bin_path, st_path = m_dir / "pytorch_model.bin", m_dir / "model.safetensors"
    if st_path.is_file() and not bin_path.is_file():
        return {"ok": True, "already": True, "size_mb": round(st_path.stat().st_size / 1048576, 1)}
    if not bin_path.is_file():
        return {"ok": False, "msg": "Model dosyası bulunamadı."}
    release_offline_engines()
    sample = ["Welcome to our tavern, hero! What brings you here tonight?", "The door is locked."]
    from engine_common import TranslationEngine

    def translate(label: str) -> List[str]:
        t0 = time.perf_counter()
        engine = TranslationEngine(model_dir=m_dir, model_kind=kind, log=log)
        engine.load_model()
        load_s = time.perf_counter() - t0
        out = engine.translate_batch(sample)
        engine.unload_model()
        log(f"{label}: yükleme {load_s:.1f} sn")
        return [out[x] for x in sample] + [round(load_s, 1)]

    before = translate("Orijinal model")
    log("fp16 safetensors oluşturuluyor…")
    if kind == "nllb":
        from transformers import AutoModelForSeq2SeqLM as Cls
    else:
        from transformers import MarianMTModel as Cls
    model = Cls.from_pretrained(str(m_dir), dtype=torch.float16, local_files_only=True, use_safetensors=False)
    with tempfile.TemporaryDirectory(dir=str(m_dir.parent)) as tmp:
        model.save_pretrained(tmp, safe_serialization=True)
        del model
        produced = Path(tmp) / "model.safetensors"
        if not produced.is_file():
            return {"ok": False, "msg": "safetensors dosyası üretilemedi."}
        partial = st_path.with_suffix(".safetensors.part")
        shutil.move(str(produced), str(partial))
        partial.replace(st_path)
    after = translate("fp16 model")  # transformers artık model.safetensors'ı yükler
    same = sum(a == b for a, b in zip(before[:-1], after[:-1]))
    if not all(after[:-1]):
        st_path.unlink(missing_ok=True)
        return {"ok": False, "msg": "fp16 model doğrulanamadı; orijinal korundu."}
    old_mb = round(bin_path.stat().st_size / 1048576, 1)
    recycled = send_to_recycle_bin(bin_path)
    return {
        "ok": True, "old_mb": old_mb, "size_mb": round(st_path.stat().st_size / 1048576, 1),
        "load_before": before[-1], "load_after": after[-1], "identical": f"{same}/{len(sample)}",
        "sample": after[0], "recycled": recycled,
    }


# ─────────────────────────────────────────────────────────────
# CANLI ÖNİZLEME VE TEKLİ TEST ÇEVİRİSİ
# ─────────────────────────────────────────────────────────────

GEMINI_HEDGE_DELAY = 2.5   # sn: ilk model bu sürede yanıt vermezse sıradaki de paralel denenir
GEMINI_MAX_PARALLEL = 3


def _gemini_hedged(models: List[str], key: str, payload: Dict[str, Any], raw: bool = False) -> Tuple[bool, str]:
    """
    Modelleri sırayla dener; yavaş kalan model beklenirken sıradakini de paralel başlatır
    ve ilk başarılı yanıtı döndürür. (başarı, metin_veya_hata) döner.
    """
    import concurrent.futures as cf

    def one(name: str) -> Tuple[bool, str, bool]:
        try:
            resp = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent",
                                 headers={"x-goog-api-key": key}, json=payload, timeout=30)
        except Exception as e:
            return False, f"{name}: {e.__class__.__name__}", False
        if resp.status_code != 200:
            return False, f"{name}: HTTP {resp.status_code}", resp.status_code in (401, 403)
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            if raw:
                return True, text, False
            parsed = _parse_json_list(text)
            return True, str(parsed[0] if parsed else text.strip()), False
        except (KeyError, IndexError, ValueError) as e:
            return False, f"{name}: yanıt okunamadı ({e})", False

    remaining = iter(models)
    pool = cf.ThreadPoolExecutor(max_workers=GEMINI_MAX_PARALLEL)
    pending: Dict[Any, str] = {}
    errors: List[str] = []

    def launch() -> bool:
        name = next(remaining, None)
        if name:
            pending[pool.submit(one, name)] = name
        return bool(name)

    launch()
    deadline = time.monotonic() + 60
    try:
        while pending and time.monotonic() < deadline:
            done, _ = cf.wait(list(pending), timeout=GEMINI_HEDGE_DELAY, return_when=cf.FIRST_COMPLETED)
            if not done:
                if len(pending) < GEMINI_MAX_PARALLEL:
                    launch()  # yavaş model: beklemeye devam ederken sıradakini de dene
                continue
            for future in done:
                name = pending.pop(future)
                ok, value, fatal = future.result()
                if ok:
                    note_gemini_success(name)
                    return True, value
                errors.append(value)
                if fatal:
                    return False, value
                launch()
        return False, "; ".join(errors[-3:]) or "zaman aşımı"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

# Önizleme için yüklenen yerel modeller bellekte tutulur; her istekte
# modeli diskten yeniden yüklemek (~5 sn) yerine tek seferlik maliyet.
_OFFLINE_ENGINES: Dict[str, Any] = {}
_OFFLINE_LOCK = threading.Lock()


def _offline_engine(kind: str, log: Callable[[str], None]):
    with _OFFLINE_LOCK:
        engine = _OFFLINE_ENGINES.get(kind)
        if engine is None:
            from engine_common import TranslationEngine
            m_dir = resolve_model_dir("model_nllb" if kind == "nllb" else "model")
            engine = TranslationEngine(model_dir=m_dir, model_kind=kind, log=log)
            engine.load_model()
            _OFFLINE_ENGINES[kind] = engine
        return engine


def release_offline_engines() -> None:
    """Önizleme modellerini bellekten (VRAM) boşaltır."""
    with _OFFLINE_LOCK:
        for engine in _OFFLINE_ENGINES.values():
            try:
                engine.unload_model()
            except Exception:
                pass
        _OFFLINE_ENGINES.clear()

def translate_single_text(
    text: str,
    provider_id: str,
    target_lang: str = "tr",
    source_lang: str = "en",
    cfg: Optional[ProviderConfig] = None,
    nsfw_mode: bool = False,
    log: Callable[[str], None] = print,
    max_tokens: int = 2048,
) -> Tuple[bool, str, int]:
    """
    Seçilen sağlayıcı ile bir metni (tek cümle ya da çok satırlı) çevirir ve
    (başarı, çevrilen_metin, gecikme_ms) üçlüsünü döndürür.
    """
    if not text.strip():
        return False, "Metin boş.", 0

    if cfg is None:
        cfg = load_provider_config()

    p_id = provider_id.casefold()
    t0 = time.monotonic()

    # 1. Google Gemini
    if p_id == "gemini":
        from engine_renpy import load_gemini_api_key
        key = cfg.gemini_keys[0] if cfg.gemini_keys else load_gemini_api_key()
        if not key:
            return False, "Gemini API Anahtarı bulunamadı! 'API ve Ajanlar' sekmesinden ekleyin.", 0

        nsfw_prompt = " Argo ve yetişkin sahneleri sansürsüz, doğal günlük konuşma diliyle çevir." if nsfw_mode else ""
        source_name = "the source language (detect it)" if source_lang == "auto" else source_lang
        system = (f"Translate the following game text from {source_name} to {target_lang}. Keep line breaks, "
                  f"tags and variables exactly. Return ONLY a valid JSON array with 1 string.{nsfw_prompt}")
        payload = {
            "contents": [{"parts": [{"text": f"{system}\n\n[ {json.dumps(text, ensure_ascii=False)} ]"}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max(256, max_tokens),
                                 "responseMimeType": "application/json"},
            "safetySettings": [{"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")],
        }
        ok, result = _gemini_hedged(gemini_model_order(cfg.gemini_model, key), key, payload)
        if ok:
            return True, result, int((time.monotonic() - t0) * 1000)
        return False, "Gemini: hiçbir model çeviremedi — " + result, int((time.monotonic() - t0) * 1000)

    # 2. OpenAI
    elif p_id == "openai":
        if not cfg.openai_key:
            return False, "OpenAI API Anahtarı girilmedi.", 0

        headers = {"Authorization": f"Bearer {cfg.openai_key}", "Content-Type": "application/json"}
        nsfw_prompt = " Argo ve yetişkin diyalogları sansürsüz, doğal aktar." if nsfw_mode else ""
        system = f"You are a professional video game translator. Translate from {source_lang} to {target_lang}. Return ONLY the direct translation of the sentence.{nsfw_prompt}"
        payload = {
            "model": cfg.openai_model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        try:
            resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=12)
            lat = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                res = resp.json()["choices"][0]["message"]["content"].strip()
                return True, res, lat
            return False, f"OpenAI Hatası {resp.status_code}: {resp.text[:120]}", lat
        except Exception as e:
            return False, f"OpenAI Hatası: {e}", 0

    # 3. Anthropic (Claude)
    elif p_id == "anthropic":
        if not cfg.anthropic_key:
            return False, "Anthropic API Anahtarı girilmedi.", 0

        headers = {
            "x-api-key": cfg.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        system = f"Translate this gaming text from {source_lang} to {target_lang}. Return ONLY the translation."
        payload = {
            "model": cfg.anthropic_model or "claude-3-5-haiku-20241022",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": text}],
        }
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=12)
            lat = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                res = resp.json()["content"][0]["text"].strip()
                return True, res, lat
            return False, f"Claude Hatası {resp.status_code}: {resp.text[:120]}", lat
        except Exception as e:
            return False, f"Claude Hatası: {e}", 0

    # 4. DeepL
    elif p_id == "deepl":
        if not cfg.deepl_key:
            return False, "DeepL API Anahtarı girilmedi.", 0

        endpoint = "https://api-free.deepl.com" if cfg.deepl_key.endswith(":fx") else "https://api.deepl.com"
        headers = {"Authorization": f"DeepL-Auth-Key {cfg.deepl_key}"}
        payload = {
            "text": [text],
            "target_lang": DEEPL_LANGS.get(target_lang, target_lang.upper()),
        }
        if source_lang and source_lang != "auto":
            payload["source_lang"] = source_lang.split("-")[0].upper()
        try:
            resp = requests.post(f"{endpoint}/v2/translate", headers=headers, json=payload, timeout=10)
            lat = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                res = data["translations"][0]["text"]
                return True, res, lat
            return False, f"DeepL Hatası {resp.status_code}: {resp.text[:120]}", lat
        except Exception as e:
            return False, f"DeepL Hatası: {e}", 0

    # 5. Ollama
    elif p_id == "ollama":
        clean_host = (cfg.ollama_host or "http://localhost:11434").rstrip("/")
        system = f"Translate from {source_lang} to {target_lang}. Output ONLY the translated text."
        payload = {
            "model": cfg.ollama_model or "qwen2.5:7b",
            "prompt": f"{system}\n\nText: {text}\n\nTranslation:",
            "stream": False,
        }
        try:
            resp = requests.post(f"{clean_host}/api/generate", json=payload, timeout=20)
            lat = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                res = resp.json().get("response", "").strip()
                return True, res, lat
            return False, f"Ollama HTTP {resp.status_code}", lat
        except Exception as e:
            return False, f"Ollama Bağlantı Hatası: {e}", 0

    # 6. Helsinki-NLP OPUS (Çevrimdışı)
    elif p_id == "opus":
        status = get_offline_model_status("opus")
        if not status["is_ready"]:
            return False, f"OPUS modeli eksik ({status['present_count']}/{status['total_files']} dosya). 'Yerel Modeller' sekmesinden indirin.", 0
        try:
            engine = _offline_engine("opus", log)
            lines = text.split("\n")
            with _OFFLINE_LOCK:
                res = engine.translate_batch([ln for ln in lines if ln.strip()])
            lat = int((time.monotonic() - t0) * 1000)
            return True, "\n".join(res.get(ln, ln) if ln.strip() else ln for ln in lines), lat
        except Exception as e:
            return False, f"OPUS Çeviri Hatası: {e}", 0

    # 7. Meta NLLB-200 (Çevrimdışı)
    elif p_id == "nllb":
        status = get_offline_model_status("nllb")
        if not status["is_ready"]:
            return False, f"NLLB-200 modeli eksik ({status['present_count']}/{status['total_files']} dosya). 'Yerel Modeller' sekmesinden indirin.", 0
        try:
            engine = _offline_engine("nllb", log)
            lines = text.split("\n")
            with _OFFLINE_LOCK:
                engine.set_languages(source_lang, target_lang)
                res = engine.translate_batch([ln for ln in lines if ln.strip()])
            lat = int((time.monotonic() - t0) * 1000)
            return True, "\n".join(res.get(ln, ln) if ln.strip() else ln for ln in lines), lat
        except Exception as e:
            return False, f"NLLB-200 Çeviri Hatası: {e}", 0

    return False, f"Bilinmeyen model: {provider_id}", 0


# ─────────────────────────────────────────────────────────────
# BULUT SAĞLAYICILARIYLA TOPLU (TAM OYUN) ÇEVİRİ — OpenAI / Claude / DeepL
# ─────────────────────────────────────────────────────────────

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEEPL_URLS = {"free": "https://api-free.deepl.com/v2/translate", "pro": "https://api.deepl.com/v2/translate"}
CLOUD_FLUSH_INTERVAL = 5.0

# Oyun etiketleri / değişkenleri: çeviride birebir korunmaları gerekir
CLOUD_PROTECTED = re.compile(
    r"\\[A-Za-z]+\[[^\]\r\n]*\]|\[[^\[\]\r\n]+\]|\{[^{}\r\n]+\}|%(?:\d+\$)?[sdif]|<[^<>\r\n]+>|\\[nrt]"
)
DEEPL_LANGS = {"en": "EN-US", "pt": "PT-PT", "pt-BR": "PT-BR", "zh-CN": "ZH-HANS", "zh-TW": "ZH-HANT"}


def placeholders_valid(source: str, target: str) -> bool:
    return collections.Counter(CLOUD_PROTECTED.findall(source)) == collections.Counter(CLOUD_PROTECTED.findall(target))


def _parse_json_list(raw: str) -> Optional[List[Any]]:
    raw = re.sub(r"^\s*`{3}(?:json)?\s*|\s*`{3}\s*$", "", raw.strip(), flags=re.I)
    try:
        data = json.loads(raw)
    except ValueError:
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), None)
    return data if isinstance(data, list) else None


def _llm_batch(provider: str, items: List[str], system: str, cfg: ProviderConfig) -> Optional[List[str]]:
    user = "Çevrilecek liste:\n" + json.dumps(items, ensure_ascii=False)
    if provider == "openai":
        resp = requests.post(OPENAI_URL, timeout=120, headers={"Authorization": f"Bearer {cfg.openai_key}"}, json={
            "model": cfg.openai_model or "gpt-4o-mini",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + '\nYanıtı {"translations": [...]} biçiminde bir JSON nesnesi olarak ver.'},
                {"role": "user", "content": user},
            ],
        })
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI HTTP {resp.status_code}: {resp.text[:160]}")
        raw = resp.json()["choices"][0]["message"]["content"]
    else:
        resp = requests.post(ANTHROPIC_URL, timeout=120, headers={
            "x-api-key": cfg.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
        }, json={
            "model": cfg.anthropic_model or "claude-3-5-haiku-20241022",
            "max_tokens": 8192,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Claude HTTP {resp.status_code}: {resp.text[:160]}")
        raw = "".join(part.get("text", "") for part in resp.json().get("content", []))
    parsed = _parse_json_list(raw)
    if parsed is None or len(parsed) != len(items):
        return None
    return ["" if x is None else str(x) for x in parsed]


def _deepl_batch(items: List[str], target_lang: str, source_lang: str, cfg: ProviderConfig) -> List[str]:
    """Etiketler <k> ile işaretlenir ve DeepL'e çevirmemesi söylenir."""
    def protect(text: str) -> str:
        out, last = [], 0
        for m in CLOUD_PROTECTED.finditer(text):
            out.append(html.escape(text[last:m.start()], quote=False))
            out.append(f"<k>{html.escape(m.group(0), quote=False)}</k>")
            last = m.end()
        out.append(html.escape(text[last:], quote=False))
        return "".join(out)

    def unprotect(text: str) -> str:
        return html.unescape(re.sub(r"</?k>", "", text))

    payload: Dict[str, Any] = {
        "text": [protect(t) for t in items],
        "target_lang": DEEPL_LANGS.get(target_lang, target_lang.upper()),
        "tag_handling": "xml",
        "ignore_tags": ["k"],
    }
    if source_lang and source_lang != "auto":
        payload["source_lang"] = source_lang.split("-")[0].upper()
    url = DEEPL_URLS["free" if cfg.deepl_key.endswith(":fx") else "pro"]
    resp = requests.post(url, timeout=60, headers={"Authorization": f"DeepL-Auth-Key {cfg.deepl_key}"}, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"DeepL HTTP {resp.status_code}: {resp.text[:160]}")
    return [unprotect(t["text"]) for t in resp.json()["translations"]]


def translate_with_cloud(
    provider: str,
    missing: List[str],
    cache: Dict[str, str],
    cache_path: Path,
    cfg: Optional[ProviderConfig] = None,
    log: Callable[[str], None] = print,
    progress: Optional[Callable[[int, int], None]] = None,
    target_lang: str = "tr",
    source_lang: str = "en",
    game_engine: str = "video game",
    failed_out: Optional[set] = None,
    extra_instruction: str = "",
) -> int:
    """
    OpenAI, Claude veya DeepL ile satırları toplu çevirir ve `cache` sözlüğüne
    yazar. Geçersiz yanıt alınan satırlar kaynak metinle bırakılır, `failed_out`
    kümesine eklenir ve diske yazılmaz (sonraki çalıştırmada yeniden denenir).
    """
    if not missing:
        return 0
    cfg = cfg or load_provider_config()
    key = {"openai": cfg.openai_key, "anthropic": cfg.anthropic_key, "deepl": cfg.deepl_key}.get(provider)
    label = PROVIDER_DISPLAY_INFO[provider]["title"]
    if not key:
        raise RuntimeError(f"{label} API anahtarı girilmemiş.")
    from languages import build_system_instruction
    system = build_system_instruction(target_lang, source_lang, game_engine)
    if extra_instruction:
        system += "\n\n" + extra_instruction
    failed = failed_out if failed_out is not None else set()
    batch_size = 50 if provider == "deepl" else 40
    total, done, last_flush = len(missing), 0, time.monotonic()
    log(f"{label} ile {total} benzersiz satır çevriliyor… [Hedef: {target_lang}]")

    def flush() -> None:
        data = {k: v for k, v in cache.items() if k not in failed}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_path)

    def translate_items(items: List[str]) -> List[Optional[str]]:
        for attempt in range(3):
            try:
                if provider == "deepl":
                    return list(_deepl_batch(items, target_lang, source_lang, cfg))
                result = _llm_batch(provider, items, system, cfg)
                if result is not None:
                    return list(result)
                break  # satır sayısı uyuşmadı: bölerek dene
            except RuntimeError as err:
                if "HTTP 429" in str(err) or "HTTP 5" in str(err):
                    time.sleep(2 + attempt * 3)
                    continue
                raise
            except requests.RequestException:
                time.sleep(2 + attempt * 3)
        if len(items) > 1:
            mid = len(items) // 2
            return translate_items(items[:mid]) + translate_items(items[mid:])
        return [None]

    for i in range(0, total, batch_size):
        chunk = missing[i:i + batch_size]
        try:
            results = translate_items(chunk)
        except RuntimeError as err:
            log(f"Uyarı: {err}")
            results = [None] * len(chunk)
        for src, tr in zip(chunk, results):
            if tr and placeholders_valid(src, tr):
                cache[src] = tr
                failed.discard(src)
            else:
                cache[src] = src
                failed.add(src)
        done += len(chunk)
        if done >= total or time.monotonic() - last_flush >= CLOUD_FLUSH_INTERVAL:
            flush()
            last_flush = time.monotonic()
        log(f"{label} Çevrildi: {done}/{total}")
        if progress:
            try:
                progress(done, total)
            except BaseException:
                flush()  # iptalde ilerleme kaybolmasın
                raise
    if failed:
        log(f"Uyarı: {len(failed)} satır {label} yanıtı geçersiz olduğu için kaynak metinle bırakıldı.")
    return done
