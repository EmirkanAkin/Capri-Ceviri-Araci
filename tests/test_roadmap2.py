"""Yol haritası (2. tur): tek pencere, bildirim balonu, ortak çeviri belleği, tarama tahmini, yama güvenliği, dil."""
import json
import os

import pytest

import app_modern
from test_app import make_bridge, make_rpgmaker_game, run_sync  # noqa: F401


@pytest.mark.skipif(os.name != "nt", reason="Windows kilidi")
def test_second_launch_of_same_install_is_refused(tmp_path, monkeypatch):
    import single_instance
    monkeypatch.delenv("CAPRI_MULTI", raising=False)
    assert single_instance.acquire(tmp_path / "A", tmp_path / "dataA") is True
    first = single_instance._handle
    assert json.loads((tmp_path / "dataA" / "instance.json").read_text())["pid"] == os.getpid()
    assert single_instance.acquire(tmp_path / "A", tmp_path / "dataA2") is False, "aynı kurulum ikinci kez açılmaz"
    assert single_instance.acquire(tmp_path / "B", tmp_path / "dataB") is True, "başka klasördeki kopya engellenmez"
    assert first and single_instance.mutex_name(tmp_path / "A") != single_instance.mutex_name(tmp_path / "B")
    assert single_instance.focus_existing(tmp_path / "yok") is False


def test_finished_translation_shows_windows_notification_when_enabled(tmp_path, monkeypatch):
    import ctypes
    import ocr
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(ocr.NOTIFYICONDATAW) == 976, "Windows'un beklediği NOTIFYICONDATAW boyutu"
    shown = []
    monkeypatch.setattr(ocr, "balloon", lambda title, text, icon=None: shown.append((title, text)) or True)
    monkeypatch.setattr(ocr, "attention", lambda title="Capri": False)
    monkeypatch.setattr(ocr, "play_sound", lambda path: True)
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._attention("done", "Çeviri tamamlandı", "Oyun · 10 satır")
    bridge._attention("done")                                   # başlıksız çağrı balon göstermez
    bridge._settings["notify"] = False
    bridge._attention("error", "Hata", "ayrıntı")
    assert shown == [("Çeviri tamamlandı", "Oyun · 10 satır")]
    assert app_modern.DEFAULT_SETTINGS["notify"] is True


def test_ui_text_rule_shares_only_short_interface_strings():
    ok = ["Save", "Load Game", "Start Day", "Options", "Back", "Rock & Roll"]
    bad = ["Thanks.", "save", "I'm sorry for being such a pervert", "Day {0}", "[mc]", "Hello there friend now",
           " Save", "Ok?", "x"]
    assert all(app_modern.is_ui_text(s) for s in ok)
    assert not any(app_modern.is_ui_text(s) for s in bad)


def test_translation_memory_is_shared_between_games(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    first = tmp_path / "first.json"
    app_modern._write_json(first, {"Save": "Kaydet", "Load Game": "Oyun Yükle", "Thanks.": "Sağ ol.", "Back": "Back"})
    assert bridge._learn_memory(first) == 2, "çevrilmemiş (aynı kalan) ve cümleler belleğe girmez"
    second = tmp_path / "second.json"
    app_modern._write_json(second, {"Save": "Kayıt"})
    assert bridge._seed_memory(second) == 1
    assert app_modern._read_json(second, {}) == {"Save": "Kayıt", "Load Game": "Oyun Yükle"}, "oyunun kendi çevirisi ezilmez"
    bridge._settings["target"] = "de"
    assert bridge._seed_memory(tmp_path / "third.json") == 0, "bellek hedef dile göre ayrı"
    bridge._settings["memory"] = False
    assert bridge._learn_memory(first) == 0


def test_scan_estimates_unity_and_unreal_lines(tmp_path, monkeypatch):
    import engine_unity
    import engine_unreal
    item = lambda text: type("T", (), {"original": text})()   # noqa: E731
    monkeypatch.setattr(engine_unity, "detect_unity_game", lambda root: object())
    monkeypatch.setattr(engine_unity, "extract_texts_unity", lambda info, log=None: [item("Save"), item("Save"), item("Load")])
    assert app_modern.quick_line_count({"path": str(tmp_path), "engine": "unity"}) == 2
    packed = type("U", (), {"locres_files": []})()
    monkeypatch.setattr(engine_unreal, "detect_unreal_game", lambda root: packed)
    assert app_modern.quick_line_count({"path": str(tmp_path), "engine": "unreal"}) is None, "paketli: analizde sayılır"
    loose = type("U", (), {"locres_files": [tmp_path / "Game.locres"]})()
    monkeypatch.setattr(engine_unreal, "detect_unreal_game", lambda root: loose)
    monkeypatch.setattr(engine_unreal, "extract_texts_unreal", lambda info, log=None: [item("Quit"), item(" ")])
    assert app_modern.quick_line_count({"path": str(tmp_path), "engine": "unreal"}) == 1


def _patch(tmp_path, engine, translations, name="p.capripatch"):
    import zipfile
    patch = tmp_path / name
    with zipfile.ZipFile(patch, "w") as z:
        z.writestr("manifest.json", json.dumps({"engine": engine, "title": "Demo"}))
        z.writestr("translations.json", json.dumps(translations))
    return patch


def test_imported_patch_cannot_inject_tags_code_or_links(tmp_path, monkeypatch):
    """Başkasından gelen yama: yalnızca kaynakla aynı etiket/kodu taşıyan düz çeviriler alınır."""
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    patch = _patch(tmp_path, "rpgmaker", {
        "New Game": "Yeni Oyun",                                         # temiz
        "Hello \\C[3]friend\\C[0]!": "Merhaba \\C[3]dostum\\C[0]!",       # kaynaktaki kodlar korunmuş
        "Welcome!": "Hoş geldin!\\js<require('child_process').exec('calc')>",  # MV/MZ eklentisiyle kod çalıştırma
        "Goodbye.": "Hoşça kal. https://evil.example/phish",            # bağlantı ekleme
        "Yes": "Evet\n\\V[9999]",                                       # fazladan satır ve değişken
        "No": "Hayır\x00",                                              # kontrol karakteri
        "Hi.": "x" * 500,                                                # anlamsız uzunluk
    })
    assert bridge._apply_patch_file(patch) is True
    cache = app_modern._read_json(bridge._cache_path(), {})
    assert cache == {"New Game": "Yeni Oyun", "Hello \\C[3]friend\\C[0]!": "Merhaba \\C[3]dostum\\C[0]!"}
    warn = [e[1] for e in bridge._ui.events if e[0] == "notify" and "alınmadı" in e[1]["title"]]
    assert warn and warn[0]["title"].startswith("5 satır")


def test_renpy_patch_cannot_add_hyperlinks_or_interpolation():
    import patch_safety
    safe, rejected = patch_safety.filter_translations({
        "Hello, [mc]!": "Merhaba, [mc]!",
        "Click here.": "Buraya tıkla {a=https://evil.example}burası{/a}.",
        "Nice.": "Güzel [renpy.os.system('calc')].",
        "Wow.": 'Vay." \n    $ import os',
    }, "renpy")
    assert safe == {"Hello, [mc]!": "Merhaba, [mc]!"} and rejected == 3


def test_patch_archive_limits(tmp_path, monkeypatch):
    import zipfile
    import patch_safety
    bomb = tmp_path / "bomb.capripatch"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", "{}")
        z.writestr("translations.json", "{" + " " * (patch_safety.MAX_TRANSLATIONS + 10) + "}")
    assert bomb.stat().st_size < 1_000_000, "sıkıştırılmış hali küçük"
    with pytest.raises(ValueError):
        patch_safety.read_patch(bomb)
    bridge = make_bridge(tmp_path, monkeypatch)
    bridge._select_game(str(make_rpgmaker_game(tmp_path / "game")))
    assert bridge._apply_patch_file(bomb) is False, "açılmadan reddedilir"


def test_english_dictionary_keeps_placeholders():
    import i18n
    broken = [k for k, v in i18n.EN.items() if not i18n.placeholders_ok(k, v)]
    assert broken == [], f"yer tutucusu bozuk: {broken[:5]}"
    assert len(i18n.EN) > 600


def test_language_codes_from_windows_locales():
    import i18n
    assert i18n.normalize("de_DE") == "de" and i18n.normalize("pt_BR") == "pt-BR" and i18n.normalize("pt-PT") == "pt"
    assert i18n.normalize("zh_TW") == "zh-TW" and i18n.normalize("zh_CN") == "zh-CN" and i18n.normalize("tr_TR") == "tr"
    assert i18n.normalize("xx_YY") is None and i18n.system_language() in {l["code"] for l in i18n.ui_languages()}


def test_ui_dictionary_is_generated_once_and_falls_back_safely(tmp_path):
    import i18n
    dictionaries = i18n.Dictionaries(tmp_path)
    assert dictionaries.get("tr") == {} and dictionaries.get("en")["Kapat"] == "Close"
    assert dictionaries.get("de") is None, "üretilmemiş dil"
    calls = []

    def fake(lines):
        calls.append(len(lines))
        return {l: ("BOZUK" if "{0}" in l else "DE:" + l) for l in lines}
    built, failed = dictionaries.build("de", fake)
    assert built["Kapat"] == "DE:Close" and built["{0} satır"] == "{0} lines", "yer tutucusu bozulan İngilizce kalır"
    assert failed > 0 and dictionaries.get("de") == built
    dictionaries.build("de", fake)
    assert len(calls) == 1, "tamamlanmış sözlük yeniden çevrilmez"
    assert i18n.translate_text("Çeviri tamamlandı", built) == built["Çeviri tamamlandı"]
    assert i18n.translate_text("Hızlı Oyun · 12 satır", {"{0} · {1} satır": "{0} · {1} Zeilen"}) == "Hızlı Oyun · 12 Zeilen"


def test_switching_ui_language_also_switches_target(tmp_path, monkeypatch):
    import i18n
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(app_modern, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(bridge, "_ui_translator", lambda code: (lambda lines: {l: "NL " + l for l in lines}))
    res = bridge.set_ui_language("de_DE")
    assert res["ok"] and res["language"] == "de" and res["target_changed"]
    assert bridge._settings["target"] == "de" and bridge._settings["ui_language"] == "de"
    assert res["dict"]["Kapat"] == "Schließen", "Almanca pakette hazır gelir"
    res = bridge.set_ui_language("nl")
    assert res["ok"] and res["dict"]["Kapat"] == "NL Close", "hazır gelmeyen dil bulutla üretilir"
    bridge._settings["target"] = "de"
    res = bridge.set_ui_language("en")
    assert res["dict"]["Kapat"] == "Close" and bridge._settings["target"] == "de", "İngilizce hedef listesinde yok: değişmez"
    monkeypatch.setattr(bridge, "_ui_translator", lambda code: None)
    res = bridge.set_ui_language("ja")
    assert not res["ok"] and "anahtar" in res["error"] and res["dict"]["Kapat"] == "Close", "anahtar yoksa İngilizce"
    assert bridge.get_state()["ui"]["pending"] is True


def test_first_run_follows_windows_language_but_existing_users_stay_turkish(tmp_path, monkeypatch):
    import i18n
    monkeypatch.setattr(i18n, "system_language", lambda: "de")
    monkeypatch.setattr(app_modern, "SETTINGS_FILE", tmp_path / "yok.json")
    fresh = app_modern.load_settings()
    assert fresh["ui_language"] == "de" and fresh["target"] == "de"
    existing = tmp_path / "settings.json"
    existing.write_text(json.dumps({"target": "tr", "model": "gemini"}), encoding="utf-8")
    monkeypatch.setattr(app_modern, "SETTINGS_FILE", existing)
    old = app_modern.load_settings()
    assert old["ui_language"] == "tr" and old["target"] == "tr"
