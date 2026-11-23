"""OPUS-MT / NLLB'nin CTranslate2 yolu: model seçimi, doğrulamalı indirme, çeviri ve hafif ortam kurulumu."""
import hashlib
import io
import sys
import types

import pytest

import app_modern
import engine_common
import gpu_runtime
import providers
from test_app import make_bridge, run_sync  # noqa: F401


def _fake_spec(tmp_path, monkeypatch, kind="opus"):
    files = {"config.json": b"{}", "model.bin": b"weights" * 10, "source.spm": b"s", "target.spm": b"t"}
    spec = {"dir": f"ct2_{kind}", "label": "Test", "repo": "test/repo", "revision": "abc",
            "files": {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in files.items()}}
    monkeypatch.setitem(engine_common.CT2_MODELS, kind, spec)
    monkeypatch.setattr(providers, "resolve_model_dir", lambda name: tmp_path / name)
    return files, spec


def test_status_prefers_ct2_then_legacy_then_missing(tmp_path, monkeypatch):
    files, spec = _fake_spec(tmp_path, monkeypatch)
    st = providers.get_offline_model_status("opus")                 # hiçbiri yok: indirilecek CT2 dosyaları
    assert not st["is_ready"] and st["backend"] == "ct2" and "model.bin" in st["missing_files"]
    legacy = tmp_path / "model"                                      # eski PyTorch modeli kurulu
    legacy.mkdir()
    for name, size in providers.OPUS_MODEL_FILES.items():
        with open(legacy / name, "wb") as f:
            f.truncate(size)
    st = providers.get_offline_model_status("opus")
    assert st["is_ready"] and st["backend"] == "torch"
    ct2 = tmp_path / spec["dir"]                                     # CT2 de inince o seçilir
    ct2.mkdir()
    for name, data in files.items():
        (ct2 / name).write_bytes(data)
    st = providers.get_offline_model_status("opus")
    assert st["is_ready"] and st["backend"] == "ct2" and st["compact"]
    assert providers.offline_model_dir("opus") == ct2


def test_download_verifies_sha256(tmp_path, monkeypatch):
    files, spec = _fake_spec(tmp_path, monkeypatch)
    served = dict(files)

    def fake_urlopen(req, timeout=60):
        name = req.full_url.rsplit("/", 1)[1]
        assert "/resolve/abc/" in req.full_url                       # sabit sürümden indirilir
        return io.BytesIO(served[name])

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    assert providers.download_offline_model("opus", log=lambda m: None)
    assert providers.get_offline_model_status("opus")["is_ready"]

    (tmp_path / spec["dir"] / "model.bin").unlink()
    served["model.bin"] = b"X" * len(files["model.bin"])            # aynı boyut, farklı içerik
    with pytest.raises(RuntimeError, match="doğrulanamadı"):
        providers.download_offline_model("opus", log=lambda m: None)
    assert not (tmp_path / spec["dir"] / "model.bin").exists()
    assert not (tmp_path / spec["dir"] / "model.bin.part").exists()


class _Sp:
    def encode(self, text, out_type=int):
        words = text.split()
        return ["▁" + w for w in words] if out_type is str else list(range(len(words)))

    def decode(self, tokens):
        return " ".join(t.lstrip("▁") for t in tokens).upper()


class _Result:
    def __init__(self, hyp):
        self.hypotheses = [hyp]


def test_ct2_engine_translates_with_nllb_language_codes(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"x")
    seen = {}

    class Translator:
        def __init__(self, path, device, compute_type, **kw):
            seen["device"], seen["compute"] = device, compute_type

        def translate_batch(self, sources, target_prefix=None, **kw):
            seen.setdefault("calls", []).append((sources, target_prefix))
            return [_Result((target_prefix[0] if target_prefix else []) + s[1:-1]) for s in sources]

    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(
        Translator=Translator, get_cuda_device_count=lambda: 0))
    monkeypatch.setitem(sys.modules, "sentencepiece", types.SimpleNamespace(SentencePieceProcessor=lambda **k: _Sp()))
    engine = engine_common.TranslationEngine(tmp_path, "nllb", log=lambda m: None, source_lang="en", target_lang="de")
    assert engine.backend == "ct2"
    out = engine.translate_batch(["good morning"])
    assert out == {"good morning": "GOOD MORNING"}                   # hedef dil kodu (deu_Latn) çıktıdan atılır
    sources, prefix = seen["calls"][-1]
    assert sources[0][0] == "eng_Latn" and sources[0][-1] == "</s>" and prefix == [["deu_Latn"]]
    assert seen["device"] == "cpu" and seen["compute"] == "int8"
    engine.set_languages("en", "tr")
    engine.translate_batch(["hello there"])
    assert seen["calls"][-1][1] == [["tur_Latn"]]
    engine.unload_model()
    assert engine._model is None


def test_torch_model_dir_keeps_torch_backend(tmp_path):
    (tmp_path / "pytorch_model.bin").write_bytes(b"x")
    assert engine_common.TranslationEngine(tmp_path, "opus").backend == "torch"


def test_download_model_installs_light_runtime_not_pytorch(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="opus")
    calls = []
    monkeypatch.setattr(gpu_runtime, "ct2_ready", lambda: False)
    monkeypatch.setattr(gpu_runtime, "install_ct2", lambda **k: calls.append("ct2"))
    monkeypatch.setattr(gpu_runtime, "install", lambda **k: calls.append("torch"))
    monkeypatch.setattr(app_modern.prov, "get_offline_model_status",
                        lambda kind: {"is_ready": False, "label": "OPUS", "size_mb": 0, "backend": "ct2"})
    monkeypatch.setattr(app_modern.prov, "download_offline_model", lambda kind, **k: calls.append(f"model:{kind}"))
    monkeypatch.setattr(bridge, "model_status", lambda: {})
    run_sync(bridge, "download_model", "opus")
    assert calls == ["ct2", "model:opus"]


def test_ct2_model_without_runtime_gives_clear_error(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="opus")
    monkeypatch.setattr(app_modern.prov, "get_offline_model_status",
                        lambda kind: {"is_ready": True, "backend": "ct2", "present_count": 5, "total_files": 5})
    monkeypatch.setattr(gpu_runtime, "ct2_ready", lambda: False)
    with pytest.raises(app_modern.UserError, match="çalışma ortamı"):
        bridge._check_model_ready(None)
    monkeypatch.setattr(gpu_runtime, "ct2_ready", lambda: True)
    monkeypatch.setattr(gpu_runtime, "ready", lambda: False)          # CT2 modeli PyTorch istemez
    monkeypatch.setattr(app_modern.prov, "release_offline_engines", lambda: None)
    bridge._check_model_ready(None)


def test_install_ct2_uses_light_package_set(monkeypatch, tmp_path):
    got = {}
    monkeypatch.setattr(gpu_runtime, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(gpu_runtime, "_install_packages", lambda pkgs, d, log, progress=None: got.setdefault("p", pkgs))
    gpu_runtime.install_ct2(log=lambda m: None)
    names = [p[0] for p in got["p"]]
    assert "ctranslate2" in names and "sentencepiece" in names and "torch" not in names and "transformers" not in names
