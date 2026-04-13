"""Hardware and system detection for CS2 OMZ."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

try:
    import wmi
except ImportError:
    wmi = None

try:
    import winreg
except ImportError:
    winreg = None

# Hide any console window spawned by subprocess (netsh, etc.).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class HardwareInfo:
    cpu_name: str = "Unknown"
    cpu_cores: int = 0
    cpu_threads: int = 0
    cpu_generation: str = "Unknown"
    cpu_vendor: str = "Unknown"  # Intel / AMD

    gpu_name: str = "Unknown"
    gpu_vram_mb: int = 0
    gpu_vendor: str = "Unknown"  # NVIDIA / AMD / Intel

    ram_total_gb: float = 0.0
    ram_frequency_mhz: int = 0

    monitor_width: int = 0
    monitor_height: int = 0
    monitor_hz: int = 60

    steam_path: Optional[str] = None
    cs2_path: Optional[str] = None

    active_adapter_name: Optional[str] = None
    active_adapter_guid: Optional[str] = None
    current_dns: list = field(default_factory=list)

    has_ssd: bool = False
    has_hdd: bool = False


def _detect_cpu_generation(name: str) -> str:
    """Best-effort CPU generation extraction for Intel/AMD."""
    if not name:
        return "Unknown"
    # Intel Core iX-YYYY: first digit(s) of YYYY = generation
    m = re.search(r"i[3579]-(\d{4,5})", name)
    if m:
        digits = m.group(1)
        gen = digits[0] if len(digits) == 4 else digits[:2]
        return f"{gen}th Gen Intel"
    # AMD Ryzen X XXXX
    m = re.search(r"Ryzen\s+\d\s+(\d{4})", name)
    if m:
        return f"Ryzen {m.group(1)[0]}000 series"
    return "Unknown"


def _detect_cpu(info: HardwareInfo) -> None:
    try:
        if wmi:
            c = wmi.WMI()
            for cpu in c.Win32_Processor():
                info.cpu_name = (cpu.Name or "Unknown").strip()
                info.cpu_cores = int(cpu.NumberOfCores or 0)
                info.cpu_threads = int(cpu.NumberOfLogicalProcessors or 0)
                info.cpu_vendor = "Intel" if "Intel" in info.cpu_name else (
                    "AMD" if "AMD" in info.cpu_name or "Ryzen" in info.cpu_name else "Unknown"
                )
                info.cpu_generation = _detect_cpu_generation(info.cpu_name)
                break
        elif psutil:
            info.cpu_cores = psutil.cpu_count(logical=False) or 0
            info.cpu_threads = psutil.cpu_count(logical=True) or 0
    except Exception:
        pass


_GPU_BLACKLIST = ("microsoft basic", "basic display", "basic render",
                  "remote display", "meta virtual", "virtual display")

_VENDOR_KEYWORDS = (
    ("NVIDIA", ("NVIDIA", "GEFORCE", "RTX", "GTX", "QUADRO", "TESLA")),
    ("AMD",    ("AMD", "RADEON", "RYZEN GRAPHICS", "VEGA", "FIREPRO")),
    ("Intel",  ("INTEL", "IRIS", "UHD GRAPHICS", "HD GRAPHICS", "ARC")),
)


def _classify_vendor(name: str) -> str:
    up = (name or "").upper()
    for vendor, keywords in _VENDOR_KEYWORDS:
        if any(k in up for k in keywords):
            return vendor
    return "Unknown"


def _read_gpu_vram_from_registry() -> int:
    """Return VRAM in MB by reading HardwareInformation.qwMemorySize (REG_QWORD)
    from each display adapter device key. Win32_VideoController.AdapterRAM is
    UINT32 and overflows to -1 for GPUs with >=4GB VRAM — the registry value
    is 64-bit and authoritative."""
    if not winreg:
        return 0
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    best_mb = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        # Skip basic/virtual adapters
                        try:
                            desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        except OSError:
                            desc = ""
                        if desc and any(b in desc.lower() for b in _GPU_BLACKLIST):
                            continue
                        size = 0
                        for val in ("HardwareInformation.qwMemorySize",
                                    "HardwareInformation.MemorySize"):
                            try:
                                raw = winreg.QueryValueEx(k, val)[0]
                            except OSError:
                                continue
                            if isinstance(raw, (bytes, bytearray)) and len(raw) >= 4:
                                raw = int.from_bytes(raw[:8], "little", signed=False)
                            if isinstance(raw, int) and raw > 0:
                                size = raw
                                break
                        if size > 0:
                            mb = size // (1024 * 1024)
                            if mb > best_mb:
                                best_mb = mb
                except OSError:
                    continue
    except OSError:
        return 0
    return best_mb


def _detect_gpu(info: HardwareInfo) -> None:
    try:
        if not wmi:
            return
        c = wmi.WMI()
        # Always skip basic/virtual adapters; pick the first discrete GPU.
        candidates = []
        for gpu in c.Win32_VideoController():
            name = (gpu.Name or "").strip()
            if not name:
                continue
            if any(b in name.lower() for b in _GPU_BLACKLIST):
                continue
            candidates.append(gpu)

        # Prefer NVIDIA/AMD discrete GPUs over Intel integrated.
        def _rank(g):
            v = _classify_vendor(g.Name or "")
            return {"NVIDIA": 0, "AMD": 1, "Intel": 2, "Unknown": 3}.get(v, 3)
        candidates.sort(key=_rank)

        best = candidates[0] if candidates else None
        if best:
            info.gpu_name = (best.Name or "Unknown").strip()
            info.gpu_vendor = _classify_vendor(info.gpu_name)

            # VRAM: prefer the 64-bit registry value (qwMemorySize) because
            # Win32_VideoController.AdapterRAM is UINT32 and wraps to -1 for
            # cards with 4GB+ of memory.
            vram_mb = _read_gpu_vram_from_registry()
            if vram_mb <= 0:
                try:
                    raw = int(best.AdapterRAM or 0)
                    # Treat negative/overflow as unknown rather than reporting -1
                    if raw > 0:
                        vram_mb = raw // (1024 * 1024)
                except Exception:
                    vram_mb = 0
            info.gpu_vram_mb = max(0, vram_mb)
    except Exception:
        pass


def _detect_ram(info: HardwareInfo) -> None:
    try:
        if psutil:
            info.ram_total_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        if wmi:
            c = wmi.WMI()
            freqs = []
            for mem in c.Win32_PhysicalMemory():
                if mem.ConfiguredClockSpeed:
                    freqs.append(int(mem.ConfiguredClockSpeed))
                elif mem.Speed:
                    freqs.append(int(mem.Speed))
            if freqs:
                info.ram_frequency_mhz = max(freqs)
    except Exception:
        pass


def _detect_monitor(info: HardwareInfo) -> None:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        info.monitor_width = user32.GetSystemMetrics(0)
        info.monitor_height = user32.GetSystemMetrics(1)
    except Exception:
        pass
    try:
        # Refresh rate via WMI
        if wmi:
            c = wmi.WMI()
            for m in c.Win32_VideoController():
                if m.CurrentRefreshRate:
                    info.monitor_hz = int(m.CurrentRefreshRate)
                    break
    except Exception:
        pass


def _detect_steam(info: HardwareInfo) -> None:
    if not winreg:
        return
    candidates = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam", "SteamPath"),
    ]
    for root, sub, val in candidates:
        try:
            with winreg.OpenKey(root, sub) as k:
                path = winreg.QueryValueEx(k, val)[0]
                if path and os.path.isdir(path):
                    info.steam_path = path.replace("/", "\\")
                    break
        except OSError:
            continue

    if not info.steam_path:
        return

    # Parse libraryfolders.vdf to locate CS2 across drives
    vdf = os.path.join(info.steam_path, "steamapps", "libraryfolders.vdf")
    libraries = [info.steam_path]
    try:
        if os.path.isfile(vdf):
            with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', data):
                libraries.append(m.group(1).replace("\\\\", "\\"))
    except Exception:
        pass

    for lib in libraries:
        cs2 = os.path.join(lib, "steamapps", "common", "Counter-Strike Global Offensive")
        if os.path.isdir(cs2):
            info.cs2_path = cs2
            break


def _detect_storage(info: HardwareInfo) -> None:
    """Detect if any SSD/HDD is present. Uses MSFT_PhysicalDisk.MediaType:
    3=HDD, 4=SSD, 5=SCM. Falls back to Win32_DiskDrive MediaType string."""
    try:
        if wmi:
            try:
                c = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
                for d in c.MSFT_PhysicalDisk():
                    mt = int(getattr(d, "MediaType", 0) or 0)
                    if mt == 4:
                        info.has_ssd = True
                    elif mt == 3:
                        info.has_hdd = True
            except Exception:
                # Namespace not available — try legacy WMI
                c = wmi.WMI()
                for d in c.Win32_DiskDrive():
                    model = (d.Model or "").lower()
                    if "ssd" in model or "nvme" in model:
                        info.has_ssd = True
                    else:
                        info.has_hdd = True
    except Exception:
        pass


def _detect_network(info: HardwareInfo) -> None:
    """Find active (connected, non-loopback) network adapter and its DNS."""
    try:
        if not psutil:
            return
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        best = None
        for name, st in stats.items():
            if not st.isup:
                continue
            if name.lower().startswith(("loopback", "lo")):
                continue
            if "virtual" in name.lower() or "vmware" in name.lower() or "vethernet" in name.lower():
                continue
            # Must have IPv4
            if name in addrs and any(a.family.name == "AF_INET" for a in addrs[name]):
                best = name
                break
        if best:
            info.active_adapter_name = best
    except Exception:
        pass

    # Adapter GUID via registry mapping (NetCfgInstanceId) — needed for TCP tweaks
    try:
        if winreg and info.active_adapter_name:
            path = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
                i = 0
                while True:
                    try:
                        guid = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, guid + r"\Connection") as sk:
                            nm = winreg.QueryValueEx(sk, "Name")[0]
                            if nm == info.active_adapter_name:
                                info.active_adapter_guid = guid
                                break
                    except OSError:
                        continue
    except Exception:
        pass

    # Current DNS via netsh
    try:
        if info.active_adapter_name:
            out = subprocess.run(
                ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={info.active_adapter_name}"],
                capture_output=True, text=True, timeout=6,
                creationflags=_NO_WINDOW,
            ).stdout
            dns = re.findall(r"(\d{1,3}(?:\.\d{1,3}){3})", out)
            info.current_dns = dns
    except Exception:
        pass


def detect_all() -> HardwareInfo:
    """Run every detector; exceptions in one never break the others."""
    info = HardwareInfo()
    for fn in (_detect_cpu, _detect_gpu, _detect_ram, _detect_monitor,
               _detect_steam, _detect_storage, _detect_network):
        try:
            fn(info)
        except Exception:
            continue
    return info


if __name__ == "__main__":
    h = detect_all()
    for k, v in h.__dict__.items():
        print(f"{k}: {v}")
