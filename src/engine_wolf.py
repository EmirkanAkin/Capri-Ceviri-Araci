"""
Capri — WOLF RPG Editor oyunları
===============================
Haritalardaki (MapData/*.mps) ve ortak olaylardaki (BasicData/CommonEvent.dat) konuşmalar, seçenekler ve metin
resimleri ile veritabanlarındaki (DataBase, CDataBase) eşya/beceri/karakter adları, açıklamalar ve savaş mesajları
çevrilir. Dağıtılan oyunların çoğu verisini şifreli Data.wolf arşivinde tutar: analizde yalnızca metin dosyaları geçici
bir klasöre açılır, çeviride arşiv oyun klasörüne açılıp yedeklenir (wolf_archive). WOLF Pro arşivleri açılamaz.
Dosya biçimi için bkz. wolf_formats.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import wolf_archive as wa
import wolf_formats as wf
from fileio import atomic_write

LogFn = Callable[[str], None]
# \cself[1] \c[2] \f[20] \i[3] \s[0] \v[5] \E \- … ve satır başındaki yüz kodu (@1)
PROTECTED_WOLF = re.compile(r"\\[A-Za-z]+\[[^\]\r\n]{0,40}\]|\\[A-Za-z]+\d*|\\[-<>.^|!\\]|^@\d+|<[A-Z]{1,3}>", re.MULTILINE)
WOLF_EXTRA_INSTRUCTION = ("\\cself[1], \\c[2], \\f[20] gibi ters bölüyle başlayan kodları ve satır başındaki @1 gibi "
                          "yüz kodlarını aynen koru. Satır sonlarını (\\n) mümkün olduğunca koru.")


@dataclass
class WolfText:
    file: str
    original: str
    context: str


DATABASES = ("DataBase", "CDataBase")       # SysDatabase (değişken adları, dosya listeleri) çevrilmez


@dataclass
class WolfGameInfo:
    root: Path
    data_dir: Path
    files: List[Tuple[str, str]] = field(default_factory=list)      # (tür, data_dir'e göre yol)
    archived: bool = False
    utf8: Optional[bool] = None
    encrypted_files: List[str] = field(default_factory=list)
    label: str = "WOLF RPG"
    parsed: Dict[str, Tuple[Tuple[int, int], wf.WolfDoc]] = field(default_factory=dict)   # yol → ((boy, mtime), belge)
    archives: List[str] = field(default_factory=list)               # oyun köküne göre .wolf yolları
    archive_label: str = ""                                         # ör. "WOLF 3.50"
    archive_error: str = ""                                         # açılamıyorsa nedeni
    file_stems: Optional[set] = None                                # oyundaki dosya adları (veritabanında korunur)

    @property
    def archive_supported(self) -> bool:
        return bool(self.archives) and not self.archive_error


def _scan(root: Path) -> Optional[WolfGameInfo]:
    data = root / "Data"
    basic, maps = data / "BasicData", data / "MapData"
    if not (basic.is_dir() and ((basic / "CommonEvent.dat").is_file() or (basic / "Game.dat").is_file())):
        return None
    info = WolfGameInfo(root, data)
    if (basic / "CommonEvent.dat").is_file():
        info.files.append(("common", "BasicData/CommonEvent.dat"))
    for stem in DATABASES:
        if (basic / f"{stem}.dat").is_file() and (basic / f"{stem}.project").is_file():
            info.files.append(("db", f"BasicData/{stem}.dat"))
    for path in sorted(maps.glob("*.mps")) if maps.is_dir() else []:
        info.files.append(("map", f"MapData/{path.name}"))
    return info


def detect_wolf(selected: Union[str, Path]) -> Optional[WolfGameInfo]:
    root = Path(selected)
    if not root.is_dir() or not any(root.glob("*.exe")):
        return None
    # Arşiv klasörün yerine geçer: BasicData.wolf varken açık BasicData klasörü motor tarafından okunmaz
    archives = [p for p in wa.find_archives(root) if p.stem.lower() in ("data", "basicdata", "mapdata")]
    info = None if archives else _scan(root)
    if info:
        return info
    if not archives:
        return None
    info = WolfGameInfo(root, root / "Data", [], True)
    info.archives = [p.relative_to(root).as_posix() for p in wa.find_archives(root)]
    state = wa.probe(root)
    info.archive_label = str(state["label"])
    info.archive_error = str(state["reason"])
    info.label = f"WOLF RPG · şifreli arşiv ({info.archive_label})" if info.archive_supported \
        else "WOLF RPG · açılamayan şifreli arşiv"
    return info


def _stems(info: WolfGameInfo) -> set:
    """Oyundaki dosya adları (uzantısız). Veritabanında bir dosya adıyla birebir aynı olan değer, oyun onu dosya yolu
    kurmak için kullanabileceğinden çevrilmez."""
    if info.file_stems is None:
        stems = set()
        if info.data_dir.is_dir():
            stems |= {p.stem for p in info.data_dir.rglob("*") if p.is_file()}
        info.file_stems = stems
    return info.file_stems


def _docs(info: WolfGameInfo, log: LogFn) -> List[Tuple[str, str, bytes, wf.WolfDoc]]:
    """Dosyaları çözümler. Analizde çözümlenen belge, dosya (boy + değişme zamanı) değişmediyse yazmada yeniden
    kullanılır; LZ4 açma ve çözümleme iki kez yapılmaz."""
    docs = []
    for kind, rel in info.files:
        path = info.data_dir / rel
        st = path.stat()
        stamp = (st.st_size, st.st_mtime_ns)
        project = path.with_suffix(".project") if kind == "db" else None
        if project is not None:
            pst = project.stat()
            stamp = stamp + (pst.st_size, pst.st_mtime_ns)
        held = info.parsed.get(rel)
        if held and held[0] == stamp:
            doc, data = held[1], None
        else:
            data = path.read_bytes()
            try:
                doc = wf.parse(kind, data, project.read_bytes() if project is not None else b"")
            except (wf.WolfFormatError, OSError) as exc:
                log(f"WOLF dosyası okunamadı (atlandı): {rel}: {exc}")
                continue
            if kind == "db":
                doc.total = len(doc.slots)
                stems = _stems(info)
                doc.slots = [s for s in doc.slots if s.text.strip() not in stems]
            info.parsed[rel] = (stamp, doc)
        if doc.encrypted:
            if rel not in info.encrypted_files:
                info.encrypted_files.append(rel)
            continue
        if info.utf8 is None:
            info.utf8 = doc.utf8
        docs.append((kind, rel, data, doc))
    return docs


def extract_texts(info: WolfGameInfo, log: LogFn = print) -> List[WolfText]:
    if info.archived:
        return preview_texts(info, log) if info.archive_supported else []
    out = []
    for _kind, rel, _data, doc in _docs(info, log):
        out += [WolfText(rel, s.text, s.context) for s in doc.slots if re.search(r"[^\W\d_]", PROTECTED_WOLF.sub("", s.text))]
    version = "3.x (UTF-8)" if info.utf8 else "2.x (Shift-JIS)" if info.utf8 is False else ""
    info.label = "WOLF RPG " + version if version else "WOLF RPG"
    return out


def preview_texts(info: WolfGameInfo, log: LogFn = print, workdir: Optional[Path] = None) -> List[WolfText]:
    """Arşivli oyun: metin dosyaları geçici bir klasöre açılıp okunur; oyuna dokunulmaz."""
    import shutil
    import tempfile
    tmp = Path(workdir or tempfile.mkdtemp(prefix="capri_wolf_"))
    try:
        wa.extract_data(info.root, tmp)
        (tmp / "Game.exe").write_bytes(b"")
        preview = _scan(tmp)
        if preview is None:
            return []
        preview.file_stems = set()
        for path in wa.find_archives(info.root):
            arc = wa.open_archive(path)
            preview.file_stems |= {Path(e.path).stem for e in arc.entries}
        texts = extract_texts(preview, log)
        info.utf8 = preview.utf8
        info.encrypted_files = preview.encrypted_files
        info.files = preview.files
        return texts
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def unpack_archives(info: WolfGameInfo, log: LogFn = print, progress=None) -> WolfGameInfo:
    """Arşivleri oyun klasörüne açar (arşivler yedeğe taşınır) ve açık klasörlü oyun bilgisini döndürür."""
    wa.unpack(info.root, log=log, progress=progress)
    fresh = _scan(info.root)
    if fresh is None:
        raise wf.WolfFormatError("Arşiv açıldı ama Data/BasicData bulunamadı.")
    return fresh


def files_to_backup(info: WolfGameInfo) -> List[Path]:
    out = []
    for kind, rel in info.files:
        out.append(info.data_dir / rel)
        if kind == "db":
            out.append((info.data_dir / rel).with_suffix(".project"))
    return out


def write_translations(info: WolfGameInfo, translations: Dict[str, str], log: LogFn = print) -> Tuple[int, int]:
    """(yazılan dize, harfi kayıplı dize). Dosyalar özgün hâllerinden üretilir (yedek geri yüklendikten sonra)."""
    written = lossy = 0
    for _kind, rel, _data, doc in _docs(info, log):
        new, changed, lost = wf.rebuild(doc, translations)
        if not new:
            continue
        atomic_write(info.data_dir / rel, new)
        written += changed
        lossy += lost
    if written:
        log(f"WOLF RPG: {written} dize yazıldı" + (f" ({lossy} dizede Shift-JIS'e sığmayan harf sadeleştirildi)" if lossy else ""))
    return written, lossy


def files_stamp_paths(root: Path) -> List[Path]:
    root = Path(root)
    data = root / "Data"
    return (list((data / "MapData").glob("*.mps")) + list((data / "BasicData").glob("*.dat"))
            + list((data / "BasicData").glob("*.project")) + list(root.glob("*.wolf")) + list(data.glob("*.wolf")))


__all__ = ["WolfGameInfo", "WolfText", "detect_wolf", "extract_texts", "preview_texts", "unpack_archives",
           "write_translations", "files_to_backup", "PROTECTED_WOLF", "WOLF_EXTRA_INSTRUCTION"]
