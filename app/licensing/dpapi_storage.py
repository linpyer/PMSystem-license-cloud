from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from app.licensing.errors import LicenseStorageError


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsDpapiProtector:
    def __init__(self, entropy: bytes = b"DDREC-License-v1") -> None:
        self.entropy = bytes(entropy)

    def protect(self, plaintext: bytes) -> bytes:
        return self._transform(plaintext, decrypt=False)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return self._transform(ciphertext, decrypt=True)

    def _transform(self, value: bytes, *, decrypt: bool) -> bytes:
        if sys.platform != "win32":
            raise LicenseStorageError("Windows DPAPI is only available on Windows")
        source, source_buffer = _blob(value)
        entropy, entropy_buffer = _blob(self.entropy)
        output = _DataBlob()
        try:
            if decrypt:
                success = ctypes.windll.crypt32.CryptUnprotectData(
                    ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(output)
                )
            else:
                success = ctypes.windll.crypt32.CryptProtectData(
                    ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(output)
                )
            if not success:
                raise ctypes.WinError()
            return ctypes.string_at(output.pbData, output.cbData)
        except OSError as exc:
            action = "decrypt" if decrypt else "encrypt"
            raise LicenseStorageError(f"DPAPI could not {action} the license data") from exc
        finally:
            _ = source_buffer, entropy_buffer
            if output.pbData:
                ctypes.windll.kernel32.LocalFree(output.pbData)
