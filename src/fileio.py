"""
Capri — Güvenli dosya yazma
==========================
Bütün kalıcı yazımlar buradan geçer: veri önce aynı klasördeki geçici dosyaya yazılır, diske işlenir (fsync), sonra tek
adımda asıl dosyanın yerine konur. Elektrik kesilirse ya da yazma yarıda kalırsa asıl dosya eski hâliyle kalır; hata
yolunda geçici dosya silinir.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Union

Writer = Callable[[BinaryIO], None]


def temp_path(path: Path) -> Path:
    return path.with_name(path.name + ".capri_tmp")


def atomic_write(path: Union[str, Path], data: Optional[bytes] = None, writer: Optional[Writer] = None,
                 durable: bool = True, in_place_fallback: bool = False) -> Path:
    """data ya da writer(dosya) ile yazar. in_place_fallback: Windows yerine koymaya izin vermezse (dosyayı başka bir
    süreç açık tutuyorsa) içerik doğrudan dosyanın üzerine yazılır — yalnızca data verilmişse."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path(path)
    try:
        with open(tmp, "wb") as out:
            if writer is not None:
                writer(out)
            else:
                out.write(data or b"")
            out.flush()
            if durable:
                os.fsync(out.fileno())
        try:
            os.replace(tmp, path)
        except PermissionError:
            if not in_place_fallback or data is None:
                raise
            with open(path, "r+b") as handle:
                handle.write(data)
                handle.truncate()
                handle.flush()
                if durable:
                    os.fsync(handle.fileno())
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8", durable: bool = True) -> Path:
    """Metni olduğu gibi (satır sonları çevrilmeden) yazar."""
    return atomic_write(path, text.encode(encoding), durable=durable)


__all__ = ["atomic_write", "atomic_write_text", "temp_path"]
