"""
Yerel model kitaplığı: ağırlık gruplarına (hafif / orta / ağır) ve ölçülen kaliteye göre sıralama, ekran kartına göre
öneri, Hy-MT2 ve Gemma 4 ailelerinin resmi istemleri, satır sonlarının korunması ve Gemma 4'ün kalite editörü olması.
Kalite puanları Capri'nin kendi testinden gelir (WMT24++ chrF++ ve oyun etiketi koruma; bkz. CHANGELOG).
"""
import pytest

import app_modern
import engine_common
import local_llm
import providers
from test_app import make_bridge
from test_local_llm import fake_runtime  # noqa: F401 (fixture)


def test_every_model_has_measured_quality_and_a_plain_description():
    for spec in local_llm.CATALOG:
        q = spec["quality"]
        assert 20 < q["tr"] < 90 and 20 < q["avg"] < 90 and 0 <= q["tags"] <= 1, spec["id"]
        assert spec["tier"] in local_llm.TIERS and spec["family"] in ("translategemma", "milmmt", "hymt", "gemma4")
        assert len(spec["use"]) > 30 and spec["speed"].startswith("RTX 5070"), "kullanıcının anlayacağı açıklama ve hız"
        assert 10 < len(spec["short"]) <= 60 and spec["rate"] > 0, "sade görünüm için kısa açıklama ve sayısal hız"
        assert spec["license"] in ("Apache-2.0", "Gemma")
    assert {m["tier"] for m in local_llm.CATALOG} == set(local_llm.TIERS), "her grupta en az bir model"


def test_library_is_ordered_by_weight_then_quality():
    order = local_llm.ordered()
    tiers = [local_llm.TIERS.index(m["tier"]) for m in order]
    assert tiers == sorted(tiers), "önce hafif, sonra orta, sonra ağır"
    for tier in local_llm.TIERS:
        scores = [local_llm.score(m) for m in order if m["tier"] == tier]
        assert scores == sorted(scores, reverse=True), f"{tier}: iyiden kötüye"
    status = local_llm.status(12)
    assert [m["id"] for m in status["models"]] == [m["id"] for m in order]
    for tier in local_llm.TIERS:
        ranks = [m["rank"] for m in status["models"] if m["tier"] == tier]
        assert ranks == list(range(1, len(ranks) + 1))
        assert sum(m["best_in_tier"] for m in status["models"] if m["tier"] == tier) == 1


@pytest.mark.parametrize("vram, tier", [(12, "heavy"), (16, "heavy"), (8, "medium"), (6, "medium"), (4, "light"),
                                        (None, "light"), (0, "light")])
def test_recommendation_fits_the_graphics_card(vram, tier):
    rec = local_llm.BY_ID[local_llm.recommend(vram)["model"]]
    assert rec["tier"] == tier
    if vram:
        assert rec["vram_gb"] <= vram, "önerilen model ekran kartı belleğine sığar"
    same_tier = [m for m in local_llm.ordered() if m["tier"] == tier and (not vram or m["vram_gb"] <= vram)]
    assert rec["id"] == same_tier[0]["id"], "sığanların en iyisi"


def test_hymt_prompt_uses_delimiter_form_for_masked_tags():
    plain = engine_common.hymt_prompt("Hello.", "en", "tr")
    assert plain.startswith("Translate the following text into Turkish.") and plain.endswith("\n\nHello.")
    masked = engine_common.hymt_prompt("Hi XPH000X!", "en", "tr")
    assert "retain the exact same number of delimiters" in masked and masked.endswith("\n\nHi XPH000X!")
    assert "into Chinese." in engine_common.hymt_prompt("x", "en", "zh-CN")
    assert "Traditional Chinese" in engine_common.hymt_prompt("x", "en", "zh-TW")
    chat = engine_common.chat_translate_prompt("Hello.", "en", "de")
    assert "into German" in chat and "XPH000X" in chat and chat.endswith("\n\nHello.")


def test_new_families_translate_and_keep_line_breaks(fake_runtime):  # noqa: F811
    server, launched = fake_runtime
    hymt = next(m["id"] for m in local_llm.CATALOG if m["family"] == "hymt")
    gemma = next(m["id"] for m in local_llm.CATALOG if m["family"] == "gemma4")
    milmmt = next(m["id"] for m in local_llm.CATALOG if m["family"] == "milmmt")
    quiet = lambda s: None
    assert local_llm.translate_one(hymt, "Hello.\n\nBye.", "en", "tr", log=quiet) == "TR(Hello.)\n\nTR(Bye.)", \
        "Hy-MT2 satırları birleştirebildiği için satır satır çevrilir"
    assert local_llm.translate_one(milmmt, "One.\nTwo.", "en", "tr", log=quiet) == "TR(One.)\nTR(Two.)"
    assert local_llm.translate_one(gemma, "Line one.\nLine two.", "en", "tr", log=quiet) == "TR(Line one.\nLine two.)", \
        "Gemma 4 çok satırlı metni bir arada görür"
    assert "--jinja" in launched[-1], "sohbet şablonu GGUF'tan okunur"


def test_engine_routes_new_families_through_the_builtin_server(monkeypatch):
    sent = []
    monkeypatch.setattr(local_llm, "translate_one", lambda mid, text, *a, **k: sent.append((mid, text)) or f"TR({text})")
    for family in ("hymt", "gemma4"):
        mid = next(m["id"] for m in local_llm.CATALOG if m["family"] == family)
        engine = engine_common.make_llm_engine("local", mid, "", None, None, lambda s: None, "tr", "en")
        assert engine.family == family
        assert engine._api_batch(["A.", "B."]) == ["TR(A.)", "TR(B.)"]
    assert {m for m, _ in sent} and all(text in ("A.", "B.") for _m, text in sent)


def test_local_gemma4_can_be_the_quality_editor(tmp_path, monkeypatch):
    gemma = next(m["id"] for m in local_llm.CATALOG if m["family"] == "gemma4")
    translator = next(m["id"] for m in local_llm.CATALOG if m["family"] == "hymt")
    bridge = make_bridge(tmp_path, monkeypatch, model="local")
    monkeypatch.setattr(local_llm, "model_installed", lambda mid: True)
    bridge._settings["local_model"] = gemma
    assert bridge._quality_provider() == "local"
    calls = []
    monkeypatch.setattr(local_llm.SERVER, "chat", lambda mid, content, *a, **k: calls.append((mid, content, k)) or '{"items": []}')
    assert bridge._completer("local", providers.ProviderConfig())("Sistem", "Kullanıcı") == '{"items": []}'
    mid, content, extra = calls[0]
    assert mid == gemma and content.startswith("Sistem\n\nKullanıcı") and extra["response_format"] == {"type": "json_object"}
    bridge._settings["local_model"] = translator
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig())
    with pytest.raises(app_modern.UserError, match="Gemma 4"):
        bridge._quality_provider()
    with pytest.raises(RuntimeError, match="yalnızca çeviri"):
        providers.llm_complete("local", "s", "u", providers.ProviderConfig(), local_model=translator)


def test_opus_and_nllb_are_ranked_inside_the_library():
    status = local_llm.status(12, classic_ready={"opus": True, "nllb": False})
    light = [m for m in status["models"] if m["tier"] == "light"]
    ids = [m["id"] for m in light]
    assert "opus" in ids and "nllb" in ids and ids[-1] == "nllb", "ölçülen kaliteye göre: NLLB hafif grubun sonunda"
    opus = next(m for m in light if m["id"] == "opus")
    assert opus["kind"] == "classic" and opus["installed"] and opus["quality"]["avg"] is None
    assert [m["rank"] for m in light] == list(range(1, len(light) + 1))
    assert not any(m["recommended"] for m in light if m["kind"] == "classic"), "öneri llama.cpp modellerinden"
    assert all(m["id"] not in ("opus", "nllb") for m in local_llm.status(12)["models"]), "bilgi verilmezse eklenmez"


def test_first_run_tour_is_remembered(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    assert bridge.get_state()["settings"]["tour_done"] is False
    assert bridge.update_settings({"tour_done": True})["tour_done"] is True
    assert bridge.get_state()["settings"]["game_tour_done"] is False, "ilk oyun turu ayrı hatırlanır"
    assert bridge.update_settings({"game_tour_done": True})["game_tour_done"] is True
