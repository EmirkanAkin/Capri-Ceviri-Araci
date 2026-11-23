"""
Capri — Ek bulut çeviri sağlayıcıları
====================================
İki tür sağlayıcı:

* **Sohbet modeli (OpenAI uyumlu API):** DeepSeek, Mistral, xAI Grok, Groq, OpenRouter, Cerebras, Alibaba Qwen,
  Cohere ve kullanıcının adresini verdiği herhangi bir OpenAI uyumlu sunucu (LM Studio, vLLM, Together, Fireworks…).
  Hepsi `/chat/completions` ve `/models` uçlarını aynı biçimde sunar; satırlar JSON listesi olarak gider ve gelir,
  etiket denetimi OpenAI ile aynıdır.
* **Makine çevirisi (MT) API'si:** Google Cloud Translation ve Azure AI Translator. Oyun etiketleri
  `<span class="notranslate" translate="no">` içine alınır; iki servis de bu bölümü çevirmez.

Model seçilmemişse sağlayıcının `/models` listesinden çeviriye uygun hızlı bir model seçilir (bir kez, oturum boyunca).
API anahtarları diğer sağlayıcılar gibi Windows Kimlik Bilgisi Yöneticisi'nde saklanır (providers.py).
"""
from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

# id → tanım. "base": OpenAI uyumlu API kökü (/chat/completions eklenir). "model": önerilen model (boşsa listeden).
CHAT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {"title": "DeepSeek", "short": "DS", "base": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                 "tag": "Bulut · uygun fiyatlı", "desc": "Ucuz ve güçlü sohbet modeli; uzun oyunlar için ekonomik.",
                 "key_url": "https://platform.deepseek.com/api_keys"},
    "mistral": {"title": "Mistral AI", "short": "M", "base": "https://api.mistral.ai/v1", "model": "mistral-small-latest",
                "tag": "Bulut · Avrupa", "desc": "Avrupa merkezli; Avrupa dillerinde akıcı çeviri.",
                "key_url": "https://console.mistral.ai/api-keys"},
    "xai": {"title": "xAI Grok", "short": "X", "base": "https://api.x.ai/v1", "model": "",
            "tag": "Bulut · Grok", "desc": "Grok modelleri; sansürsüz ve doğal konuşma dili.",
            "key_url": "https://console.x.ai"},
    "groq": {"title": "Groq", "short": "GQ", "base": "https://api.groq.com/openai/v1", "model": "",
             "tag": "Bulut · çok hızlı", "desc": "Açık modelleri (Llama, Qwen, Kimi…) çok hızlı çalıştırır; ücretsiz kotası var.",
             "key_url": "https://console.groq.com/keys"},
    "openrouter": {"title": "OpenRouter", "short": "OR", "base": "https://openrouter.ai/api/v1", "model": "openrouter/auto",
                   "tag": "Bulut · yüzlerce model", "desc": "Tek anahtarla yüzlerce modele (Qwen, Llama, Gemma, Claude, GPT…) erişim.",
                   "key_url": "https://openrouter.ai/keys"},
    "cerebras": {"title": "Cerebras", "short": "CB", "base": "https://api.cerebras.ai/v1", "model": "",
                 "tag": "Bulut · çok hızlı", "desc": "Açık modelleri çok yüksek hızda çalıştırır; ücretsiz kotası var.",
                 "key_url": "https://cloud.cerebras.ai"},
    "qwen": {"title": "Alibaba Qwen", "short": "Q", "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             "model": "qwen-plus", "tag": "Bulut · Asya dilleri", "desc": "Qwen modelleri (uluslararası DashScope); Çince, Japonca, Korece kaynaklı oyunlarda güçlü.",
             "key_url": "https://modelstudio.console.alibabacloud.com"},
    "cohere": {"title": "Cohere", "short": "CO", "base": "https://api.cohere.ai/compatibility/v1", "model": "",
               "tag": "Bulut · çok dilli", "desc": "Command modelleri; çok dilli kurumsal çeviri.",
               "key_url": "https://dashboard.cohere.com/api-keys"},
    "custom": {"title": "OpenAI uyumlu (özel)", "short": "API", "base": "", "model": "", "optional_key": True,
               "tag": "Kendi sunucun", "desc": "LM Studio, vLLM, Together, Fireworks gibi OpenAI uyumlu herhangi bir adres. Yerel sunucularda anahtar gerekmez.",
               "key_url": ""},
}
MT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "google_translate": {"title": "Google Çeviri (Cloud)", "short": "GT", "tag": "Bulut · makine çevirisi",
                         "desc": "Google Cloud Translation API (API anahtarıyla). Çok hızlı, 100+ dil.",
                         "key_url": "https://console.cloud.google.com/apis/credentials"},
    "azure_translator": {"title": "Microsoft Translator", "short": "MS", "tag": "Bulut · makine çevirisi",
                         "desc": "Azure AI Translator. Bölgesel kaynaklarda bölge adını da gir (ör. westeurope).",
                         "key_url": "https://portal.azure.com"},
}
ALL = {**CHAT_PROVIDERS, **MT_PROVIDERS}
# Toplu çeviriyi providers.translate_with_cloud yapan bulut sağlayıcıları (Gemini'nin kendi yolu var)
TRANSLATE_IDS = ("openai", "anthropic", "deepl", *ALL)
GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
AZURE_URL = "https://api.cognitive.microsofttranslator.com/translate"
_MODEL_CACHE: Dict[Tuple[str, str], str] = {}
# Çeviriye uygun olmayan modeller (ses, görsel, gömme, denetim…)
_NOT_CHAT = re.compile(r"embed|whisper|tts|speech|audio|image|vision-only|moderation|guard|rerank|dall|sora|ocr|"
                       r"transcri|realtime|search|code(?!x)|-vl\b|reason(?!ing)", re.I)
_PREFERRED = ("flash", "mini", "small", "fast", "lite", "turbo", "chat", "instant", "plus")


# ── Yapılandırma ────────────────────────────────────────────────────────────
def extra(cfg: Any, pid: str) -> Dict[str, str]:
    store = getattr(cfg, "extra", None)
    if store is None:
        return {}
    return store.setdefault(pid, {})


def key_of(cfg: Any, pid: str) -> str:
    return (extra(cfg, pid).get("key") or "").strip()


def base_of(cfg: Any, pid: str) -> str:
    if pid == "custom":
        return (extra(cfg, pid).get("base_url") or "").strip().rstrip("/")
    return CHAT_PROVIDERS[pid]["base"]


def configured(cfg: Any, pid: str) -> bool:
    if pid == "custom":
        return bool(base_of(cfg, pid))
    return bool(key_of(cfg, pid))


def secret_names() -> List[str]:
    return [f"{pid}_key" for pid in ALL]


# ── Sohbet modelleri ────────────────────────────────────────────────────────
def _headers(cfg: Any, pid: str, key: Optional[str] = None) -> Dict[str, str]:
    key = key if key is not None else key_of(cfg, pid)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if pid == "openrouter":
        headers["X-Title"] = "Capri"                # OpenRouter'ın uygulama adı başlığı (kişisel veri yok)
    return headers


def list_models(cfg: Any, pid: str, key: Optional[str] = None, base: Optional[str] = None, timeout: int = 20) -> List[str]:
    base = (base or base_of(cfg, pid)).rstrip("/")
    if not base:
        raise RuntimeError("Sunucu adresi girilmemiş.")
    resp = requests.get(f"{base}/models", headers=_headers(cfg, pid, key), timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:160]}")
    data = resp.json()
    items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
    names = []
    for item in items or []:
        name = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name:
            names.append(name)
    return names


def pick_model(models: List[str]) -> str:
    """Çeviri için hızlı bir sohbet modeli: ses/görsel/gömme modelleri elenir; adında flash/mini/small… geçen öne alınır."""
    chat = [m for m in models if not _NOT_CHAT.search(m)] or list(models)
    if not chat:
        return ""
    def rank(name: str) -> Tuple[int, int, str]:
        n = name.lower()
        pref = next((i for i, word in enumerate(_PREFERRED) if word in n), len(_PREFERRED))
        return (0 if pref < len(_PREFERRED) else 1, pref, n)
    return sorted(chat, key=rank)[0]


def model_of(cfg: Any, pid: str) -> str:
    chosen = (extra(cfg, pid).get("model") or "").strip() or CHAT_PROVIDERS[pid]["model"]
    if chosen:
        return chosen
    cache_key = (pid, base_of(cfg, pid))
    if cache_key not in _MODEL_CACHE:
        _MODEL_CACHE[cache_key] = pick_model(list_models(cfg, pid))
    if not _MODEL_CACHE[cache_key]:
        raise RuntimeError(f"{ALL[pid]['title']}: kullanılabilir model bulunamadı; Sağlayıcılar sayfasından model gir.")
    return _MODEL_CACHE[cache_key]


def chat(cfg: Any, pid: str, system: str, user: str, json_mode: bool = True, max_tokens: int = 8192,
         timeout: int = 180, model: Optional[str] = None) -> str:
    """Ham yanıt metni. JSON kipini desteklemeyen sağlayıcı/modelde (HTTP 400) kipsiz bir kez daha denenir."""
    base = base_of(cfg, pid)
    if not base:
        raise RuntimeError("Sunucu adresi girilmemiş.")
    if pid != "custom" and not key_of(cfg, pid):
        raise RuntimeError(f"{ALL[pid]['title']} API anahtarı girilmemiş.")
    payload: Dict[str, Any] = {"model": model or model_of(cfg, pid), "temperature": 0.2, "max_tokens": max_tokens,
                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    resp = requests.post(f"{base}/chat/completions", headers=_headers(cfg, pid), json=payload, timeout=timeout)
    if resp.status_code in (400, 422) and json_mode:
        payload.pop("response_format", None)
        resp = requests.post(f"{base}/chat/completions", headers=_headers(cfg, pid), json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"{ALL[pid]['title']} HTTP {resp.status_code}: {resp.text[:160]}")
    message = (resp.json().get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):                   # bazı sağlayıcılar içerik parçaları döndürür
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def llm_batch(cfg: Any, pid: str, items: List[str], system: str) -> Optional[List[str]]:
    from providers import _parse_json_list
    user = "Çevrilecek liste:\n" + json.dumps(items, ensure_ascii=False)
    raw = chat(cfg, pid, system + '\nYanıtı {"translations": [...]} biçiminde bir JSON nesnesi olarak ver.', user,
               timeout=120)
    parsed = _parse_json_list(raw)
    if parsed is None or len(parsed) != len(items):
        return None
    return ["" if x is None else str(x) for x in parsed]


# ── Makine çevirisi (Google / Azure) ────────────────────────────────────────
_GOOGLE_LANGS = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "pt-BR": "pt", "pt": "pt-PT"}
_AZURE_LANGS = {"zh-CN": "zh-Hans", "zh-TW": "zh-Hant", "pt-BR": "pt", "pt": "pt-pt"}
_SPAN = '<span class="notranslate" translate="no">'


def _protect(text: str, pattern: Any) -> str:
    out, last = [], 0
    for m in pattern.finditer(text) if pattern is not None else []:
        out.append(html.escape(text[last:m.start()], quote=False))
        out.append(f"{_SPAN}{html.escape(m.group(0), quote=False)}</span>")
        last = m.end()
    out.append(html.escape(text[last:], quote=False))
    return "".join(out).replace("\n", "<br>")


def _unprotect(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r'<span class="notranslate" translate="no">(.*?)</span>', r"\1", text, flags=re.S)
    text = re.sub(r"</?span[^>]*>", "", text)
    return html.unescape(text)


def mt_batch(cfg: Any, pid: str, items: List[str], target_lang: str, source_lang: str, pattern: Any) -> List[str]:
    key = key_of(cfg, pid)
    if not key:
        raise RuntimeError(f"{ALL[pid]['title']} API anahtarı girilmemiş.")
    texts = [_protect(t, pattern) for t in items]
    source = "" if not source_lang or source_lang == "auto" else source_lang
    if pid == "google_translate":
        body: Dict[str, Any] = {"q": texts, "target": _GOOGLE_LANGS.get(target_lang, target_lang), "format": "html"}
        if source:
            body["source"] = _GOOGLE_LANGS.get(source, source.split("-")[0])
        resp = requests.post(GOOGLE_URL, params={"key": key}, json=body, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Google Çeviri HTTP {resp.status_code}: {resp.text[:160]}")
        return [_unprotect(t["translatedText"]) for t in resp.json()["data"]["translations"]]
    params = {"api-version": "3.0", "to": _AZURE_LANGS.get(target_lang, target_lang), "textType": "html"}
    if source:
        params["from"] = _AZURE_LANGS.get(source, source.split("-")[0])
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json"}
    region = (extra(cfg, pid).get("region") or "").strip()
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region
    resp = requests.post(AZURE_URL, params=params, headers=headers, json=[{"Text": t} for t in texts], timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Microsoft Translator HTTP {resp.status_code}: {resp.text[:160]}")
    return [_unprotect(item["translations"][0]["text"]) for item in resp.json()]


# ── Ortak ───────────────────────────────────────────────────────────────────
def translate_one(cfg: Any, pid: str, text: str, target_lang: str, source_lang: str, system: str, pattern: Any) -> str:
    if pid in MT_PROVIDERS:
        return mt_batch(cfg, pid, [text], target_lang, source_lang, pattern)[0]
    result = llm_batch(cfg, pid, [text], system)
    if not result:
        raise RuntimeError("Geçerli yanıt alınamadı.")
    return result[0]


def test(cfg: Any, pid: str, value: str = "") -> Tuple[bool, str, List[str]]:
    """(başarılı mı, ileti, modeller). value: kaydedilmemiş anahtar ya da (özel sağlayıcıda) adres."""
    import copy
    from providers import CLOUD_PROTECTED
    cfg = copy.deepcopy(cfg)                      # denenen (kaydedilmemiş) anahtar ayarlara karışmasın
    title = ALL[pid]["title"]
    if pid in MT_PROVIDERS:
        if value:
            extra(cfg, pid)["key"] = value
        try:
            out = mt_batch(cfg, pid, ["Welcome back, {name}!"], "tr", "en", CLOUD_PROTECTED)[0]
        except Exception as exc:
            return False, str(exc), []
        return ("{name}" in out), f"{title} çalışıyor: {out}", []
    if value:
        extra(cfg, pid)["base_url" if pid == "custom" else "key"] = value
    try:
        models = list_models(cfg, pid)
    except Exception as exc:
        return False, f"{title}: {exc}", []
    if not (extra(cfg, pid).get("model") or CHAT_PROVIDERS[pid]["model"]):
        _MODEL_CACHE[(pid, base_of(cfg, pid))] = pick_model(models)       # listeyi ikinci kez istemeye gerek yok
    try:
        model = model_of(cfg, pid)
        out = llm_batch(cfg, pid, ["Welcome back, traveler!"], "Translate each item of the JSON list into Turkish.")
    except Exception as exc:
        return False, f"{title}: {exc}", models
    if not out:
        return False, f"{title}: model yanıt verdi ama çeviri listesi okunamadı ({model}).", models
    return True, f"{title} çalışıyor ({model}): {out[0]}", models


__all__ = ["CHAT_PROVIDERS", "MT_PROVIDERS", "ALL", "chat", "llm_batch", "mt_batch", "list_models", "pick_model",
           "model_of", "key_of", "base_of", "configured", "secret_names", "translate_one", "test"]
