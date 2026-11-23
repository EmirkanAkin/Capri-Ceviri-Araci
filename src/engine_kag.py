"""
Capri — TyranoScript ve KiriKiri oyunları
========================================
Algılama, senaryo metinlerini okuma ve çeviriyi geri yazma. Senaryo dili için bkz. kag_script, arşivler için
bkz. archives.

TyranoScript (HTML5): senaryo data/scenario/*.ks. Oyun klasör olarak, NW.js paketi (package.nw ya da exe'nin
sonuna eklenmiş zip) veya Electron paketi (resources/app.asar) içinde olabilir.
KiriKiri (2 / Z): senaryo .ks dosyaları data.xp3 (ve varsa patch.xp3…) arşivlerinde ya da açık data/ klasöründe.
Şifreli xp3 arşivleri (oyuna özel şifre) okunamaz; bu durum anlaşılır bir mesajla bildirilir.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import kag_script
from archives import AsarContainer, Container, DirContainer, Xp3Archive, Xp3Container, ZipContainer

LogFn = Callable[[str], None]
PROTECTED_KAG = kag_script.PROTECTED_KAG
KAG_EXTRA_INSTRUCTION = (
    "Satırlardaki [p], [l], [r], [cm], [font ...], [emb ...] gibi köşeli parantezli etiketleri aynen ve aynı sırayla "
    "koru; yeni köşeli parantez ekleme. Satırı bölme. Japonca isimleri Latin harflerle yaz (ör. あかね → Akane)."
)


@dataclass
class KagGameInfo:
    root: Path
    dialect: str                     # tyrano | kirikiri
    container: Container
    scenario: List[str]              # kap içindeki .ks dosyaları
    label: str
    encrypted: bool = False


# ── Algılama ────────────────────────────────────────────────────────────────
def _tyrano_dir(base: Path) -> bool:
    return (base / "data" / "scenario").is_dir() and ((base / "tyrano").is_dir() or (base / "index.html").is_file())


def _scenario_names(names: List[str], dialect: str) -> List[str]:
    if dialect == "tyrano":
        found = [n for n in names if n.lower().endswith(".ks") and "data/scenario/" in ("/" + n.lower())]
    else:
        found = [n for n in names if n.lower().endswith(".ks")]
    return sorted(found)


def _nw_exe(root: Path) -> Optional[Path]:
    """Sonuna zip eklenmiş (NW.js) ve içinde TyranoScript senaryosu olan exe."""
    for exe in sorted(root.glob("*.exe"))[:6]:
        try:
            if exe.stat().st_size < 1 << 20 or not zipfile.is_zipfile(exe):
                continue
            with zipfile.ZipFile(exe) as zf:
                if any(n.lower().startswith("data/scenario/") and n.lower().endswith(".ks") for n in zf.namelist()):
                    return exe
        except (OSError, zipfile.BadZipFile):
            continue
    return None


def detect_tyrano(root: Path) -> Optional[KagGameInfo]:
    root = Path(root)
    candidates: List[Tuple[str, Callable[[], Container]]] = []
    for base in (root, root / "resources" / "app", root / "package.nw", root / "www"):
        if base.is_dir() and _tyrano_dir(base):
            candidates.append((f"klasör ({base.relative_to(root).as_posix() or '.'})", lambda b=base: DirContainer(b)))
    asar = root / "resources" / "app.asar"
    if asar.is_file():
        candidates.append(("Electron paketi (app.asar)", lambda: AsarContainer(asar)))
    nw = root / "package.nw"
    if nw.is_file() and zipfile.is_zipfile(nw):
        candidates.append(("NW.js paketi (package.nw)", lambda: ZipContainer(nw)))
    for label, make in candidates:
        try:
            container = make()
            scenario = _scenario_names(container.names(), "tyrano")
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
        if scenario:
            return KagGameInfo(root, "tyrano", container, scenario, f"TyranoScript · {label}")
    exe = _nw_exe(root)
    if exe:
        container = ZipContainer(exe)
        return KagGameInfo(root, "tyrano", container, _scenario_names(container.names(), "tyrano"),
                           f"TyranoScript · NW.js ({exe.name} içinde)")
    return None


def _xp3_order(root: Path) -> List[Path]:
    """KiriKiri'nin bindirme sırası: data.xp3, sonra patch.xp3, patch2.xp3, … (sonraki öncekini ezer)."""
    archives = [root / "data.xp3"] if (root / "data.xp3").is_file() else []
    patches = []
    for p in root.glob("patch*.xp3"):
        m = re.fullmatch(r"patch(\d*)\.xp3", p.name.lower())
        if m:
            patches.append((int(m.group(1) or 1), p))
    return archives + [p for _n, p in sorted(patches)]


def _looks_like_text(raw: bytes) -> bool:
    try:
        text, _enc = kag_script.decode(raw[:4096])
    except Exception:
        return False
    if not text:
        return True
    bad = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t") + text.count("�")
    return bad / max(1, len(text)) < 0.02


def detect_kirikiri(root: Path) -> Optional[KagGameInfo]:
    root = Path(root)
    if not any(root.glob("*.exe")):
        return None
    archives = _xp3_order(root)
    loose = root / "data"
    if archives:
        try:
            container = Xp3Container(root, archives)
        except (OSError, ValueError, KeyError) as exc:
            return KagGameInfo(root, "kirikiri", DirContainer(root), [], f"KiriKiri · arşiv okunamadı ({exc})", True)
        scenario = _scenario_names(container.names(), "kirikiri")
        if not scenario and not any(n.lower().endswith((".tjs", ".ks")) for n in container.names()):
            return None
        encrypted = False
        probe = next(iter(scenario), None) or next((n for n in container.names() if n.lower().endswith(".tjs")), None)
        if probe:
            try:
                encrypted = not _looks_like_text(container.read(probe))
            except (OSError, ValueError, Exception):
                encrypted = True
        return KagGameInfo(root, "kirikiri", container, scenario, "KiriKiri · " + ", ".join(p.name for p in archives),
                           encrypted)
    if loose.is_dir() and ((loose / "startup.tjs").is_file() or any(loose.rglob("*.ks"))):
        container = DirContainer(loose)
        return KagGameInfo(root, "kirikiri", container, _scenario_names(container.names(), "kirikiri"),
                           "KiriKiri · açık data klasörü")
    return None


def detect_kag_game(selected: Union[str, Path]) -> Optional[KagGameInfo]:
    root = Path(selected)
    if not root.is_dir():
        return None
    return detect_tyrano(root) or detect_kirikiri(root)


# ── Okuma ───────────────────────────────────────────────────────────────────
@dataclass
class ScenarioFile:
    name: str
    text: str
    encoding: str


def load_scenario(info: KagGameInfo, log: LogFn = print) -> List[ScenarioFile]:
    files = []
    for name in info.scenario:
        try:
            text, encoding = kag_script.decode(info.container.read(name))
        except Exception as exc:
            log(f"Okunamadı: {name}: {exc}")
            continue
        files.append(ScenarioFile(name, text, encoding))
    return files


def extract_texts(info: KagGameInfo, log: LogFn = print, files: Optional[List[ScenarioFile]] = None
                  ) -> List[kag_script.KagText]:
    if info.encrypted:
        return []
    files = files if files is not None else load_scenario(info, log)
    ids = kag_script.character_ids(f.text for f in files) if info.dialect == "tyrano" else {}
    units: List[kag_script.KagText] = []
    for f in files:
        units += kag_script.extract(f.text, f.name, info.dialect, ids)
    return units


def character_names(info: KagGameInfo, log: LogFn = print) -> List[str]:
    """Karakter adları: TyranoScript'te chara_new jname / #Ad satırları, KiriKiri'de 【Ad】 satırları."""
    names: List[str] = []
    for unit in extract_texts(info, log):
        if unit.context == "name" and unit.original not in names:
            names.append(unit.original)
    return names


# ── Yazma ───────────────────────────────────────────────────────────────────
def files_to_backup(info: KagGameInfo) -> Tuple[List[Path], List[Path]]:
    """(yedeklenecek dosyalar, Capri'nin oluşturacağı dosyalar)."""
    if isinstance(info.container, Xp3Container):
        return [], info.container.created_files()
    if isinstance(info.container, DirContainer):
        return info.container.files(info.scenario), []
    return info.container.touched_files(), []


def write_translations(info: KagGameInfo, translations: Dict[str, str], log: LogFn = print) -> int:
    """Çevirileri senaryo dosyalarına yazar; yazılan birim sayısı. Dosyalar her seferinde özgün hâlinden üretilir
    (yedek geri yüklendikten sonra çağrılmalıdır), değişmeyen dosyalar yazılmaz."""
    if info.encrypted:
        raise ValueError("Arşiv şifreli; KiriKiri senaryosu okunamıyor.")
    files = load_scenario(info, log)
    ids = kag_script.character_ids(f.text for f in files) if info.dialect == "tyrano" else {}
    changes: Dict[str, bytes] = {}
    total = 0
    for f in files:
        units = kag_script.extract(f.text, f.name, info.dialect, ids)
        new, changed = kag_script.apply(f.text, units, translations)
        if changed:
            changes[f.name] = kag_script.encode(new, f.encoding, info.dialect)
            total += changed
    if not changes:
        return 0
    info.container.write(changes, log)
    log(f"{len(changes)} senaryo dosyası yazıldı ({total} satır).")
    return total


def files_stamp_paths(root: Path) -> List[Path]:
    """Oyun güncellemesi algılama için ana dosyalar (Capri'nin yazdığı yama arşivi hariç)."""
    root = Path(root)
    files = list(root.glob("*.xp3")) + list(root.glob("*.exe")) + list(root.glob("package.nw"))
    files += list((root / "resources").glob("app.asar"))
    for base in (root / "data" / "scenario", root / "resources" / "app" / "data" / "scenario", root / "data"):
        if base.is_dir():
            files += list(base.glob("*.ks"))
    return files


__all__ = ["KagGameInfo", "detect_kag_game", "detect_tyrano", "detect_kirikiri", "extract_texts", "load_scenario",
           "write_translations", "files_to_backup", "character_names", "PROTECTED_KAG", "KAG_EXTRA_INSTRUCTION"]
