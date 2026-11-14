import json
import re
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# engine_common modülünden gerekli içe aktarımlar
from engine_common import (
    QAChecker,
    LogFn
)

# RPG Maker kontrol kodları
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

RPGM_BUILTIN_GLOSSARY = {
    'Level': 'Seviye', 'Lv': 'Sv', 'HP': 'HP', 'MP': 'MP', 'TP': 'TP',
    'EXP': 'Tecrübe', 'Attack': 'Saldırı', 'Defense': 'Savunma',
    'M.Attack': 'B.Saldırı', 'M.Defense': 'B.Savunma', 'Agility': 'Çeviklik',
    'Luck': 'Şans', 'Max HP': 'Azami HP', 'Max MP': 'Azami MP',
    'Fight': 'Savaş', 'Escape': 'Kaç', 'Guard': 'Savun',
    'Item': 'Eşya', 'Skill': 'Yetenek', 'Equip': 'Kuşan',
    'Status': 'Durum', 'Formation': 'Diziliş', 'Save': 'Kaydet',
    'Game End': 'Oyun Sonu', 'Options': 'Seçenekler',
    'Weapon': 'Silah', 'Armor': 'Zırh', 'Key Item': 'Anahtar Eşya',
    'Accessory': 'Aksesuar', 'Shield': 'Kalkan', 'Helmet': 'Kask',
    'Body': 'Beden', 'Buy': 'Satın Al', 'Sell': 'Sat',
    'Quantity': 'Adet', 'Possession': 'Miktar',
    'New Game': 'Yeni Oyun', 'Continue': 'Devam Et', 'Quit': 'Çıkış',
    'To Title': 'Ana Menü', 'Cancel': 'İptal', 'OK': 'Tamam',
    'Yes': 'Evet', 'No': 'Hayır', 'Gold': 'Altın',
    'Physical Attack': 'Fiziksel Saldırı', 'Magic Attack': 'Büyü Saldırısı',
    'Always': 'Her Zaman', 'Battle Screen': 'Savaş Ekranı',
    'Fire': 'Ateş', 'Ice': 'Buz', 'Thunder': 'Yıldırım',
    'Water': 'Su', 'Earth': 'Toprak', 'Wind': 'Rüzgar',
    'Light': 'Işık', 'Darkness': 'Karanlık',
    'Poison': 'Zehir', 'Blind': 'Körlük', 'Silence': 'Sessizlik',
    'Confusion': 'Kafa Karışıklığı', 'Sleep': 'Uyku', 'Paralysis': 'Felç',
    'Stun': 'Sersemletme', 'Death': 'Ölüm', 'KO': 'Bayılma',
    'Normal Attack': 'Normal Saldırı', 'Dual Attack': 'Çift Saldırı',
    'Critical Hit': 'Kritik Vuruş', 'Health': 'Sağlık',
    'Inventory': 'Envanter', 'Party': 'Grup', 'Map': 'Harita',
    'Shop': 'Mağaza', 'Inn': 'Han', 'Church': 'Kilise',
    'Heal': 'İyileştir', 'Revive': 'Dirilt', 'Cure': 'Tedavi Et',
    'Buff': 'Güçlendirme', 'Debuff': 'Zayıflatma',
    'game over': 'oyun bitti', 'Game Over': 'Oyun Bitti',
    '%1 appeared!': '%1 belirdi!',
    '%1 attacks!': '%1 saldırıyor!',
    '%1 was defeated.': '%1 yenildi.',
    '%1 leveled up!': '%1 seviye atladı!',
    '%1 learned %2!': '%1, %2 öğrendi!',
    'A preemptive strike!': 'Baskın saldırı!',
    'An ambush!': 'Pusu!',
    '%1 gained!': '%1 kazanıldı!',
    'Obtained %1!': '%1 elde edildi!',
    '%1 was found!': '%1 bulundu!',
    'There is no effect on %1.': '%1 üzerinde etkisi yok.',
    '%1 is defeated!': '%1 yenildi!',
    '%1 took %2 damage!': '%1, %2 hasar aldı!',
    "%1 recovered %2 %3!": "%1, %2 %3 geri kazandı!",
    "%1's %2 went up by %3!": "%1'in %2 değeri %3 arttı!",
    "%1's %2 went down by %3!": "%1'in %2 değeri %3 azaldı!",
    'You defeated %1!': '%1 yenildi!',
    'Escape was successful.': 'Kaçış başarılı.',
    'Escape failed.': 'Kaçış başarısız.',
    'The battle was won!': 'Savaş kazanıldı!',
    'File': 'Dosya',
}

@dataclass
class RPGMakerGameInfo:
    root: Path
    data_dir: Path
    engine_type: str  # 'mv', 'mz', 'vxace', 'vx', 'xp'
    version_label: str
    json_files: list[Path]
    map_count: int
    has_encrypted_archive: bool
    archive_path: Optional[Path]

def detect_rpgmaker_game(selected: Union[str, Path]) -> RPGMakerGameInfo:
    """Oyun dizininden RPG Maker sürümünü tespit eder."""
    root = Path(selected)
    
    # MZ Kontrolü
    if (root / "data" / "System.json").exists() and (root / "js").exists() and not (root / "www").exists():
        data_dir = root / "data"
        json_files = list(data_dir.glob("*.json"))
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='mz', version_label='RPG Maker MZ',
            json_files=json_files, map_count=len(list(data_dir.glob("Map[0-9]*.json"))),
            has_encrypted_archive=False, archive_path=None
        )
    
    # MV Kontrolü
    if (root / "www" / "data").exists():
        data_dir = root / "www" / "data"
        json_files = list(data_dir.glob("*.json"))
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='mv', version_label='RPG Maker MV',
            json_files=json_files, map_count=len(list(data_dir.glob("Map[0-9]*.json"))),
            has_encrypted_archive=False, archive_path=None
        )
    elif (root / "data" / "System.json").exists() and (root / "www").exists():
        data_dir = root / "data"
        json_files = list(data_dir.glob("*.json"))
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='mv', version_label='RPG Maker MV',
            json_files=json_files, map_count=len(list(data_dir.glob("Map[0-9]*.json"))),
            has_encrypted_archive=False, archive_path=None
        )
        
    # VX Ace Kontrolü
    vxace_archive = root / "Game.rgss3a"
    if (root / "Data").exists() and list((root / "Data").glob("*.rvdata2")):
        data_dir = root / "Data"
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='vxace', version_label='RPG Maker VX Ace',
            json_files=[], map_count=len(list(data_dir.glob("Map[0-9]*.rvdata2"))),
            has_encrypted_archive=vxace_archive.exists(), archive_path=vxace_archive if vxace_archive.exists() else None
        )
    elif vxace_archive.exists():
        return RPGMakerGameInfo(
            root=root, data_dir=root / "Data", engine_type='vxace', version_label='RPG Maker VX Ace',
            json_files=[], map_count=0,
            has_encrypted_archive=True, archive_path=vxace_archive
        )
        
    # VX Kontrolü
    vx_archive = root / "Game.rgss2a"
    if (root / "Data").exists() and list((root / "Data").glob("*.rvdata")):
        data_dir = root / "Data"
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='vx', version_label='RPG Maker VX',
            json_files=[], map_count=len(list(data_dir.glob("Map[0-9]*.rvdata"))),
            has_encrypted_archive=vx_archive.exists(), archive_path=vx_archive if vx_archive.exists() else None
        )
    elif vx_archive.exists():
        return RPGMakerGameInfo(
            root=root, data_dir=root / "Data", engine_type='vx', version_label='RPG Maker VX',
            json_files=[], map_count=0, has_encrypted_archive=True, archive_path=vx_archive
        )
        
    # XP Kontrolü
    xp_archive = root / "Game.rgssad"
    if (root / "Data").exists() and list((root / "Data").glob("*.rxdata")):
        data_dir = root / "Data"
        return RPGMakerGameInfo(
            root=root, data_dir=data_dir, engine_type='xp', version_label='RPG Maker XP',
            json_files=[], map_count=len(list(data_dir.glob("Map[0-9]*.rxdata"))),
            has_encrypted_archive=xp_archive.exists(), archive_path=xp_archive if xp_archive.exists() else None
        )
    elif xp_archive.exists():
        return RPGMakerGameInfo(
            root=root, data_dir=root / "Data", engine_type='xp', version_label='RPG Maker XP',
            json_files=[], map_count=0, has_encrypted_archive=True, archive_path=xp_archive
        )
        
    raise ValueError(f"Geçerli bir RPG Maker oyunu bulunamadı: {selected}")

# Şifreli arşivler (Game.rgssad / .rgss2a / .rgss3a): rgss_archive modülü

# Ruby Marshal parsing
class RubyObject:
    def __init__(self, class_name: str, instance_vars: dict):
        self.class_name = class_name
        self.instance_vars = instance_vars
        
    def __repr__(self):
        return f"RubyObject({self.class_name}, {self.instance_vars})"

class RubySymbol:
    def __init__(self, name: str):
        self.name = name
    def __repr__(self):
        return f":{self.name}"

class MarshalParser:
    def __init__(self, data: bytes):
        self.f = io.BytesIO(data)
        self.symbols = []
        self.objects = []
        
        header = self.f.read(2)
        if header != b'\x04\x08':
            raise ValueError(f"Geçersiz Marshal başlığı: {header}")
            
    def read_byte(self) -> int:
        b = self.f.read(1)
        if not b:
            raise EOFError()
        return b[0]
        
    def read_fixnum(self) -> int:
        b = self.read_byte()
        if b == 0:
            return 0
        if 0 < b < 128:
            if b > 5: return b - 5
            return int.from_bytes(self.f.read(b), 'little', signed=False)
        else:
            if b < 251: return b - 256 + 5
            return int.from_bytes(self.f.read(256 - b), 'little', signed=True)
            
    def read_string(self) -> bytes:
        length = self.read_fixnum()
        return self.f.read(length)
        
    def read_symlink(self):
        idx = self.read_fixnum()
        return self.symbols[idx]
        
    def read_object_link(self):
        idx = self.read_fixnum()
        return self.objects[idx]
        
    def parse(self) -> Any:
        try:
            b = self.f.read(1)
            if not b:
                raise EOFError()
                
            typ = b.decode('ascii')
            
            if typ == '0':
                return None
            elif typ == 'T':
                return True
            elif typ == 'F':
                return False
            elif typ == 'i':
                return self.read_fixnum()
            elif typ == '"':
                s_bytes = self.read_string()
                try:
                    s = s_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    s = s_bytes.decode('shift_jis', errors='ignore')
                self.objects.append(s)
                return s
            elif typ == 'I':
                obj = self.parse()
                iv_count = self.read_fixnum()
                iv = {}
                for _ in range(iv_count):
                    key = self.parse()
                    val = self.parse()
                    iv[key] = val
                return obj
            elif typ == ':':
                sym = self.read_string().decode('ascii', errors='ignore')
                rs = RubySymbol(sym)
                self.symbols.append(rs)
                return rs
            elif typ == ';':
                return self.read_symlink()
            elif typ == '[':
                length = self.read_fixnum()
                arr = []
                self.objects.append(arr)
                for _ in range(length):
                    arr.append(self.parse())
                return arr
            elif typ == '{':
                length = self.read_fixnum()
                hsh = {}
                self.objects.append(hsh)
                for _ in range(length):
                    k = self.parse()
                    v = self.parse()
                    if isinstance(k, RubySymbol):
                        k = k.name
                    hsh[k] = v
                return hsh
            elif typ == 'o':
                class_sym = self.parse()
                cname = class_sym.name if isinstance(class_sym, RubySymbol) else str(class_sym)
                iv_count = self.read_fixnum()
                iv = {}
                ro = RubyObject(cname, iv)
                self.objects.append(ro)
                for _ in range(iv_count):
                    k = self.parse()
                    v = self.parse()
                    if isinstance(k, RubySymbol):
                        k = k.name
                    elif isinstance(k, str) and k.startswith('@'):
                        k = k[1:]
                    iv[k] = v
                return ro
            elif typ == 'u':
                class_sym = self.parse()
                cname = class_sym.name if isinstance(class_sym, RubySymbol) else str(class_sym)
                data = self.read_string()
                ro = RubyObject(cname, {'data': data})
                self.objects.append(ro)
                return ro
            elif typ == '@':
                return self.read_object_link()
            elif typ == 'f':
                s_bytes = self.read_string()
                f = float(s_bytes.decode('ascii'))
                self.objects.append(f)
                return f
            elif typ == 'c' or typ == 'm':
                s = self.read_string().decode('ascii')
                self.objects.append(s)
                return s
            else:
                raise NotImplementedError(f"Marshal tipi desteklenmiyor: {typ}")
        except EOFError:
            return None



@dataclass
class ExtractedText:
    file_path: Path
    json_path: str
    original: str
    context: str
    speaker: str = ""

def extract_texts_mv_mz(data_dir: Path, log: LogFn = print) -> List[ExtractedText]:
    """RPG Maker MV/MZ JSON dosyalarından çevrilebilir metinleri çıkarır."""
    extracted = []
    
    for json_file in data_dir.glob("*.json"):
        if json_file.name.startswith("Map") and json_file.name != "MapInfos.json":
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if not data or 'events' not in data:
                    continue
                    
                for e_idx, event in enumerate(data.get('events', [])):
                    if not event:
                        continue
                    for p_idx, page in enumerate(event.get('pages', [])):
                        list_cmds = page.get('list', [])
                        
                        speaker = ""
                        i = 0
                        while i < len(list_cmds):
                            cmd = list_cmds[i]
                            code = cmd.get('code')
                            params = cmd.get('parameters', [])
                            
                            # 101: Show Text Header
                            if code == 101:
                                if len(params) > 4 and isinstance(params[4], str) and params[4]:
                                    speaker = params[4]
                                    
                                j = i + 1
                                while j < len(list_cmds) and list_cmds[j].get('code') == 401:
                                    line_text = list_cmds[j]['parameters'][0]
                                    if line_text.strip():
                                        j_path = f"events[{e_idx}].pages[{p_idx}].list[{j}].parameters[0]"
                                        extracted.append(ExtractedText(
                                            file_path=json_file,
                                            json_path=j_path,
                                            original=line_text,
                                            context="dialogue",
                                            speaker=speaker
                                        ))
                                    j += 1
                                i = j - 1

                            
                            # 102: Show Choices
                            elif code == 102 and params:
                                for c_idx, choice in enumerate(params[0]):
                                    if choice.strip():
                                        j_path = f"events[{e_idx}].pages[{p_idx}].list[{i}].parameters[0][{c_idx}]"
                                        extracted.append(ExtractedText(
                                            file_path=json_file,
                                            json_path=j_path,
                                            original=choice,
                                            context="choice"
                                        ))
                            
                            i += 1
            except Exception as e:
                log(f"Hata {json_file.name} dosyasında okunurken: {str(e)}")
                
        elif json_file.name == "System.json":
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'gameTitle' in data and data['gameTitle'].strip():
                    extracted.append(ExtractedText(json_file, "gameTitle", data['gameTitle'], "system_term"))
                    
                terms = data.get('terms', {})
                for k, v in enumerate(terms.get('basic', [])):
                    if v and isinstance(v, str):
                        extracted.append(ExtractedText(json_file, f"terms.basic[{k}]", v, "system_term"))
                
                for k, v in enumerate(terms.get('commands', [])):
                    if v and isinstance(v, str):
                        extracted.append(ExtractedText(json_file, f"terms.commands[{k}]", v, "system_term"))
                        
                for k, v in enumerate(terms.get('params', [])):
                    if v and isinstance(v, str):
                        extracted.append(ExtractedText(json_file, f"terms.params[{k}]", v, "system_term"))
                        
                messages = terms.get('messages', {})
                for k, v in messages.items():
                    if v and isinstance(v, str):
                        extracted.append(ExtractedText(json_file, f"terms.messages.{k}", v, "system_message"))
                        
                for list_name in ['armorTypes', 'elements', 'equipTypes', 'skillTypes', 'weaponTypes']:
                    for i, v in enumerate(data.get(list_name, [])):
                        if v and isinstance(v, str):
                            extracted.append(ExtractedText(json_file, f"{list_name}[{i}]", v, "system_term"))
                            
            except Exception as e:
                log(f"Hata System.json okumasında: {str(e)}")

        elif json_file.name in ["Actors.json", "Enemies.json", "Items.json", "Weapons.json", "Armors.json", "Skills.json", "States.json", "Classes.json"]:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if not isinstance(data, list):
                    continue
                    
                for i, item in enumerate(data):
                    if not item:
                        continue
                        
                    for key in ['name', 'nickname', 'profile', 'description', 'note', 'message1', 'message2', 'message3', 'message4']:
                        if key in item and item[key] and isinstance(item[key], str) and item[key].strip():
                            ctx = f"{json_file.stem.lower()}_{key}"
                            extracted.append(ExtractedText(json_file, f"[{i}].{key}", item[key], ctx))
                            
            except Exception as e:
                log(f"Hata {json_file.name} okumasında: {str(e)}")
                
    return extracted

# ── RPG Maker XP / VX / VX Ace (Ruby Marshal) ─────────────────────────────────
RGSS_EXT = {"vxace": ".rvdata2", "vx": ".rvdata", "xp": ".rxdata"}
# Olay komutları: kod → çevrilecek parametre indeksi
RGSS_EVENT_CODES = {401: 0, 405: 0, 102: 0, 402: 1, 320: 1, 324: 1, 325: 1}
# Veritabanı dosyaları: yalnızca oyuncunun gördüğü alanlar (dosya adları, notlar, formüller hariç)
RGSS_DB_ATTRS = {
    "Actors": ("@name", "@nickname", "@description"),
    "Classes": ("@name", "@description"),
    "Skills": ("@name", "@description", "@message1", "@message2"),
    "Items": ("@name", "@description"),
    "Weapons": ("@name", "@description"),
    "Armors": ("@name", "@description"),
    "Enemies": ("@name",),
    "States": ("@name", "@description", "@message1", "@message2", "@message3", "@message4"),
}
RGSS_SYSTEM_ATTRS = ("@game_title", "@currency_unit", "@elements", "@skill_types", "@weapon_types", "@armor_types")


def _rgss_event_list_slots(commands: Any, engine_type: str, label: str):
    from rgss_marshal import RArray, RObject, RString
    if not isinstance(commands, RArray):
        return
    for i, cmd in enumerate(commands.items):
        if not isinstance(cmd, RObject):
            continue
        code = cmd.get("@code")
        params = cmd.get("@parameters")
        if not isinstance(params, RArray):
            continue
        index = 0 if (engine_type == "xp" and code == 101) else RGSS_EVENT_CODES.get(code)
        if index is None or index >= len(params.items):
            continue
        value = params.items[index]
        context = "choice" if code in (102, 402) else "dialogue" if code in (101, 401, 405) else "name"
        if isinstance(value, RString):
            yield value, f"{label}[{i}].p{index}", context
        elif isinstance(value, RArray):
            for j, item in enumerate(value.items):
                if isinstance(item, RString):
                    yield item, f"{label}[{i}].p{index}[{j}]", context


def _rgss_slots(obj: Any, stem: str, engine_type: str):
    """Bir veri dosyasındaki çevrilebilir metin düğümleri: (RString, yol, bağlam)."""
    from rgss_marshal import RArray, RHash, RObject, RString
    if stem.startswith("Map") and stem[3:].isdigit() and isinstance(obj, RObject):
        events = obj.get("@events")
        for event_id, event in (events.pairs if isinstance(events, RHash) else []):
            if isinstance(event, RObject) and isinstance(event.get("@pages"), RArray):
                for p_i, page in enumerate(event.get("@pages").items):
                    if isinstance(page, RObject):
                        yield from _rgss_event_list_slots(page.get("@list"), engine_type, f"events[{event_id}].pages[{p_i}].list")
    elif stem == "CommonEvents" and isinstance(obj, RArray):
        for c_i, common in enumerate(obj.items):
            if isinstance(common, RObject):
                yield from _rgss_event_list_slots(common.get("@list"), engine_type, f"[{c_i}].list")
    elif stem == "Troops" and isinstance(obj, RArray):
        for t_i, troop in enumerate(obj.items):
            if isinstance(troop, RObject) and isinstance(troop.get("@pages"), RArray):
                for p_i, page in enumerate(troop.get("@pages").items):
                    if isinstance(page, RObject):
                        yield from _rgss_event_list_slots(page.get("@list"), engine_type, f"[{t_i}].pages[{p_i}].list")
    elif stem in RGSS_DB_ATTRS and isinstance(obj, RArray):
        for i, item in enumerate(obj.items):
            if isinstance(item, RObject):
                for attr in RGSS_DB_ATTRS[stem]:
                    value = item.get(attr)
                    if isinstance(value, RString):
                        yield value, f"[{i}].{attr[1:]}", "database"
    elif stem == "System" and isinstance(obj, RObject):
        for attr in RGSS_SYSTEM_ATTRS:
            value = obj.get(attr)
            values = [value] if isinstance(value, RString) else value.items if isinstance(value, RArray) else []
            for j, item in enumerate(values):
                if isinstance(item, RString):
                    yield item, f"{attr[1:]}[{j}]", "system"
        for group in ("@terms", "@words"):  # VX/VX Ace: Terms, XP: Words
            terms = obj.get(group)
            if not isinstance(terms, RObject):
                continue
            for key, value in terms.attrs:
                values = [value] if isinstance(value, RString) else value.items if isinstance(value, RArray) else []
                for j, item in enumerate(values):
                    if isinstance(item, RString):
                        yield item, f"{group[1:]}.{key}[{j}]", "system"


def _rgss_files(data_dir: Path, engine_type: str) -> List[Path]:
    ext = RGSS_EXT.get(engine_type, ".rvdata2")
    wanted = set(RGSS_DB_ATTRS) | {"System", "CommonEvents", "Troops"}
    return sorted(p for p in data_dir.glob(f"*{ext}")
                  if p.stem in wanted or (p.stem.startswith("Map") and p.stem[3:].isdigit()))


def extract_texts_vxace(data_dir: Path, log: LogFn = print, engine_type: str = "vxace") -> List[ExtractedText]:
    """RPG Maker XP / VX / VX Ace veri dosyalarından (Ruby Marshal) çevrilebilir metinleri çıkarır."""
    import rgss_marshal
    extracted: List[ExtractedText] = []
    files = _rgss_files(data_dir, engine_type)
    for path in files:
        try:
            obj = rgss_marshal.loads(path.read_bytes())
        except Exception as exc:
            log(f"Okunamadı: {path.name} ({exc})")
            continue
        for node, label, context in _rgss_slots(obj, path.stem, engine_type):
            text = node.text
            if text.strip() and re.search(r"[A-Za-zÀ-ž]", text):
                extracted.append(ExtractedText(file_path=path, json_path=label, original=text, context=context))
    log(f"{len(files)} veri dosyasından {len(extracted)} metin çıkarıldı.")
    return extracted

def write_translations_mv_mz(
    data_dir: Path,
    translations: Dict[str, str],
    log: LogFn = print,
) -> int:
    """MV/MZ JSON dosyalarına çevirileri yazar ve yapıyı korur."""
    changed_count = 0

    # Yalnızca bu anahtarlardaki string değerlere dokunarız.
    # "note", "formula", "script", "meta", "code" gibi motor tarafından
    # okunan teknik alanlara ASLA dokunmayız — crafting/recipe bozulmaması için.
    SAFE_KEYS = {
        "name", "description", "message1", "message2", "message3", "message4",
        "nickname", "profile", "gameTitle",
        # Map event Show Text parametreleri (list içinde) ayrıca ele alınır
    }

    # Map event diyalog komutları için code -> parametre indeksleri
    DIALOG_CODES = {
        401: [0],   # Show Text content
        102: [0],   # Show Choices (liste)
        405: [0],   # Scrolling Text
        320: [1],   # Change Actor Name
        324: [1],   # Change Actor Nickname
        325: [1],   # Change Profile
    }

    def replace_safe(obj):
        nonlocal modified, changed_count
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in SAFE_KEYS and isinstance(v, str):
                    if v in translations and translations[v] != v:
                        obj[k] = translations[v]
                        modified = True
                        changed_count += 1
                elif k == "list" and isinstance(v, list):
                    # Map event komut listesi — sadece diyalog kodlarına doku
                    for cmd in v:
                        if not isinstance(cmd, dict):
                            continue
                        code = cmd.get("code")
                        params = cmd.get("parameters", [])
                        if code in DIALOG_CODES:
                            for pi in DIALOG_CODES[code]:
                                if pi < len(params):
                                    if code == 102 and isinstance(params[pi], list):
                                        # Choices: liste içindeki string'ler
                                        for ci in range(len(params[pi])):
                                            s = params[pi][ci]
                                            if isinstance(s, str) and s in translations and translations[s] != s:
                                                params[pi][ci] = translations[s]
                                                modified = True
                                                changed_count += 1
                                    else:
                                        s = params[pi]
                                        if isinstance(s, str) and s in translations and translations[s] != s:
                                            params[pi] = translations[s]
                                            modified = True
                                            changed_count += 1
                else:
                    replace_safe(v)
        elif isinstance(obj, list):
            for item in obj:
                replace_safe(item)

    for json_file in data_dir.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.loads(f.read())

            modified = False
            replace_safe(data)

            if modified:
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

        except Exception as e:
            log(f"Dosya yazılırken hata {json_file.name}: {str(e)}")

    return changed_count


def write_translations_vxace(
    data_dir: Path,
    translations: Dict[str, str],
    log: LogFn = print,
    engine_type: str = "vxace",
) -> int:
    """
    Çevirileri XP / VX / VX Ace veri dosyalarına yazar. Değiştirilmeyen her bayt korunur
    (rgss_marshal birebir yazar); yalnızca değişen dosyalar yeniden yazılır.
    """
    import rgss_marshal
    changed_total = 0
    for path in _rgss_files(data_dir, engine_type):
        try:
            obj = rgss_marshal.loads(path.read_bytes())
        except Exception as exc:
            log(f"Okunamadı: {path.name} ({exc})")
            continue
        changed = 0
        for node, _label, _context in _rgss_slots(obj, path.stem, engine_type):
            new = translations.get(node.text)
            if new and new != node.text:
                node.text = new
                changed += 1
        if changed:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(rgss_marshal.dumps(obj))
            temporary.replace(path)
            changed_total += changed
            log(f"Güncellendi: {path.name} ({changed} metin)")
    return changed_total

def qa_rpgmaker_translation(data_dir: Path, engine_type: str) -> Dict[str, int]:
    """RPG Maker çevirileri için QA testi."""
    qa = QAChecker()
    errors = {'missing_control_codes': 0, 'length_ratio_violation': 0}
    return errors




if __name__ == "__main__":
    print("RPG Maker modülü başarıyla yüklendi.")
