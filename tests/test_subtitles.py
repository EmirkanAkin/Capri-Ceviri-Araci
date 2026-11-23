"""Altyazı çevirisi: SRT, WebVTT ve ASS/SSA. Zaman kodları, stil satırları ve etiketler aynen kalmalı."""
import json

import pytest

import app_modern
import providers
import subtitles
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401 (fixture)

SRT = ("1\r\n00:00:01,000 --> 00:00:03,500\r\n<i>Where are you going?</i>\r\n\r\n"
       "2\r\n00:00:04,000 --> 00:00:06,000\r\nTo the castle.\r\nCome with me.\r\n\r\n"
       "3\r\n00:00:07,000 --> 00:00:08,000\r\n♪ ♪\r\n\r\n"
       "4\r\n00:00:09,000 --> 00:00:10,000\r\n{\\an8}Hello, {name}!\r\n")

VTT = ("WEBVTT\n\nNOTE This is a comment\nwith two lines\n\nSTYLE\n::cue { color: yellow }\n\n"
       "intro\n00:01.000 --> 00:03.000 align:start position:10%\nGood morning.\n\n"
       "00:00:04.000 --> 00:00:05.000\n<v Mary>Is it raining?</v>\n")

ASS = ("[Script Info]\nTitle: Demo\nScriptType: v4.00+\n\n[V4+ Styles]\n"
       "Format: Name, Fontname, Fontsize\nStyle: Default,Arial,20\n\n[Events]\n"
       "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
       "Dialogue: 0,0:00:01.00,0:00:03.00,Default,Mary,0,0,0,,{\\i1}Wait, please!{\\i0}\\NI'm coming.\n"
       "Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,This note is not shown\n"
       "Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,Yes, sir.\n")


def fake(texts):
    return {t: "TR(" + t + ")" for t in texts}


def test_srt_keeps_numbers_times_and_tags(tmp_path):
    path = tmp_path / "film.en.srt"
    path.write_bytes(SRT.replace("♪ ♪", "Café!").encode("cp1252"))
    sub = subtitles.load(path)
    assert sub.kind == "srt" and sub.newline == "\r\n"
    assert sub.encoding == "cp1254", "UTF-8 olmayan eski dosya"
    assert subtitles.texts(sub) == ["<i>Where are you going?</i>", "To the castle.\nCome with me.", "Café!",
                                    "{\\an8}Hello, {name}!"]
    target = subtitles.save(sub, {"<i>Where are you going?</i>": "<i>Nereye gidiyorsun?</i>",
                                  "To the castle.\nCome with me.": "Şatoya.\nBenimle gel.",
                                  "{\\an8}Hello, {name}!": "{\\an8}Merhaba, {name}!"},
                            subtitles.output_path(path, "tr"))
    assert target.name == "film.tr.srt"
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "eski kod sayfası UTF-8 (BOM) olarak yazılır"
    out = raw[3:].decode("utf-8")
    assert out.split("\r\n")[:4] == ["1", "00:00:01,000 --> 00:00:03,500", "<i>Nereye gidiyorsun?</i>", ""]
    assert "Şatoya.\r\nBenimle gel.\r\n\r\n3\r\n00:00:07,000 --> 00:00:08,000\r\nCafé!" in out, "çevirisi olmayan satır aynen kalır"
    assert "{\\an8}Merhaba, {name}!" in out
    assert path.read_bytes() == SRT.replace("♪ ♪", "Café!").encode("cp1252"), "orijinale dokunulmaz"


def test_translation_with_different_line_count_keeps_the_block_intact(tmp_path):
    path = tmp_path / "a.srt"
    path.write_bytes(SRT.encode("utf-8"))
    sub = subtitles.load(path)
    out = subtitles.render(sub, {"To the castle.\nCome with me.": "Şatoya, benimle gel.\n\n",
                                 "<i>Where are you going?</i>": "<i>Nereye?</i>\nDur!\nBekle!"})
    blocks = out.split("\r\n\r\n")
    assert blocks[0].split("\r\n") == ["1", "00:00:01,000 --> 00:00:03,500", "<i>Nereye?</i>", "Dur!", "Bekle!"]
    assert blocks[1].split("\r\n") == ["2", "00:00:04,000 --> 00:00:06,000", "Şatoya, benimle gel."]
    assert len(blocks) == 4


def test_vtt_skips_notes_and_styles(tmp_path):
    path = tmp_path / "talk.vtt"
    path.write_bytes(VTT.encode("utf-8"))
    sub = subtitles.load(path)
    assert subtitles.texts(sub) == ["Good morning.", "<v Mary>Is it raining?</v>"]
    out = subtitles.render(sub, fake(subtitles.texts(sub)))
    assert "NOTE This is a comment\nwith two lines" in out and "::cue { color: yellow }" in out
    assert "00:01.000 --> 00:03.000 align:start position:10%\nTR(Good morning.)" in out


def test_ass_translates_only_dialogue_text_field(tmp_path):
    path = tmp_path / "ep01.ass"
    path.write_bytes(ASS.encode("utf-8"))
    sub = subtitles.load(path)
    assert subtitles.texts(sub) == ["{\\i1}Wait, please!{\\i0}\nI'm coming.", "Yes, sir."]
    out = subtitles.render(sub, {"{\\i1}Wait, please!{\\i0}\nI'm coming.": "{\\i1}Bekle, lütfen!{\\i0}\nGeliyorum.",
                                 "Yes, sir.": "Evet, efendim."})
    lines = out.split("\n")
    assert lines[10] == "Dialogue: 0,0:00:01.00,0:00:03.00,Default,Mary,0,0,0,,{\\i1}Bekle, lütfen!{\\i0}\\NGeliyorum."
    assert lines[11] == "Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,This note is not shown"
    assert lines[12] == "Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,Evet, efendim."
    assert "Style: Default,Arial,20" in out


@pytest.mark.parametrize("name, target, expected", [
    ("film.srt", "tr", "film.tr.srt"), ("film.en.srt", "tr", "film.tr.srt"), ("film.eng.ass", "de", "film.de.ass"),
    ("S01E02.WEB.srt", "tr", "S01E02.WEB.tr.srt"), ("a.b.c.vtt", "pt-BR", "a.b.c.pt-BR.vtt"),
])
def test_output_name_marks_the_language(tmp_path, name, target, expected):
    assert subtitles.output_path(tmp_path / name, target).name == expected


def test_save_refuses_to_overwrite_the_source(tmp_path):
    path = tmp_path / "x.srt"
    path.write_bytes(SRT.encode("utf-8"))
    with pytest.raises(ValueError):
        subtitles.save(subtitles.load(path), {}, path)


def test_file_translator_page_handles_a_subtitle_folder(tmp_path, monkeypatch, fake_ollama):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    folder = tmp_path / "subs"
    (folder / "season1").mkdir(parents=True)
    (folder / "season1" / "e1.srt").write_bytes(SRT.encode("utf-8"))
    (folder / "e2.ass").write_bytes(ASS.encode("utf-8"))
    (folder / "old.tr.srt").write_bytes(SRT.encode("utf-8"))           # daha önceki çıktı: kaynak sayılmaz
    run_sync(bridge, "json_translate", str(folder), "")
    out1 = (folder / "season1" / "e1.tr.srt").read_text(encoding="utf-8")
    assert "TR(To the castle.\nCome with me.)" in out1.replace("\r\n", "\n") or "TR(To the castle." in out1
    assert "00:00:04,000 --> 00:00:06,000" in out1
    out2 = (folder / "e2.tr.ass").read_text(encoding="utf-8")
    assert ",,TR(Yes, sir.)" in out2
    assert not (folder / "old.tr.tr.srt").exists()
    assert any(e == "notify" and p["title"] == "Altyazı çevirisi tamamlandı" for e, p in bridge._ui.events)


def test_single_subtitle_file_with_explicit_output(tmp_path, monkeypatch, fake_ollama):
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    src = tmp_path / "in.vtt"
    src.write_bytes(VTT.encode("utf-8"))
    out = tmp_path / "out" / "result.vtt"
    run_sync(bridge, "json_translate", str(src), str(out))
    assert "TR(Good morning.)" in out.read_text(encoding="utf-8")
