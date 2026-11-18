"""Naninovel: yönetilen referans kayıt defteri (sürüm 1 ve 2) okuma/yazma, metin alanları, arayüz belgeleri."""
import json
import struct
from types import SimpleNamespace

import pytest

import unity_naninovel as N

TypeTreeNode = pytest.importorskip("UnityPy.helpers.TypeTreeNode").TypeTreeNode
ALIGN = 0x4000


def node(level, kind, name, flag=0):
    return SimpleNamespace(m_Level=level, m_Type=kind, m_Name=name, m_MetaFlag=flag)


def string_nodes(level, name, flag=0):
    return [node(level, "string", name, flag), node(level + 1, "Array", "Array", ALIGN),
            node(level + 2, "int", "size"), node(level + 2, "char", "data")]


def string_param(level, name):
    return [node(level, "StringParameter", name)] + string_nodes(level + 1, "value") + \
           [node(level + 1, "UInt8", "hasValue", ALIGN)]


MONO_HEADER = [node(1, "PPtr<GameObject>", "m_GameObject", ALIGN), node(2, "int", "m_FileID"),
               node(2, "SInt64", "m_PathID"), node(1, "UInt8", "m_Enabled", ALIGN),
               node(1, "PPtr<MonoScript>", "m_Script", ALIGN), node(2, "int", "m_FileID"),
               node(2, "SInt64", "m_PathID")] + string_nodes(1, "m_Name", ALIGN)


class FakeGenerator:
    """Üretici gibi davranır: her türün başına MonoBehaviour başlığını ekler (gerçeğinde de öyle)."""
    TYPES = {
        "Naninovel.Commands.PrintText": string_param(1, "Text") + string_param(1, "AuthorId"),
        "Naninovel.Commands.AddChoice": string_param(1, "ChoiceSummary") + string_param(1, "GotoPath"),
        "Naninovel.CommentScriptLine": [node(1, "int", "lineIndex")] + string_nodes(1, "commentText", ALIGN),
    }

    def get_nodes(self, assembly, fullname):
        return [node(0, fullname.rsplit(".", 1)[-1], "Base")] + MONO_HEADER + self.TYPES[fullname]


def script_node(version):
    nodes = [node(0, "Script", "Base")] + string_nodes(1, "m_Name", ALIGN) + [
        node(1, "managedReference", "lines"), node(2, "Array", "Array", ALIGN), node(3, "int", "size"),
        node(3, "managedReference", "data"), node(4, "int", "id"),
        node(1, "ManagedReferencesRegistry", "references"), node(2, "int", "version")]
    kind = [node(3 if version == 1 else 5, "ReferencedManagedType", "type")]
    base = kind[0].m_Level
    for field in ("class", "ns", "asm"):
        kind += string_nodes(base + 1, field, ALIGN)
    if version == 1:
        nodes += [node(2, "ReferencedObject", "00000000")] + kind + [node(3, "ReferencedObjectData", "data")]
    else:
        nodes += [node(2, "vector", "RefIds"), node(3, "Array", "Array", ALIGN), node(4, "int", "size"),
                  node(4, "ReferencedObject", "data"), node(5, "SInt64", "rid")] + kind + \
                 [node(5, "ReferencedObjectData", "data")]
    return TypeTreeNode.from_list([TypeTreeNode(n.m_Level, n.m_Type, n.m_Name, 0, 0, m_MetaFlag=n.m_MetaFlag)
                                   for n in nodes])


def s(text):
    data = text.encode("utf-8")
    return struct.pack("<i", len(data)) + data + b"\0" * ((-len(data)) % 4)


def param(text, has=1):
    return s(text) + bytes([has]) + b"\0\0\0"


def kind(cls, ns="Naninovel.Commands", asm="Elringus.Naninovel.Runtime"):
    return s(cls) + s(ns) + s(asm)


REFS = [
    (kind("CommentScriptLine", "Naninovel"), struct.pack("<i", 0) + s("Chinese (T) <zh-TW> to English <en> "
                                                                   "localization document for `Demo` naninovel script")),
    (kind("PrintText"), param("Hello there.") + param("Kira")),
    (kind("AddChoice"), param("Go to the park") + param(".Park")),
]


def raw_script(version):
    out = s("Demo") + struct.pack("<i", 3) + struct.pack("<3i", 0, 1, 2) + struct.pack("<i", version)
    if version == 1:
        for index, (k, data) in enumerate(REFS):
            out += k + data
        return out + kind("Terminus", "UnityEngine.DMAT", "FAKE_ASM")
    out += struct.pack("<i", len(REFS))
    for index, (k, data) in enumerate(REFS):
        out += struct.pack("<q", index) + k + data
    return out


class FakeObj:
    def __init__(self, raw, version):
        self.raw, self.version = raw, version
        self.reader = SimpleNamespace(endian="<")
        self.assets_file = None

    def get_raw_data(self):
        return self.raw

    def _get_typetree_node(self):
        return script_node(self.version)

    def set_raw_data(self, data):
        self.raw = data


@pytest.mark.parametrize("version", [1, 2])
def test_registry_round_trip_and_text_fields(version):
    obj = FakeObj(raw_script(version), version)
    registry = N.Registry(obj, FakeGenerator())
    assert registry.layout == ("v1" if version == 1 else "v2") and registry.exact(), "bayt bayt aynı yazılmalı"
    assert "to English <en>" in registry.header_comment()
    fields = registry.text_fields()
    assert [(f[1], f[2]) for f in fields] == [(["Text", "value"], "Hello there."),
                                             (["ChoiceSummary", "value"], "Go to the park")]
    assert all("Kira" != f[2] and ".Park" != f[2] for f in fields), "konuşmacı kimliği ve atlama hedefi çevrilmez"


@pytest.mark.parametrize("version", [1, 2])
def test_apply_script_changes_only_text_and_verifies(version):
    from engine_unity import UnityTextItem
    obj = FakeObj(raw_script(version), version)
    generator = FakeGenerator()
    items = [UnityTextItem("resources.assets", "nani:x:1", index, json.dumps(path), text, "typed")
             for index, path, text in N.Registry(obj, generator).text_fields()]
    stale = UnityTextItem("resources.assets", "nani:x:1", 1, json.dumps(["Text", "value"]), "Old text", "typed")
    done = N.apply_script(obj, generator, items + [stale],
                          {"Hello there.": "Merhaba oradaki!", "Go to the park": "Parka git", "Old text": "X"})
    assert len(done) == 2, "değeri değişmiş satıra dokunulmaz"
    again = N.Registry(obj, generator)
    assert [f[2] for f in again.text_fields()] == ["Merhaba oradaki!", "Parka git"]
    assert again.refs[1]["data"]["AuthorId"]["value"] == "Kira"
    assert N.verify_script(obj, generator, done)


def test_broken_registry_is_refused():
    obj = FakeObj(raw_script(1)[:-6], 1)
    with pytest.raises(Exception):
        N.Registry(obj, FakeGenerator())


def test_plain_nodes_drop_monobehaviour_header():
    tree = N.plain_nodes(FakeGenerator(), "Elringus.Naninovel.Runtime", "Naninovel.Commands.PrintText")
    assert [c.m_Name for c in tree.m_Children] == ["Text", "AuthorId"]


DOC = ("; Chinese (T) <zh-TW> to English <en> localization document for `DefaultUI` managed text document\r\n"
       "\r\n"
       "ControlPanel.Save: SAVE\r\n"
       "LoadMenuText: This is the loading page: saving is next to me!\r\n"
       "Empty.Key: \r\n")


def test_managed_text_cells_and_rewrite_keep_everything_else():
    cells = N.managed_text_cells(DOC)
    assert [(k, v) for _n, k, v in cells] == [("ControlPanel.Save", "SAVE"),
                                             ("LoadMenuText", "This is the loading page: saving is next to me!")]
    replacements = {(n, k): (v, {"SAVE": "KAYDET"}.get(v, "Yükleme sayfası\nbu")) for n, k, v in cells}
    out, changed = N.rewrite_managed_text(DOC, replacements)
    assert changed == 2
    assert "ControlPanel.Save: KAYDET\r\n" in out and "LoadMenuText: Yükleme sayfası bu\r\n" in out, "satır sonu korunur"
    assert out.startswith(DOC.split("\n")[0]) and out.endswith("Empty.Key: \r\n")
    assert N.rewrite_managed_text(DOC, {(2, "ControlPanel.Save"): ("LOAD", "X")}) == (DOC, 0)


def test_doc_header_and_detection(tmp_path):
    match = N._DOC_HEADER.search(DOC)
    assert match.group(1) == "zh-TW" and match.group(2) == "en" and match.group(3) == "DefaultUI"
    assert N._is_english("en") and N._is_english("en-US") and not N._is_english("ja-JP")
    data = tmp_path / "Game_Data"
    (data / "Managed").mkdir(parents=True)
    info = SimpleNamespace(data_dir=data)
    assert not N.is_naninovel(info)
    (data / "Managed" / N.RUNTIME_DLL).write_bytes(b"MZ")
    assert N.is_naninovel(info)
