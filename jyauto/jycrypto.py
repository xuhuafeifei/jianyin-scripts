"""JianYing draft crypto via videoeditor.dll (EncryptUtils).

Mirrors what jy-draftc does in draft_crypto.cpp:

    using DecryptWithFlag = std::string *(*)(void *, std::string *, const std::string *,
                                             const std::string *, bool *);
    using Encrypt         = std::string *(*)(void *, std::string *, const std::string *);
    using Enable          = void (*)(void *, bool);

The MSVC x64 `this` pointer is passed as nullptr, and non-trivial return values
use a hidden sret pointer. std::string layout on MSVC x64 is 32 bytes:
    +0   union { char _Buf[16]; char * _Ptr; }
    +16  size_t _Mysize
    +24  size_t _Myres
"""

from __future__ import annotations

import ctypes
import os
from typing import Optional

SSO_CAP = 15


class StdString(ctypes.Structure):
    """MSVC std::string (x64)."""

    _fields_ = [
        ("w0", ctypes.c_uint64),   # union { char buf[16]; char *ptr; }  first 8 bytes
        ("w1", ctypes.c_uint64),   # union  second 8 bytes
        ("size", ctypes.c_size_t),
        ("cap", ctypes.c_size_t),
    ]

    def set_bytes(self, data: bytes, keepalive: list) -> None:
        n = len(data)
        if n <= SSO_CAP:
            raw = ctypes.string_at(ctypes.addressof(self), 32)
            buf = bytes(data) + b"\0" * (16 - n)
            self.w0 = int.from_bytes(buf[0:8], "little")
            self.w1 = int.from_bytes(buf[8:16], "little")
            self.size = n
            self.cap = SSO_CAP
        else:
            mem = ctypes.create_string_buffer(bytes(data), n)  # NUL-terminated
            keepalive.append(mem)
            self.w0 = ctypes.addressof(mem)
            self.w1 = 0
            self.size = n
            self.cap = n

    def to_bytes(self) -> bytes:
        n = int(self.size)
        if n == 0:
            return b""
        if int(self.cap) > SSO_CAP:
            return ctypes.string_at(int(self.w0), n)
        return ctypes.string_at(ctypes.addressof(self), n)


def _bind(dll, symbol: str, restype, argtypes):
    fn = getattr(dll, symbol)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


class DraftCrypto:
    SYM_DECRYPT_FLAG = ("?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@"
                        "std@@AEBV34@0AEA_N@Z")
    SYM_DECRYPT = ("?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@"
                   "std@@AEBV34@0@Z")
    SYM_ENCRYPT = ("?encrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@"
                   "std@@AEBV34@@Z")
    SYM_ENABLE = "?enable@EncryptUtils@lvve@@QEAAX_N@Z"
    SYM_IS_ENABLE = "?isEnable@EncryptUtils@lvve@@QEAA_NXZ"

    def __init__(self, jianying_dir: str):
        self.dir = jianying_dir
        self._keepalive: list = []
        if hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(jianying_dir)
        self.dll = ctypes.WinDLL(os.path.join(jianying_dir, "videoeditor.dll"))

        sp = ctypes.POINTER(StdString)
        self._decrypt_flag = None
        try:
            self._decrypt_flag = _bind(
                self.dll, self.SYM_DECRYPT_FLAG, sp,
                [ctypes.c_void_p, sp, sp, sp, ctypes.POINTER(ctypes.c_bool)],
            )
        except AttributeError:
            self._decrypt_flag = None
        self._decrypt = _bind(self.dll, self.SYM_DECRYPT, sp,
                              [ctypes.c_void_p, sp, sp, sp])
        self._encrypt = _bind(self.dll, self.SYM_ENCRYPT, sp,
                              [ctypes.c_void_p, sp, sp])
        self._enable = _bind(self.dll, self.SYM_ENABLE, None,
                             [ctypes.c_void_p, ctypes.c_bool])
        self._param = StdString()
        self._param.set_bytes(b"{}", self._keepalive)

    def _call_decrypt(self, text: bytes) -> Optional[bytes]:
        src = StdString()
        src.set_bytes(text, self._keepalive)
        out = StdString()
        if self._decrypt_flag is not None:
            ok = ctypes.c_bool(False)
            self._decrypt_flag(None, ctypes.byref(out), ctypes.byref(src),
                               ctypes.byref(self._param), ctypes.byref(ok))
            if not ok.value:
                return None
        else:
            self._decrypt(None, ctypes.byref(out), ctypes.byref(src), ctypes.byref(self._param))
        return out.to_bytes() or None

    def decrypt(self, text: bytes) -> bytes:
        result = self._call_decrypt(text)
        if result is None:
            raise ValueError("decrypt failed (empty output or bad ok-flag)")
        return result

    def encrypt(self, plain: bytes) -> bytes:
        self._enable(None, True)
        src = StdString()
        src.set_bytes(plain, self._keepalive)
        out = StdString()
        self._encrypt(None, ctypes.byref(out), ctypes.byref(src))
        encrypted = out.to_bytes()
        if not encrypted:
            raise ValueError("encrypt returned empty")
        return encrypted


def decrypt_file(crypto: DraftCrypto, path: str) -> bytes:
    return crypto.decrypt(open(path, "rb").read())


def encrypt_file(crypto: DraftCrypto, plain: bytes) -> bytes:
    return crypto.encrypt(plain)
