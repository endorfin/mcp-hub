import ctypes
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
# Credential Manager caps a blob at 5 × 512 bytes; OAuth records can be larger, so they are split.
CHUNK = 2048


class CREDENTIAL(ctypes.Structure):
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


_advapi = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
_advapi.CredReadW.restype = wintypes.BOOL
_advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
_advapi.CredWriteW.restype = wintypes.BOOL
_advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_advapi.CredDeleteW.restype = wintypes.BOOL
_advapi.CredFree.argtypes = [ctypes.c_void_p]


class CredentialError(Exception):
    pass


def _target(name, part):
    return name if part == 0 else f"{name}#{part}"


def _read_part(target):
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not _advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None, None
        raise CredentialError(f"CredRead failed ({error})")
    try:
        cred = pointer.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return blob, cred.Comment or ""
    finally:
        _advapi.CredFree(pointer)


def _write_part(target, user, blob, comment):
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=target, Comment=comment, CredentialBlobSize=len(blob),
                      CredentialBlob=buffer, Persist=CRED_PERSIST_LOCAL_MACHINE, UserName=user)
    if not _advapi.CredWriteW(ctypes.byref(cred), 0):
        raise CredentialError(f"CredWrite failed ({ctypes.get_last_error()})")


def read(name):
    blob, comment = _read_part(_target(name, 0))
    if blob is None:
        return None
    parts = int(comment.removeprefix("parts=")) if comment.startswith("parts=") else 1
    for part in range(1, parts):
        more, _ = _read_part(_target(name, part))
        if more is None:
            raise CredentialError(f"Part {part} of {name} is missing")
        blob += more
    return blob.decode("utf-8")


def write(name, user, value):
    data = value.encode("utf-8")
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    delete(name)
    for part, chunk in enumerate(chunks):
        _write_part(_target(name, part), user, chunk, f"parts={len(chunks)}" if part == 0 else "")


def delete(name):
    part = 0
    while _advapi.CredDeleteW(_target(name, part), CRED_TYPE_GENERIC, 0):
        part += 1
