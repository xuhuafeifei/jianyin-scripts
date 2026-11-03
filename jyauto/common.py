"""Shared helpers: ids, timeranges, paths, logging."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from typing import Any

JIANYING_EXE = r"F:\JianyingPro\JianyingPro.exe"
JIANYING_VERSION_DIR = r"F:\JianyingPro\11.6.0.14552"
DRAFT_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\发\AppData\Local"),
    "JianyingPro", "User Data", "Projects", "com.lveditor.draft",
)
PROJECT_ROOT = r"F:\JYAutoEdit"
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FONT_PATH = JIANYING_VERSION_DIR + r"\Resources\Font\SystemFont\zh-hans.ttf"

US = 1_000_000  # microseconds per second


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def uid4() -> str:
    return str(uuid.uuid4())


def sec_to_us(value: float) -> int:
    return int(round(value * US))


def tr(start_us: int, duration_us: int) -> dict[str, int]:
    return {"start": int(start_us), "duration": int(duration_us)}


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> "None":
    print(f"error: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
