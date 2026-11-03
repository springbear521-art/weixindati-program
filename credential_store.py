"""Store the DeepSeek API key in the current user's Windows Credential Manager."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


TARGET = "WeReadQuizHelper/DeepSeekApiKey"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
_advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
_advapi32.CredWriteW.restype = wintypes.BOOL
_advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
_advapi32.CredReadW.restype = wintypes.BOOL
_advapi32.CredFree.argtypes = [ctypes.c_void_p]
_advapi32.CredFree.restype = None


def save_key(key: str) -> None:
    value = key.strip()
    if not value:
        raise ValueError("请输入 DeepSeek API 密钥。")
    raw = value.encode("utf-8")
    if len(raw) > 2560:
        raise ValueError("密钥太长，Windows 凭据管理器无法保存。")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = _CREDENTIALW()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = TARGET
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "DeepSeek API"
    if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def load_key() -> str | None:
    credential = ctypes.POINTER(_CREDENTIALW)()
    if not _advapi32.CredReadW(TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(error)
    try:
        return ctypes.string_at(credential.contents.CredentialBlob,
                                credential.contents.CredentialBlobSize).decode("utf-8")
    finally:
        _advapi32.CredFree(credential)
