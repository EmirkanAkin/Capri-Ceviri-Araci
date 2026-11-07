"""
Capri — Uygulama klasörleri
===========================
Kaynak koddan çalışırken her şey bu dosyanın klasöründedir. Paketlenmiş exe'de (PyInstaller)
arayüz ve varsayılan sözlükler `_internal` içinde gelir (RES_DIR); kullanıcı verisi, modeller ve
önbellekler ise exe'nin yanında tutulur (APP_DIR) — uygulama taşınabilir kalır.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Capri"
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
WEB_DIR = RES_DIR / "web"
ICON_FILE = RES_DIR / "assets" / "capri.ico"
# Kullanıcının düzenleyebildiği sözlükler (exe sürümünde ilk açılışta paketten kopyalanır)
GLOSSARY_DIR = APP_DIR / "data"
USER_DIR = APP_DIR / "portable_cache"
SEED_FILES = ("glossary.json", "glossary_rpgm.json", "glossary_nsfw.json", "terms.json")


def harden_stdio() -> None:
    """
    Konsola yazmak hiçbir zaman işi düşürmemeli. Pencereli exe'de stdout/stderr None'dur ve pywebview bunları
    sistem kod sayfasıyla (Türkçe Windows'ta cp1254) açar; `→`, `✔` gibi karakterler UnicodeEncodeError verir.
    pywebview içe aktarılmadan önce UTF-8 akışlarla doldurulur, var olanlar da hatasız yazacak şekilde ayarlanır.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:
                pass
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def seed_user_files() -> None:
    if RES_DIR == APP_DIR:
        return
    for name in SEED_FILES:
        target = GLOSSARY_DIR / name
        if not target.exists() and (RES_DIR / "data" / name).exists():
            try:
                GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(RES_DIR / "data" / name, target)
            except OSError:
                pass
