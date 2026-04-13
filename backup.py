"""Registry backup/restore helpers for CS2 OMZ.

Every optimization that modifies the registry should first call
``backup_keys([...])`` and verify the returned ``ok`` flag before
proceeding — a failed backup means the change would not be reversible.

``session_start()`` records a timestamp when the app launches;
``restore_session_backups()`` then imports every .reg file created
after that timestamp so a single "Revert Changes" click undoes the
entire session's worth of optimizations.
"""
from __future__ import annotations

import datetime
import glob
import os
import time
from typing import Iterable, Optional, Tuple

from utils import NO_WINDOW, run_cmd

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
_SESSION_MARKER = os.path.join(BACKUP_DIR, ".session_start")


def _ensure_dir() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def session_start() -> None:
    """Record the current time as the start of a revertable session."""
    _ensure_dir()
    with open(_SESSION_MARKER, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def _session_start_time() -> Optional[float]:
    try:
        with open(_SESSION_MARKER, "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def backup_keys(keys: Iterable[str], tag: str = "backup"
                ) -> Tuple[bool, Optional[str], str]:
    """Export each given registry key to a single .reg file.

    Returns a triple ``(ok, path, message)``:
      * ``(True, path, "ok")``         — backup written to ``path``.
      * ``(True, None,  "no existing keys")`` — keys didn't exist yet
        (legitimate for new keys like QoS); safe to proceed.
      * ``(False, None, "<reason>")``  — backup genuinely failed; the
        caller MUST NOT proceed with its change, since a later revert
        would have nothing to restore.
    """
    _ensure_dir()
    ts = _timestamp()
    safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)
    final_path = os.path.join(BACKUP_DIR, f"{safe_tag}_{ts}.reg")

    keys = list(keys)
    if not keys:
        return True, None, "no keys requested"

    parts: list[str] = []
    export_errors: list[str] = []
    any_existed = False

    for idx, key in enumerate(keys):
        tmp = os.path.join(BACKUP_DIR, f"_tmp_{idx}_{ts}.reg")
        try:
            import subprocess
            res = subprocess.run(
                ["reg", "export", key, tmp, "/y"],
                capture_output=True, text=True, timeout=15,
                creationflags=NO_WINDOW,
            )
            if res.returncode == 0 and os.path.isfile(tmp):
                any_existed = True
                try:
                    with open(tmp, "r", encoding="utf-16") as f:
                        parts.append(f.read())
                except UnicodeError:
                    with open(tmp, "r", encoding="utf-8", errors="ignore") as f:
                        parts.append(f.read())
            else:
                stderr = (res.stderr or "").strip().lower()
                # reg export on a non-existent key is NOT a real failure — the
                # caller is about to create it, so there's nothing to back up.
                if "unable to find" in stderr or "cannot find" in stderr:
                    continue
                export_errors.append(f"{key}: {res.stderr.strip() or res.stdout.strip()}")
        except Exception as e:
            export_errors.append(f"{key}: {e}")
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    if not any_existed and export_errors:
        return False, None, "backup failed: " + "; ".join(export_errors)

    if not parts:
        return True, None, "no existing keys to back up"

    # Merge: keep first header, strip subsequent ones
    merged = parts[0]
    for extra in parts[1:]:
        lines = [ln for ln in extra.splitlines()
                 if not ln.startswith("Windows Registry Editor")]
        merged += "\r\n" + "\r\n".join(lines)

    try:
        with open(final_path, "w", encoding="utf-16") as f:
            f.write(merged)
    except Exception as e:
        return False, None, f"backup write failed: {e}"
    return True, final_path, "ok"


def list_backups() -> list[str]:
    _ensure_dir()
    files = glob.glob(os.path.join(BACKUP_DIR, "*.reg"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def _import_reg(path: str) -> Tuple[bool, str]:
    ok, msg = run_cmd(["reg", "import", path], timeout=20)
    if ok:
        return True, f"Restored {os.path.basename(path)}"
    return False, f"reg import failed for {os.path.basename(path)}: {msg}"


def restore_session_backups() -> Tuple[bool, str]:
    """Import every .reg backup created since the last ``session_start()``.

    Falls back to restoring only the newest backup when no session marker
    exists (e.g. the user launched an older build that never set one).
    """
    start = _session_start_time()
    files = list_backups()
    if not files:
        return False, "No backups found."

    if start is None:
        ok, msg = _import_reg(files[0])
        return ok, msg + "  (no session marker — restored latest only)"

    session_files = [p for p in files if os.path.getmtime(p) >= start]
    if not session_files:
        return False, "No backups from this session."

    # Restore oldest-first so later changes (which may reference earlier
    # state) re-apply cleanly on top.
    session_files.sort(key=os.path.getmtime)

    restored = 0
    errors: list[str] = []
    for path in session_files:
        ok, msg = _import_reg(path)
        if ok:
            restored += 1
        else:
            errors.append(msg)

    if restored and not errors:
        return True, f"Restored {restored} backup(s) from this session."
    if restored and errors:
        return True, (f"Restored {restored} backup(s); {len(errors)} failed: "
                      + "; ".join(errors))
    return False, "All restores failed: " + "; ".join(errors)


def restore_latest_backup() -> Tuple[bool, str]:
    """Compatibility shim — prefer ``restore_session_backups()``."""
    return restore_session_backups()


def restore_backup(path: str) -> Tuple[bool, str]:
    if not os.path.isfile(path):
        return False, "Backup file not found."
    return _import_reg(path)
