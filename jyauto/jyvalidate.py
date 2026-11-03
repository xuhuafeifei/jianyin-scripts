"""Validate a draft JSON with the engine's own parser.

    std::shared_ptr<lvve::Draft> lvve::GetDraftFromJson(std::string const&)
    std::string                  lvve::GetJsonFromDraft(std::shared_ptr<lvve::Draft> const&)

If `GetDraftFromJson` yields a non-null pointer the JSON is structurally
acceptable to the same engine 剪映 itself uses, which makes it a far better
gate than eyeballing the file.
"""

from __future__ import annotations

import ctypes
import os
from typing import Optional

from .jycrypto import StdString

SYM_GET_DRAFT = ("?GetDraftFromJson@lvve@@YA?AV?$shared_ptr@VDraft@lvve@@@std@@AEBV?$basic_string@DU?"
                 "$char_traits@D@std@@V?$allocator@D@2@@3@@Z")
SYM_GET_JSON = ("?GetJsonFromDraft@lvve@@YA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@"
                "std@@AEBV?$shared_ptr@VDraft@lvve@@@3@@Z")


class SharedPtr(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("ctrl", ctypes.c_void_p)]


class DraftValidator:
    def __init__(self, jianying_dir: str):
        self._keepalive: list = []
        if hasattr(os, "add_dll_directory"):
            self._handle = os.add_dll_directory(jianying_dir)
        self.dll = ctypes.WinDLL(os.path.join(jianying_dir, "videoeditor.dll"))
        dll = self.dll

        self._get_draft = getattr(dll, SYM_GET_DRAFT)
        self._get_draft.restype = ctypes.POINTER(SharedPtr)
        self._get_draft.argtypes = [ctypes.POINTER(SharedPtr), ctypes.POINTER(StdString)]

        self._get_json = getattr(dll, SYM_GET_JSON)
        self._get_json.restype = ctypes.POINTER(StdString)
        self._get_json.argtypes = [ctypes.POINTER(StdString), ctypes.POINTER(SharedPtr)]

    def parse(self, json_text: str) -> Optional[SharedPtr]:
        src = StdString()
        src.set_bytes(json_text.encode("utf-8"), self._keepalive)
        out = SharedPtr()
        self._get_draft(ctypes.byref(out), ctypes.byref(src))
        if not out.ptr:
            return None
        return out

    def roundtrip(self, json_text: str) -> Optional[str]:
        sp = self.parse(json_text)
        if sp is None:
            return None
        out = StdString()
        self._get_json(ctypes.byref(out), ctypes.byref(sp))
        return out.to_bytes().decode("utf-8", "replace")

    def validate(self, json_text: str) -> tuple[bool, str]:
        sp = self.parse(json_text)
        if sp is None:
            return False, "GetDraftFromJson returned null"
        back = self.roundtrip(json_text)
        if not back:
            return True, "parsed, but GetJsonFromDraft was empty"
        return True, f"parsed and re-serialised ({len(back)} chars)"
