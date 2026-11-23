"""
Çeviri kalitesi araçları: düzeltme belleği, karakter adları, metin kutusu sığma denetimi, incelenmelileri düzeltme,
güncelleme sonrası yeniden uygulama ve ücretli çeviri onayı.
"""
import json
from pathlib import Path

import pytest

import app_modern
import providers
import text_fit
from test_app import fake_ollama, make_bridge, make_rpgmaker_game, run_sync  # noqa: F401 (fixture)


def _mv_game(root: Path, lines, face="") -> Path:
    data = root / "www" / "data"
    data.mkdir(parents=True)
    (data / "System.json").write_text(json.dumps({"gameTitle": "Fit Demo"}), encoding="utf-8")
    cmds = [{"code": 101, "parameters": [face, 0, 0, 2, ""]}] + [{"code": 401, "parameters": [t]} for t in lines]
    events = [None, {"pages": [{"list": cmds + [{"code": 0, "parameters": []}]}]}]
    (data / "Map001.json").write_text(json.dumps({"events": events}), encoding="utf-8")
    (data / "MapInfos.json").write_text("[]", encoding="utf-8")
    return root


# ── Düzeltme belleği ─────────────────────────────────────────────────────────
def test_editor_fixes_are_reused_in_another_game(tmp_path, monkeypatch, fake_ollama):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    first = make_rpgmaker_game(tmp_path / "first")
    bridge._select_game(str(first))
    run_sync(bridge, "translate")
    src = "The king is waiting for you."
    assert bridge.editor_save("ollama", {src: "Kral seni bekliyor."})["ok"]
    assert json.loads(bridge._fixes_file().read_text(encoding="utf-8")) == {src: "Kral seni bekliyor."}
    # Kaydedilen ama değişmeyen satır düzeltme sayılmaz
    bridge.editor_save("ollama", {"Welcome to our village, traveler.": "TR(Welcome to our village, traveler.)"})
    assert len(json.loads(bridge._fixes_file().read_text(encoding="utf-8"))) == 1

    second = make_rpgmaker_game(tmp_path / "second")      # aynı cümleler: serinin devamı gibi
    bridge._select_game(str(second))
    run_sync(bridge, "translate")
    cache = json.loads(bridge._cache_path().read_text(encoding="utf-8"))
    assert cache[src] == "Kral seni bekliyor.", "elle düzeltilen hâl makine çevirisinin yerine geçer"
    assert cache["Welcome to our village, traveler."] == "TR(Welcome to our village, traveler.)"


def test_fixes_respect_the_memory_setting_and_existing_lines(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, memory=False)
    assert bridge._learn_fixes({"Hello": "Merhaba"}) == 0 and not bridge._fixes_file().exists()
    bridge._settings["memory"] = True
    bridge._learn_fixes({"Hello": "Merhaba", "Save": "Kaydet", "Same": "Same"})
    assert json.loads(bridge._fixes_file().read_text(encoding="utf-8")) == {"Hello": "Merhaba", "Save": "Kaydet"}
    assert json.loads(bridge._memory_file().read_text(encoding="utf-8"))["Save"] == "Kaydet", "kısa arayüz metni"
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"Hello": "Selam"}), encoding="utf-8")
    bridge._seed_memory(cache)
    assert json.loads(cache.read_text(encoding="utf-8")) == {"Hello": "Selam", "Save": "Kaydet"}, \
        "bu oyunda zaten çevrilmiş satıra dokunulmaz"


# ── Karakter adları ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, ok", [
    ("Elena", True), ("Mary Jane", True), ("O'Brien", True), ("Zoë", True),
    ("Mom", False), ("Old Man", False), ("???", False), ("Guard", False), ("mc", False), ("[player_name]", False),
    ("A", False), ("The Brave Knight", False), ("Mysterious Girl", False),
])
def test_looks_like_name(name, ok):
    assert app_modern.looks_like_name(name) is ok


def _renpy_game(root: Path) -> Path:
    game = root / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text(
        'define e = Character("Elena")\ndefine m = Character("Mom")\ndefine g = Character("Mysterious Girl")\n'
        'define j = Character("Jake", color="#fff")\n\nlabel start:\n    e "Hi."\n    return\n', encoding="utf-8")
    (root / "Demo.exe").write_bytes(b"")
    return root


def test_character_names_are_added_once_before_the_first_translation(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    root = _renpy_game(tmp_path / "vn")
    bridge._select_game(str(root))
    game = bridge._game
    assert bridge._auto_character_names(game) == ["Elena", "Jake"]
    pg = bridge._project_glossary()
    assert pg["terms"] == {"Elena": "Elena", "Jake": "Jake"} and pg["names_scanned"] is True
    assert any(e == "notify" for e, _ in bridge._ui.events)
    # Kullanıcı bir adı sildiyse ikinci çeviride geri eklenmez
    bridge.project_glossary_save([["Jake", "Jake"]])
    assert bridge._auto_character_names(game) == []
    assert bridge._project_glossary()["terms"] == {"Jake": "Jake"} and bridge._project_glossary()["names_scanned"]


def test_character_names_skip_non_latin_targets_and_the_setting(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, target="ru")
    bridge._select_game(str(_renpy_game(tmp_path / "vn")))
    assert bridge._auto_character_names(bridge._game) == []
    bridge._settings.update(target="de", auto_names=False)
    assert bridge._auto_character_names(bridge._game) == []
    bridge._settings["auto_names"] = True
    assert bridge._auto_character_names(bridge._game) == ["Elena", "Jake"]


# ── Metin kutusuna sığma ────────────────────────────────────────────────────
def test_rpgmaker_width_counts_escape_codes_like_the_game():
    assert text_fit.rpgm_width("Hello") == 5
    assert text_fit.rpgm_width(r"\C[2]Hello\C[0]") == 5, "renk kodu yer kaplamaz"
    assert text_fit.rpgm_width(r"\N[1] waves.") == 8 + 7, "aktör adı ~8 karakter"
    assert text_fit.rpgm_width(r"\I[64]Potion") == 3 + 6
    assert text_fit.rpgm_width("こんにちは") == 10, "tam genişlik karakterler iki birim"
    assert text_fit.rpgm_width("short\nmuch longer line") == 16


def test_rpgmaker_message_width_reads_mz_system_and_mv_plugin(tmp_path):
    mz = tmp_path / "mz" / "data"
    mz.mkdir(parents=True)
    (mz / "System.json").write_text(json.dumps({"advanced": {"uiAreaWidth": 808, "fontSize": 26}}), encoding="utf-8")
    assert text_fit.rpgm_message_units(mz, "mz") == {"plain": 60, "face": 47}
    mv = tmp_path / "mv" / "www" / "data"
    mv.mkdir(parents=True)
    (mv / "System.json").write_text("{}", encoding="utf-8")
    assert text_fit.rpgm_message_units(mv, "mv") == {"plain": 55, "face": 43}
    (mv.parent / "js").mkdir()
    (mv.parent / "js" / "plugins.js").write_text(
        'var $plugins =\n[\n{"name":"Community_Basic","status":true,"description":"","parameters":{"screenWidth":"1280"}}\n];\n',
        encoding="utf-8")
    assert text_fit.rpgm_message_units(mv, "mv")["plain"] == (1280 - 36) // 14


def test_rpgmaker_overflow_is_flagged_only_when_the_translation_breaks_the_box(tmp_path, monkeypatch):
    from engine_rpgmaker import detect_rpgmaker_game, extract_texts_mv_mz
    long_ok = "x" * 40                                         # orijinal yüzlü kutuya da sığıyor (43)
    root = _mv_game(tmp_path / "g", ["Short line.", long_ok, "y" * 60, r"<WordWrap>" + "z" * 50], face="Actor1")
    info = detect_rpgmaker_game(root)
    limits = text_fit.rpgm_limits(extract_texts_mv_mz(info.data_dir, log=lambda s: None), info.data_dir, "mv")
    assert limits[long_ok] == 43, "yüz görseli olan mesaj daha dar"
    assert all("<WordWrap>" not in k for k in limits), "kaydırma eklentisi kullanan satır denetlenmez"
    cache = {"Short line.": "Kısa satır.", long_ok: "ü" * 70, "y" * 60: "ç" * 80}
    assert text_fit.overflowing(cache, limits, "rpgmaker") == {long_ok: 43}, \
        "zaten sığmayan orijinalin çevirisi işaretlenmez"


def test_renpy_limits_use_gui_sizes_and_only_dialogue(tmp_path):
    game = tmp_path / "game"
    tl = game / "tl" / "turkish"
    tl.mkdir(parents=True)
    (game / "gui.rpy").write_text("init python:\n    gui.init(1920, 1080)\ndefine gui.text_size = 40\n"
                                  "define gui.dialogue_width = 1000\ndefine gui.textbox_height = 250\n"
                                  "define gui.dialogue_ypos = 50\n", encoding="utf-8")
    (tl / "script.rpy").write_text(
        'translate turkish start_1:\n\n    # e "Hello there."\n    e "Merhaba."\n\n'
        'translate turkish start_2:\n\n    # "Narration [mc]."\n    "Anlatım."\n\n'
        'translate turkish strings:\n\n    # game/screens.rpy:10\n    old "Start"\n    new "Başla"\n', encoding="utf-8")
    limits = text_fit.renpy_limits(game, tl)
    per_line, lines = 1000 / 20, int((250 - 50) // (40 * 1.25))
    assert limits == {"Hello there.": int(per_line * lines), "Narration [mc].": int(per_line * lines)}
    assert text_fit.renpy_width("{i}Hi{/i} [mc]") == 2 + 1 + 6


# ── İncelenmelileri düzelt ──────────────────────────────────────────────────
def test_editor_shows_why_and_fixes_flagged_lines_with_a_chat_model(tmp_path, monkeypatch):
    long_src = "I will wait for you at the gate."
    root = _mv_game(tmp_path / "g", ["Talk to Elena now.", long_src, "Keep {0} safe.", "Fine."], face="Actor1")
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    bridge.project_glossary_save([["Elena", "Elena"]])
    app_modern._write_json(bridge._cache_path(), {
        "Talk to Elena now.": "Şimdi Helen ile konuş.", long_src: "Kapıda seni bekleyeceğim " + "ve " * 20 + "işte.",
        "Keep {0} safe.": "Güvende tut.", "Fine.": "İyi."})
    items = {i["src"]: i for i in bridge.editor_load("gemini", only_review=True)["items"]}
    assert set(items) == {"Talk to Elena now.", long_src, "Keep {0} safe."}
    assert items["Talk to Elena now."]["why"] == ["Oyun terimi çeviride yok"]
    assert items[long_src]["why"] == ["Kutuya sığmayabilir (en çok 43 karakter)"]
    assert items["Keep {0} safe."]["why"] == ["Etiket ya da değişken farklı"]

    sent = []

    def fake_complete(provider, system, user, cfg):
        payload = json.loads(user)
        sent.extend(payload)
        fixes = {"Talk to Elena now.": "Şimdi Elena ile konuş.", long_src: "Kapıda bekleyeceğim.",
                 "Keep {0} safe.": "{0} güvende kalsın."}
        return json.dumps([{"id": p["id"], "tr": fixes[p["en"]]} for p in payload], ensure_ascii=False)

    monkeypatch.setattr(app_modern.prov, "llm_complete", fake_complete)
    monkeypatch.setattr(bridge, "_quality_provider", lambda: "openai")
    run_sync(bridge, "editor_fix_review", "gemini")
    issues = {p["en"]: p.get("issue", "") for p in sent}
    assert "Elena → Elena" in issues["Talk to Elena now."]
    assert "at most 43 characters" in issues[long_src]
    assert "tags/variables" in issues["Keep {0} safe."]
    cache = json.loads(bridge._cache_path().read_text(encoding="utf-8"))
    assert cache[long_src] == "Kapıda bekleyeceğim." and cache["Talk to Elena now."] == "Şimdi Elena ile konuş."
    assert cache["Keep {0} safe."] == "{0} güvende kalsın." and cache["Fine."] == "İyi."
    assert bridge.editor_load("gemini", only_review=True)["total"] == 0


def test_fix_review_rejects_suggestions_that_break_tags_or_stay_too_long(tmp_path, monkeypatch):
    long_src = "I will wait for you at the gate."
    root = _mv_game(tmp_path / "g", [long_src, r"Take \C[2]this\C[0]."], face="Actor1")
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    too_long = "Kapıda seni bekleyeceğim " + "ve " * 20 + "işte."
    app_modern._write_json(bridge._cache_path(), {long_src: too_long, r"Take \C[2]this\C[0].": r"Take \C[2]this\C[0]."})

    def fake_complete(provider, system, user, cfg):
        return json.dumps([{"id": p["id"], "tr": {long_src: too_long + " daha da uzun",
                                                  r"Take \C[2]this\C[0].": "Bunu al."}[p["en"]]}
                           for p in json.loads(user)], ensure_ascii=False)

    monkeypatch.setattr(app_modern.prov, "llm_complete", fake_complete)
    monkeypatch.setattr(bridge, "_quality_provider", lambda: "openai")
    run_sync(bridge, "editor_fix_review", "gemini")
    cache = json.loads(bridge._cache_path().read_text(encoding="utf-8"))
    assert cache[long_src] == too_long, "kısalmayan öneri alınmaz"
    assert cache[r"Take \C[2]this\C[0]."] == r"Take \C[2]this\C[0].", "renk kodunu silen öneri alınmaz"


def test_overflow_after_translation_goes_to_the_review_list(tmp_path, monkeypatch):
    long_src = "I will wait for you at the gate."
    root = _mv_game(tmp_path / "g", [long_src], face="Actor1")
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    app_modern._write_json(bridge._cache_path(), {long_src: "x" * 60})
    assert bridge._overflow_after_translate(bridge._game) == [long_src]
    assert any(e == "notify" and "sığmayabilir" in p["title"] for e, p in bridge._ui.events)


# ── Güncelleme sonrası ve maliyet ───────────────────────────────────────────
def test_updated_game_offers_one_click_reapply(tmp_path, monkeypatch):
    root = make_rpgmaker_game(tmp_path / "g")
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(root))
    bridge._library.upsert(str(root), status="translated", files_stamp="eski")
    run_sync(bridge, "analyze")
    advice = bridge._game["analysis"]["advice"]
    assert advice[0]["action"] == "reapply" and advice[0]["text"] == app_modern.OUTDATED_NOTE
    run_sync(bridge, "analyze", True)
    assert [a["action"] for a in bridge._game["analysis"]["advice"]].count("reapply") == 1


def test_expensive_cloud_translation_asks_first(tmp_path, monkeypatch):
    root = make_rpgmaker_game(tmp_path / "g")
    bridge = make_bridge(tmp_path, monkeypatch, model="openai")
    monkeypatch.setattr(app_modern.prov, "load_provider_config",
                        lambda: providers.ProviderConfig(openai_key="k", openai_model="gpt-4o"))
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    monkeypatch.setattr(bridge, "_estimate", lambda g: {"seconds": 10, "pending": 50000, "cost": {"usd": 12.5, "text": "x"}})
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300: asked.append(text) or False)
    called = []
    monkeypatch.setattr(bridge, "_translate_rpgmaker", lambda g, f: called.append(1) or 0)
    run_sync(bridge, "translate")
    assert asked and "12.50 $" in asked[0] and not called
    assert bridge._library.get(str(root))["status"] == "analyzed"


# ── Konuşan karakter bağlamı ────────────────────────────────────────────────
def test_speaker_note_lists_only_known_speakers_by_index():
    from languages import speaker_note
    note = speaker_note(["Hi.", "Hello.", "Bye."], {"Hello.": "Elena", "Bye.": "Jake"}, "de")
    assert note.endswith("1: Elena, 2: Jake") and "gender" in note
    assert speaker_note(["Hi."], {}, "tr") == "" and speaker_note(["Hi."], None, "tr") == ""
    assert "Konuşan karakterler" in speaker_note(["Hi."], {"Hi.": "Elena"}, "tr")


def test_renpy_entry_speakers_map_variables_to_names(tmp_path):
    import engine_renpy as er
    tl = tmp_path / "tl"
    tl.mkdir()
    (tl / "a.rpy").write_text(
        'translate de s1:\n\n    # e "Hello."\n    e ""\n\n'
        'translate de s2:\n\n    # "Narration."\n    ""\n\n'
        'translate de s3:\n\n    # p "Who am I?"\n    p ""\n\n'
        'translate de s4:\n\n    # e "Hello."\n    j ""\n', encoding="utf-8")
    entries, _ = er.collect_empty_entries(tl)
    names = {"e": "Elena", "j": "Jake", "p": "[player_name]"}
    assert er.entry_speakers(entries, names) == {"Hello.": "Elena"}, "anlatıcı ve değişken adlı karakter atlanır"
    assert er.entry_speakers(entries, None) == {}


def test_cloud_prompt_tells_who_speaks(tmp_path, monkeypatch):
    seen = []

    def fake_batch(provider, items, system, cfg):
        seen.append((list(items), system))
        return [f"TR {x}" for x in items]

    monkeypatch.setattr(providers, "_llm_batch", fake_batch)
    game = make_rpgmaker_game(tmp_path / "game")          # 101 başlığında konuşmacı: Guard
    bridge = make_bridge(tmp_path, monkeypatch, model="openai", target="de")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(openai_key="k"))
    bridge._select_game(str(game))
    run_sync(bridge, "translate")
    items, system = seen[0]
    index = items.index("Welcome to our village, traveler.")
    assert f"{index}: Guard" in system
    assert "Guard" not in json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"][1]["parameters"][0]


# ── Toplu çeviri ────────────────────────────────────────────────────────────
def test_queue_translates_games_one_by_one_and_continues_after_errors(tmp_path, monkeypatch, fake_ollama):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    games = [make_rpgmaker_game(tmp_path / n) for n in ("a", "b", "done", "gone")]
    empty = tmp_path / "empty" / "www" / "data"
    empty.mkdir(parents=True)
    (empty / "System.json").write_text("{}", encoding="utf-8")
    for g in games + [tmp_path / "empty"]:
        bridge._select_game(str(g))
    bridge._game = None
    bridge._library.upsert(str(games[2]), status="translated")
    import shutil
    shutil.rmtree(games[3])
    state = bridge.queue_add([str(g) for g in games] + [str(tmp_path / "empty"), str(games[0])])
    assert [i["state"] for i in state["items"]] == ["waiting"] * 5, "aynı oyun iki kez eklenmez"
    run_sync(bridge, "queue_start")
    items = {Path(i["path"]).name: (i["state"], i["note"]) for i in bridge.queue_state()["items"]}
    assert items["a"] == ("done", "") and items["b"] == ("done", "")
    assert items["done"] == ("skipped", "Zaten çevrilmiş")
    assert items["gone"][0] == "failed" and items["empty"][0] == "failed"
    for g in games[:2]:
        data = json.loads((g / "www/data/Map001.json").read_text(encoding="utf-8"))
        assert data["events"][1]["pages"][0]["list"][2]["parameters"][0] == "TR(The king is waiting for you.)"
        assert bridge._library.get(str(g))["status"] == "translated"
    assert not bridge.queue_state()["running"]
    assert any(e == "notify" and p["title"] == "Toplu çeviri bitti" for e, p in bridge._ui.events)
    assert [i["state"] for i in bridge.queue_clear()["items"]] == []


def test_stopping_the_queue_keeps_the_rest_waiting(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    games = [make_rpgmaker_game(tmp_path / n) for n in ("a", "b")]
    for g in games:
        bridge._select_game(str(g))
    bridge.queue_add([str(g) for g in games])

    def stop():
        bridge._cancel.set()
        raise app_modern.TranslationCancelled()

    monkeypatch.setattr(bridge, "_translate_game", stop)
    run_sync(bridge, "queue_start")
    assert [(i["state"], i["note"]) for i in bridge.queue_state()["items"]] == [("waiting", "Durduruldu"), ("waiting", "")]


def test_declined_question_skips_only_that_game(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    games = [make_rpgmaker_game(tmp_path / n) for n in ("a", "b")]
    for g in games:
        bridge._select_game(str(g))
    bridge.queue_add([str(g) for g in games])
    calls = []

    def maybe():
        calls.append(bridge._game["root"])
        if len(calls) == 1:
            raise app_modern.TranslationCancelled()      # ör. şifreli arşiv onayı verilmedi
        bridge._library.upsert(bridge._game["root"], status="translated")

    monkeypatch.setattr(bridge, "_translate_game", maybe)
    run_sync(bridge, "queue_start")
    assert [(i["state"], i["note"]) for i in bridge.queue_state()["items"]] == [("skipped", "Onay verilmedi"), ("done", "")]


def test_unity_localization_tables_are_detected(tmp_path):
    from types import SimpleNamespace
    from engine_unity import localization_tables
    aa = tmp_path / "StreamingAssets" / "aa" / "StandaloneWindows64"
    aa.mkdir(parents=True)
    for name in ("localization-string-tables-english(en)_assets_all.bundle", "localization-assets-shared_assets_all.bundle",
                 "defaultlocalgroup_assets_all.bundle"):
        (aa / name).write_bytes(b"UnityFS")
    found = localization_tables(SimpleNamespace(streaming_assets_dir=tmp_path / "StreamingAssets"))
    assert [p.name for p in found] == ["localization-string-tables-english(en)_assets_all.bundle"]
    assert localization_tables(SimpleNamespace(streaming_assets_dir=None)) == []
