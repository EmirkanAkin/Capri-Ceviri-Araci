"""
Capri — Godot oyunları (3.x ve 4.x)
==================================
Dışa aktarılmış bir Godot oyununda metinler iki yerde olur:

1. **Çeviri tabloları** (internationalization/locale/translations): CSV'den üretilen OptimizedTranslation (anahtarlar
   yalnızca özet olarak saklanır) ya da düz Translation / .po. Kaynak dilin (çoğunlukla İngilizce) tablosundaki
   metinler çevrilir.
2. **Sahnelerdeki arayüz yazıları** (Label, Button, … "text"): Godot bunları gösterirken çeviri sunucusundan geçirir
   (otomatik çeviri), bu yüzden kaynak dile eklenen bir çeviri tablosuyla değiştirilebilirler.
3. **Betiklere gömülü metinler** (GDScript: .gd, .gdc): `label.text = "Kapı kilitli."` gibi arayüze atanan dizeler de
   aynı otomatik çeviriden geçer. Betikler değiştirilmez; doğal dil gibi görünen dizeler (godot_script) tabloya eklenir.
   Birleştirilerek üretilen ("Puan: " + str(x)) ya da doğrudan çizilen metinler bu yolla çevrilemez.

Oyunun kendi dosyalarına dokunulmaz. Capri oyunun klasörüne üç dosya yazar:
  capri_tr.pck   → değiştirilmiş çeviri tabloları ve arayüz metinleri (messages.json)
  capri_tr.gd    → oyun açılırken yamayı yükleyen küçük betik
  override.cfg   → Godot'nun her dışa aktarılmış oyunda okuduğu ayar dosyası; betiği "autoload" olarak ekler
Yedekten geri dönünce bu dosyalar silinir (oyunun önceden bir override.cfg'si varsa o geri yüklenir).
Betik çalıştırılabilir dosyanın yanındaki yamayı bulur; oyun klasörü taşınırsa çeviri yeniden uygulanmalıdır.

Desteklenmeyen: şifreli paketler ve şifreli betikler (.gde).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from struct import error as struct_error
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import godot_formats as gf
import godot_script as gscript

LogFn = Callable[[str], None]
PATCH_NAME = "capri_tr.pck"
SCRIPT_NAME = "capri_tr.gd"
AUTOLOAD_KEY = "CapriTr"
MESSAGES_PATH = "capri_tr/messages.json"
TEXT_PROPS = {"text", "tooltip_text", "placeholder_text", "title", "dialog_text", "hint_tooltip", "ok_button_text",
              "cancel_button_text"}
# %s %d %.2f, {isim}, BBCode [b] [color=…] [url=…], \n
PROTECTED_GODOT = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdifxXoc]|%%|\{[A-Za-z0-9_]*\}|\[/?[A-Za-z_][^\[\]\r\n]{0,80}\]|\\n")
GODOT_EXTRA_INSTRUCTION = ("%s, %d, {isim} gibi yer tutucuları ve [b], [color=...] gibi BBCode etiketlerini aynen koru.")
_KEY_LIKE = re.compile(r"^[A-Z0-9_.\-]{3,}$")


@dataclass
class GodotUnit:
    kind: str                 # ot (özetli tablo) | msg (anahtarı bilinen tablo) | ui (sahne yazısı)
    path: str                 # kaynak dosya (res:// olmadan)
    ref: Union[int, str]      # ot: bucket öğesi konumu; msg/ui: anahtar
    original: str
    context: str = "dialogue"


@dataclass
class GodotGameInfo:
    root: Path
    exe: Optional[Path]
    pck_path: Path
    pck: gf.Pck
    major: int
    label: str
    encrypted: bool = False
    settings: Dict[str, object] = field(default_factory=dict)
    source_locale: str = "en"
    translations: List[str] = field(default_factory=list)       # res:// olmadan
    locales: Dict[str, str] = field(default_factory=dict)       # tablo → dil (bir kez okunur)
    loaded: bool = False                                         # ayrıntılar (ayarlar, diller) okundu mu


# ── Algılama ────────────────────────────────────────────────────────────────
def _is_pck(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == gf.PCK_MAGIC
    except OSError:
        return False


def _embedded(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return gf._find_embedded(f) >= 0
    except OSError:
        return False


def detect_godot(selected: Union[str, Path]) -> Optional[GodotGameInfo]:
    root = Path(selected)
    if not root.is_dir():
        return None
    exes = sorted(p for p in root.glob("*.exe") if not p.name.lower().endswith("_console.exe"))
    pcks = [p for p in sorted(root.glob("*.pck")) if p.name.lower() != PATCH_NAME and _is_pck(p)]
    pck_path, exe = None, None
    for candidate in exes:
        twin = candidate.with_suffix(".pck")
        if twin in pcks:
            pck_path, exe = twin, candidate
            break
    if pck_path is None and pcks and exes:
        pck_path, exe = pcks[0], exes[0]
    if pck_path is None:
        exe = next((e for e in exes if e.stat().st_size > 1 << 20 and _embedded(e)), None)
        pck_path = exe
    if pck_path is None:
        return None
    try:
        pck = gf.read_pck(pck_path)
    except (OSError, gf.GodotFormatError):
        return None
    major = 3 if pck.version <= 1 else 4
    label = f"Godot {pck.engine[0]}.{pck.engine[1]}.{pck.engine[2]} · " + (
        f"{pck_path.name}" if pck_path.suffix.lower() == ".pck" else f"{pck_path.name} içine gömülü paket")
    # Algılama hafif kalır (oyun taraması her klasörde çağırır): ayarlar ve diller load_details'te okunur
    return GodotGameInfo(root, exe, pck_path, pck, major, label, pck.encrypted)


def load_details(info: GodotGameInfo) -> GodotGameInfo:
    """Proje ayarları, çeviri tabloları ve kaynak dil (bir kez)."""
    if info.loaded or info.encrypted:
        return info
    pck = info.pck
    with pck.opened():
        try:
            info.settings = gf.read_project_binary(pck.read("project.binary")) if "project.binary" in pck.entries else {}
        except (gf.GodotFormatError, OSError, struct_error):
            info.settings = {}
        paths = info.settings.get("internationalization/locale/translations") or \
            info.settings.get("locale/translations") or []
        info.translations = [str(p)[6:] if str(p).startswith("res://") else str(p) for p in paths if isinstance(p, str)]
        info.source_locale = _source_locale(info)
    info.loaded = True
    return info


def _locale_of(info: GodotGameInfo, path: str) -> str:
    if path not in info.locales:
        info.locales[path] = _read_locale(info, path)
    return info.locales[path]


def _read_locale(info: GodotGameInfo, path: str) -> str:
    if path.lower().endswith(".po"):
        m = re.search(r'"Language:\s*([^\\"]+)', info.pck.read(path).decode("utf-8", errors="replace"))
        return m.group(1).strip() if m else ""
    try:
        res = gf.read_resource(info.pck.read(path))
    except (gf.GodotFormatError, KeyError, OSError):
        return ""
    return str(res.get("locale") or "en")


def _source_locale(info: GodotGameInfo) -> str:
    locales = [loc for loc in (_locale_of(info, p) for p in info.translations if p in info.pck.entries) if loc]
    for loc in locales:
        if loc.lower().split("_")[0] == "en":
            return loc
    fallback = str(info.settings.get("internationalization/locale/fallback") or info.settings.get("locale/fallback") or "en")
    if fallback in locales or not locales:
        return fallback
    return locales[0]


def _same_locale(a: str, b: str) -> bool:
    return a.replace("-", "_").lower() == b.replace("-", "_").lower()


# ── Okuma ───────────────────────────────────────────────────────────────────
def _po_messages(text: str) -> Dict[str, str]:
    """msgid → msgstr (boşsa msgid). Bağlamlı (msgctxt) ve çoğul girdiler atlanır."""
    out: Dict[str, str] = {}
    entry: Dict[str, str] = {}
    field_name = ""

    def flush():
        if "msgid" in entry and entry.get("msgid") and "msgctxt" not in entry and "msgid_plural" not in entry:
            out[entry["msgid"]] = entry.get("msgstr") or entry["msgid"]
        entry.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush()
            field_name = ""
            continue
        if line.startswith("#"):
            continue
        m = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+"(.*)"$', line)
        if m:
            if m.group(1) == "msgid" and "msgid" in entry:
                flush()
            field_name = m.group(1).split("[")[0]
            entry[field_name] = _po_unescape(m.group(2))
        elif line.startswith('"') and field_name:
            entry[field_name] = entry.get(field_name, "") + _po_unescape(line[1:-1])
    flush()
    return out


def _po_unescape(s: str) -> str:
    return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")


def _messages_of(info: GodotGameInfo, path: str) -> Dict[str, str]:
    """Anahtarı bilinen bir tablonun bütün girdileri (harf içermeyenler dahil)."""
    if path.lower().endswith(".po"):
        return _po_messages(info.pck.read(path).decode("utf-8", errors="replace"))
    return _plain_messages(gf.read_resource(info.pck.read(path)))


def _plain_messages(res: gf.Resource) -> Dict[str, str]:
    messages = res.get("messages")
    if isinstance(messages, dict):
        return {str(k): str(v) for k, v in messages.items() if isinstance(k, str) and isinstance(v, str)}
    if isinstance(messages, list):                 # Godot 3: [anahtar, değer, anahtar, değer…]
        return {str(messages[i]): str(messages[i + 1]) for i in range(0, len(messages) - 1, 2)}
    return {}


def _has_letters(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", PROTECTED_GODOT.sub("", text)))


def extract_texts(info: GodotGameInfo, log: LogFn = print) -> List[GodotUnit]:
    if info.encrypted:
        return []
    load_details(info)
    with info.pck.opened():
        return _extract(info, log)


def _extract(info: GodotGameInfo, log: LogFn) -> List[GodotUnit]:
    units: List[GodotUnit] = []
    keys_known: List[Callable[[str], bool]] = []
    for path in info.translations:
        if path not in info.pck.entries or not _same_locale(_locale_of(info, path) or "en", info.source_locale):
            continue
        if path.lower().endswith(".po"):
            messages = _po_messages(info.pck.read(path).decode("utf-8", errors="replace"))
            units += [GodotUnit("msg", path, k, v) for k, v in messages.items() if _has_letters(v)]
            keys_known.append(lambda key, m=messages: key in m)
            continue
        try:
            res = gf.read_resource(info.pck.read(path))
        except (gf.GodotFormatError, OSError) as exc:
            log(f"Çeviri tablosu okunamadı: {path}: {exc}")
            continue
        if res.type in ("OptimizedTranslation", "PHashTranslation"):
            if not res.writable:
                log(f"Çeviri tablosu yeniden yazılamıyor (atlandı): {path}")
                continue
            table = gf.optimized_table(res)
            units += [GodotUnit("ot", path, at, msg) for at, msg in table.messages() if _has_letters(msg)]
            keys_known.append(lambda key, t=table: t.lookup(key) is not None)
        elif res.type == "Translation":
            messages = _plain_messages(res)
            units += [GodotUnit("msg", path, k, v) for k, v in messages.items() if _has_letters(v)]
            keys_known.append(lambda key, m=messages: key in m)
    seen = set()
    for path in sorted(info.pck.entries):
        if not path.lower().endswith((".scn", ".tscn")):   # ikili (.scn) ya da metin (.tscn) sahne
            continue
        try:
            data = info.pck.read(path)
            texts = scene_texts(data) if data[:4] == b"RSRC" else text_scene_texts(data.decode("utf-8", "replace"))
        except (gf.GodotFormatError, OSError, struct_error) as exc:
            log(f"Sahne okunamadı (atlandı): {path}: {exc}")
            continue
        for text in texts:
            if text in seen or _KEY_LIKE.match(text) or any(known(text) for known in keys_known):
                continue
            seen.add(text)
            units.append(GodotUnit("ui", path, text, text, "ui"))
    scripts = 0
    for path in sorted(info.pck.entries):
        if not path.lower().endswith((".gd", ".gdc")) or path.startswith(("addons/", ".godot/")):
            continue
        try:
            texts = gscript.script_strings(info.pck.read(path))
        except (gscript.GodotScriptError, OSError, UnicodeDecodeError) as exc:
            log(f"Betik okunamadı (atlandı): {path}: {exc}")
            continue
        for text in texts:
            if text in seen or not gscript.is_display_text(text) or _KEY_LIKE.match(text.strip()) \
                    or any(known(text) for known in keys_known):
                continue
            seen.add(text)
            context = "dialogue" if "\n" in text or len(text) > 40 or text.rstrip()[-1:] in ".!?…。！？" else "ui"
            units.append(GodotUnit("ui", path, text, text, context))
            scripts += 1
    if scripts:
        log(f"Godot betikleri: {scripts} gömülü metin bulundu")
    return units


def scene_texts(data: bytes) -> List[str]:
    """Paketlenmiş sahnedeki (PackedScene) düğümlerin arayüz yazıları."""
    res = gf.read_resource(data)
    if res.type != "PackedScene":
        return []
    bundled = res.get("_bundled")
    if not isinstance(bundled, dict):
        return []
    names, variants, nodes = bundled.get("names") or [], bundled.get("variants") or [], bundled.get("nodes") or []
    count = int(bundled.get("node_count") or 0)
    out, i = [], 0
    for _ in range(count):
        if i + 6 > len(nodes):
            break
        props = nodes[i + 5]
        j = i + 6
        for _p in range(props):
            name_idx, value_idx = nodes[j] & 0xFFFFFF, nodes[j + 1]
            j += 2
            if 0 <= name_idx < len(names) and names[name_idx] in TEXT_PROPS and 0 <= value_idx < len(variants):
                value = variants[value_idx]
                if isinstance(value, str) and value.strip() and _has_letters(value) and value not in out:
                    out.append(value)
        groups = nodes[j] if j < len(nodes) else 0
        i = j + 1 + groups
    return out


_TSCN_PROP = re.compile(r'^([A-Za-z_][\w/]*)\s*=\s*"')


def _tscn_unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def text_scene_texts(text: str) -> List[str]:
    """Metin sahnedeki (.tscn) düğümlerin arayüz yazıları; dizeler birden çok satıra yayılabilir."""
    out: List[str] = []
    lines = text.replace("\r\n", "\n").split("\n")
    in_node = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("["):
            in_node = line.startswith("[node ")
            i += 1
            continue
        m = _TSCN_PROP.match(line)
        if not m:
            i += 1
            continue
        buf, rest = [], line[m.end():]
        while True:
            j, closed = 0, -1
            while j < len(rest):
                if rest[j] == "\\":
                    j += 2
                    continue
                if rest[j] == '"':
                    closed = j
                    break
                j += 1
            if closed >= 0:
                buf.append(rest[:closed])
                break
            buf.append(rest)
            i += 1
            if i >= len(lines):
                break
            rest = "\n" + lines[i]
        value = _tscn_unescape("".join(buf))
        if in_node and m.group(1) in TEXT_PROPS and value.strip() and _has_letters(value) and value not in out:
            out.append(value)
        i += 1
    return out


# ── Yazma ───────────────────────────────────────────────────────────────────
SCRIPT_4 = '''extends Node
# Capri çeviri yaması. Kaldırmak için Capri'de "Orijinale dön"; ya da capri_tr.pck, capri_tr.gd dosyalarını ve
# override.cfg'deki CapriTr satırını sil.
const PATCH := "capri_tr.pck"
const REPLACED := __REPLACED__
const REMOVED := __REMOVED__
const LOCALE := "__LOCALE__"

func _init() -> void:
	var base := OS.get_executable_path().get_base_dir()
	if not ProjectSettings.load_resource_pack(base.path_join(PATCH), true):
		push_warning("Capri: ceviri yamasi yuklenemedi: " + base.path_join(PATCH))
		return
	for path in REPLACED + REMOVED:
		if ResourceLoader.has_cached(path):
			var old = load(path)
			if old is Translation:
				TranslationServer.remove_translation(old)
	for path in REPLACED:
		var fresh = ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE)
		if fresh is Translation:
			TranslationServer.add_translation(fresh)
	var file := FileAccess.open("res://capri_tr/messages.json", FileAccess.READ)
	if file:
		var data = JSON.parse_string(file.get_as_text())
		if data is Dictionary and not data.is_empty():
			var t := Translation.new()
			t.locale = LOCALE
			for key in data:
				t.add_message(key, data[key])
			TranslationServer.add_translation(t)
'''

SCRIPT_3 = '''extends Node
# Capri çeviri yaması. Kaldırmak için Capri'de "Orijinale dön"; ya da capri_tr.pck, capri_tr.gd dosyalarını ve
# override.cfg'deki CapriTr satırını sil.
const PATCH = "capri_tr.pck"
const REPLACED = __REPLACED__
const REMOVED = __REMOVED__
const LOCALE = "__LOCALE__"

func _init():
	var base = OS.get_executable_path().get_base_dir()
	if not ProjectSettings.load_resource_pack(base + "/" + PATCH, true):
		push_warning("Capri: ceviri yamasi yuklenemedi: " + base + "/" + PATCH)
		return
	for path in REPLACED + REMOVED:
		if ResourceLoader.has_cached(path):
			var old = load(path)
			if old is Translation:
				TranslationServer.remove_translation(old)
	for path in REPLACED:
		var fresh = ResourceLoader.load(path, "", true)
		if fresh is Translation:
			TranslationServer.add_translation(fresh)
	var file = File.new()
	if file.open("res://capri_tr/messages.json", File.READ) == OK:
		var data = parse_json(file.get_as_text())
		file.close()
		if typeof(data) == TYPE_DICTIONARY and not data.empty():
			var t = Translation.new()
			t.locale = LOCALE
			for key in data:
				t.add_message(key, data[key])
			TranslationServer.add_translation(t)
'''


def patch_files(info: GodotGameInfo) -> List[Path]:
    return [info.root / PATCH_NAME, info.root / SCRIPT_NAME]


def files_to_backup(info: GodotGameInfo) -> Tuple[List[Path], List[Path]]:
    """(yedeklenecek, Capri'nin oluşturacağı) dosyalar."""
    override = info.root / "override.cfg"
    created = patch_files(info) + ([] if override.is_file() else [override])
    return ([override] if override.is_file() else []), created


def _gd_list(items: List[str]) -> str:
    return "[" + ", ".join(json.dumps("res://" + p, ensure_ascii=False) for p in items) + "]"


def merge_override(text: str, value: str) -> str:
    """override.cfg'ye [autoload] CapriTr="*…" satırını ekler/günceller; diğer ayarlara dokunmaz."""
    lines = text.replace("\r\n", "\n").split("\n") if text else []
    lines = [l for l in lines if not re.match(rf"^\s*{AUTOLOAD_KEY}\s*=", l)]
    entry = f'{AUTOLOAD_KEY}="*{value}"'
    for i, line in enumerate(lines):
        if line.strip() == "[autoload]":
            lines.insert(i + 1, entry)
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[autoload]", "", entry]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_translations(info: GodotGameInfo, translations: Dict[str, str], log: LogFn = print,
                       units: Optional[List[GodotUnit]] = None) -> int:
    """Yamayı yazar; çevrilen birim sayısı. Oyunun dosyaları değişmez. units: analizde çıkarılmış birimler (verilirse
    sahneler yeniden okunmaz)."""
    if info.encrypted:
        raise ValueError("Godot paketi şifreli.")
    load_details(info)
    units = units if units is not None else extract_texts(info, log)
    with info.pck.opened():
        return _write(info, translations, log, units)


def _write(info: GodotGameInfo, translations: Dict[str, str], log: LogFn, units: List[GodotUnit]) -> int:
    files: Dict[str, bytes] = {}
    messages: Dict[str, str] = {}
    replaced, removed = [], []
    written = 0
    by_path: Dict[str, List[GodotUnit]] = {}
    for unit in units:
        by_path.setdefault(unit.path, []).append(unit)
    for path, items in by_path.items():
        kinds = {u.kind for u in items}
        if "ot" in kinds:
            res = gf.read_resource(info.pck.read(path))
            table = gf.optimized_table(res)
            repl = {u.ref: translations[u.original] for u in items
                    if translations.get(u.original) and translations[u.original] != u.original}
            if repl:
                files[path] = gf.write_optimized(res, table.rebuilt(repl))
                replaced.append(path)
                written += len(repl)
        elif "msg" in kinds:
            # Düz tablo: yerine bütün girdileriyle yenisi konur (çevrilmeyenler ve harfsizler özgün metniyle)
            full = _messages_of(info, path)
            new = {k: (translations.get(v) or v) for k, v in full.items()}
            changed = sum(1 for k in full if new[k] != full[k])
            if changed:
                messages.update(new)
                removed.append(path)
                written += changed
        else:
            for u in items:
                target = translations.get(u.original)
                if target and target != u.original:
                    messages[str(u.ref)] = target
                    written += 1
    if not written:
        return 0
    files[MESSAGES_PATH] = json.dumps(messages, ensure_ascii=False, indent=0).encode("utf-8")
    gf.write_pck(info.root / PATCH_NAME, files, info.pck.engine, version=1 if info.major == 3 else 2)
    script = (SCRIPT_3 if info.major == 3 else SCRIPT_4).replace("__REPLACED__", _gd_list(replaced)) \
        .replace("__REMOVED__", _gd_list(removed)).replace("__LOCALE__", info.source_locale.replace('"', ""))
    (info.root / SCRIPT_NAME).write_text(script, encoding="utf-8", newline="\n")
    override = info.root / "override.cfg"
    current = override.read_text(encoding="utf-8", errors="replace") if override.is_file() else ""
    override.write_text(merge_override(current, (info.root / SCRIPT_NAME).resolve().as_posix()), encoding="utf-8",
                        newline="\n")
    check = gf.read_pck(info.root / PATCH_NAME)
    for name, data in files.items():
        if check.read(name) != data:
            raise OSError(f"Yama paketi doğrulanamadı: {name}")
    log(f"Godot yaması yazıldı: {PATCH_NAME} ({len(replaced)} tablo, {len(messages)} metin)")
    return written


def files_stamp_paths(root: Path) -> List[Path]:
    root = Path(root)
    return [p for p in list(root.glob("*.pck")) + list(root.glob("*.exe")) if p.name.lower() != PATCH_NAME]


__all__ = ["GodotGameInfo", "GodotUnit", "detect_godot", "extract_texts", "write_translations", "files_to_backup",
           "scene_texts", "merge_override", "PROTECTED_GODOT", "GODOT_EXTRA_INSTRUCTION", "PATCH_NAME", "SCRIPT_NAME"]
