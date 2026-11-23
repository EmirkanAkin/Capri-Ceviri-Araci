"""
Ek bulut sağlayıcıları: OpenAI uyumlu sohbet API'leri (DeepSeek, Mistral, Grok, Groq, OpenRouter, Cerebras, Qwen,
Cohere, özel sunucu) ve makine çevirisi API'leri (Google Cloud Translation, Microsoft Translator). Ağ yerine yerel
sahte sunucular kullanılır.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import app_modern
import cloud_providers as cp
import providers
from test_app import make_bridge, make_rpgmaker_game, run_sync

SPAN = re.compile(r'(<span class="notranslate" translate="no">.*?</span>)', re.S)


class _Fake(BaseHTTPRequestHandler):
    requests = []
    reject_json_mode = False
    models = ["text-embedding-3", "whisper-large", "big-model-pro", "speedy-mini"]

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        _Fake.requests.append(("GET", self.path, dict(self.headers), None))
        if self.path.endswith("/models"):
            if self.headers.get("Authorization") != "Bearer good-key":
                return self._send(401, {"error": "bad key"})
            return self._send(200, {"data": [{"id": m} for m in _Fake.models]})
        self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.requests.append(("POST", self.path, dict(self.headers), body))
        path = urlparse(self.path).path
        if path.endswith("/chat/completions"):
            if _Fake.reject_json_mode and "response_format" in body:
                return self._send(400, {"error": "response_format not supported"})
            user = body["messages"][1]["content"]
            items = json.loads(user.split("\n", 1)[1] if user.startswith("Çevrilecek") else user)
            content = json.dumps({"translations": [f"TR {x}" for x in items]})
            if "response_format" not in body:
                content = "```json\n" + content + "\n```"
            return self._send(200, {"choices": [{"message": {"content": content}}]})
        if path.endswith("/language/translate/v2"):            # Google
            out = [{"translatedText": SPAN.sub(r"\1", "TR " + q)} for q in body["q"]]
            return self._send(200, {"data": {"translations": out}})
        if path.endswith("/translate"):                          # Azure
            return self._send(200, [{"translations": [{"text": "TR " + item["Text"], "to": "tr"}]} for item in body])
        self._send(404, {})

    def log_message(self, *args):
        pass


@pytest.fixture
def fake(monkeypatch):
    _Fake.requests = []
    _Fake.reject_json_mode = False
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    for pid in cp.CHAT_PROVIDERS:
        if pid != "custom":
            monkeypatch.setitem(cp.CHAT_PROVIDERS[pid], "base", f"{base}/{pid}/v1")
    monkeypatch.setattr(cp, "GOOGLE_URL", f"{base}/language/translate/v2")
    monkeypatch.setattr(cp, "AZURE_URL", f"{base}/translate")
    cp._MODEL_CACHE.clear()
    yield base
    server.shutdown()


def cfg_with(**extra):
    cfg = providers.ProviderConfig()
    cfg.extra = {pid: dict(values) for pid, values in extra.items()}
    return cfg


def test_registry_is_wired_everywhere():
    assert set(cp.ALL) <= set(app_modern.MODEL_LABELS) and set(cp.ALL) <= set(app_modern.CLOUD_MODELS)
    assert set(cp.CHAT_PROVIDERS) <= set(providers.LLM_PROVIDERS) and set(cp.CHAT_PROVIDERS) <= set(app_modern.SPEAKER_MODELS)
    assert not set(cp.MT_PROVIDERS) & set(providers.LLM_PROVIDERS), "makine çevirisi kalite editörü olamaz"
    assert all(pid in providers.CLOUD_TRANSLATE_IDS for pid in cp.ALL)


def test_model_picker_skips_non_chat_models():
    assert cp.pick_model(["text-embedding-3", "whisper-1", "tts-1", "grok-4", "grok-4-fast"]) == "grok-4-fast"
    assert cp.pick_model(["llama-3.3-70b", "llama-guard-4"]) == "llama-3.3-70b"
    assert cp.pick_model([]) == ""


def test_game_translation_through_an_openai_compatible_provider(tmp_path, monkeypatch, fake):
    game = make_rpgmaker_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="deepseek")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: cfg_with(deepseek={"key": "good-key"}))
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    data = json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))
    assert data["events"][1]["pages"][0]["list"][2]["parameters"][0] == "TR The king is waiting for you."
    post = next(r for r in _Fake.requests if r[0] == "POST")
    assert post[1] == "/deepseek/v1/chat/completions" and post[2]["Authorization"] == "Bearer good-key"
    assert post[3]["model"] == "deepseek-chat" and post[3]["response_format"] == {"type": "json_object"}


def test_auto_model_and_json_mode_fallback(fake):
    _Fake.reject_json_mode = True
    cfg = cfg_with(xai={"key": "good-key"})
    assert cp.llm_batch(cfg, "xai", ["Hello"], "Translate.") == ["TR Hello"]
    posts = [r for r in _Fake.requests if r[0] == "POST"]
    assert [("response_format" in r[3]) for r in posts] == [True, False], "JSON kipi reddedilince kipsiz yeniden denenir"
    assert posts[-1][3]["model"] == "speedy-mini", "model listeden seçildi"


def test_custom_server_needs_no_key_and_uses_its_address(fake):
    cfg = cfg_with(custom={"base_url": f"{fake}/lmstudio/v1/", "model": "local-model"})
    assert cp.configured(cfg, "custom") and cp.llm_batch(cfg, "custom", ["Hi"], "T") == ["TR Hi"]
    post = [r for r in _Fake.requests if r[0] == "POST"][-1]
    assert post[1] == "/lmstudio/v1/chat/completions" and "Authorization" not in post[2]


@pytest.mark.parametrize("pid, extra", [("google_translate", {"key": "g"}), ("azure_translator", {"key": "a", "region": "westeurope"})])
def test_machine_translation_keeps_tags_and_lines(fake, pid, extra):
    cfg = cfg_with(**{pid: extra})
    out = cp.mt_batch(cfg, pid, ["Hello [name]!\nBye \\C[2]x", "a < b & c"], "tr", "en", providers.CLOUD_PROTECTED)
    assert out[1] == "TR a < b & c"
    assert "[name]" in out[0] and "\n" in out[0]
    post = [r for r in _Fake.requests if r[0] == "POST"][-1]
    if pid == "azure_translator":
        assert post[2]["Ocp-Apim-Subscription-Region"] == "westeurope" and post[2]["Ocp-Apim-Subscription-Key"] == "a"
        assert parse_qs(urlparse(post[1]).query)["textType"] == ["html"]
    else:
        assert parse_qs(urlparse(post[1]).query)["key"] == ["g"] and post[3]["format"] == "html"


def test_config_keys_go_to_the_secure_store(tmp_path, monkeypatch):
    import secrets_store
    vault = {}
    monkeypatch.setattr(secrets_store, "available", lambda: True)
    monkeypatch.setattr(secrets_store, "get", lambda name: vault.get(name))
    monkeypatch.setattr(secrets_store, "set", lambda name, value: vault.__setitem__(name, value) or True)
    monkeypatch.setattr(providers, "CONFIG_FILE", tmp_path / "providers.json")
    cfg = providers.ProviderConfig()
    cp.extra(cfg, "mistral").update(key="m-key", model="mistral-large-latest")
    cp.extra(cfg, "custom").update(base_url="http://127.0.0.1:1234/v1")
    providers.save_provider_config(cfg)
    saved = json.loads((tmp_path / "providers.json").read_text(encoding="utf-8"))
    assert "m-key" not in json.dumps(saved) and vault["mistral_key"] == "m-key"
    assert saved["extra"]["mistral"] == {"model": "mistral-large-latest"}
    again = providers.load_provider_config()
    assert cp.key_of(again, "mistral") == "m-key" and cp.base_of(again, "custom") == "http://127.0.0.1:1234/v1"


def test_bridge_save_test_and_state(tmp_path, monkeypatch, fake):
    store = {"cfg": providers.ProviderConfig()}
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: store["cfg"])
    monkeypatch.setattr(app_modern.prov, "save_provider_config", lambda cfg: store.__setitem__("cfg", cfg))
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge.save_providers({"groq_key": " good-key ", "groq_model": "", "active": "groq"})
    assert cp.key_of(store["cfg"], "groq") == "good-key" and bridge._settings["model"] == "groq"
    result = bridge.test_provider("groq")
    assert result["ok"] and "speedy-mini" in result["msg"] and "big-model-pro" in result["models"]
    assert not bridge.test_provider("groq", "wrong-key")["ok"]
    state = bridge.get_state()
    assert state["providers"]["groq_key"] == "good-key"
    ids = [p["id"] for p in state["provider_catalog"]]
    assert ids == list(cp.ALL) and next(p for p in state["provider_catalog"] if p["id"] == "custom")["test"] == "custom_base_url"


def test_text_translator_and_quality_editor_use_new_providers(tmp_path, monkeypatch, fake):
    cfg = cfg_with(mistral={"key": "good-key"}, google_translate={"key": "g"})
    monkeypatch.setattr(providers, "load_provider_config", lambda: cfg)
    ok, text, _ = providers.translate_single_text("Hello", "mistral", target_lang="tr", source_lang="en", cfg=cfg)
    assert ok and text == "TR Hello"
    ok, text, _ = providers.translate_single_text("Hi {name}", "google_translate", target_lang="tr", source_lang="en", cfg=cfg)
    assert ok and "{name}" in text
    raw = providers.llm_complete("mistral", "Fix", json.dumps(["x"]), cfg)
    assert "translations" in raw
    bridge = make_bridge(tmp_path, monkeypatch, model="mistral")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: cfg)
    assert bridge._quality_provider() == "mistral"


def test_missing_key_is_reported_before_translation(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="openrouter")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig())
    with pytest.raises(app_modern.UserError, match="OpenRouter"):
        bridge._check_model_ready("rpgmaker")
    bridge._settings["model"] = "custom"
    with pytest.raises(app_modern.UserError, match="sunucu adresi"):
        bridge._check_model_ready("rpgmaker")


def test_renpy_templates_route_new_providers_to_the_cloud(tmp_path, monkeypatch):
    import engine_renpy
    tl = tmp_path / "tl" / "Turkish"
    tl.mkdir(parents=True)
    (tl / "a.rpy").write_text('translate Turkish s1:\n\n    # e "Hello there."\n    e ""\n', encoding="utf-8")
    seen = []

    def fake_cloud(provider, missing, cache, cache_path, **kw):
        seen.append(provider)
        cache.update({m: "TR " + m for m in missing})
        return len(missing)

    monkeypatch.setattr(providers, "translate_with_cloud", fake_cloud)
    engine_renpy.translate_templates(tl, tmp_path, tmp_path / "c.json", None, log=lambda s: None, model_kind="cohere")
    assert seen == ["cohere"] and 'e "TR Hello there."' in (tl / "a.rpy").read_text(encoding="utf-8")
