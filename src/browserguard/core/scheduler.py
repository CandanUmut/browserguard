"""Registering the background task that keeps policy in step with the clock.

Browser policy is static, so something has to rewrite it when a schedule window
opens or closes, and when a pending change becomes due. A Windows scheduled task
running ``browserguard --sync`` every few minutes does that.

The task is ordinary and visible in Task Scheduler. It is deliberately not
hidden, protected or self-restoring.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "BrowserGuard Sync"
DEFAULT_INTERVAL_MINUTES = 5


def _executable_command() -> str:
    """The command the task should run, frozen or from source."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}" --sync'
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    runner = windowless if windowless.exists() else python
    return f'"{runner}" -m browserguard --sync'


def _run(args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return False, str(exc)
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output.strip()


def is_registered() -> bool:
    ok, _ = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return ok


def register(interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> tuple[bool, str]:
    """Create or replace the scheduled task. Needs administrator rights."""
    ok, output = _run(
        [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/TR",
            _executable_command(),
            "/SC",
            "MINUTE",
            "/MO",
            str(interval_minutes),
            "/RU",
            "SYSTEM",
            "/RL",
            "HIGHEST",
        ]
    )
    if ok:
        return True, f"Background sync registered, every {interval_minutes} minutes."
    return False, output or "Could not register the scheduled task."


def unregister() -> tuple[bool, str]:
    ok, output = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    if ok:
        return True, "Background sync removed."
    return False, output or "Could not remove the scheduled task."


def run_now() -> tuple[bool, str]:
    ok, output = _run(["schtasks", "/Run", "/TN", TASK_NAME])
    return ok, output or ("Triggered." if ok else "Could not trigger the task.")
