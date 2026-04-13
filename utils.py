"""Shared helpers for CS2 OMZ.

Centralizes the subprocess invocation pattern, the CREATE_NO_WINDOW flag,
the common ``Result`` type alias, and the Killer NIC keyword list so the
same values don't drift across modules.
"""
from __future__ import annotations

import subprocess
from typing import Tuple

Result = Tuple[bool, str]

# Hide console windows for child processes (reg.exe, powershell, netsh, ...)
# so the GUI doesn't flash black boxes.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_cmd(cmd: list[str], timeout: int = 20) -> Result:
    """Run ``cmd`` hidden and return ``(ok, stdout_or_stderr)``."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        if r.returncode == 0:
            return True, (r.stdout.strip() or "ok")
        return False, (r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    except Exception as e:
        return False, str(e)


# Killer / Rivet Networks NICs clash with Windows TCP stack tweaks — any
# optimization that touches netsh/TCP registry must bail out when one is
# the active adapter.
KILLER_NIC_KEYWORDS = (
    "killer", "rivet networks",
    "killer e2400", "killer e2500", "killer e3000", "killer ax1650",
)
KILLER_SKIP_MESSAGE = (
    "Killer NIC detected — TCP optimizations skipped to avoid "
    "conflicts with Killer software"
)
