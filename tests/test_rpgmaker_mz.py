"""RPG Maker MZ: ortak olaylar, savaş olayları, kayan metin, System terimleri, konuşmacı adları ve etiket denetimi.
Konuşmaların çoğu CommonEvents.json'da olan oyunlarda bunlar hiç çevrilmiyordu."""
import io
import json
from pathlib import Path

import app_modern
import engine_renpy
from engine_common import protected_content_valid
from engine_rpgmaker import (PROTECTED_RPGM, extract_texts_mv_mz, join_speaker, speaker_sources, split_speaker,
                             write_translations_mv_mz)
from test_app import make_bridge, run_sync  # noqa: F401

SE = {"name": "Attack", "volume": 90, "pitch": 100, "pan": 0}


def make_mz_game(root: Path) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    (root / "js").mkdir()
    say = lambda text: {"code": 401, "indent": 0, "parameters": [text]}  # noqa: E731
    head = {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]}
    end = {"code": 0, "indent": 0, "parameters": []}
    system = {"gameTitle": "Demo Quest", "terms": {"basic": ["Level", "HP"], "commands": ["Fight", "Escape"],
                                                  "params": ["Attack"], "messages": {"actorDamage": "%1 took %2 damage!"}},
              "elements": ["", "Fire"], "skillTypes": ["", "Magic"], "weaponTypes": [""], "armorTypes": [""],
              "equipTypes": ["", "Weapon"], "attackMotions": [], "sounds": [SE]}
    # BOM'lu dosya: bazı oyunlar böyle kaydediliyor
    (data / "System.json").write_text("﻿" + json.dumps(system), encoding="utf-8")
    page = {"list": [head, say("\\name[勇者]\\C[27] Welcome!\\C[0]"), say("\\name[勇者] Come again."),
                     head, say("\\name[\\V[4]] I'm back."),
                     {"code": 250, "indent": 0, "parameters": [dict(SE)]}, end]}
    (data / "Map001.json").write_text(json.dumps({"events": [None, {"pages": [page]}]}), encoding="utf-8")
    common = [None, {"id": 1, "list": [
        head, say("\\name[伝言板] Your quest has been updated."),
        {"code": 105, "indent": 0, "parameters": [2, False]},
        {"code": 405, "indent": 0, "parameters": ["This is the [old bridge]."]},
        {"code": 102, "indent": 0, "parameters": [["Accept", "Refuse"], 1, 0, 2, 0]},
        end]}]
    (data / "CommonEvents.json").write_text(json.dumps(common), encoding="utf-8")
    troops = [None, {"pages": [{"list": [head, say("You can't beat this!"), end]}]}]
    (data / "Troops.json").write_text(json.dumps(troops), encoding="utf-8")
    skills = [None, {"name": "Attack", "description": "[Axe] A battle axe.", "note": "<cost:5>", "message1": "%1 attacks!"}]
    (data / "Skills.json").write_text(json.dumps(skills), encoding="utf-8")
    return root


def test_common_events_troops_scroll_text_and_choices_are_extracted(tmp_path):
    game = make_mz_game(tmp_path / "g")
    texts = {t.original: t for t in extract_texts_mv_mz(game / "data", log=lambda s: None)}
    assert "\\name[伝言板] Your quest has been updated." in texts, "ortak olay"
    assert texts["This is the [old bridge]."].context == "scroll", "kayan metin (405)"
    assert {"Accept", "Refuse"} <= set(texts), "ortak olaydaki seçenekler"
    assert "You can't beat this!" in texts, "savaş olayı"
    assert {"Fight", "Escape", "%1 took %2 damage!", "Fire"} <= set(texts), "BOM'lu System.json okunur"
    assert "<cost:5>" not in texts, "not alanı eklentilerindir, çevrilmez"


def test_speaker_name_and_line_are_translated_separately():
    lines = ["\\name[勇者]\\C[27] Welcome!\\C[0]", "\\name[勇者] Come again.", "\\name[\\V[4]] I'm back.", "Plain"]
    assert split_speaker(lines[0]) == ("勇者", "\\C[27] Welcome!\\C[0]")
    assert split_speaker(lines[2]) == (None, lines[2]), "içinde kod olan ad olduğu gibi kalır"
    sources = speaker_sources(lines)
    assert sources == ["勇者", "\\C[27] Welcome!\\C[0]", "Come again.", lines[2], "Plain"], "ad bir kez gönderilir"
    tr = {"勇者": "Kahraman", "\\C[27] Welcome!\\C[0]": "\\C[27] Hoş geldin!\\C[0]", "Come again.": "Yine gel.",
          lines[2]: "\\name[\\V[4]] Geri döndüm.", "Plain": "Düz"}
    joined = join_speaker(lines, tr)
    assert joined[lines[0]] == "\\name[Kahraman]\\C[27] Hoş geldin!\\C[0]"
    assert joined[lines[1]] == "\\name[Kahraman] Yine gel."
    assert joined[lines[2]] == "\\name[\\V[4]] Geri döndüm."
    assert join_speaker(["\\name[勇者] Hi."], {"勇者": "Bad]name\\x"})["\\name[勇者] Hi."] == "\\name[Badnamex] Hi.", \
        "ad içinde kodu bozacak karakter kalmaz"


def test_rpgmaker_tags_allow_translating_brackets_but_keep_codes():
    ok = lambda s, t: protected_content_valid(s, t, PROTECTED_RPGM)  # noqa: E731
    assert not ok("Second Path if(s[12])", "İkinci Yol eğer(s[12])"), "seçenek koşulu (eklenti) korunur"
    assert ok("Second Path if(s[12])", "İkinci Yol if(s[12])")
    assert ok("[Axe] A battle axe.", "[Balta] Bir savaş baltası."), "köşeli parantez RPG Maker'da sıradan metindir"
    assert ok("\\pop<1> Ah!? \\!", "\\pop<1> Ah!? \\!")
    assert not ok("\\pop<1> Ah!?", "Ah!?"), "eklenti kodu kaybolursa çeviri reddedilir"
    assert not ok("\\C[27] Hi \\C[0]", "\\C[27] Selam"), "renk kodu korunur"
    assert not ok("%1 took %2 damage!", "%1 hasar aldı!"), "savaş mesajı yer tutucusu korunur"


def test_gemini_uses_engine_tag_rule_when_given(tmp_path, monkeypatch):
    import providers

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        items = json.loads(json.loads(req.data)["contents"][0]["parts"][0]["text"].split("liste:\n", 1)[1])
        out = [s.replace("[Axe] A battle axe.", "[Balta] Bir savaş baltası.") for s in items]
        return Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]}).encode())

    monkeypatch.setattr(engine_renpy.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(engine_renpy, "load_gemini_api_keys", lambda: ["k1"])
    monkeypatch.setattr(engine_renpy.time, "sleep", lambda s: None)
    monkeypatch.setattr(providers, "gemini_model_order", lambda *a: ["gemini-2.5-flash-lite"])
    monkeypatch.setattr(providers, "note_gemini_success", lambda m: None)
    monkeypatch.setattr(engine_renpy, "_write_cache_file", lambda *a, **k: None)
    renpy_cache, rpgm_cache, failed = {}, {}, set()
    engine_renpy.translate_with_gemini(["[Axe] A battle axe."], renpy_cache, tmp_path / "a.json", "k1", log=lambda s: None,
                                       failed_out=failed)
    assert renpy_cache["[Axe] A battle axe."] == "[Axe] A battle axe." and failed, "Ren'Py kuralı değişmedi: [..] değişkendir"
    engine_renpy.translate_with_gemini(["[Axe] A battle axe."], rpgm_cache, tmp_path / "b.json", "k1", log=lambda s: None,
                                       protected=PROTECTED_RPGM)
    assert rpgm_cache["[Axe] A battle axe."] == "[Balta] Bir savaş baltası."


def test_writer_updates_system_terms_and_never_touches_audio_names(tmp_path):
    game = make_mz_game(tmp_path / "g")
    tr = {"Fight": "savaş", "Escape": "kaç", "Level": "İlerleme", "HP": "HP", "%1 took %2 damage!": "%1, %2 hasar aldı!", "Fire": "Ateş", "Attack": "Saldırı",
          "Accept": "Kabul et", "This is the [old bridge].": "Burası [eski köprü]."}
    write_translations_mv_mz(game / "data", tr, log=lambda s: None)
    system = json.loads((game / "data" / "System.json").read_text(encoding="utf-8"))
    assert system["terms"]["commands"] == ["Savaş", "Kaç"], "menü terimi büyük harfle başlar"
    assert system["elements"] == ["", "Ateş"]
    assert system["terms"]["messages"]["actorDamage"] == "%1, %2 hasar aldı!"
    assert system["terms"]["params"] == ["Saldırı"]
    assert system["sounds"][0]["name"] == "Attack", "ses dosyası adı çevrilmez (oyun dosyayı bulamaz)"
    page = json.loads((game / "data" / "Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"]
    assert page[5]["parameters"][0]["name"] == "Attack", "haritadaki ses efekti de"
    skills = json.loads((game / "data" / "Skills.json").read_text(encoding="utf-8"))
    assert skills[1]["name"] == "Saldırı"
    common = json.loads((game / "data" / "CommonEvents.json").read_text(encoding="utf-8"))[1]["list"]
    assert common[3]["parameters"][0] == "Burası [eski köprü]." and common[4]["parameters"][0][0] == "Kabul et"


def test_rpgmaker_mz_end_to_end_translates_common_events_and_speakers(tmp_path, monkeypatch):
    game = make_mz_game(tmp_path / "game")
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    seen = {}

    def fake_gemini(missing, cache, cache_path, api_key, **kw):
        seen["protected"], seen["extra"], seen["sent"] = kw.get("protected"), kw.get("extra_instruction"), list(missing)
        cache.update({m: ("Kahraman" if m == "勇者" else f"TR {m}") for m in missing})
        return len(missing)

    monkeypatch.setattr(engine_renpy, "translate_with_gemini", fake_gemini)
    monkeypatch.setattr(engine_renpy, "load_gemini_api_key", lambda: "k")
    bridge._select_game(str(game))
    run_sync(bridge, "analyze")
    run_sync(bridge, "translate")
    assert seen["protected"] is PROTECTED_RPGM and "RPG Maker" in seen["extra"]
    assert "勇者" in seen["sent"] and not any(s.startswith("\\name[勇者]") for s in seen["sent"])
    common = json.loads((game / "data" / "CommonEvents.json").read_text(encoding="utf-8"))[1]["list"]
    assert common[1]["parameters"][0] == "\\name[TR 伝言板] TR Your quest has been updated."
    assert common[3]["parameters"][0] == "TR This is the [old bridge]."
    page = json.loads((game / "data" / "Map001.json").read_text(encoding="utf-8"))["events"][1]["pages"][0]["list"]
    assert page[1]["parameters"][0] == "\\name[Kahraman]TR \\C[27] Welcome!\\C[0]"
    troops = json.loads((game / "data" / "Troops.json").read_text(encoding="utf-8"))
    assert troops[1]["pages"][0]["list"][1]["parameters"][0] == "TR You can't beat this!"
    # Analiz, önbelleği çeviriyle aynı birimlerle (ad ve satır ayrı) arar: çevrilmiş ad "çevrilecek" sayılmaz
    fresh = make_mz_game(tmp_path / "copy")
    bridge._select_game(str(fresh))
    run_sync(bridge, "analyze")
    assert "勇者" in bridge._game["uniques"] and "\\name[勇者] Come again." not in bridge._game["uniques"]


def test_cached_untranslated_chinese_lines_are_retried(tmp_path, monkeypatch):
    game = make_mz_game(tmp_path / "game")
    data = game / "data" / "CommonEvents.json"
    common = json.loads(data.read_text(encoding="utf-8"))
    common[1]["list"].insert(1, {"code": 401, "indent": 0, "parameters": ["\pop<1> 哇!"]})
    data.write_text(json.dumps(common), encoding="utf-8")
    bridge = make_bridge(tmp_path, monkeypatch, model="gemini")
    bridge._select_game(str(game))
    cache_path = bridge._cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"\pop<1> 哇!": "\pop<1> 哇!", "Accept": "Accept"}), encoding="utf-8")
    sent = []

    def fake_gemini(missing, cache, cache_path, api_key, **kw):
        sent.extend(missing)
        cache.update({m: f"TR {m}" for m in missing})
        return len(missing)

    monkeypatch.setattr(engine_renpy, "translate_with_gemini", fake_gemini)
    monkeypatch.setattr(engine_renpy, "load_gemini_api_key", lambda: "k")
    run_sync(bridge, "analyze")
    run_sync(bridge, "translate")
    assert "\pop<1> 哇!" in sent, "önbellekte çevrilmeden kalmış Çince satır yeniden denenir"
    assert "Accept" not in sent, "Latin harfli ve önbellekte kendisiyle kayıtlı satır (ör. ad) yeniden gönderilmez"
