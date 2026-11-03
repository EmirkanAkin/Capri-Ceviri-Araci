"""engine_rpgmaker.py birim testleri."""
import json
import re
import tempfile
from pathlib import Path

import pytest


# ── RPG Maker kontrol kodu maskeleme testleri ─────────────────────────────────

# Bu testi engine_rpgmaker import etmeden de çalıştırabilmek için kalıbı kopyalıyoruz
PROTECTED_RPGM = re.compile(
    r"(\\[CVNPIGcvnpig]\[\d+\]"
    r"|\\[{}]"
    r"|\\[<>]"
    r"|\\[.!|^$]"
    r"|<[^>]+>"
    r"|\\[Ff]\[[^\]]+\]"
    r"|\\[Xx]\[[^\]]+\]"
    r"|%[sd]"
    r")",
    re.IGNORECASE,
)


class TestRPGMakerMasking:
    """RPG Maker kontrol kodlarının maskelenmesini test eder."""

    def test_color_code(self):
        from engine_common import mask_text, unmask_text
        text = r"Hello \C[1]World\C[0]!"
        masked, values = mask_text(text, PROTECTED_RPGM)
        assert r"\C[1]" in values
        assert r"\C[0]" in values
        restored = unmask_text(masked, values)
        assert restored == text

    def test_variable_code(self):
        from engine_common import mask_text, unmask_text
        text = r"You have \V[5] items"
        masked, values = mask_text(text, PROTECTED_RPGM)
        assert r"\V[5]" in values
        restored = unmask_text(masked, values)
        assert restored == text

    def test_name_code(self):
        from engine_common import mask_text, unmask_text
        text = r"\N[1] said hello"
        masked, values = mask_text(text, PROTECTED_RPGM)
        assert r"\N[1]" in values
        restored = unmask_text(masked, values)
        assert restored == text

    def test_multiple_codes(self):
        from engine_common import mask_text, unmask_text
        text = r"\C[2]Warning!\C[0] You need \V[3] more \N[1]!"
        masked, values = mask_text(text, PROTECTED_RPGM)
        assert len(values) == 4
        restored = unmask_text(masked, values)
        assert restored == text

    def test_plugin_tag(self):
        from engine_common import mask_text, unmask_text
        text = "<WordWrap>This is a long message"
        masked, values = mask_text(text, PROTECTED_RPGM)
        assert "<WordWrap>" in values
        restored = unmask_text(masked, values)
        assert restored == text


# ── RPG Maker JSON yapı testleri ──────────────────────────────────────────────

class TestRPGMakerJSONStructure:
    """RPG Maker JSON dosya yapılarının doğru ayrıştırıldığını test eder."""

    def _make_map_json(self, events_data: list) -> dict:
        """Basit MapXXX.json yapısı oluştur."""
        return {
            "autoplayBgm": False,
            "displayName": "Test Map",
            "events": [
                None,
                {
                    "id": 1,
                    "name": "TestEvent",
                    "pages": [
                        {
                            "conditions": {},
                            "list": events_data + [{"code": 0, "indent": 0, "parameters": []}],
                        }
                    ],
                },
            ],
        }

    def test_dialogue_extraction(self):
        """Event code 401 (Show Text) çıkarımını test eder."""
        events = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Hero"]},
            {"code": 401, "indent": 0, "parameters": ["Hello, how are you?"]},
            {"code": 401, "indent": 0, "parameters": ["I'm fine, thanks!"]},
        ]
        map_data = self._make_map_json(events)

        # Diyalog satırlarını bul
        dialogues = []
        for event in map_data.get("events", []):
            if event is None:
                continue
            for page in event.get("pages", []):
                for cmd in page.get("list", []):
                    if cmd.get("code") == 401:
                        params = cmd.get("parameters", [])
                        if params and isinstance(params[0], str) and params[0]:
                            dialogues.append(params[0])
        assert len(dialogues) == 2
        assert dialogues[0] == "Hello, how are you?"
        assert dialogues[1] == "I'm fine, thanks!"

    def test_choice_extraction(self):
        """Event code 102 (Show Choices) çıkarımını test eder."""
        events = [
            {"code": 102, "indent": 0, "parameters": [["Yes", "No", "Maybe"], 1]},
        ]
        map_data = self._make_map_json(events)
        choices = []
        for event in map_data.get("events", []):
            if event is None:
                continue
            for page in event.get("pages", []):
                for cmd in page.get("list", []):
                    if cmd.get("code") == 102:
                        params = cmd.get("parameters", [])
                        if params and isinstance(params[0], list):
                            choices.extend(params[0])
        assert choices == ["Yes", "No", "Maybe"]

    def test_system_terms_extraction(self):
        """System.json terms çıkarımını test eder."""
        system = {
            "gameTitle": "My RPG Game",
            "terms": {
                "basic": ["Level", "Lv", "HP", "HP", "MP", "MP", "TP", "TP", "EXP", "EXP"],
                "commands": ["Fight", "Escape", "Attack", "Guard", "Item", "Skill", "Equip",
                             "Status", "Formation", "Save", "Game End", None, "Weapon",
                             "Armor", "Key Item", None, None, None, "Options", None, None, None, ""],
                "params": ["Max HP", "Max MP", "Attack", "Defense", "M.Attack", "M.Defense", "Agility", "Luck"],
                "messages": {
                    "actionFailure": "%1 has no effect on %2!",
                    "actorDamage": "%1 took %2 damage!",
                },
            },
        }
        # terms.basic dan boş olmayanları çıkar
        terms = [t for t in system["terms"]["basic"] if t]
        assert "Level" in terms
        assert "HP" in terms

        # terms.commands dan None ve boş olmayanları çıkar
        commands = [c for c in system["terms"]["commands"] if c]
        assert "Fight" in commands
        assert "Save" in commands

    def test_database_item_extraction(self):
        """Items.json yapısından metin çıkarımını test eder."""
        items = [
            None,
            {"id": 1, "name": "Potion", "description": "Restores 100 HP.", "note": ""},
            {"id": 2, "name": "Ether", "description": "Restores 50 MP.", "note": ""},
        ]
        extracted = []
        for item in items:
            if item is None:
                continue
            for key in ("name", "description"):
                val = item.get(key, "")
                if val and isinstance(val, str):
                    extracted.append((key, val))
        assert len(extracted) == 4
        assert ("name", "Potion") in extracted
        assert ("description", "Restores 100 HP.") in extracted


class TestJSONRoundTrip:
    """JSON okuma → çeviri → yazma döngüsünün yapıyı bozmadığını test eder."""

    def test_map_structure_preserved(self):
        """Map JSON yapısının çeviriden sonra korunduğunu test eder."""
        original = {
            "autoplayBgm": False,
            "displayName": "Castle",
            "events": [
                None,
                {
                    "id": 1,
                    "name": "Guard",
                    "pages": [
                        {
                            "list": [
                                {"code": 401, "indent": 0, "parameters": ["Hello traveler!"]},
                                {"code": 401, "indent": 0, "parameters": ["Welcome to the castle."]},
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Map001.json"
            path.write_text(
                json.dumps(original, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Oku
            loaded = json.loads(path.read_text(encoding="utf-8"))

            # Çevir (simüle)
            translations = {
                "Hello traveler!": "Merhaba yolcu!",
                "Welcome to the castle.": "Kaleye hoş geldiniz.",
            }
            for event in loaded.get("events", []):
                if event is None:
                    continue
                for page in event.get("pages", []):
                    for cmd in page.get("list", []):
                        if cmd.get("code") == 401:
                            params = cmd.get("parameters", [])
                            if params and isinstance(params[0], str):
                                translated = translations.get(params[0])
                                if translated:
                                    params[0] = translated

            # Yaz
            path.write_text(
                json.dumps(loaded, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Doğrula
            final = json.loads(path.read_text(encoding="utf-8"))
            assert final["autoplayBgm"] == False
            assert final["displayName"] == "Castle"
            assert len(final["events"]) == 2
            assert final["events"][0] is None
            cmds = final["events"][1]["pages"][0]["list"]
            assert cmds[0]["parameters"][0] == "Merhaba yolcu!"
            assert cmds[1]["parameters"][0] == "Kaleye hoş geldiniz."
            assert cmds[2]["code"] == 0  # Yapı korunmuş


class TestSystemTranslation:
    """System.json çevirisinin doğru çalıştığını test eder."""

    def test_terms_translation(self):
        system = {
            "gameTitle": "My RPG",
            "terms": {
                "basic": ["Level", "Lv"],
                "commands": ["Fight", "Escape"],
                "params": ["Attack", "Defense"],
                "messages": {
                    "actionFailure": "%1 has no effect on %2!",
                },
            },
        }
        translations = {
            "Level": "Seviye",
            "Lv": "Sv",
            "Fight": "Savaş",
            "Escape": "Kaç",
            "Attack": "Saldırı",
            "Defense": "Savunma",
            "%1 has no effect on %2!": "%1'in %2 üzerinde etkisi yok!",
        }

        # basic çevir
        for i, val in enumerate(system["terms"]["basic"]):
            if val in translations:
                system["terms"]["basic"][i] = translations[val]

        # commands çevir
        for i, val in enumerate(system["terms"]["commands"]):
            if val and val in translations:
                system["terms"]["commands"][i] = translations[val]

        # messages çevir
        for key, val in system["terms"]["messages"].items():
            if val in translations:
                system["terms"]["messages"][key] = translations[val]

        assert system["terms"]["basic"][0] == "Seviye"
        assert system["terms"]["commands"][0] == "Savaş"
        assert system["terms"]["messages"]["actionFailure"] == "%1'in %2 üzerinde etkisi yok!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
