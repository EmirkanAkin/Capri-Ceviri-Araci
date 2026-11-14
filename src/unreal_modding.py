"""
Unreal Engine Gelişmiş Modlama & Runtime Entegrasyon Modülü (B ve C Aşaması)
========================================================================
Unreal Engine oyunlarında:
1. Pak / IoStore (~mods/ ve Patch _P.pak) mod yapısı hazırlama
2. UE4SS (Unreal Engine 4/5 Scripting System) runtime hooking köprüsü
"""
from __future__ import annotations

from pathlib import Path

from engine_common import LogFn
from engine_unreal import UnrealGameInfo


def setup_unreal_mods_folder(info: UnrealGameInfo, log: LogFn = print) -> Path:
    """
    Unreal Engine'in yerel mod klasörünü oluşturur: Content/Paks/~mods
    Unreal Engine, '~mods' altındaki tüm .pak dosyalarını otomatik olarak
    orijinal oyun dosyalarının üzerine yazar!
    """
    if not info.paks_dir or not info.paks_dir.exists():
        target = info.content_dir / "Paks" / "~mods"
    else:
        target = info.paks_dir / "~mods"

    target.mkdir(parents=True, exist_ok=True)
    log(f"Unreal Engine ~mods klasörü hazır: {target}")
    return target


def generate_ue4ss_translation_config(
    info: UnrealGameInfo,
    log: LogFn = print,
) -> Path:
    """
    UE4SS için optimize edilmiş, metin kancalama (FText Hooking)
    ve canlı konsol desteği sunan yapılandırma dosyasını oluşturur.
    """
    bin_dir = info.root / info.game_project_name / "Binaries" / "Win64"
    if not bin_dir.exists():
        bin_dir = info.root / "Binaries" / "Win64"
    bin_dir.mkdir(parents=True, exist_ok=True)

    config_file = bin_dir / "UE4SS-settings.ini"

    config_content = """; UE4SS Configuration for Live Localization and Translation Hooking
[General]
EnableConsole = 1
EnableHotReload = 1
GUIConsoleVisible = 0

[Hooks]
HookFText = 1
HookProcessConsoleExec = 1

[Debug]
DebugConsoleVisible = 0
GraphicsAPI = dx11
"""
    config_file.write_text(config_content, encoding="utf-8")
    log(f"UE4SS Translation kancalama yapılandırması oluşturuldu: {config_file.name}")
    return config_file
