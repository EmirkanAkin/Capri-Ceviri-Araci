"""Unity bileşen metinleri (unity_typed): PlayMaker dil dalları, anahtar ayıklama, çok dilli XML, TMP font zinciri,
okuyucunun indirilip doğrulanması ve uygulamaya bağlanması."""
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

import engine_unity
import unity_typed as U


# ─── Sentetik PlayMaker verisi ────────────────────────────────────────────────
def fs(value="", var=None):
    return {"useVariable": 1 if var else 0, "name": var or "", "tooltip": "", "showInInspector": 0,
            "networkSync": 0, "value": value}


def action_data(actions, properties=()):
    ad = {k: [] for k in ("actionNames", "actionStartIndex", "paramDataType", "paramName", "paramDataPos",
                          "fsmStringParams", "fsmIntParams", "stringParams")}
    ad["fsmPropertyParams"] = list(properties)
    for name, params in actions:
        ad["actionNames"].append("HutongGames.PlayMaker.Actions." + name)
        ad["actionStartIndex"].append(len(ad["paramDataType"]))
        for kind, pname, payload in params:
            store = {18: "fsmStringParams", 16: "fsmIntParams", 23: "stringParams", 3: "stringParams"}.get(kind)
            pos = 0
            if store:
                pos = len(ad[store])
                ad[store].append(payload)
            ad["paramDataType"].append(kind)
            ad["paramName"].append(pname)
            ad["paramDataPos"].append(pos)
    return ad


def set_string(var, value):
    return "SetStringValue", [(18, "stringVariable", fs("", var)), (18, "stringValue", fs(value))]


def set_fsm_string(var, value):
    return "SetFsmString", [(18, "fsmName", fs("FSM")), (18, "variableName", fs(var)), (18, "setValue", fs(value))]


def int_switch(var, values, events):
    return "IntSwitch", ([(16, "intVariable", {"useVariable": 1, "name": var, "value": 0}), (12, "compareTo", None)]
                         + [(16, "", {"useVariable": 0, "name": "", "value": v}) for v in values]
                         + [(12, "sendEvent", None)] + [(23, "", e) for e in events] + [(1, "everyFrame", None)])


def text_property(value, kind="UnityEngine.UI.Text"):
    return {"TargetTypeName": kind, "PropertyName": "text", "setProperty": 1, "StringParameter": fs(value)}


def state(name, transitions=(), actions=(), properties=()):
    return {"name": name, "transitions": [{"fsmEvent": {"name": e}, "toState": t} for e, t in transitions],
            "actionData": action_data(actions, properties)}


def named_fsm():
    """Dil olayları adlı: Japanese/English/Korean → JP/EN/KR; EN dalı EN2'ye zincirlenir; End ortak."""
    return {"fsm": {"name": "FSM", "states": [
        state("Switch", [("Japanese", "JP"), ("English", "EN"), ("Korean", "KR")],
              [int_switch("LangIndex", [0, 1, 4], ["Japanese", "English", "Korean"])]),
        state("JP", [("FINISHED", "End")], [set_string("Text_1", "こんにちは"), set_string("Room", "Room_Main"),
                                             set_string("Lang", "Lang_jp"), set_fsm_string("Mode", "Sit")]),
        state("EN", [("FINISHED", "EN2")], [set_string("Text_1", "Hello there"), set_string("Room", "Room_Main"),
                                             set_string("Lang", "Lang_en"), set_fsm_string("Mode", "Sit")]),
        state("EN2", [("FINISHED", "End")], [set_fsm_string("Msg_2", "The gate is closed...")]),
        state("KR", [("FINISHED", "End")], [set_string("Text_1", "안녕"), set_string("Room", "Room_Main"),
                                             set_string("Lang", "Lang_kr"), set_fsm_string("Mode", "Sit")]),
        state("End", [], [set_string("Pose", "Stand"), set_string("Msg", "This sentence is shared by all."),
                          set_string("Hint", "Go")]),
    ]}}


def numbered_fsm():
    """Aynı dil değişkenine '0', '1', '4' olaylarıyla bakar; metin SetProperty ile doğrudan UI Text'e yazılır."""
    return {"fsm": {"name": "Menu", "states": [
        state("Pick", [("0", "S0"), ("1", "S1"), ("4", "S4")], [int_switch("LangIndex", [0, 1, 4], ["0", "1", "4"])]),
        state("S0", properties=[text_property("日本語"), text_property("買う")]),
        state("S1", properties=[text_property("ENGLISH"), text_property("Buy")]),
        state("S4", properties=[text_property("한국어"), text_property("구매")]),
    ]}}


def texts_of(tree, numbers):
    found = U.fsm_texts(tree, ("fsm",), numbers)
    for path, value in found:
        assert U.get_path(tree, path) == value, "ağaç yolu metni göstermeli"
    return sorted(v for _p, v in found)


def test_language_codes_and_display_rules():
    assert U.lang_code("English") == "en" and U.lang_code("jp") == "ja" and U.lang_code("Chinese_S") == "zh-hans"
    assert U.lang_code("cht") == "zh-hant" and U.lang_code("Korean") == "ko" and U.lang_code("FINISHED") is None
    for key in ("Room_Main", "Room_Side", "Lang_en", "Slot1.sav", "Lv1", "fsmName", "Door_Left_B", "UI/Panel"):
        assert not U.is_display_text(key), key
    for text in ("Hello there", "Buy", "ENGLISH", "DAY", "The gate is closed...", "Gold - 2", "Level Up!"):
        assert U.is_display_text(text), text
    assert not U.is_display_text("こんにちは") and not U.is_display_text("123") and not U.is_display_text(" ")
    assert U.sentence_like("This sentence is shared by all.") and not U.sentence_like("Go")
    assert not U.sentence_like("Stand")


def test_playmaker_language_branches_keep_logic_keys():
    tree = named_fsm()
    numbers = U.learn_language_numbers([tree["fsm"]])
    assert numbers == {"LangIndex": {0: "ja", 1: "en", 4: "ko"}}
    langs = U.fsm_language_states(tree["fsm"], numbers)
    assert langs["EN"] == langs["EN2"] == "en", "dal zinciri boyunca yayılır"
    assert "End" not in langs and "Switch" not in langs, "ortak durum ve dil seçicisi hiçbir dile ait değil"
    # Her dilde aynı değer alan Room_Main/Sit ve tanımlayıcı Lang_en çevrilmez; ortak durumdaki cümle alınır
    assert texts_of(tree, numbers) == ["Hello there", "The gate is closed...", "This sentence is shared by all."]


def test_numbered_language_switch_uses_learned_mapping():
    numbers = U.learn_language_numbers([named_fsm()["fsm"]])
    tree = numbered_fsm()
    assert U.fsm_language_states(tree["fsm"], numbers) == {"S0": "ja", "S1": "en", "S4": "ko"}
    assert texts_of(tree, numbers) == ["Buy", "ENGLISH"]
    assert U.fsm_language_states(tree["fsm"], {}) == {}, "eşleme bilinmezse sayılar dil sayılmaz"


def test_fsm_without_languages_takes_only_direct_text_and_sentences():
    tree = {"fsm": {"states": [state("A", [], [set_string("Key", "Key_A"), set_string("Pose", "Sit"),
                                               set_string("Line", "You found a rusty key!")],
                                     [text_property("Start"), text_property("Ui_Label_3")])]}}
    assert texts_of(tree, {}) == ["Start", "You found a rusty key!"]


# ─── Çok dilli XML ────────────────────────────────────────────────────────────
XML = ('<?xml version="1.0" encoding="UTF-8"?>\r\n<Job>\r\n'
       '\t<Language ID="1" kr="상인" jp="商人" en="Merchant" chs="商人"/>\r\n'
       '\t<Language ID="2" kr="가" jp="あ" en="Tom &amp; Jerry fan" chs="中"/>\r\n'
       '\t<Note text="not a language row"/>\r\n</Job>\r\n')


def test_xml_language_cells_and_rewrite_only_touch_source_attribute():
    cells = U.xml_language_cells(XML)
    assert [(c[1], c[2]) for c in cells] == [("en", "Merchant"), ("en", "Tom & Jerry fan")]
    replacements = {(n, a): (v, {"Merchant": "Tüccar", "Tom & Jerry fan": "Tom & Jerry \"hayranı\""}[v])
                    for n, a, v in cells}
    out, changed = U.xml_rewrite(XML, replacements)
    assert changed == 2
    assert 'en="Tüccar"' in out and 'en="Tom &amp; Jerry &quot;hayranı&quot;"' in out
    assert out.replace('en="Tüccar"', 'en="Merchant"').replace(
        'en="Tom &amp; Jerry &quot;hayranı&quot;"', 'en="Tom &amp; Jerry fan"') == XML, "başka hiçbir bayt değişmez"
    stale = {(cells[0][0], "en"): ("Something else", "X")}
    assert U.xml_rewrite(XML, stale) == (XML, 0), "değer değişmişse dokunulmaz"


def test_names_table_is_not_translated():
    assert U.names_table("Names", ["Mark", "Rose", "Grace", "Mary Ann"])
    assert not U.names_table("Jobs", ["Merchant", "Blacksmith"])
    assert not U.names_table("Names", ["Night guard", "street cook", "a b c"])


# ─── TextMeshPro font zinciri ────────────────────────────────────────────────
class _Asset:
    def __init__(self, name):
        self.name, self.externals = name, [type("E", (), {"path": "archive/other.assets"})()]


class _Obj:
    def __init__(self, file):
        self.assets_file = file


def test_tmp_glyphs_follow_fallbacks_settings_and_default_font():
    main, other = _Asset("level2"), _Asset("other.assets")
    latin = [{"m_Unicode": ord(c)} for c in "abcdefghijklmnopqrstuvwxyz"]
    fonts = {
        ("level2", 1): {"m_CharacterTable": latin, "m_FallbackFontAssetTable": []},               # CJK benzeri, TR yok
        ("other.assets", 5): {"m_CharacterTable": latin + [{"m_Unicode": ord(c)} for c in "ğş"],
                              "m_FallbackFontAssetTable": [{"m_FileID": 0, "m_PathID": 6}]},
        ("other.assets", 6): {"m_CharacterTable": [{"m_Unicode": ord("ı")}], "m_FallbackFontAssetTable": []},
    }
    objects = {("level2", 1): _Obj(main), ("other.assets", 5): _Obj(other), ("other.assets", 6): _Obj(other)}
    used = [("level2", 1)]
    assert ord("ğ") not in U.tmp_effective_glyphs(objects, fonts, None, used)
    settings = (_Obj(main), {"m_defaultFontAsset": {"m_FileID": 1, "m_PathID": 5}, "m_fallbackFontAssets": []})
    glyphs = U.tmp_effective_glyphs(objects, fonts, settings, used)
    assert {ord(c) for c in "ğşı"} <= glyphs, "varsayılan font ve onun yedeği de aranır"


# ─── Okuyucu: indirme, doğrulama, kurulum ─────────────────────────────────────
def _wheel(extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("TypeTreeGeneratorAPI/__init__.py", "MARK = 1\n")
        archive.writestr("TypeTreeGeneratorAPI/TypeTreeGeneratorAPI.dll", b"MZ")
        archive.writestr("typetreegeneratorapi-0.0.10.dist-info/licenses/LICENSE", "MIT")
        archive.writestr("typetreegeneratorapi-0.0.10.dist-info/RECORD", "x")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _opener(data):
    class Response(io.BytesIO):
        def __exit__(self, *args):
            self.close()

    return lambda request, timeout=60: Response(data)


def _pin(monkeypatch, tmp_path, data):
    monkeypatch.setattr(U, "reader_dir", lambda: tmp_path / "tools" / "typetree" / "0.0.10")
    monkeypatch.setattr(U, "READER_WHEEL", {**U.READER_WHEEL, "size": len(data),
                                            "sha256": hashlib.sha256(data).hexdigest()})


def test_reader_install_verifies_and_extracts_only_its_package(tmp_path, monkeypatch):
    data = _wheel()
    _pin(monkeypatch, tmp_path, data)
    folder = U.install_reader(opener=_opener(data), log=lambda s: None)
    assert sorted(p.name for p in folder.iterdir()) == ["LICENSE", "SOURCE.txt", "TypeTreeGeneratorAPI"]
    assert "GPL-3.0" in (folder / "SOURCE.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(U, "READER_WHEEL", {**U.READER_WHEEL, "sha256": "0" * 64})
    with pytest.raises(ValueError):
        U.install_reader(opener=_opener(data), log=lambda s: None)
    assert (folder / "TypeTreeGeneratorAPI" / "__init__.py").is_file(), "başarısız indirme kurulu sürümü bozmaz"


def test_reader_install_rejects_path_traversal(tmp_path, monkeypatch):
    data = _wheel({"../evil.py": "x"})
    _pin(monkeypatch, tmp_path, data)
    with pytest.raises(RuntimeError):
        U.install_reader(opener=_opener(data), log=lambda s: None)
    assert not (tmp_path / "tools" / "typetree" / "evil.py").exists()
    assert not U.reader_dir().exists()


def test_reader_is_pinned_to_the_published_wheel():
    assert U.READER_WHEEL["url"].startswith("https://files.pythonhosted.org/") and U.READER_WHEEL["url"].endswith(
        U.READER_WHEEL["name"])
    assert len(U.READER_WHEEL["sha256"]) == 64 and U.READER_SIZE_MB > 1


# ─── Motora ve uygulamaya bağlanma ────────────────────────────────────────────
def make_bundled_game(root: Path) -> Path:
    data = root / "Demo_Data"
    (data / "Managed").mkdir(parents=True)
    (data / "boot.config").write_text("", encoding="utf-8")
    (data / "data.unity3d").write_bytes(b"UnityFS\0")
    (root / "Demo.exe").write_bytes(b"MZ")
    return root


def test_bundled_game_reports_missing_reader(tmp_path, monkeypatch):
    info = engine_unity.detect_unity_game(make_bundled_game(tmp_path / "g"))
    monkeypatch.setattr(U, "generator_available", lambda: False)
    assert engine_unity.extract_texts_unity(info, log=lambda s: None) == []
    assert info.typed_reader_missing and U.containers(info) == [info.data_dir / "data.unity3d"]
    assert U.wants_reader(info, 0)


def test_typed_items_are_written_through_the_engine(tmp_path, monkeypatch):
    info = engine_unity.detect_unity_game(make_bundled_game(tmp_path / "g"))
    item = engine_unity.UnityTextItem("data.unity3d", "fsm:level0:1", 0, "[]", "Buy", "typed")
    seen = {}
    monkeypatch.setattr(U, "write", lambda info, tr, items, log, target="tr", replace_file=None:
                        seen.update(target=target, n=len(items)) or 1)
    assert engine_unity.write_translations_unity(info, {"Buy": "Satın al"}, [item], log=lambda s: None,
                                                 target_lang="de") == 1
    assert seen == {"target": "de", "n": 1}


def test_app_offers_reader_once_and_respects_no(tmp_path, monkeypatch):
    from test_app import make_bridge
    bridge = make_bridge(tmp_path, monkeypatch)
    root = make_bundled_game(tmp_path / "game")
    monkeypatch.setattr(U, "generator_available", lambda: False)
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append(text) or False)
    game = {"root": str(root), "type": "unity", "info": None, "texts": None}
    result = bridge._analyze_unity(game)
    assert len(asked) == 1 and "SHA-256" in asked[0] and game["reader_declined"]
    assert result["bepinex"]["needed"], "okuyucu reddedilince BepInEx yolu kalır"
    bridge._analyze_unity(game)
    assert len(asked) == 1, "aynı oturumda yeniden sorulmaz"


def test_app_downloads_reader_and_rescans(tmp_path, monkeypatch):
    from test_app import make_bridge
    bridge = make_bridge(tmp_path, monkeypatch)
    root = make_bundled_game(tmp_path / "game")
    state = {"installed": False}
    monkeypatch.setattr(U, "generator_available", lambda: state["installed"])
    monkeypatch.setattr(U, "install_reader", lambda log=print, **k: state.update(installed=True))
    item = engine_unity.UnityTextItem("data.unity3d", "fsm:level0:1", 0, "[]", "Buy", "typed")
    monkeypatch.setattr(U, "scan", lambda info, log=print, source="en":
                        U.TypedScan([item], set(), {"fsm": 1}))
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: True)
    game = {"root": str(root), "type": "unity", "info": None, "texts": None}
    result = bridge._analyze_unity(game)
    assert result["lines"] == 1 and not result["bepinex"]["needed"]
    assert any("PlayMaker" in n for n in result["notes"])


# ─── Gerçek okuyucu ve gerçek oyun (dosyalar verilirse) ───────────────────────
WHEEL = os.environ.get("CAPRI_TTG_WHEEL", "")
SAMPLE = os.environ.get("CAPRI_UNITY_SAMPLE", "")   # yazılabilir bir KOPYA: içindeki data.unity3d değiştirilir


@pytest.mark.skipif(not (WHEEL and Path(WHEEL).is_file()), reason="CAPRI_TTG_WHEEL verilmedi")
def test_real_reader_wheel_matches_pin(tmp_path, monkeypatch):
    data = Path(WHEEL).read_bytes()
    assert len(data) == U.READER_WHEEL["size"] and hashlib.sha256(data).hexdigest() == U.READER_WHEEL["sha256"]
    monkeypatch.setattr(U, "reader_dir", lambda: tmp_path / "typetree")
    folder = U.install_reader(opener=_opener(data), log=lambda s: None)
    assert (folder / "TypeTreeGeneratorAPI" / "TypeTreeGeneratorAPI.dll").stat().st_size > 1_000_000


@pytest.mark.skipif(not (SAMPLE and Path(SAMPLE).is_dir()), reason="CAPRI_UNITY_SAMPLE verilmedi")
def test_real_game_copy_round_trip(tmp_path):
    assert U.generator_available(), "örnek oyun testi için okuyucu kurulu olmalı"
    info = engine_unity.detect_unity_game(SAMPLE)
    items = engine_unity.extract_texts_unity(info, log=lambda s: None)
    typed = [i for i in items if i.format_type == "typed"]
    assert typed, "örnek oyunda bileşen metni bulunmalı"
    translations = {i.original: "Çeviri·" + i.original for i in typed}
    assert engine_unity.write_translations_unity(info, translations, items, log=lambda s: None) == len(typed)
    again = engine_unity.extract_texts_unity(engine_unity.detect_unity_game(SAMPLE), log=lambda s: None)
    assert all(i.original.startswith("Çeviri·") or i.original.isupper() for i in again if i.format_type == "typed")


def test_letter_spaced_titles_are_translated_collapsed(monkeypatch, tmp_path):
    assert engine_unity.collapse_spaced("S T A R T   G A M E") == "START GAME"
    assert engine_unity.collapse_spaced("A B") is None and engine_unity.collapse_spaced("2 0 1 9 © U R A P") is None
    seen = []
    monkeypatch.setattr(engine_unity, "_translate_texts_unity",
                        lambda sources, *a, **k: seen.extend(sources) or {"START GAME": "OYUNA BAŞLA", "Quit": "Çık"})
    out = engine_unity.translate_texts_unity(["S T A R T   G A M E", "Quit"], tmp_path / "c.json")
    assert sorted(seen) == ["Quit", "START GAME"], "modele sıkıştırılmış hâli gider"
    assert out["S T A R T   G A M E"] == "O Y U N A   B A Ş L A"


def test_player_log_missing_glyphs_are_read_and_forced_on_next_write(tmp_path, monkeypatch):
    """Oyun çalışırken TextMeshPro'nun "bulunamadı" dediği harfler (Player.log) bulunur; sonraki yazımda en yakın harfle
    yazılır. app.info'daki ad yol geçişi içeriyorsa kayıt aranmaz."""
    import os
    import time as _time
    from types import SimpleNamespace
    import engine_unity
    data = tmp_path / "Oyun_Data"
    data.mkdir()
    (data / "app.info").write_text("Studio\nOyun Adi", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    logdir = tmp_path / "home" / "AppData" / "LocalLow" / "Studio" / "Oyun Adi"
    logdir.mkdir(parents=True)
    line = ("The character with Unicode value \\u{0} was not found in the [LiberationSans SDF] font asset or any "
            "potential fallbacks. It was replaced by Unicode character \\u25A1 in text object [Text].\n")
    (logdir / "Player.log").write_text(line.format("011F") + line.format("015F") + line.format("2665"), encoding="utf-8")
    info = SimpleNamespace(data_dir=data, tmp_glyphs=set(), runtime_missing=set())
    assert engine_unity.runtime_missing_glyphs(info) == {"LiberationSans SDF": ["ğ", "ş"]}
    assert engine_unity.runtime_missing_glyphs(info, since=_time.time() + 60) == {}
    info.runtime_missing = {"ğ", "ş"}
    glyphs = engine_unity.effective_glyphs(info)
    assert engine_unity.glyph_fallback("Doğru yaşıyorsun", glyphs) == "Dogru yasıyorsun"
    info.runtime_missing = set()
    assert engine_unity.effective_glyphs(info) == set()
    (data / "app.info").write_text("..\nEvil", encoding="utf-8")
    assert engine_unity.player_log_paths(info) == []


def test_unity_glyph_advice_ignores_letters_not_in_our_translation(tmp_path, monkeypatch):
    """Gerçek bir oyunun kaydında dil listesindeki Arapça/Hintçe harfler de "bulunamadı" diye geçiyordu: yalnızca bizim
    çevirimizde geçen harfler uyarıya ve zorunlu harf değişimine girer."""
    import json
    import time as _time
    from types import SimpleNamespace
    import app_modern
    from test_app import make_bridge
    data = tmp_path / "Oyun_Data"
    data.mkdir()
    (data / "app.info").write_text("Studio\nOyun", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    logdir = tmp_path / "home" / "AppData" / "LocalLow" / "Studio" / "Oyun"
    logdir.mkdir(parents=True)
    entry = "The character with Unicode value \\u{0} was not found in the [Main SDF] font asset or any potential fallbacks.\n"
    (logdir / "Player.log").write_text(entry.format("062C") + entry.format("011F"), encoding="utf-8")
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._game = {"root": str(tmp_path), "type": "unity", "title": "Oyun",
                    "info": SimpleNamespace(data_dir=data, tmp_glyphs=set(), runtime_missing=set())}
    cache = bridge._cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"Right": "Doğru"}), encoding="utf-8")
    bridge._library.upsert(tmp_path, status="translated", translated_at=_time.time() - 100)
    analysis = {"advice": []}
    bridge._check_unity_glyphs(bridge._game, analysis, bridge._library.get(tmp_path))
    assert bridge._library.get(tmp_path)["runtime_missing"] == "ğ"
    assert "ğ" in analysis["advice"][0]["text"] and "ج" not in analysis["advice"][0]["text"]
