"""
Unity bileşenlerini oyunun kendi tip bilgisiyle okuyup yazar
============================================================
Bazı Unity oyunları metnini tablo yerine bileşenlerin içinde tutar: PlayMaker durum makineleri (FSM), sahnedeki
UI Text / TextMeshPro bileşenleri ve çok dilli XML tabloları; hepsi çoğu zaman tek bir data.unity3d paketindedir.
Bu veri tipsiz (typetree'siz) kaydedildiği için alanların adı ve sınırı ancak oyunun kendi DLL'lerinden üretilen
tip bilgisiyle bilinir (TypeTreeGeneratorAPI: Mono'da Managed/*.dll, IL2CPP'de GameAssembly + metadata).

Güvenlik ilkeleri:
  * Her bileşen tip bilgisiyle sonuna kadar okunmalı ve geri yazıldığında bayt bayt aynı çıkmalıdır; tutmayan
    bileşene dokunulmaz (yanlış tip bilgisi oyunu bozmasın).
  * PlayMaker'da aynı dizide hem ekrana gelen metin hem de mantık anahtarı (olay, değişken, kayıt anahtarı, sahne
    adı) durur. Yalnızca dile göre değer alan atamalar çevrilir: oyunun dil dalında (English durumu) bir değişkene
    yazılan ve diğer dillerin dallarında farklı değer alan metin. Her dilde aynı kalan değer anahtardır, dokunulmaz.
  * Yazmadan önce her hücrenin hâlâ çıkarılan metni taşıdığı doğrulanır; kayıttan sonra paket yeniden okunup
    yeni değerler denetlenir, tutmazsa dosya değiştirilmez.
"""
from __future__ import annotations

import gc
import json
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

LogFn = Callable[[str], None]
FORMAT = "typed"

# Oyunların dil adları ve kısaltmaları → ortak kod
_LANG_ALIASES = {
    "en": ("english", "eng", "en", "en_us", "en_gb", "englis"),
    "ja": ("japanese", "jp", "ja", "jpn", "jap"),
    "ko": ("korean", "kr", "ko", "kor"),
    "zh-hans": ("chinese_s", "chs", "sc", "zh_cn", "zh_hans", "schinese", "simplifiedchinese", "chinesesimplified", "cn"),
    "zh-hant": ("chinese_t", "cht", "tc", "zh_tw", "zh_hant", "tchinese", "traditionalchinese", "chinesetraditional", "tw"),
    "fr": ("french", "fr", "fra"), "de": ("german", "de", "deu", "ger"), "es": ("spanish", "es", "spa"),
    "ru": ("russian", "ru", "rus"), "pt": ("portuguese", "pt", "pt_br", "ptbr"), "it": ("italian", "it", "ita"),
    "pl": ("polish", "pl", "pol"), "tr": ("turkish", "tr", "tur"),
}
_LANG_LOOKUP = {alias: code for code, aliases in _LANG_ALIASES.items() for alias in aliases}

# Hedef dilin kendi adı: oyunun dil menüsündeki "English" yazısı bununla değiştirilir
LANGUAGE_NAMES = {"tr": "Türkçe", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano",
                  "pt": "Português", "ru": "Русский", "pl": "Polski", "en": "English"}

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")
_LETTER = re.compile(r"[^\W\d_]")
# Boşluksuz tanımlayıcılar: Lang_en, Slot1.sav, Room_Main, fsmName, Ui/Panel… (ekrana gelen metin değildir)
_IDENTIFIER = re.compile(
    r"(?:[A-Za-z0-9]+(?:[_./\\:#-][A-Za-z0-9]+)+|[a-z]+[A-Z]\w*|[A-Z]{2,}[a-z]\w*|[A-Za-z]+\d\w*|\w*_\w*)")

PLAYMAKER_CLASSES = {"PlayMakerFSM": ("fsm",), "FsmTemplate": ("fsm",)}
TEXT_CLASSES = {"Text": "m_Text", "TextMeshProUGUI": "m_text", "TextMeshPro": "m_text"}
FONT_CLASSES = {"TMP_FontAsset", "TMP_Settings"}

# PlayMaker ParamDataType kodları (HutongGames.PlayMaker.ParamDataType sırası)
P_STRING, P_ARRAY, P_FSM_INT, P_FSM_STRING, P_FSM_EVENT, P_FSM_PROPERTY = 3, 12, 16, 18, 23, 36


def lang_code(name: str) -> Optional[str]:
    key = re.sub(r"[\s\-()]+", "_", (name or "").strip().casefold()).strip("_").replace("__", "_")
    return _LANG_LOOKUP.get(key) or _LANG_LOOKUP.get(key.replace("_", ""))


def is_display_text(value: str) -> bool:
    """Ekranda okunacak Latin metni mi (harf içerir, CJK değildir, boşluksuz bir tanımlayıcı değildir)."""
    text = (value or "").strip()
    if not text or not _LETTER.search(text) or _CJK.search(text):
        return False
    return bool(re.search(r"\s", text)) or not _IDENTIFIER.fullmatch(text)


def sentence_like(value: str) -> bool:
    """Dil dalı olmayan FSM'lerde değişkene atanan metin ancak açıkça cümleyse alınır."""
    text = value.strip()
    return is_display_text(text) and (len(text.split()) >= 3 or (" " in text and text[-1:] in ".!?…:"))


# ─── Tip bilgisi üretici (isteğe bağlı indirilen okuyucu) ──────────────────────
# TypeTreeGeneratorAPI'nin yerel DLL'i GPL-3.0 lisanslı AssetRipper kodu içerir; Capri (MIT) onu paketine koymaz.
# Gerektiğinde kullanıcının izniyle PyPI'dan sabit sürüm + SHA-256 doğrulamasıyla indirilir (GPL kullanımı kısıtlamaz).
READER_VERSION = "0.0.10"
READER_WHEEL = {
    "name": "typetreegeneratorapi-0.0.10-cp36-abi3-win_amd64.whl",
    "url": "https://files.pythonhosted.org/packages/ed/bc/f911995cae93fa8fd882a677f6bc304965db6f066bbabdee6e761762d512/"
           "typetreegeneratorapi-0.0.10-cp36-abi3-win_amd64.whl",
    "size": 7859632,
    "sha256": "e96003e973c8d52d221b4ae50f377bcaf7538f2098e437d5383a1b7f13fa72ba",
}
READER_SIZE_MB = round(READER_WHEEL["size"] / 1048576, 1)


def reader_dir() -> Path:
    from paths import APP_DIR
    return Path(APP_DIR) / "tools" / "typetree" / READER_VERSION


def _add_reader_path() -> None:
    import sys

    folder = reader_dir()
    if (folder / "TypeTreeGeneratorAPI" / "__init__.py").is_file() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


def generator_available() -> bool:
    _add_reader_path()
    try:
        import TypeTreeGeneratorAPI  # noqa: F401
        return True
    except Exception:
        return False


def install_reader(progress=None, cancel=None, log: LogFn = print, opener=None) -> Path:
    """Okuyucuyu indirir, doğrular ve yalnızca kendi paket klasörünü (ve lisansını) çıkarır."""
    import shutil
    import urllib.request
    import zipfile

    from local_llm import _download

    folder = reader_dir()
    staging = folder.with_name(folder.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        wheel = staging / READER_WHEEL["name"]
        _download(READER_WHEEL["url"], wheel, READER_WHEEL["size"], READER_WHEEL["sha256"], progress, cancel,
                  opener or urllib.request.urlopen)
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.namelist():
                parts = Path(member).parts
                if not parts or ".." in parts or Path(member).is_absolute():
                    raise RuntimeError(f"Okuyucu arşivinde geçersiz yol: {member}")
                if parts[0] == "TypeTreeGeneratorAPI" or member.endswith("/licenses/LICENSE"):
                    target = staging / ("LICENSE" if member.endswith("LICENSE") else member)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
        wheel.unlink()
        (staging / "SOURCE.txt").write_text(
            f"TypeTreeGeneratorAPI {READER_VERSION} (MIT, K0lb3) — {READER_WHEEL['url']}\n"
            "Yerel DLL; AssetRipper (GPL-3.0), AssetsTools.NET, Cpp2IL, AsmResolver, Mono.Cecil (MIT), "
            "Capstone (BSD-3) kodu içerir. Kaynak: https://github.com/K0lb3/TypeTreeGeneratorAPI\n", encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        staging.replace(folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    log(f"Unity bileşen okuyucusu kuruldu ({READER_SIZE_MB} MB)")
    return folder


def _generator_class():
    from TypeTreeGeneratorAPI import TypeTreeGenerator as Base
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode

    class FixedGenerator(Base):
        """UnityPy'nin üretici arayüzü (get_nodes_up) + TypeTreeGeneratorAPI 0.0.10'un iki sapmasının düzeltmesi
        (bayt bayt doğrulamayla bulundu): m_Enabled'dan sonraki hizalama bayrağı eksik ve List<string> alanları
        'string' diye etiketleniyor."""

        def __init__(self, unity_version: str):
            super().__init__(unity_version)
            self.cache: Dict[Tuple[str, str], Any] = {}

        def get_nodes(self, assembly: str, fullname: str):
            nodes = super().get_nodes(assembly, fullname)
            for index, node in enumerate(nodes):
                if node.m_Level == 1 and node.m_Name == "m_Enabled":
                    node.m_MetaFlag |= 0x4000
                if (node.m_Type == "string" and index + 3 < len(nodes) and nodes[index + 1].m_Type == "Array"
                        and nodes[index + 3].m_Level == node.m_Level + 2 and nodes[index + 3].m_Type != "char"):
                    node.m_Type = "vector"
            return nodes

        def get_nodes_up(self, assembly: str, fullname: str):
            key = (assembly, fullname)
            if key not in self.cache:
                name = assembly if assembly.endswith(".dll") else f"{assembly}.dll"
                base = self.get_nodes(name, fullname)
                self.cache[key] = TypeTreeNode.from_list([
                    TypeTreeNode(n.m_Level, n.m_Type, n.m_Name, 0, 0, m_MetaFlag=n.m_MetaFlag) for n in base])
            return self.cache[key]

    return FixedGenerator


def wants_reader(info: Any, other_texts: int) -> bool:
    """Bu oyunda bileşen okuyucusu işe yarar mı: tek paket (data.unity3d) ya da başka çevrilebilir metin yok."""
    data_dir = Path(info.data_dir)
    has_types = (data_dir / "Managed").is_dir() or (Path(info.root) / "GameAssembly.dll").is_file()
    return has_types and ((data_dir / "data.unity3d").is_file() or not other_texts)


def attach_generator(env: Any, info: Any, log: LogFn = print) -> bool:
    """Oyunun DLL'lerinden tip bilgisi üreticisini ortama bağlar; olmazsa False (o zaman hiçbir şeye dokunulmaz)."""
    if getattr(env, "typetree_generator", None) is not None:
        return True
    if not generator_available():
        log("Tip bilgisi üreticisi (TypeTreeGeneratorAPI) yok; bileşen metinleri okunamıyor")
        return False
    try:
        version = next(iter(env.objects)).assets_file.unity_version
        generator = _generator_class()(version)
        root, data_dir = Path(info.root), Path(info.data_dir)
        game_assembly = root / "GameAssembly.dll"
        metadata = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
        if game_assembly.is_file() and metadata.is_file():
            generator.load_il2cpp(game_assembly.read_bytes(), metadata.read_bytes())
        elif (data_dir / "Managed").is_dir():
            for dll in sorted((data_dir / "Managed").glob("*.dll")):
                try:
                    generator.load_dll(dll.read_bytes())
                except Exception:
                    pass   # yerel (native) ya da bozuk DLL: o derlemedeki türler üretilemez, diğerleri etkilenmez
        else:
            return False
        env.typetree_generator = generator
        return True
    except Exception as error:
        log(f"Tip bilgisi üretilemedi: {error}")
        return False


def script_class(obj: Any) -> str:
    try:
        return obj.parse_monobehaviour_head().m_Script.deref_parse_as_object().m_ClassName or ""
    except Exception:
        return ""


def read_exact(obj: Any) -> Optional[Tuple[Any, dict]]:
    """(düğüm, ağaç): yalnızca okuma tam tutuyor ve geri yazım bayt bayt aynıysa."""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    try:
        node = obj._get_typetree_node()
        tree = obj.read_typetree(nodes=node, check_read=True)
        writer = EndianBinaryWriter(endian=obj.reader.endian)
        TypeTreeHelper.write_typetree(tree, node, writer, obj.assets_file)
        return (node, tree) if writer.bytes == obj.get_raw_data() else None
    except Exception:
        return None


def get_path(tree: Any, path: List[Any]) -> Any:
    for key in path:
        tree = tree[key]
    return tree


def set_path(tree: Any, path: List[Any], value: Any) -> None:
    for key in path[:-1]:
        tree = tree[key]
    tree[path[-1]] = value


# ─── PlayMaker ────────────────────────────────────────────────────────────────
@dataclass
class _Assign:
    path: List[Any]        # ağaçtaki yeri (…, "value")
    target: Tuple          # atandığı yer: ("var", ad) / ("fsm", fsm, değişken) / ("prop", tür)
    value: str
    direct: bool           # doğrudan ekrana yazar (SetProperty text, UI metin eylemi)


def _action_params(ad: dict) -> Iterable[Tuple[int, str, List[Tuple[int, int, str]]]]:
    """Her eylem için (sıra, kısa ad, [(tür, konum, parametre adı)…])."""
    types, names, positions = ad.get("paramDataType", []), ad.get("paramName", []), ad.get("paramDataPos", [])
    starts = list(ad.get("actionStartIndex", [])) + [len(types)]
    for index, full in enumerate(ad.get("actionNames", [])):
        start, end = starts[index], starts[index + 1] if index + 1 < len(starts) else len(types)
        yield index, full.rsplit(".", 1)[-1], [(types[i], positions[i], names[i]) for i in range(start, min(end, len(types)))]


def _state_assigns(ad: dict, base: List[Any]) -> List[_Assign]:
    out: List[_Assign] = []
    strings = ad.get("fsmStringParams", [])
    for _index, action, params in _action_params(ad):
        named = {name: (kind, pos) for kind, pos, name in params if name}

        def literal(name: str) -> Optional[Tuple[int, dict]]:
            kind, pos = named.get(name, (None, None))
            if kind == P_FSM_STRING and pos is not None and pos < len(strings):
                return pos, strings[pos]
            return None

        if action == "SetStringValue":
            var, val = literal("stringVariable"), literal("stringValue")
            if var and val and not val[1].get("useVariable"):
                out.append(_Assign(base + ["fsmStringParams", val[0], "value"], ("var", var[1].get("name", "")),
                                   val[1].get("value", ""), False))
        elif action == "SetFsmString":
            fsm, var, val = literal("fsmName"), literal("variableName"), literal("setValue")
            if var and val and not val[1].get("useVariable"):
                out.append(_Assign(base + ["fsmStringParams", val[0], "value"],
                                   ("fsm", fsm[1].get("value", "") if fsm else "", var[1].get("value", "")),
                                   val[1].get("value", ""), False))
        elif action in ("UiTextSetText", "SetTextMeshProText", "TextMeshProSetText", "SetGUIText", "SetTextMeshProUGuiText"):
            for name in ("text", "textString", "Text"):
                val = literal(name)
                if val and not val[1].get("useVariable"):
                    out.append(_Assign(base + ["fsmStringParams", val[0], "value"], ("action", action),
                                       val[1].get("value", ""), True))
    for index, prop in enumerate(ad.get("fsmPropertyParams", [])):
        param = prop.get("StringParameter") or {}
        if prop.get("setProperty") and prop.get("PropertyName") == "text" and not param.get("useVariable"):
            out.append(_Assign(base + ["fsmPropertyParams", index, "StringParameter", "value"],
                               ("prop", prop.get("TargetTypeName", "")), param.get("value", ""), True))
    return out


def _switch_branches(ad: dict) -> List[Tuple[str, int, str]]:
    """IntSwitch eylemleri: (değişken adı, karşılaştırılan sayı, gönderilen olay adı) üçlüleri."""
    out = []
    ints, strings = ad.get("fsmIntParams", []), ad.get("stringParams", [])
    for _index, action, params in _action_params(ad):
        if action != "IntSwitch":
            continue
        variable, values, events, mode = "", [], [], None
        for kind, pos, name in params:
            if name == "intVariable" and kind == P_FSM_INT and pos < len(ints):
                variable = ints[pos].get("name", "") if ints[pos].get("useVariable") else ""
            elif name == "compareTo":
                mode = "values"
            elif name == "sendEvent":
                mode = "events"
            elif not name and mode == "values" and kind == P_FSM_INT and pos < len(ints):
                values.append(int(ints[pos].get("value", 0)))
            elif not name and mode == "events" and kind == P_FSM_EVENT and pos < len(strings):
                events.append(strings[pos])
        if variable:
            out.extend((variable, v, e) for v, e in zip(values, events))
    return out


def learn_language_numbers(fsms: Iterable[dict]) -> Dict[str, Dict[int, str]]:
    """Dil değişkeninin sayı → dil eşlemesi, olayları dil adı taşıyan IntSwitch'lerden öğrenilir
    (ör. LangIndex: 0 → Japanese, 1 → English); başka FSM'ler aynı değişkene '0', '1' gibi olaylarla bakar."""
    learned: Dict[str, Dict[int, str]] = defaultdict(dict)
    for fsm in fsms:
        for state in fsm.get("states", []):
            for variable, value, event in _switch_branches(state.get("actionData", {})):
                code = lang_code(event)
                if code:
                    learned[variable].setdefault(value, code)
    return {name: mapping for name, mapping in learned.items() if len(set(mapping.values())) >= 2}


def fsm_language_states(fsm: dict, numbers: Dict[str, Dict[int, str]]) -> Dict[str, str]:
    """Durum adı → dil: dil olayıyla girilen dal kökleri ve yalnızca o kökten ulaşılan durumlar."""
    states = {s.get("name", ""): s for s in fsm.get("states", [])}
    roots: Dict[str, str] = {}
    switches: Set[str] = set()
    any_numbers = {}
    for mapping in numbers.values():
        for value, code in mapping.items():
            any_numbers.setdefault(value, code)
    for name, state in states.items():
        by_event = {t.get("fsmEvent", {}).get("name", ""): t.get("toState", "") for t in state.get("transitions", [])}
        for event, target in by_event.items():
            code = lang_code(event)
            if code and target in states:
                roots.setdefault(target, code)
                switches.add(name)
        for variable, value, event in _switch_branches(state.get("actionData", {})):
            mapping = numbers.get(variable) or (any_numbers if "lang" in variable.casefold() else {})
            code = mapping.get(value)
            target = by_event.get(event)
            if code and target in states:
                roots.setdefault(target, code)
                switches.add(name)
    if len(set(roots.values())) < 2:
        return {}
    reached: Dict[str, Set[str]] = defaultdict(set)
    for root, code in roots.items():
        queue, seen = [root], {root}
        while queue:
            name = queue.pop()
            reached[name].add(code)
            for transition in states[name].get("transitions", []):
                nxt = transition.get("toState", "")
                if nxt in states and nxt not in seen and nxt not in switches and (nxt not in roots or roots[nxt] == code):
                    seen.add(nxt)
                    queue.append(nxt)
    return {name: next(iter(codes)) for name, codes in reached.items() if len(codes) == 1}


def fsm_texts(tree: dict, prefix: Tuple[str, ...], numbers: Dict[str, Dict[int, str]],
              source: str = "en") -> List[Tuple[List[Any], str]]:
    """Bir FSM'de çevrilecek (ağaç yolu, metin) çiftleri."""
    fsm = get_path(tree, list(prefix))
    lang_of = fsm_language_states(fsm, numbers)
    per_state: List[Tuple[Optional[str], _Assign]] = []
    for index, state in enumerate(fsm.get("states", [])):
        base = list(prefix) + ["states", index, "actionData"]
        for assign in _state_assigns(state.get("actionData", {}), base):
            per_state.append((lang_of.get(state.get("name", "")), assign))
    out: List[Tuple[List[Any], str]] = []
    if lang_of:
        others: Dict[Tuple, Set[str]] = defaultdict(set)
        for code, assign in per_state:
            if code and code != source:
                others[assign.target].add(assign.value)
        for code, assign in per_state:
            if code != source or not is_display_text(assign.value):
                continue
            # Diğer dillerde aynı değeri alan atama dile bağlı değildir: anahtardır
            if assign.value in others.get(assign.target, ()):
                continue
            out.append((assign.path, assign.value))
        shared = [a for code, a in per_state if code is None]
    else:
        shared = [a for _code, a in per_state]
    if source == "en":
        for assign in shared:   # dil dalı dışı: doğrudan ekrana yazanlar ya da açıkça cümle olanlar
            if (assign.direct and is_display_text(assign.value)) or sentence_like(assign.value):
                out.append((assign.path, assign.value))
    return out


# ─── Çok dilli XML tabloları ──────────────────────────────────────────────────
_XML_ELEMENT = re.compile(r"<([A-Za-z_][\w.\-]*)(\s[^<>]*?)/?>", re.S)
_XML_ATTR = re.compile(r"([A-Za-z_][\w.\-]*)\s*=\s*(\"[^\"]*\"|'[^']*')")


def _xml_unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'")
            .replace("&#10;", "\n").replace("&#13;", "\r").replace("&amp;", "&"))


def _xml_escape(text: str, quote: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("\"", "&quot;") if quote == "\"" else text.replace("'", "&apos;")


def xml_language_cells(script: str, source: str = "en") -> List[Tuple[int, str, str]]:
    """<Language ID="1" kr="…" jp="…" en="Merchant"/> gibi öğelerde kaynak dilin değeri: (öğe sırası, nitelik, metin).
    Öğede en az iki dil niteliği yoksa tablo dil tablosu sayılmaz."""
    if "<" not in script[:400]:
        return []
    cells = []
    for number, element in enumerate(_XML_ELEMENT.finditer(script)):
        attributes = _XML_ATTR.findall(element.group(2) or "")
        codes = {name: lang_code(name) for name, _value in attributes}
        if len({c for c in codes.values() if c}) < 2:
            continue
        for name, quoted in attributes:
            if codes.get(name) == source:
                value = _xml_unescape(quoted[1:-1])
                if _LETTER.search(value):
                    cells.append((number, name, value))
    return cells


def names_table(asset_name: str, values: List[str]) -> bool:
    """Kişi adı tablosu mu (Names: Mark, Rose, Grace…): adlar çevrilirse "Grace" → "Zarafet" olur."""
    if "name" not in asset_name.casefold() or not values:
        return False
    single = sum(1 for v in values if re.fullmatch(r"[A-Z][a-z'\-]+(?: [A-Z][a-z'\-]+)?", v.strip()))
    return single >= 0.7 * len(values)


def xml_rewrite(script: str, replacements: Dict[Tuple[int, str], Tuple[str, str]]) -> Tuple[str, int]:
    """(öğe sırası, nitelik) → (eski, yeni). Yalnızca o niteliğin değeri değişir; eski değer tutmuyorsa dokunulmaz."""
    out, last, changed = [], 0, 0
    for number, element in enumerate(_XML_ELEMENT.finditer(script)):
        wanted = {attr: pair for (n, attr), pair in replacements.items() if n == number}
        if not wanted:
            continue
        body_start = element.start(2)
        for attr in _XML_ATTR.finditer(element.group(2) or ""):
            pair = wanted.get(attr.group(1))
            if not pair or _xml_unescape(attr.group(2)[1:-1]) != pair[0]:
                continue
            quote = attr.group(2)[0]
            start, end = body_start + attr.start(2), body_start + attr.end(2)
            out.append(script[last:start] + quote + _xml_escape(pair[1], quote) + quote)
            last = end
            changed += 1
    out.append(script[last:])
    return "".join(out), changed


# ─── Fontlar (TextMeshPro) ────────────────────────────────────────────────────
def _resolve(assets_file: Any, pointer: dict) -> Optional[Tuple[str, int]]:
    file_id, path_id = int(pointer.get("m_FileID", 0)), int(pointer.get("m_PathID", 0))
    if not path_id:
        return None
    if file_id == 0:
        return assets_file.name, path_id
    try:
        return Path(assets_file.externals[file_id - 1].path).name, path_id
    except Exception:
        return None


def _font_cmap(obj: Any) -> Set[int]:
    from engine_common import FontChecker

    try:
        data = bytes(obj.read_typetree(check_read=False).get("m_FontData") or b"")
        if not data:
            return set()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "font.ttf"
            path.write_bytes(data)
            return set(FontChecker._read_cmap(path))
    except Exception:
        return set()


def tmp_effective_glyphs(objects: Dict[Tuple[str, int], Any], fonts: Dict[Tuple[str, int], dict],
                         settings: Optional[Tuple[Any, dict]], used: Iterable[Tuple[str, int]]) -> Set[int]:
    """Kullanılan TMP fontlarının hepsinde çizilebilen karakterler: fontun kendi tablosu (dinamikse kaynak TTF),
    yedek fontları, TMP Ayarları'ndaki genel yedekler ve varsayılan font zinciri. TMP eksik harfi bu sırayla arar."""
    own_cache: Dict[Tuple[str, int], Set[int]] = {}

    def own(key: Tuple[str, int]) -> Set[int]:
        if key not in own_cache:
            tree = fonts.get(key) or {}
            glyphs = {int(c.get("m_Unicode", 0)) for c in tree.get("m_CharacterTable", [])}
            glyphs |= {int(c.get("id", 0)) for c in tree.get("m_glyphInfoList", [])}
            if tree.get("m_AtlasPopulationMode") == 1 and key in objects:
                source = _resolve(objects[key].assets_file, tree.get("m_SourceFontFile") or {})
                if source and source in objects:
                    glyphs |= _font_cmap(objects[source])
            own_cache[key] = glyphs
        return own_cache[key]

    def chain(key: Optional[Tuple[str, int]], seen: Set[Tuple[str, int]]) -> Set[int]:
        if not key or key in seen or key not in fonts:
            return set()
        seen.add(key)
        glyphs = set(own(key))
        tree = fonts[key]
        for pointer in list(tree.get("m_FallbackFontAssetTable", [])) + list(tree.get("fallbackFontAssets", [])):
            glyphs |= chain(_resolve(objects[key].assets_file, pointer), seen)
        return glyphs

    global_glyphs: Set[int] = set()
    if settings:
        settings_obj, tree = settings
        for pointer in tree.get("m_fallbackFontAssets", []):
            global_glyphs |= chain(_resolve(settings_obj.assets_file, pointer), set())
        global_glyphs |= chain(_resolve(settings_obj.assets_file, tree.get("m_defaultFontAsset") or {}), set())
    result: Optional[Set[int]] = None
    for key in set(used):
        glyphs = chain(key, set()) | global_glyphs
        if sum(1 for c in "abcdefghijklmnopqrstuvwxyz" if ord(c) in glyphs) < 20:
            continue   # okunamayan ya da simge fontu
        result = glyphs if result is None else result & glyphs
    return result or set()


# ─── Çıkarma ve yazma ─────────────────────────────────────────────────────────
def containers(info: Any) -> List[Path]:
    """Tip bilgisiyle taranacak dosyalar: tek paket (data.unity3d) ya da sahne ve paylaşılan varlık dosyaları."""
    data_dir = Path(info.data_dir)
    bundle = data_dir / "data.unity3d"
    if bundle.is_file():
        return [bundle]
    files = [data_dir / "resources.assets", *sorted(data_dir.glob("sharedassets*.assets")),
             *sorted(p for p in data_dir.glob("level*") if p.suffix in ("", ".assets") and p.is_file())]
    return [p for p in files if p.is_file()]


@dataclass
class TypedScan:
    items: List[Any]
    tmp_glyphs: Set[int]
    counts: Dict[str, int]


def _item_key(kind: str, file_name: str, path_id: int) -> str:
    return f"{kind}:{file_name}:{path_id}"


def scan(info: Any, log: LogFn = print, source: str = "en") -> TypedScan:
    """Bileşen metinlerini UnityTextItem olarak çıkarır (format_type='typed', key_id = JSON ağaç yolu)."""
    import UnityPy
    from engine_unity import UnityTextItem

    items: List[Any] = []
    counts: Dict[str, int] = defaultdict(int)
    tmp_glyphs: Set[int] = set()
    for path in containers(info):
        try:
            env = UnityPy.load(str(path))
        except Exception as error:
            log(f"{path.name} açılamadı: {error}")
            continue
        if not attach_generator(env, info, log):
            break
        objects = {(o.assets_file.name, o.path_id): o for o in env.objects}
        fsm_trees: List[Tuple[Any, Tuple[str, ...], dict]] = []
        fonts: Dict[Tuple[str, int], dict] = {}
        settings = None
        used_fonts: List[Tuple[str, int]] = []
        skipped = 0
        for obj in env.objects:
            kind = obj.type.name
            try:
                if kind == "TextAsset":
                    data = obj.read()
                    script = data.m_Script if isinstance(data.m_Script, str) else bytes(data.m_Script).decode("utf-8", "ignore")
                    cells = xml_language_cells(script, source)
                    if cells and names_table(getattr(data, "m_Name", ""), [c[2] for c in cells]):
                        log(f"İsim tablosu: {getattr(data, 'm_Name', '')} — kişi adları çevrilmez")
                        continue
                    for number, attr, value in cells:
                        items.append(UnityTextItem(path.name, _item_key("xml", obj.assets_file.name, obj.path_id),
                                                   number, attr, value, FORMAT))
                    if cells:
                        counts["xml"] += len(cells)
                        log(f"Çok dilli tablo: {getattr(data, 'm_Name', '')} — {len(cells)} metin")
                    continue
                if kind != "MonoBehaviour":
                    continue
                cls = script_class(obj)
                if cls not in PLAYMAKER_CLASSES and cls not in TEXT_CLASSES and cls not in FONT_CLASSES:
                    continue
                exact = read_exact(obj)
                if exact is None:
                    skipped += 1
                    continue
                tree = exact[1]
                if cls in PLAYMAKER_CLASSES:
                    fsm_trees.append((obj, PLAYMAKER_CLASSES[cls], tree))
                elif cls in TEXT_CLASSES:
                    field = TEXT_CLASSES[cls]
                    if cls != "Text":
                        font = _resolve(obj.assets_file, tree.get("m_fontAsset") or {})
                        if font:
                            used_fonts.append(font)
                    value = tree.get(field) or ""
                    if is_display_text(value):
                        items.append(UnityTextItem(path.name, _item_key("ui", obj.assets_file.name, obj.path_id),
                                                   len(items), json.dumps([field]), value, FORMAT))
                        counts["ui"] += 1
                elif cls == "TMP_FontAsset":
                    fonts[(obj.assets_file.name, obj.path_id)] = tree
                elif cls == "TMP_Settings":
                    settings = (obj, tree)
            except Exception as error:
                skipped += 1
                log(f"{path.name} #{obj.path_id} atlandı: {error}")
        numbers = learn_language_numbers(get_path(t, list(p)) for _o, p, t in fsm_trees)
        for obj, prefix, tree in fsm_trees:
            for tree_path, value in fsm_texts(tree, prefix, numbers, source):
                items.append(UnityTextItem(path.name, _item_key("fsm", obj.assets_file.name, obj.path_id),
                                           len(items), json.dumps(tree_path), value, FORMAT))
                counts["fsm"] += 1
        if used_fonts:
            tmp_glyphs = tmp_effective_glyphs(objects, fonts, settings, used_fonts)
        if skipped:
            log(f"{path.name}: {skipped} bileşen tip bilgisiyle birebir okunamadığı için dokunulmadan bırakıldı")
        del env, objects
        gc.collect()
    if counts:
        log("Bileşen metinleri: " + ", ".join(f"{label} {counts[key]}" for key, label in
                                              (("fsm", "PlayMaker"), ("ui", "arayüz"), ("xml", "tablo")) if counts.get(key)))
    return TypedScan(items, tmp_glyphs, dict(counts))


def _match_case(original: str, name: str) -> str:
    if original.isupper():
        return name.upper() if name != "Türkçe" else "TÜRKÇE"
    return name


def write(info: Any, translations: Dict[str, str], items: List[Any], log: LogFn = print,
          target: str = "tr", replace_file: Optional[Callable[[Path, bytes], None]] = None) -> int:
    """Çevirileri bileşenlere yazar. Her dosya bellekte değiştirilir, kaydedilen paket yeniden okunup doğrulanır."""
    import UnityPy

    by_container: Dict[str, List[Any]] = defaultdict(list)
    for item in items:
        if item.format_type == FORMAT:
            by_container[item.source_file].append(item)
    written = 0
    language_name = LANGUAGE_NAMES.get(target)
    for container, container_items in by_container.items():
        path = Path(info.data_dir) / container
        if not path.is_file():
            continue
        by_object: Dict[Tuple[str, int], List[Any]] = defaultdict(list)
        for item in container_items:
            kind, file_name, path_id = item.asset_name.split(":", 2)
            by_object[(file_name, int(path_id))].append(item)
        env = UnityPy.load(path.read_bytes())   # bellekten: dosya açık kalırsa Windows yerine yazmaya izin vermez
        if not attach_generator(env, info, log):
            continue
        expected: Dict[Tuple[str, int], List[Tuple[Any, str]]] = defaultdict(list)
        for obj in env.objects:
            key = (obj.assets_file.name, obj.path_id)
            wanted = by_object.get(key)
            if not wanted:
                continue
            kind = wanted[0].asset_name.split(":", 1)[0]
            if kind == "xml" and obj.type.name == "TextAsset":
                data = obj.read()
                script = data.m_Script if isinstance(data.m_Script, str) else bytes(data.m_Script).decode("utf-8")
                replacements = {}
                for item in wanted:
                    new = translations.get(item.original)
                    if new and new != item.original:
                        replacements[(item.line_index, item.key_id)] = (item.original, new)
                script, changed = xml_rewrite(script, replacements)
                if changed:
                    data.m_Script = script
                    data.save()
                    written += changed
                    expected[key].append(("xml", script))
                continue
            exact = read_exact(obj)
            if exact is None:
                log(f"{container} #{obj.path_id}: bileşen birebir okunamadı; dokunulmadı")
                continue
            node, tree = exact
            changed = 0
            for item in wanted:
                tree_path = json.loads(item.key_id)
                try:
                    current = get_path(tree, tree_path)
                except (KeyError, IndexError, TypeError):
                    continue
                if current != item.original:
                    continue
                if kind in ("fsm", "ui") and language_name and item.original.strip().casefold() == "english":
                    new = _match_case(item.original.strip(), language_name)   # dil menüsündeki "English" yazısı
                else:
                    new = translations.get(item.original)
                if not new or new == item.original:
                    continue
                set_path(tree, tree_path, new)
                expected[key].append((tree_path, new))
                changed += 1
            if changed:
                obj.save_typetree(tree, nodes=node)
                written += changed
        if not expected:
            continue
        log(f"{container} kaydediliyor…")
        from UnityPy.files import BundleFile
        # Paket LZ4 ile sıkıştırılır (Unity'nin kendi biçimi); sıkıştırmasız yazmak boyutu katlar
        data_bytes = env.file.save(packer="lz4") if isinstance(env.file, BundleFile) else env.file.save()
        del env
        gc.collect()
        if not _verify(data_bytes, info, expected):
            raise RuntimeError(f"{container}: kaydedilen paket doğrulanamadı; oyun dosyası değiştirilmedi")
        (replace_file or _write_file)(path, data_bytes)
        log(f"Kaydedildi: {container} ({len(data_bytes) / 1048576:.0f} MB)")
    return written


def _verify(data: bytes, info: Any, expected: Dict[Tuple[str, int], List[Tuple[Any, str]]]) -> bool:
    """Yeni paket açılıyor ve değişen her alan yazılan değeri taşıyor mu."""
    import UnityPy

    try:
        env = UnityPy.load(data)
        if not attach_generator(env, info, lambda _m: None):
            return False
        found = 0
        for obj in env.objects:
            checks = expected.get((obj.assets_file.name, obj.path_id))
            if not checks:
                continue
            if checks[0][0] == "xml":
                data_obj = obj.read()
                script = data_obj.m_Script if isinstance(data_obj.m_Script, str) else bytes(data_obj.m_Script).decode("utf-8")
                if script != checks[-1][1]:
                    return False
            else:
                exact = read_exact(obj)
                if exact is None or any(get_path(exact[1], p) != v for p, v in checks):
                    return False
            found += 1
        return found == len(expected)
    except Exception:
        return False
    finally:
        gc.collect()


def _write_file(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".capri-tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
