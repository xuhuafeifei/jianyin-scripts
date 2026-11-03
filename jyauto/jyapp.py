"""JianYing process control.

剪映 only rebuilds its draft list at startup, and it writes root_meta_info.json
back on exit — so drafts must be created while the app is closed.
"""

from __future__ import annotations

import os
import subprocess
import time

from .common import JIANYING_EXE, log

PROC_NAMES = ("JianyingPro", "JianyingProTray")


def running() -> list:
    out = []
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { $_.ProcessName -match '^JianyingPro' } | "
         "Select-Object -ExpandProperty Id"],
        capture_output=True, text=True)
    for line in ps.stdout.split():
        if line.strip().isdigit():
            out.append(int(line))
    return out


def main_window_open() -> bool:
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process JianyingPro -ErrorAction SilentlyContinue | "
         "Where-Object { $_.MainWindowTitle -ne '' } | Measure-Object).Count"],
        capture_output=True, text=True)
    try:
        return int(ps.stdout.strip() or 0) > 0
    except ValueError:
        return False


def close(timeout: float = 25.0) -> bool:
    """Ask 剪映 to close, then fall back to terminating leftovers."""
    if not running():
        return True
    log("  正在关闭剪映（先优雅退出，让它在退出前把草稿落盘）…")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process JianyingPro -ErrorAction SilentlyContinue | "
         "Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { $_.CloseMainWindow() | Out-Null }"],
        capture_output=True, text=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not running():
            return True
        time.sleep(0.5)
    log("  仍有剪映进程，强制结束…")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process JianyingPro,JianyingProTray -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True, text=True)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not running():
            return True
        time.sleep(0.5)
    return not running()


def launch(wait: float = 6.0) -> None:
    log("  启动剪映…")
    subprocess.Popen([JIANYING_EXE], close_fds=True)
    time.sleep(wait)


def open_draft(name: str) -> None:
    """Best effort: launch 剪映; a deep link is not available for local drafts."""
    launch()
