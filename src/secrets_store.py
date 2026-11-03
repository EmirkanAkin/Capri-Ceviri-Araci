"""
Capri — API anahtarları için Windows Kimlik Bilgisi Yöneticisi (Credential Manager)
=====================================================================================
Anahtarlar Windows hesabına bağlı olarak şifreli (DPAPI) saklanır; uygulama klasöründe
düz metin olarak durmaz. Windows dışında ya da hata durumunda `available()` False döner.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from typing import Optional

PREFIX = "Capri/"
LEGACY_PREFIXES = ("OmniTrans/",)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
MAX_BLOB = 2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME), ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR), ("UserName", wt.LPWSTR),
    ]


try:
    _adv = ctypes.windll.advapi32
    _adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wt.DWORD]
    _adv.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
    _adv.CredFree.argtypes = [ctypes.c_void_p]
except (AttributeError, OSError):  # Windows değil
    _adv = None


def available() -> bool:
    return _adv is not None


def get(name: str) -> Optional[str]:
    """Kayıtlı değeri döndürür; yoksa None. Eski önekle kaydedilmiş değer yeni öneke taşınır."""
    if not _adv:
        return None
    value = _read(PREFIX + name)
    if value is None and PREFIX == "Capri/":
        for legacy in LEGACY_PREFIXES:
            value = _read(legacy + name)
            if value is not None:
                if set(name, value) and _read(PREFIX + name) == value:
                    _adv.CredDeleteW(legacy + name, CRED_TYPE_GENERIC, 0)
                break
    return value


def _read(target: str) -> Optional[str]:
    pcred = ctypes.POINTER(CREDENTIALW)()
    if not _adv.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        return None
    try:
        cred = pcred.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        _adv.CredFree(pcred)


def set(name: str, value: str) -> bool:
    """Değeri kaydeder; boş değer kaydı siler."""
    if not _adv:
        return False
    if not value:
        delete(name)
        return True
    blob = value.encode("utf-16-le")
    if len(blob) > MAX_BLOB:
        return False
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = PREFIX + name
    cred.Comment = "Capri çeviri sağlayıcısı API anahtarı"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "Capri"
    return bool(_adv.CredWriteW(ctypes.byref(cred), 0))


def delete(name: str) -> None:
    if _adv:
        _adv.CredDeleteW(PREFIX + name, CRED_TYPE_GENERIC, 0)
