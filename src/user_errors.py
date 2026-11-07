"""
Capri — Hataları kullanıcının anlayacağı dile çevirme
=====================================================
`describe_error` bir istisnayı {title, hint, detail, action} sözlüğüne çevirir: ne oldu, ne yapmalı,
teknik ayrıntı ve varsa ilgili sayfaya giden düğme. Teknik metin yalnızca "Ayrıntılar" altında görünür.
"""
from __future__ import annotations

import errno
import socket
import urllib.error
from typing import Any, Dict, Optional

AI_MODULES = {"torch", "transformers", "tokenizers", "safetensors", "sentencepiece", "sacremoses", "huggingface_hub"}
PROVIDERS_ACTION = {"label": "Sağlayıcılara git", "page": "providers"}
MODELS_ACTION = {"label": "Yerel modellere git", "page": "models"}


def _result(title: str, hint: str, detail: str, action: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {"title": title, "hint": hint, "detail": detail, "action": action}


def describe_error(exc: BaseException) -> Dict[str, Any]:
    detail = f"{type(exc).__name__}: {exc}"
    text = str(exc).lower()

    if isinstance(exc, MemoryError) or "out of memory" in text:
        return _result("Bellek yetmedi",
                       "Diğer uygulamaları kapatıp tekrar dene. Sürerse bulut motoruna geç; yapılan çeviriler kaybolmadı.",
                       detail, MODELS_ACTION)
    if isinstance(exc, ImportError):
        module = (getattr(exc, "name", "") or "").split(".")[0]
        if module in AI_MODULES:
            return _result("Yerel model ortamı eksik",
                           "Bu motor için gereken kütüphaneler kurulu değil. Yerel Modeller sayfasından tek tıkla kurabilirsin.",
                           detail, MODELS_ACTION)
        return _result("Uygulamanın bir parçası eksik",
                       "Bu bir Capri paketleme hatası. Son sürümü indirip aynı klasöre açman sorunu çözer; ayarların ve "
                       "çevirilerin korunur.", detail, {"label": "Güncellemeleri kontrol et", "update": True})
    if any(k in text for k in ("resource_exhausted", "quota", "rate limit", "too many requests", " 429")):
        return _result("API kotası doldu",
                       "Sağlayıcının kullanım sınırına ulaşıldı. Biraz bekleyip kaldığın yerden devam et ya da başka bir "
                       "anahtar ekle. Yapılan çeviriler kaybolmadı.", detail, PROVIDERS_ACTION)
    if any(k in text for k in ("api key", "api_key", "permission_denied", "unauthorized", "invalid_api", " 401", " 403")):
        return _result("API anahtarı kabul edilmedi",
                       "Anahtar yanlış, süresi dolmuş ya da yetkisiz olabilir. Sağlayıcılar sayfasından kontrol et.",
                       detail, PROVIDERS_ACTION)
    if isinstance(exc, PermissionError):
        return _result("Oyun dosyalarına yazılamadı",
                       "Oyun açıksa kapat. Klasör Program Files altındaysa Capri'yi yönetici olarak çalıştır ya da oyunu "
                       "başka bir klasöre taşı.", detail)
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return _result("Diskte yer kalmadı", "Biraz yer açıp kaldığın yerden devam et.", detail)
    if isinstance(exc, FileNotFoundError):
        return _result("Dosya bulunamadı",
                       "Oyun klasörü taşınmış ya da silinmiş olabilir. Oyun dosyalarını doğrulayıp yeniden dene.", detail)
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in text or "timeout" in text:
        return _result("Sunucu yanıt vermedi", "Bağlantın yavaş ya da sağlayıcı yoğun olabilir. Biraz sonra tekrar dene.", detail)
    if isinstance(exc, (ConnectionError, urllib.error.URLError)) or any(
            k in text for k in ("connection", "name resolution", "getaddrinfo", "ssl")):
        return _result("İnternet bağlantısı kurulamadı",
                       "Bağlantını kontrol edip kaldığın yerden devam et. Yapılan çeviriler kaybolmadı.", detail)
    return _result("Beklenmeyen bir hata oluştu",
                   "Yapılan çeviriler kaybolmadı. Tekrar dene; sürerse aşağıdaki ayrıntıyı bize ilet.", detail)
