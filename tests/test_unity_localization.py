"""
Unity Localization (com.unity.localization) dize tabloları: Unity 6 veri dosyaları (StreamingAssets/LocalizationTables)
ve Addressables kataloğundaki CRC kapatma. Paket (StringTable) yazımı unity_typed'ın birebir okuma/geri yazma
denetimini ve kayıt sonrası doğrulamayı kullanır.
"""
import base64
import json
import struct

import pytest

import app_modern
import unity_localization as ul
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401 (fixture)
from test_ux import _unity_game


def _entries(values, field="Value"):
    return [{"Id": 1000 + i, "Key": f"KEY_{i}", field: v, "Metadata": ""} for i, v in enumerate(values)]


def _write_tables(data_dir, field="Value", second=True):
    base = data_dir / "StreamingAssets" / "LocalizationTables"
    base.mkdir(parents=True, exist_ok=True)
    en = {"CollectionGuid": "abc", "CollectionName": "Menus", "LocaleCode": "en", "SchemaVersion": "3",
          "Entries": _entries(["New Game", "Hello {player}!", "42"], field)}
    (base / "Menus_en.json").write_text(json.dumps(en), encoding="utf-8")
    if second:
        fr = dict(en, LocaleCode="fr", Entries=_entries(["Nouvelle partie", "Bonjour {player} !", "42"], field))
        (base / "Menus_fr.json").write_text(json.dumps(fr), encoding="utf-8")
    return base


class _Info:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.streaming_assets_dir = data_dir / "StreamingAssets"


@pytest.mark.parametrize("field, second", [("Value", True), ("Localized", False), ("Translation", True)])
def test_data_file_tables_value_field_and_new_language_file(tmp_path, field, second):
    data = tmp_path / "Game_Data"
    base = _write_tables(data, field, second)
    tables = ul.file_tables(_Info(data))
    assert len(tables) == 1 and tables[0].locale == "en" and tables[0].value_field == field
    path, changed = ul.write_file_table(tables[0], {"New Game": "Yeni Oyun", "Hello {player}!": "Merhaba {player}!"}, "tr")
    assert path == base / "Menus_tr.json" and changed == 2
    out = json.loads(path.read_text(encoding="utf-8"))
    assert out["LocaleCode"] == "tr" and out["SchemaVersion"] == "3" and out["CollectionGuid"] == "abc"
    assert [e[field] for e in out["Entries"]] == ["Yeni Oyun", "Merhaba {player}!", "42"]
    assert [e["Key"] for e in out["Entries"]] == ["KEY_0", "KEY_1", "KEY_2"], "anahtarlar ve kimlikler değişmez"
    assert json.loads((base / "Menus_en.json").read_text(encoding="utf-8"))["Entries"][0][field] == "New Game"


def test_unknown_entry_layout_is_skipped(tmp_path):
    data = tmp_path / "Game_Data"
    base = data / "StreamingAssets" / "LocalizationTables"
    base.mkdir(parents=True)
    (base / "Menus_en.json").write_text(json.dumps({"Entries": [{"A": "x y", "B": "z w"}], "LocaleCode": "en"}), encoding="utf-8")
    logs = []
    assert ul.file_tables(_Info(data), log=logs.append) == [] and "tanınmadı" in logs[0]


def _json_object(type_name, payload):
    asm = b"Unity.ResourceManager, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
    body = json.dumps(payload, separators=(",", ":")).encode("utf-16-le")
    return bytes([7, len(asm)]) + asm + bytes([len(type_name)]) + type_name + struct.pack("<i", len(body)) + body


def _catalog(crc_loc=123456789, crc_other=987654):
    extra = b"\x00\x05\x00\x00\x00hello"
    extra += _json_object(ul.REQUEST_OPTIONS, {"m_Hash": "aa", "m_Crc": crc_loc, "m_Timeout": 0,
                                               "m_BundleName": "localization-string-tables-english(en)_assets_all",
                                               "m_BundleSize": 2048})
    extra += _json_object(ul.REQUEST_OPTIONS, {"m_Hash": "bb", "m_Crc": crc_other, "m_BundleName": "defaultlocalgroup_assets_all"})
    return json.dumps({"m_LocatorId": "AddressablesMainContentCatalog", "m_InternalIds": ["x"],
                       "m_ExtraDataString": base64.b64encode(extra).decode("ascii"), "m_EntryDataString": "AAAA"},
                      indent=None), extra


def test_catalog_crc_is_zeroed_for_changed_bundles_only():
    text, extra = _catalog()
    new, found = ul.zero_crcs(text, ["localization-string-tables-english(en)_assets_all_0f3a9c1d"])
    assert found == ["localization-string-tables-english(en)_assets_all_0f3a9c1d"]
    new_extra = base64.b64decode(json.loads(new)["m_ExtraDataString"])
    assert len(new_extra) == len(extra), "kayma tablosu bozulmasın: uzunluk aynı"
    decoded = new_extra.decode("latin-1")
    assert '"m_Crc":0        ,'.encode("utf-16-le") in new_extra
    assert '"m_Crc":987654'.encode("utf-16-le") in new_extra, "diğer paketlere dokunulmaz"
    assert decoded and new.replace(json.loads(new)["m_ExtraDataString"], "") == text.replace(json.loads(text)["m_ExtraDataString"], "")
    assert ul.zero_crcs(new, ["localization-string-tables-english(en)_assets_all"])[0] == new, "ikinci kez değişmez"
    assert ul.zero_crcs(text, ["başka-paket"]) == (text, [])


def test_bridge_writes_turkish_data_file_and_restore_removes_it(tmp_path, monkeypatch, fake_ollama):
    import providers
    _unity_game(tmp_path / "Game", tsv=False)
    base = _write_tables(tmp_path / "Game" / "Game_Data")
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    monkeypatch.setattr(bridge, "_ask", lambda title, *a, **k: title == "Yedeği geri yükle")   # BepInEx'e hayır
    bridge._select_game(str(tmp_path / "Game"))
    run_sync(bridge, "analyze")
    assert bridge._game["analysis"]["lines"] == 2
    run_sync(bridge, "translate")
    out = json.loads((base / "Menus_tr.json").read_text(encoding="utf-8"))
    values = [e["Value"] for e in out["Entries"]]
    assert values[0] in ("TR(New Game)", "Yeni Oyun") and values[1:] == ["TR(Hello {player}!)", "42"]
    assert bridge._library.get(bridge._game["root"])["status"] == "translated"
    run_sync(bridge, "restore_backup", "")
    assert not (base / "Menus_tr.json").exists(), "geri yükleme Capri'nin eklediği dil dosyasını siler"
    assert (base / "Menus_en.json").exists() and (base / "Menus_fr.json").exists()
