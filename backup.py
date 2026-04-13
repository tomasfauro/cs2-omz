"""Registry backup/restore helpers for CS2 OMZ.

Every optimization that modifies the registry should first call
`backup_keys([...])` so changes can be reversed via `restore_latest_backup()`.
"""
from __future__ import annotations

import datetime
import glob
import os
import subprocess
from typing import Iterable, Optional

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")

# Hide the reg.exe console window when exporting/importing backups.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ensure_dir() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_keys(keys: Iterable[str], tag: str = "backup") -> Optional[str]:
    """Export each given registry key to a single .reg file.

    Keys must be in full form, e.g. ``HKLM\\SYSTEM\\CurrentControlSet\\...``.
    Returns the path to the combined .reg file, or None if nothing was backed up.
    """
    _ensure_dir()
    ts = _timestamp()
    safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)
    final_path = os.path.join(BACKUP_DIR, f"{safe_tag}_{ts}.reg")
    parts: list[str] = []

    for idx, key in enumerate(keys):
        tmp = os.path.join(BACKUP_DIR, f"_tmp_{idx}_{ts}.reg")
        try:
            res = subprocess.run(
                ["reg", "export", key, tmp, "/y"],
                capture_output=True, text=True, timeout=15,
                creationflags=_NO_WINDOW,
            )
            if res.returncode == 0 and os.path.isfile(tmp):
                try:
                    with open(tmp, "r", encoding="utf-16") as f:
                        parts.append(f.read())
                except UnicodeError:
                    with open(tmp, "r", encoding="utf-8", errors="ignore") as f:
                        parts.append(f.read())
        except Exception:
            continue
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    if not parts:
        return None

    # Merge: keep first header, strip subsequent ones
    merged = parts[0]
    for extra in parts[1:]:
        lines = extra.splitlines()
        # Drop "Windows Registry Editor" line + blank
        lines = [ln for ln in lines if not ln.startswith("Windows Registry Editor")]
        merged += "\r\n" + "\r\n".join(lines)

    try:
        with open(final_path, "w", encoding="utf-16") as f:
            f.write(merged)
    except Exception:
        return None
    return final_path


def list_backups() -> list[str]:
    _ensure_dir()
    files = glob.glob(os.path.join(BACKUP_DIR, "*.reg"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def restore_latest_backup() -> tuple[bool, str]:
    """Silently import the most recent .reg file."""
    files = list_backups()
    if not files:
        return False, "No backups found."
    latest = files[0]
    try:
        res = subprocess.run(
            ["reg", "import", latest],
            capture_output=True, text=True, timeout=20,
            creationflags=_NO_WINDOW,
        )
        if res.returncode == 0:
            return True, f"Restored from {os.path.basename(latest)}"
        return False, f"reg import failed: {res.stderr.strip() or res.stdout.strip()}"
    except Exception as e:
        return False, f"Restore error: {e}"


def restore_backup(path: str) -> tuple[bool, str]:
    if not os.path.isfile(path):
        return False, "Backup file not found."
    try:
        res = subprocess.run(
            ["reg", "import", path],
            capture_output=True, text=True, timeout=20,
            creationflags=_NO_WINDOW,
        )
        if res.returncode == 0:
            return True, f"Restored from {os.path.basename(path)}"
        return False, f"reg import failed: {res.stderr.strip()}"
    except Exception as e:
        return False, f"Restore error: {e}"
