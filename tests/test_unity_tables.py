"""Utage senaryo kitapları, I2 Localization kaynakları ve TextMeshPro font tabloları (ham veri, tip bilgisi yok)."""
import struct

import pytest

import engine_unity
import unity_i2
import unity_utage


def _int(value):
    return struct.pack("<i", value)


def _str(text):
    return unity_utage.encode_string(text)


HEADER = b"\0" * 12 + _int(1) + b"\0" * 12          # m_GameObject, m_Enabled, m_Script


def make_book(rows, columns=("Command", "Arg1", "Text", "Korean")):
    body = HEADER + _str("ADV_Test.book") + _int(0) + _int(1) + _int(len(rows) + 1)
    for index, cells in enumerate([list(columns)] + rows):
        body += _int(index) + _int(len(cells)) + b"".join(_str(c) for c in cells) + _int(0) + _int(0)
    return body + _str("Assets/ADV_Test") + _int(1) + _int(1234) + _int(0) + _int(0) + _int(0)


def make_i2(terms, languages=("English",), description=False):
    body = HEADER + _str("I2Languages") + _int(0) + _int(0) + _int(1) + _int(len(terms))
    for key, kind, values in terms:
        body += _str(key) + _int(kind) + (_str("") if description else b"")
        body += _int(len(values)) + b"".join(_str(v) for v in values)
        body += _int(len(values)) + bytes(len(values)) + b"\0" * ((-len(values)) % 4)   # Flags
        body += _int(0)                                                                  # Languages_Touch
    body += _int(0) + _int(0) + _str("") + _int(len(languages))
    for name in languages:
        body += _str(name) + _str(name[:2].lower()) + _int(0)
    return body + _int(0) * 6


def test_utage_book_reads_text_column_and_rewrites_only_changed_cells():
    raw = make_book([["", "Umi", '"Let\'s go home."', "같이 가자"], ["Wait", "1"], ["", "Umi", '"Thanks."']])
    grids = unity_utage.parse_book(raw)
    assert len(grids) == 1 and grids[0].header[2] == "Text" and unity_utage.text_column(grids[0]) == 2
    texts = [row[2].text for row in grids[0].rows if len(row) > 2]
    assert texts == ['"Let\'s go home."', '"Thanks."'], "kısa (kırpılmış) satırlar atlanır"
    cells = {c.start: c for row in grids[0].rows for c in row}
    assert unity_utage.rewrite(raw, {}, cells) == raw, "değişiklik yoksa bayt bayt aynı"
    target = grids[0].rows[0][2]
    changed = unity_utage.rewrite(raw, {target.start: '"Hadi eve gidelim, ğüşıöç."'}, cells)
    again = unity_utage.parse_book(changed)
    assert again[0].rows[0][2].text == '"Hadi eve gidelim, ğüşıöç."'
    assert again[0].rows[0][3].text == "같이 가자" and again[0].rows[2][2].text == '"Thanks."'
    assert changed.endswith(raw[-24:]), "kitabın sonundaki alanlar korunur"


def test_utage_prefers_english_column_and_rejects_broken_data():
    raw = make_book([["", "A", "日本語", "Hello there"]], columns=("Command", "Arg1", "Text", "English"))
    assert unity_utage.text_column(unity_utage.parse_book(raw)[0]) == 3
    assert unity_utage.parse_book(b"no utage here") == []
    with pytest.raises(unity_utage.UtageFormatError):
        unity_utage.parse_book(raw[:-60])


@pytest.mark.parametrize("description", [False, True])
def test_i2_source_translates_only_text_terms(description):
    raw = make_i2([("Menu/Start", 0, ["Start Day"]), ("Title/Logo", 5, ["LOGO_EN"]), ("Talk/1", 0, ["“Hi.”"])],
                  description=description)
    source = unity_i2.parse_source(raw)
    assert source.terms == ["Menu/Start", "Title/Logo", "Talk/1"] and source.languages == ["English"]
    assert [source.is_text(i) for i in range(3)] == [True, False, True], "resim terimi (Sprite) çevrilmez"
    cells = {c.start: c for row in source.cells for c in row}
    changed = unity_utage.rewrite(raw, {source.cells[0][0].start: "Güne Başla"}, cells)
    again = unity_i2.parse_source(changed)
    assert again.cells[0][0].text == "Güne Başla" and again.cells[1][0].text == "LOGO_EN"


def test_i2_picks_english_among_languages():
    raw = make_i2([("A", 0, ["こんにちは", "Hello"])], languages=("Japanese", "English"))
    source = unity_i2.parse_source(raw)
    assert source.column("English") == 1 and source.cells[0][1].text == "Hello"


def test_tmp_font_table_and_glyph_fallback():
    entries = [ord(c) for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZçöüÇÖÜ .,'"]
    raw = b"".join(struct.pack("<IIf", code, index, 1.0) for index, code in enumerate(entries))
    glyphs = engine_unity.tmp_character_table(b"\0" * 64 + raw)
    assert ord("ç") in glyphs and ord("ğ") not in glyphs
    text = "Değil mi? Işığı gördüm, çok güzel <param=PlayerName>."
    assert engine_unity.glyph_fallback(text, glyphs) == "Degil mi? Isigi gördüm, çok güzel <param=PlayerName>."
    assert engine_unity.glyph_fallback(text, set()) == text, "font bilinmiyorsa dokunulmaz"
    assert engine_unity.tmp_character_table(struct.pack("<IIf", 287, 1, 1.0) * 3) == set(), "tablo değilse boş"
