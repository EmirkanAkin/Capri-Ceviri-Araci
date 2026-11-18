"""
Naninovel (Unity görsel roman motoru) senaryo ve arayüz metinleri
=================================================================
Naninovel senaryoları (.nani) derlenince `Naninovel.Script` nesnesine dönüşür: her satır ve her komut
[SerializeReference] ile kaydedilen ayrı bir nesnedir. UnityPy bu "yönetilen referans kayıt defteri"nin yalnızca
tek kayıtlı biçimini okur; bu modül Unity'nin iki biçimini de okur ve yazar:
  * sürüm 1 (Unity 2019.3–2021.1): kayıtlar art arda gelir, "Terminus" türüyle biter; kimlik sıradır.
  * sürüm 2 (Unity 2021.2+): kayıt sayısı + her kayıtta 64 bit kimlik.
Her kaydın içeriği oyunun kendi DLL'lerinden üretilen tip bilgisiyle okunur (bkz. unity_typed).

Yerelleştirme: oyunun dili başka olsa da "Naninovel/Localization/<dil>/Scripts/…" altında her dilin senaryosu durur.
Kaynak olarak İngilizce yerelleştirme seçilir; Türkçe onun yerine yazılır (oyunda English seçilince Türkçe görünür).
İngilizce yerelleştirme yoksa ve senaryonun kendisi İngilizceyse onun metni çevrilir. Arayüz metinleri ("managed
text": "Anahtar: Değer" satırlı TextAsset'ler) aynı kuralla seçilir.

Güvenlik: bir senaryo nesnesi okunup yeniden yazıldığında bayt bayt aynı çıkmıyorsa ona hiç dokunulmaz; çevrilen
yalnızca diyalog (PrintText.Text), seçenek (AddChoice.ChoiceSummary) ve tip bilgisinde LocalizableTextParameter
olan alanlardır. Karakter kimliği, etiketler, atlama hedefleri ve ifadeler değişmez.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LogFn = Callable[[str], None]
RUNTIME_DLL = "Elringus.Naninovel.Runtime.dll"
_HEADER_FIELDS = {"m_GameObject", "m_Enabled", "m_Script", "m_Name"}
# Ekrana metin yazan komut alanları (eski sürümlerde StringParameter; yenilerde LocalizableTextParameter)
TEXT_FIELDS = {"PrintText": ("Text",), "AddChoice": ("ChoiceSummary",)}
_DOC_HEADER = re.compile(r";?\s*.*?<([\w-]+)> to .*?<([\w-]+)> localization document for `([^`]+)`")
_LATIN = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def is_naninovel(info: Any) -> bool:
    managed = Path(info.data_dir) / "Managed"
    return (managed / RUNTIME_DLL).is_file()


def _is_english(tag: str) -> bool:
    return tag.lower() == "en" or tag.lower().startswith("en-")


# ─── Yönetilen referans kayıt defteri ─────────────────────────────────────────
class Registry:
    """Bir Naninovel.Script nesnesi: başlık alanları + kayıtlar. write() aynı baytları üretmelidir."""

    def __init__(self, obj: Any, generator: Any):
        from UnityPy.helpers.TypeTreeHelper import TypeTreeConfig, read_value
        from UnityPy.streams import EndianBinaryReader

        self.obj, self.generator = obj, generator
        self.raw = obj.get_raw_data()
        self.node = obj._get_typetree_node()
        reader = EndianBinaryReader(self.raw, endian=obj.reader.endian)
        config = TypeTreeConfig(True, obj.assets_file, True)
        self.head: Dict[str, Any] = {}
        registry = None
        for child in self.node.m_Children:
            if child.m_Type == "ManagedReferencesRegistry":
                registry = child
                break
            self.head[child.m_Name] = read_value(child, reader, config)
        if registry is None:
            raise ValueError("kayıt defteri yok")
        self.version = reader.read_int()
        entry = registry.m_Children[1]
        self.layout = "v1" if entry.m_Type == "ReferencedObject" else "v2"
        if self.layout == "v1":
            self.type_node = entry.m_Children[0]
        else:   # vector RefIds → Array → ReferencedObject{rid, type, data}
            entry = entry.m_Children[0].m_Children[1]
            self.type_node = next(c for c in entry.m_Children if c.m_Type == "ReferencedManagedType")
        self.refs: List[Dict[str, Any]] = []
        count = reader.read_int() if self.layout == "v2" else None
        while True:
            if count is not None and len(self.refs) >= count:
                break
            rid = reader.read_long() if self.layout == "v2" else None
            kind = read_value(self.type_node, reader, config)
            if self.layout == "v1" and (kind["class"] in ("Terminus", "") or not kind["class"]):
                self.refs.append({"rid": rid, "type": kind, "data": None})
                break
            node = self.data_node(kind)
            self.refs.append({"rid": rid, "type": kind, "data": read_value(node, reader, config) if node else None})
        if reader.Position != len(self.raw):
            raise ValueError(f"{len(self.raw) - reader.Position} bayt okunmadı")

    def data_node(self, kind: Dict[str, str]):
        if not kind.get("class"):
            return None
        full = f"{kind['ns']}.{kind['class']}" if kind.get("ns") else kind["class"]
        return plain_nodes(self.generator, kind["asm"], full)

    def write(self) -> bytes:
        from UnityPy.helpers.TypeTreeHelper import TypeTreeConfig, write_value
        from UnityPy.streams import EndianBinaryWriter

        writer = EndianBinaryWriter(endian=self.obj.reader.endian)
        config = TypeTreeConfig(True, self.obj.assets_file, True)
        for child in self.node.m_Children:
            if child.m_Type == "ManagedReferencesRegistry":
                break
            write_value(self.head[child.m_Name], child, writer, config)
        writer.write_int(self.version)
        if self.layout == "v2":
            writer.write_int(len(self.refs))
        for ref in self.refs:
            if self.layout == "v2":
                writer.write_long(ref["rid"])
            write_value(ref["type"], self.type_node, writer, config)
            if ref["data"] is not None:
                write_value(ref["data"], self.data_node(ref["type"]), writer, config)
        return writer.bytes

    def exact(self) -> bool:
        return self.write() == self.raw

    def header_comment(self) -> str:
        """Yerelleştirme senaryosunun ilk satırı: "Chinese (T) <zh-TW> to English <en> localization document …"."""
        for ref in self.refs[:4]:
            if ref["type"].get("class") == "CommentScriptLine" and ref["data"]:
                return str(ref["data"].get("commentText", ""))
        return ""

    def text_fields(self) -> List[Tuple[int, List[str], str]]:
        """(kayıt sırası, alan yolu, metin): diyalog, seçenek ve LocalizableTextParameter alanları."""
        out = []
        for index, ref in enumerate(self.refs):
            data, kind = ref["data"], ref["type"]
            if not isinstance(data, dict) or kind.get("ns", "").split(".")[0] != "Naninovel":
                continue
            names = set(TEXT_FIELDS.get(kind.get("class", ""), ()))
            node = self.data_node(kind)
            if node is not None:
                names |= {c.m_Name for c in node.m_Children if c.m_Type == "LocalizableTextParameter"}
            for name in sorted(names):
                param = data.get(name)
                if isinstance(param, dict) and param.get("hasValue") and isinstance(param.get("value"), str):
                    out.append((index, [name, "value"], param["value"]))
        return out


_PLAIN_CACHE: Dict[Tuple[int, str, str], Any] = {}


def plain_nodes(generator: Any, assembly: str, fullname: str):
    """[Serializable] sınıfın düğümleri: üreticinin her türe eklediği MonoBehaviour başlığı atılır."""
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode

    key = (id(generator), assembly, fullname)
    if key not in _PLAIN_CACHE:
        name = assembly if assembly.endswith(".dll") else f"{assembly}.dll"
        base = generator.get_nodes(name, fullname)
        out, skipping = [], False
        for node in base:
            if node.m_Level == 1:
                skipping = node.m_Name in _HEADER_FIELDS
            if skipping and node.m_Level >= 1:
                continue
            out.append(TypeTreeNode(node.m_Level, node.m_Type, node.m_Name, 0, 0, m_MetaFlag=node.m_MetaFlag))
        _PLAIN_CACHE[key] = TypeTreeNode.from_list(out) if out else None
    return _PLAIN_CACHE[key]


# ─── Arayüz metinleri (managed text) ──────────────────────────────────────────
def managed_text_cells(script: str) -> List[Tuple[int, str, str]]:
    """(satır no, anahtar, değer): "Anahtar: Değer" satırları; yorum (;) ve boş satırlar atlanır."""
    cells = []
    for number, line in enumerate(script.split("\n")):
        body = line.rstrip("\r")
        if not body.strip() or body.lstrip().startswith(";"):
            continue
        key, sep, value = body.partition(": ")
        if sep and key.strip() and value.strip():
            cells.append((number, key, value))
    return cells


def rewrite_managed_text(script: str, replacements: Dict[Tuple[int, str], Tuple[str, str]]) -> Tuple[str, int]:
    """(satır no, anahtar) → (eski, yeni); yalnızca değer değişir, eski değer tutmuyorsa satıra dokunulmaz."""
    lines = script.split("\n")
    changed = 0
    for (number, key), (old, new) in replacements.items():
        if number >= len(lines):
            continue
        body = lines[number]
        ending = "\r" if body.endswith("\r") else ""
        current_key, sep, value = body[:len(body) - len(ending)].partition(": ")
        if not sep or current_key != key or value != old:
            continue
        lines[number] = f"{key}: {new.replace(chr(10), ' ').replace(chr(13), ' ')}{ending}"
        changed += 1
    return "\n".join(lines), changed


# ─── Çıkarma ──────────────────────────────────────────────────────────────────
def scan(env: Any, container: str, log: LogFn = print) -> Tuple[List[Any], Dict[str, int]]:
    """Ortamdaki Naninovel metinleri: UnityTextItem listesi (format_type='typed'; tür nani / mtext) ve sayılar."""
    from engine_unity import UnityTextItem
    import unity_typed

    generator = env.typetree_generator
    english_scripts, source_scripts = [], []
    skipped = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour" or unity_typed.script_class(obj) != "Script":
            continue
        raw = obj.get_raw_data()
        if b"localization document" in raw[:4096] or b"localization document" in raw:
            header = _DOC_HEADER.search(raw[:20000].decode("utf-8", "ignore"))
            if not header or not _is_english(header.group(2)):
                continue
            bucket = english_scripts
        else:
            bucket = source_scripts
        try:
            registry = Registry(obj, generator)
            if not registry.exact():
                raise ValueError("yeniden yazım aynı değil")
        except Exception:
            skipped += 1
            continue
        bucket.append((obj, registry))
    chosen = english_scripts
    if not chosen and source_scripts:
        texts = [t for _o, r in source_scripts for _i, _p, t in r.text_fields()][:2000]
        latin = sum(1 for t in texts if _LATIN.search(t) and not _CJK.search(t))
        chosen = source_scripts if texts and latin >= 0.8 * len(texts) else []
    items: List[Any] = []
    for obj, registry in chosen:
        for index, path, text in registry.text_fields():
            if text.strip() and _LATIN.search(text):
                items.append(UnityTextItem(container, f"nani:{obj.assets_file.name}:{obj.path_id}", index,
                                           json.dumps(path), text, unity_typed.FORMAT))
    script_lines = len(items)
    # Arayüz metinleri: İngilizce yerelleştirme belgeleri
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        try:
            data = obj.read()
            script = data.m_Script if isinstance(data.m_Script, str) else bytes(data.m_Script).decode("utf-8")
        except Exception:
            continue
        header = _DOC_HEADER.search(script[:400])
        if not header or not _is_english(header.group(2)) or "managed text" not in script[:400]:
            continue
        document = header.group(3)
        for number, key, value in managed_text_cells(script):
            if document == "Locales":   # dil listesi: yalnızca bu belgenin dili (en) hedef dilin adı olur
                if key.strip().lower() != header.group(2).lower():
                    continue
            elif not _LATIN.search(value):
                continue
            items.append(UnityTextItem(container, f"mtext:{obj.assets_file.name}:{obj.path_id}", number, key,
                                       value, unity_typed.FORMAT))
    counts = {"naninovel": script_lines, "naninovel_ui": len(items) - script_lines}
    if skipped:
        log(f"Naninovel: {skipped} senaryo birebir okunamadığı için dokunulmadan bırakıldı")
    if items:
        source = "İngilizce yerelleştirme" if english_scripts else "senaryonun kendisi"
        log(f"Naninovel: {len(chosen)} senaryo ({source}), {script_lines} satır + {counts['naninovel_ui']} arayüz metni")
    return items, counts


# ─── Yazma ────────────────────────────────────────────────────────────────────
def apply_script(obj: Any, generator: Any, items: List[Any], translations: Dict[str, str]) -> List[Tuple[Any, str]]:
    """Bir senaryo nesnesine çevirileri yazar; doğrulama için (yol, yeni değer) listesi döndürür."""
    registry = Registry(obj, generator)
    if not registry.exact():
        return []
    done = []
    for item in items:
        path = json.loads(item.key_id)
        if item.line_index >= len(registry.refs):
            continue
        data = registry.refs[item.line_index]["data"]
        param = data.get(path[0]) if isinstance(data, dict) else None
        if not isinstance(param, dict) or param.get(path[1]) != item.original:
            continue
        new = translations.get(item.original)
        if not new or new == item.original:
            continue
        param[path[1]] = new
        done.append(((item.line_index, path), new))
    if done:
        obj.set_raw_data(registry.write())
    return done


def verify_script(obj: Any, generator: Any, checks: List[Tuple[Any, str]]) -> bool:
    registry = Registry(obj, generator)
    if not registry.exact():
        return False
    for (index, path), value in checks:
        data = registry.refs[index]["data"]
        if data.get(path[0], {}).get(path[1]) != value:
            return False
    return True
