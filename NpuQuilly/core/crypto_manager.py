"""DPAPI protect/unprotect on Windows, with read support for older settings.

ctypes discipline (a use-after-free here segfaults the whole app):
- every buffer is a NAMED local alive for the entire native call (no temporaries),
- argtypes/restype are always set,
- output blobs are read with string_at and freed with LocalFree.
"""
import base64


def _dpapi(data: bytes, do_protect: bool) -> bytes | None:
    try:
        import ctypes
        import ctypes.wintypes as wt
    except Exception:
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_byte))]

        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), wt.LPCWSTR, ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptProtectData.restype = wt.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            wt.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptUnprotectData.restype = wt.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        buf_in = (ctypes.c_byte * len(data))(*data)  # keep alive through the call
        blob_in = DATA_BLOB(len(data), buf_in)
        blob_out = DATA_BLOB()
        if do_protect:
            ok = crypt32.CryptProtectData(
                ctypes.byref(blob_in), "NpuQuilly", None, None, None, 0,
                ctypes.byref(blob_out))
        else:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def protect(secret: str) -> str:
    raw = secret.encode("utf-8")
    enc = _dpapi(raw, True)
    if enc is None:
        raise RuntimeError("Windows could not encrypt the API key. The saved key was kept.")
    return "dpapi:" + base64.b64encode(enc).decode()


def unprotect(token: str) -> str:
    if token.startswith("dpapi:"):
        raw = base64.b64decode(token[6:])
        dec = _dpapi(raw, False)
        return (dec or b"").decode("utf-8", "ignore")
    if token.startswith("b64:"):
        return base64.b64decode(token[4:]).decode("utf-8", "ignore")
    return token  # legacy plaintext
