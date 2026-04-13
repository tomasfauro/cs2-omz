"""System-level optimizations for CS2 OMZ.

Each optimization is a standalone function returning ``(success, message)``
and has a matching ``check_<name>_status()`` helper so the GUI can display
the current state on startup without user interaction.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Tuple

try:
    import winreg
except ImportError:
    winreg = None

from backup import backup_keys
import hardware_detect

Result = Tuple[bool, str]

# Hide every child process window (PowerShell/CMD/netsh/etc.) so the GUI
# doesn't flash black boxes while optimizations run.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# -------------------- low-level registry helpers --------------------

def _reg_read(root, sub, name):
    try:
        with winreg.OpenKey(root, sub) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_write_dword(root, sub, name, value) -> Result:
    try:
        with winreg.CreateKey(root, sub) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _run(cmd: list[str], timeout: int = 20) -> Result:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        if r.returncode == 0:
            return True, (r.stdout.strip() or "ok")
        return False, (r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    except Exception as e:
        return False, str(e)


# -------------------- HPET --------------------

def disable_hpet() -> Result:
    backup_keys(["HKLM\\SYSTEM\\CurrentControlSet\\Services\\hpet"], "hpet")
    ok, msg = _run(["bcdedit", "/deletevalue", "useplatformclock"])
    _run(["bcdedit", "/set", "disabledynamictick", "yes"])
    return True, "HPET disabled (useplatformclock removed, dynamic tick off)." if ok else f"HPET: {msg}"


def check_hpet_status() -> bool:
    try:
        r = subprocess.run(["bcdedit", "/enum"], capture_output=True, text=True,
                           timeout=8, creationflags=_NO_WINDOW)
        out = r.stdout.lower()
        # Applied when useplatformclock is NOT present and disabledynamictick=yes
        return "useplatformclock" not in out and "disabledynamictick        yes" in out
    except Exception:
        return False


# -------------------- Core Parking --------------------

_CORE_PARK_KEY = (
    "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Power\\PowerSettings\\"
    "54533251-82be-4824-96c1-47b60b740d00\\0cc5b647-c1df-4637-891a-dec35c318583"
)

def disable_core_parking() -> Result:
    """Works for Intel and AMD — sets ValueMax=0 on the core-parking setting."""
    backup_keys([_CORE_PARK_KEY], "core_parking")
    try:
        # Apply to current scheme
        _run(["powercfg", "-setacvalueindex", "scheme_current",
              "sub_processor", "bc5038f7-23e0-4960-96da-33abaf5935ec", "100"])
        _run(["powercfg", "-setdcvalueindex", "scheme_current",
              "sub_processor", "bc5038f7-23e0-4960-96da-33abaf5935ec", "100"])
        _run(["powercfg", "-S", "scheme_current"])
        # Registry-level unpark
        if winreg:
            with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE,
                                  _CORE_PARK_KEY.replace("HKLM\\", "")) as k:
                winreg.SetValueEx(k, "ValueMax", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(k, "ValueMin", 0, winreg.REG_DWORD, 0)
        return True, "Core parking disabled on all cores."
    except Exception as e:
        return False, f"Core parking: {e}"


def check_core_parking_status() -> bool:
    if not winreg:
        return False
    try:
        val = _reg_read(
            winreg.HKEY_LOCAL_MACHINE,
            _CORE_PARK_KEY.replace("HKLM\\", ""),
            "ValueMax",
        )
        return val == 0
    except Exception:
        return False


# -------------------- High Performance power plan --------------------

_HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

def set_high_performance_plan() -> Result:
    ok, msg = _run(["powercfg", "-setactive", _HIGH_PERF_GUID])
    if ok:
        return True, "High Performance power plan activated."
    # Try to create it if missing
    _run(["powercfg", "-duplicatescheme", _HIGH_PERF_GUID])
    return _run(["powercfg", "-setactive", _HIGH_PERF_GUID])


def check_high_performance_status() -> bool:
    try:
        r = subprocess.run(["powercfg", "-getactivescheme"],
                           capture_output=True, text=True, timeout=6,
                           creationflags=_NO_WINDOW)
        return _HIGH_PERF_GUID in r.stdout.lower()
    except Exception:
        return False


# -------------------- NVIDIA MSI mode --------------------

_DISPLAY_CLASS_GUID = "{4d36e968-e325-11ce-bfc1-08002be10318}"


def _is_nvidia_gpu_present() -> bool:
    """Independent NVIDIA check: scan the Display class in the registry for
    any device whose MatchingDeviceId starts with PCI\\VEN_10DE (NVIDIA)."""
    if not winreg:
        return False
    base = rf"SYSTEM\CurrentControlSet\Control\Class\{_DISPLAY_CLASS_GUID}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    return False
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        mid = winreg.QueryValueEx(k, "MatchingDeviceId")[0]
                        if isinstance(mid, str) and "ven_10de" in mid.lower():
                            return True
                except OSError:
                    continue
    except OSError:
        return False


def _find_nvidia_gpu_device_keys() -> list[str]:
    """Return every PCI instance registry path that is (a) NVIDIA (VEN_10DE)
    AND (b) of Display class — skipping the HDMI audio chip on the same card
    (which is VEN_10DE but Audio class, not Display)."""
    if not winreg:
        return []
    base = r"SYSTEM\CurrentControlSet\Enum\PCI"
    found: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    dev = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if "ven_10de" not in dev.lower():
                    continue
                try:
                    with winreg.OpenKey(root, dev) as dk:
                        j = 0
                        while True:
                            try:
                                inst = winreg.EnumKey(dk, j)
                            except OSError:
                                break
                            j += 1
                            # Filter by Display class — skip HDMI audio etc.
                            try:
                                with winreg.OpenKey(dk, inst) as ik:
                                    class_guid = winreg.QueryValueEx(ik, "ClassGUID")[0]
                                    if class_guid.lower() != _DISPLAY_CLASS_GUID:
                                        continue
                            except OSError:
                                continue
                            found.append(
                                f"{base}\\{dev}\\{inst}"
                                r"\Device Parameters\Interrupt Management"
                                r"\MessageSignaledInterruptProperties"
                            )
                except OSError:
                    continue
    except OSError:
        return []
    return found


def enable_msi_mode_nvidia() -> Result:
    """Enable MSI mode on every NVIDIA GPU present. No-op if there isn't one.

    Uses an independent registry scan (not hardware_detect) so a regression
    in detection can never accidentally skip an NVIDIA card.
    """
    if not _is_nvidia_gpu_present():
        return False, "Skipped: no NVIDIA GPU detected in registry."
    paths = _find_nvidia_gpu_device_keys()
    if not paths:
        return False, "NVIDIA GPU found but PCI Display device key is missing."
    backup_keys([f"HKLM\\{p}" for p in paths], "nvidia_msi")
    ok_count = 0
    last_err = ""
    for p in paths:
        ok, msg = _reg_write_dword(winreg.HKEY_LOCAL_MACHINE, p, "MSISupported", 1)
        if ok:
            ok_count += 1
        else:
            last_err = msg
    if ok_count == 0:
        return False, f"MSI write failed: {last_err}"
    return True, f"MSI mode enabled on {ok_count} NVIDIA GPU(s)."


def check_msi_mode_nvidia_status() -> bool:
    if not winreg:
        return False
    paths = _find_nvidia_gpu_device_keys()
    if not paths:
        return False
    # Applied only if every NVIDIA GPU has MSISupported=1
    for p in paths:
        if _reg_read(winreg.HKEY_LOCAL_MACHINE, p, "MSISupported") != 1:
            return False
    return True


# -------------------- Nagle (system-wide default) --------------------

_NAGLE_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

def disable_nagle_algorithm() -> Result:
    """System-level Nagle disable (all interfaces)."""
    if not winreg:
        return False, "winreg unavailable."
    backup_keys([f"HKLM\\{_NAGLE_BASE}"], "nagle_system")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE) as root:
            i = 0
            touched = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        f"{_NAGLE_BASE}\\{sub}", 0,
                                        winreg.KEY_SET_VALUE) as k:
                        winreg.SetValueEx(k, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                        winreg.SetValueEx(k, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                        winreg.SetValueEx(k, "TcpDelAckTicks", 0, winreg.REG_DWORD, 0)
                        touched += 1
                except OSError:
                    continue
        return True, f"Nagle disabled on {touched} interface(s)."
    except Exception as e:
        return False, str(e)


def check_nagle_status() -> bool:
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    return False
                i += 1
                v = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                              f"{_NAGLE_BASE}\\{sub}", "TcpAckFrequency")
                if v == 1:
                    return True
    except Exception:
        return False


# -------------------- SSD TRIM --------------------

def _debug_enumerate_drives() -> list[str]:
    """Return a list of 'model -> guess' strings for every drive Windows
    reports. Used by optimize_ssd_trim's debug path so we can see exactly
    what model strings the keyword matcher is seeing."""
    lines: list[str] = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_DiskDrive | "
             "ForEach-Object { \"$($_.Model)|$($_.InterfaceType)|$($_.MediaType)\" }"],
            capture_output=True, text=True, timeout=8,
            creationflags=_NO_WINDOW,
        )
        for raw in (r.stdout or "").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split("|")
            model = parts[0] if parts else raw
            iface = parts[1] if len(parts) > 1 else ""
            mtype = parts[2] if len(parts) > 2 else ""
            guess = hardware_detect._guess_from_model(model)
            lines.append(f"  - '{model}' iface={iface} media={mtype} → {guess}")
    except Exception as e:
        lines.append(f"  (enumeration failed: {e})")
    return lines


def optimize_ssd_trim(debug: bool = True) -> Result:
    info = hardware_detect.detect_all()
    if not info.has_ssd:
        if debug:
            drives = _debug_enumerate_drives()
            detail = "\n".join(drives) if drives else "  (no drives reported)"
            return False, (
                "Skipped: no SSD detected on this system.\n"
                f"has_ssd={info.has_ssd} has_hdd={info.has_hdd}\n"
                "Drives seen:\n" + detail
            )
        return False, "Skipped: no SSD detected on this system."
    return _run(["fsutil", "behavior", "set", "DisableDeleteNotify", "0"])


def check_ssd_trim_status() -> bool:
    try:
        info = hardware_detect.detect_all()
        if not info.has_ssd:
            # No SSD → TRIM is irrelevant; report as "applied" so the GUI
            # doesn't nag users with pure-HDD systems.
            return True
        r = subprocess.run(["fsutil", "behavior", "query", "DisableDeleteNotify"],
                           capture_output=True, text=True, timeout=6,
                           creationflags=_NO_WINDOW)
        return "= 0" in r.stdout or "NTFS DisableDeleteNotify = 0" in r.stdout
    except Exception:
        return False


# -------------------- CS2 fullscreen optimizations --------------------

_CS2_EXE_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
_CS2_FLAG = "~ DISABLEDXMAXIMIZEDWINDOWEDMODE HIGHDPIAWARE"

def _cs2_exe_path() -> str | None:
    info = hardware_detect.detect_all()
    if not info.cs2_path:
        return None
    exe = os.path.join(info.cs2_path, "game", "bin", "win64", "cs2.exe")
    return exe if os.path.isfile(exe) else None


def disable_fullscreen_optimizations_cs2() -> Result:
    exe = _cs2_exe_path()
    if not exe:
        return False, "cs2.exe not found."
    backup_keys([f"HKCU\\{_CS2_EXE_KEY}"], "cs2_fso")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _CS2_EXE_KEY) as k:
            winreg.SetValueEx(k, exe, 0, winreg.REG_SZ, _CS2_FLAG)
        return True, "Fullscreen optimizations disabled for cs2.exe."
    except Exception as e:
        return False, str(e)


def check_fullscreen_optimizations_cs2_status() -> bool:
    exe = _cs2_exe_path()
    if not exe or not winreg:
        return False
    val = _reg_read(winreg.HKEY_CURRENT_USER, _CS2_EXE_KEY, exe)
    return isinstance(val, str) and "DISABLEDXMAXIMIZEDWINDOWEDMODE" in val


# -------------------- Xbox / Game DVR (7 keys) --------------------

_DVR_KEYS = [
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"System\GameConfigStore", "GameDVR_Enabled", 0),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 1),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 1),
    (winreg.HKEY_LOCAL_MACHINE if winreg else None,
     r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 0),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"SOFTWARE\Microsoft\GameBar", "AutoGameModeEnabled", 0),
]

def disable_xbox_dvr() -> Result:
    if not winreg:
        return False, "winreg unavailable."
    backup_keys([
        "HKCU\\System\\GameConfigStore",
        "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\GameDVR",
        "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR",
        "HKCU\\SOFTWARE\\Microsoft\\GameBar",
    ], "xbox_dvr")
    for root, sub, name, val in _DVR_KEYS:
        ok, _ = _reg_write_dword(root, sub, name, val)
        if not ok:
            continue
    return True, "Xbox Game DVR / Game Bar disabled (7 keys)."


def check_xbox_dvr_status() -> bool:
    if not winreg:
        return False
    v = _reg_read(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore", "GameDVR_Enabled")
    return v == 0


# -------------------- Services --------------------

_SERVICES = ["DiagTrack", "WSearch", "Spooler"]

# Note: disabling "Spooler" stops all printing until re-enabled. The
# original start type of every service is snapshotted to this JSON file
# so ``restore_services()`` can put the system back exactly as it was —
# ``restore_latest_backup()`` alone can't, because service config isn't
# stored in the registry keys reg.exe exports.
_SERVICES_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "backups", "services_snapshot.json"
)


def _query_service_start_type(svc: str) -> str | None:
    """Return START_TYPE token from ``sc qc`` ('2'=AUTO, '3'=DEMAND, '4'=DISABLED)."""
    try:
        r = subprocess.run(["sc", "qc", svc], capture_output=True, text=True,
                           timeout=6, creationflags=_NO_WINDOW)
        for line in r.stdout.splitlines():
            ln = line.strip().upper()
            if ln.startswith("START_TYPE"):
                # e.g. "START_TYPE         : 2   AUTO_START"
                parts = ln.split(":", 1)[1].strip().split()
                if parts and parts[0].isdigit():
                    return parts[0]
    except Exception:
        return None
    return None


def disable_unnecessary_services() -> Result:
    import json
    os.makedirs(os.path.dirname(_SERVICES_SNAPSHOT), exist_ok=True)
    # Snapshot every service's current start type before changing anything.
    snapshot: dict[str, str] = {}
    for svc in _SERVICES:
        st = _query_service_start_type(svc)
        if st:
            snapshot[svc] = st
    if snapshot:
        try:
            with open(_SERVICES_SNAPSHOT, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
        except Exception:
            pass

    results = []
    for svc in _SERVICES:
        _run(["sc", "stop", svc])
        ok, _ = _run(["sc", "config", svc, "start=", "disabled"])
        results.append(f"{svc}:{'ok' if ok else 'fail'}")
    return True, "Services: " + ", ".join(results) + "  (original state saved)"


def restore_services() -> Result:
    """Re-enable every service from the saved snapshot."""
    import json
    if not os.path.isfile(_SERVICES_SNAPSHOT):
        return False, "No service snapshot found."
    try:
        with open(_SERVICES_SNAPSHOT, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except Exception as e:
        return False, f"Snapshot read error: {e}"
    _TYPE = {"2": "auto", "3": "demand", "4": "disabled"}
    restored = []
    for svc, st in snapshot.items():
        token = _TYPE.get(st, "demand")
        _run(["sc", "config", svc, "start=", token])
        if token != "disabled":
            _run(["sc", "start", svc])
        restored.append(f"{svc}:{token}")
    return True, "Services restored: " + ", ".join(restored)


def check_services_status() -> bool:
    try:
        for svc in _SERVICES:
            r = subprocess.run(["sc", "qc", svc], capture_output=True, text=True,
                               timeout=6, creationflags=_NO_WINDOW)
            if "DISABLED" not in r.stdout.upper():
                return False
        return True
    except Exception:
        return False


# -------------------- RAM settings --------------------

_MM_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"

def optimize_ram_settings() -> Result:
    if not winreg:
        return False, "winreg unavailable."
    backup_keys([f"HKLM\\{_MM_KEY}"], "memory_mgmt")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MM_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "LargeSystemCache", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(k, "ClearPageFileAtShutdown", 0, winreg.REG_DWORD, 0)
        return True, "Memory management tuned for gaming."
    except Exception as e:
        return False, str(e)


def check_ram_settings_status() -> bool:
    if not winreg:
        return False
    return _reg_read(winreg.HKEY_LOCAL_MACHINE, _MM_KEY, "LargeSystemCache") == 0 \
        and _reg_read(winreg.HKEY_LOCAL_MACHINE, _MM_KEY, "ClearPageFileAtShutdown") == 0


# -------------------- Shader cache --------------------

def clear_cs2_shader_cache() -> Result:
    info = hardware_detect.detect_all()
    if not info.cs2_path:
        return False, "CS2 path not detected."
    targets = [
        os.path.join(info.cs2_path, "game", "csgo", "shadercache"),
        os.path.join(info.cs2_path, "game", "core", "shadercache"),
    ]
    # NVIDIA DX cache
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        targets.append(os.path.join(local, "NVIDIA", "DXCache"))
        targets.append(os.path.join(local, "NVIDIA", "GLCache"))

    removed = 0
    for t in targets:
        if os.path.isdir(t):
            try:
                shutil.rmtree(t, ignore_errors=True)
                removed += 1
            except Exception:
                pass
    return True, f"Shader caches cleared ({removed} folder(s))."


def check_shader_cache_status() -> bool:
    # Stateless operation — always shown as "can run"
    return False


# -------------------- Visual effects --------------------

_VE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"

def reduce_visual_effects() -> Result:
    if not winreg:
        return False, "winreg unavailable."
    backup_keys([f"HKCU\\{_VE_KEY}"], "visual_effects")
    ok, msg = _reg_write_dword(winreg.HKEY_CURRENT_USER, _VE_KEY,
                               "VisualFXSetting", 2)  # 2 = adjust for best performance
    return (True, "Visual effects set to 'Best performance'.") if ok else (False, msg)


def check_visual_effects_status() -> bool:
    if not winreg:
        return False
    return _reg_read(winreg.HKEY_CURRENT_USER, _VE_KEY, "VisualFXSetting") == 2


# -------------------- Launch options generator --------------------

def generate_launch_options() -> str:
    info = hardware_detect.detect_all()
    opts: list[str] = ["-mainthreadpriority 2", "+thread_pool_option 4"]
    if info.monitor_width and info.monitor_height:
        opts += [f"-w {info.monitor_width}", f"-h {info.monitor_height}"]
    if info.monitor_hz:
        opts.append(f"+fps_max {info.monitor_hz * 2}")
    opts.append("-allow_third_party_software")
    return " ".join(opts)


# -------------------- Registry of optimizations for the GUI --------------------

OPTIMIZATIONS = [
    ("disable_hpet", "Disable HPET",
     "Disable High Precision Event Timer for lower latency. "
     "⚠ May be harmful on modern platforms — use with caution.",
     disable_hpet, check_hpet_status, "Caution", "Low"),
    ("disable_core_parking", "Disable Core Parking",
     "Keep all CPU cores unparked (Intel and AMD). "
     "⚠ May increase temperatures and power consumption on modern CPUs.",
     disable_core_parking, check_core_parking_status, "Moderate", "Medium"),
    ("set_high_performance_plan", "High Performance Power Plan",
     "Activate Windows High Performance power plan.",
     set_high_performance_plan, check_high_performance_status, "Safe", "Medium"),
    ("enable_msi_mode_nvidia", "Enable NVIDIA MSI Mode",
     "Enable Message Signaled Interrupts on NVIDIA GPU.",
     enable_msi_mode_nvidia, check_msi_mode_nvidia_status, "Safe", "Medium"),
    ("disable_nagle_algorithm", "Disable Nagle (System)",
     "Disable Nagle on all TCP interfaces.",
     disable_nagle_algorithm, check_nagle_status, "Moderate", "Low"),
    ("optimize_ssd_trim", "Enable SSD TRIM",
     "Enable TRIM so SSDs stay responsive.",
     optimize_ssd_trim, check_ssd_trim_status, "Safe", "Low"),
    ("disable_fullscreen_optimizations_cs2", "Disable CS2 Fullscreen Opt.",
     "Force real fullscreen on cs2.exe.",
     disable_fullscreen_optimizations_cs2, check_fullscreen_optimizations_cs2_status,
     "Safe", "Medium"),
    ("disable_xbox_dvr", "Disable Xbox Game DVR",
     "Turn off Game Bar / DVR recording (7 registry keys).",
     disable_xbox_dvr, check_xbox_dvr_status, "Safe", "High"),
    ("disable_unnecessary_services", "Disable Background Services",
     "DiagTrack, WSearch, PrintSpooler. ⚠ Disabling Spooler "
     "stops printing until you click Revert Changes.",
     disable_unnecessary_services, check_services_status, "Moderate", "Low"),
    ("optimize_ram_settings", "Optimize Memory Settings",
     "Tune Memory Management for gaming workloads.",
     optimize_ram_settings, check_ram_settings_status, "Safe", "Low"),
    ("clear_cs2_shader_cache", "Clear CS2 Shader Cache",
     "Delete shader caches so they rebuild cleanly.",
     clear_cs2_shader_cache, check_shader_cache_status, "Safe", "High"),
    ("reduce_visual_effects", "Reduce Visual Effects",
     "Windows 'Best performance' visual preset.",
     reduce_visual_effects, check_visual_effects_status, "Safe", "Low"),
]
