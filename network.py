"""Network optimizations for CS2 OMZ.

All functions operate on the currently active network adapter (auto-detected;
never hardcoded) and return ``(success, message)``. DNS changes are fully
reversible. Ping uses the system ``ping`` command via subprocess — no external
dependency required.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time

try:
    import winreg
except ImportError:
    winreg = None

from backup import backup_keys
from utils import (
    NO_WINDOW as _NO_WINDOW,
    Result,
    run_cmd as _run,
    KILLER_NIC_KEYWORDS,
    KILLER_SKIP_MESSAGE,
)
import hardware_detect


def _ensure_backup(keys, tag) -> Result:
    ok, _path, msg = backup_keys(keys, tag)
    if not ok:
        return False, f"Aborted — {msg}"
    return True, msg


def _is_killer_nic() -> bool:
    info = hardware_detect.detect_all()
    if getattr(info, "is_killer_nic", False):
        return True
    haystack = " ".join(filter(None, [
        info.active_adapter_name,
        getattr(info, "active_adapter_description", None),
    ])).lower()
    return any(k in haystack for k in KILLER_NIC_KEYWORDS)

_TCPIP_INTERFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "backups", "ping_results.json")


def _active_adapter():
    info = hardware_detect.detect_all()
    return info.active_adapter_name, info.active_adapter_guid


# -------------------- Nagle (per-adapter) --------------------

def disable_nagle_algorithm() -> Result:
    if _is_killer_nic():
        return False, KILLER_SKIP_MESSAGE
    name, guid = _active_adapter()
    if not guid or not winreg:
        return False, "Active adapter GUID not found."
    sub = f"{_TCPIP_INTERFACES}\\{guid}"
    bok, bmsg = _ensure_backup([f"HKLM\\{sub}"], "nagle_adapter")
    if not bok:
        return False, bmsg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "TcpDelAckTicks", 0, winreg.REG_DWORD, 0)
        return True, f"Nagle disabled on {name}."
    except Exception as e:
        return False, str(e)


def check_nagle_adapter_status() -> bool:
    _, guid = _active_adapter()
    if not guid or not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            f"{_TCPIP_INTERFACES}\\{guid}") as k:
            return winreg.QueryValueEx(k, "TcpAckFrequency")[0] == 1
    except OSError:
        return False


# -------------------- TCP stack --------------------

def optimize_tcp_stack() -> Result:
    if _is_killer_nic():
        return False, KILLER_SKIP_MESSAGE
    # (label, argv) pairs so failure messages identify which tweak failed.
    cmds = [
        ("RSS on",         ["netsh", "int", "tcp", "set", "global", "rss=enabled"]),
        ("DCA on",         ["netsh", "int", "tcp", "set", "global", "dca=enabled"]),
        ("ECN off",        ["netsh", "int", "tcp", "set", "global", "ecncapability=disabled"]),
        ("timestamps off", ["netsh", "int", "tcp", "set", "global", "timestamps=disabled"]),
        ("heuristics off", ["netsh", "int", "tcp", "set", "heuristics", "disabled"]),
    ]
    succeeded: list[str] = []
    failures: list[str] = []
    for label, argv in cmds:
        ok, msg = _run(argv)
        if ok:
            succeeded.append(label)
        else:
            failures.append(f"{label}: {msg}")
    if not failures:
        return True, "TCP stack tuned (" + ", ".join(succeeded) + ")."
    if not succeeded:
        return False, "TCP stack: all commands failed (" + "; ".join(failures) + ")"
    return False, (f"TCP stack: {len(succeeded)}/{len(cmds)} applied. "
                   "Failed: " + "; ".join(failures))


def _ps_query(script: str, timeout: int = 8) -> str:
    """Run a PowerShell one-liner and return stripped stdout (locale-independent)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def check_tcp_stack_status() -> bool:
    """RSS enabled AND ECN disabled AND timestamps disabled AND heuristics off.

    Uses Get-NetOffloadGlobalSetting + Get-NetTCPSetting which return
    structured English values regardless of the system locale (netsh
    output is localized and breaks string matching).
    """
    try:
        rss = _ps_query("(Get-NetOffloadGlobalSetting).ReceiveSideScaling")
        if rss.lower() != "enabled":
            return False
        tcp = _ps_query(
            "$s = Get-NetTCPSetting -SettingName Internet -ErrorAction SilentlyContinue; "
            "if ($s) { "
            "  \"$($s.EcnCapability);$($s.Timestamps);$($s.ScalingHeuristics)\" "
            "}"
        )
        if not tcp:
            return False
        ecn, ts, heur = [x.strip().lower() for x in tcp.split(";")]
        return ecn == "disabled" and ts == "disabled" and heur == "disabled"
    except Exception:
        return False


# -------------------- TCP autotuning --------------------

def disable_tcp_autotuning() -> Result:
    if _is_killer_nic():
        return False, KILLER_SKIP_MESSAGE
    return _run(["netsh", "int", "tcp", "set", "global", "autotuninglevel=disabled"])


def check_tcp_autotuning_status() -> bool:
    """True when AutoTuningLevelLocal is Disabled on the Internet profile."""
    val = _ps_query(
        "(Get-NetTCPSetting -SettingName Internet "
        "-ErrorAction SilentlyContinue).AutoTuningLevelLocal")
    return val.strip().lower() == "disabled"


# -------------------- QoS for CS2 --------------------

_QOS_KEY = r"SOFTWARE\Policies\Microsoft\Windows\QoS\CS2-OMZ"

def set_qos_cs2() -> Result:
    if not winreg:
        return False, "winreg unavailable."
    cs2 = hardware_detect.detect_all().cs2_path
    exe_path = ""
    if cs2:
        candidate = os.path.join(cs2, "game", "bin", "win64", "cs2.exe")
        if os.path.isfile(candidate):
            exe_path = candidate
    bok, bmsg = _ensure_backup(
        ["HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS"], "qos")
    if not bok:
        return False, bmsg
    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _QOS_KEY) as k:
            winreg.SetValueEx(k, "Version", 0, winreg.REG_SZ, "1.0")
            winreg.SetValueEx(k, "Application Name", 0, winreg.REG_SZ,
                              exe_path or "cs2.exe")
            winreg.SetValueEx(k, "Protocol", 0, winreg.REG_SZ, "*")
            winreg.SetValueEx(k, "Local Port", 0, winreg.REG_SZ, "*")
            winreg.SetValueEx(k, "Remote Port", 0, winreg.REG_SZ, "*")
            winreg.SetValueEx(k, "DSCP Value", 0, winreg.REG_SZ, "46")   # EF
            winreg.SetValueEx(k, "Throttle Rate", 0, winreg.REG_SZ, "-1")
        return True, "QoS policy for CS2 created (DSCP 46)."
    except Exception as e:
        return False, str(e)


def check_qos_cs2_status() -> bool:
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _QOS_KEY):
            return True
    except OSError:
        return False


# -------------------- Network adapter (power & interrupt moderation) --------------------

def optimize_network_adapter() -> Result:
    name, _ = _active_adapter()
    if not name:
        return False, "No active adapter."
    ps = (
        f"$a = Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue; "
        f"if ($a) {{ "
        f"Set-NetAdapterPowerManagement -Name '{name}' -AllowComputerToTurnOffDevice Disabled -ErrorAction SilentlyContinue; "
        f"Set-NetAdapterAdvancedProperty -Name '{name}' -DisplayName 'Interrupt Moderation' -DisplayValue 'Disabled' -ErrorAction SilentlyContinue; "
        f"Set-NetAdapterAdvancedProperty -Name '{name}' -DisplayName 'Energy-Efficient Ethernet' -DisplayValue 'Disabled' -ErrorAction SilentlyContinue; "
        f"Set-NetAdapterAdvancedProperty -Name '{name}' -DisplayName 'Flow Control' -DisplayValue 'Disabled' -ErrorAction SilentlyContinue; "
        f"}}"
    )
    return _run(["powershell", "-NoProfile", "-Command", ps])


def check_network_adapter_status() -> bool:
    """Considered applied when power-saving is off AND at least one of the
    advanced properties we touched (interrupt moderation / EEE / flow
    control) is Disabled. We don't require all three because some NICs
    don't expose every property — missing ones return empty strings."""
    name, _ = _active_adapter()
    if not name:
        return False
    script = (
        f"$n='{name}'; "
        "$p=(Get-NetAdapterPowerManagement -Name $n -ErrorAction SilentlyContinue)."
        "AllowComputerToTurnOffDevice; "
        "$im=(Get-NetAdapterAdvancedProperty -Name $n -DisplayName 'Interrupt Moderation' "
        "-ErrorAction SilentlyContinue).DisplayValue; "
        "$eee=(Get-NetAdapterAdvancedProperty -Name $n -DisplayName 'Energy-Efficient Ethernet' "
        "-ErrorAction SilentlyContinue).DisplayValue; "
        "$fc=(Get-NetAdapterAdvancedProperty -Name $n -DisplayName 'Flow Control' "
        "-ErrorAction SilentlyContinue).DisplayValue; "
        "\"$p|$im|$eee|$fc\""
    )
    out = _ps_query(script)
    if not out or "|" not in out:
        return False
    power, im, eee, fc = [x.strip() for x in out.split("|")]
    if power and power.lower() != "disabled":
        return False
    advanced = [v for v in (im, eee, fc) if v]
    if not advanced:
        # Only power-saving was available and it's disabled → consider applied.
        return bool(power) and power.lower() == "disabled"
    return any(v.lower() == "disabled" for v in advanced)


# -------------------- DNS --------------------

_DNS_PROVIDERS = {
    "cloudflare": ("1.1.1.1", "1.0.0.1"),
    "google": ("8.8.8.8", "8.8.4.4"),
}

def set_dns(provider: str) -> Result:
    name, _ = _active_adapter()
    if not name:
        return False, "No active adapter."
    provider = provider.lower()
    if provider in ("default", "dhcp", "revert"):
        ok1, _ = _run(["netsh", "interface", "ipv4", "set", "dnsservers",
                       f"name={name}", "source=dhcp"])
        ok2, _ = _run(["netsh", "interface", "ipv6", "set", "dnsservers",
                       f"name={name}", "source=dhcp"])
        return ok1 or ok2, f"DNS reverted to DHCP on {name}."
    if provider not in _DNS_PROVIDERS:
        return False, f"Unknown provider: {provider}"
    primary, secondary = _DNS_PROVIDERS[provider]
    ok, msg = _run(["netsh", "interface", "ipv4", "set", "dnsservers",
                    f"name={name}", "static", primary, "primary"])
    if ok:
        _run(["netsh", "interface", "ipv4", "add", "dnsservers",
              f"name={name}", secondary, "index=2"])
    return ok, f"DNS set to {provider.title()} ({primary}/{secondary}) on {name}." \
        if ok else f"DNS error: {msg}"


def check_dns_provider() -> str:
    name, _ = _active_adapter()
    if not name:
        return "unknown"
    try:
        r = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={name}"],
            capture_output=True, text=True, timeout=6,
            creationflags=_NO_WINDOW)
        out = r.stdout
        if "1.1.1.1" in out:
            return "cloudflare"
        if "8.8.8.8" in out:
            return "google"
        if "DHCP" in out.upper():
            return "default"
        return "custom"
    except Exception:
        return "unknown"


# -------------------- Ping Valve servers --------------------

# Valve SDR (Steam Datagram Relay) ingress endpoints per region.
#
# Valve blocks ICMP on their relays, so we measure latency by timing the
# TCP three-way handshake instead. SDR ingress IPs also rotate over time
# and many relay IPs filter inbound TCP entirely — so each region has a
# list of candidates and we use the first one that responds. If every
# candidate is down we fall back to the global Steam API endpoint so the
# before/after comparison still produces a reading.
VALVE_SERVERS: dict[str, list[str]] = {
    "Stockholm": ["146.66.152.10", "146.66.152.11", "155.133.234.10",
                  "155.133.234.11", "155.133.233.10"],
    "Frankfurt": ["155.133.232.10", "155.133.232.11", "146.66.158.10",
                  "146.66.159.10", "185.25.180.10"],
    "Warsaw":    ["155.133.230.10", "155.133.229.10", "146.66.155.10",
                  "146.66.156.10"],
    "Madrid":    ["155.133.238.10", "155.133.240.10", "146.66.157.10",
                  "146.66.158.11"],
}
_GLOBAL_FALLBACK = ("api.steampowered.com", "steamcommunity.com")

# Ports to try, in order. 27015 is the classic Source/CS2 game port (often
# firewalled on relays); 443 almost always answers and gives a clean RTT.
_TCP_PORTS = (27015, 443, 80)
_TCP_TIMEOUT = 1.5  # seconds per attempt


def _resolve(host: str) -> str | None:
    # Already an IPv4 literal?
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def _tcp_connect_ms(ip: str, port: int, timeout: float = _TCP_TIMEOUT) -> float | None:
    """Return time-to-TCP-handshake in ms, or None on failure.

    Works regardless of ICMP being blocked: we only need the remote to
    respond to SYN with SYN-ACK (or RST — see below).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    start = time.perf_counter()
    try:
        sock.connect((ip, port))
        elapsed = (time.perf_counter() - start) * 1000.0
        return elapsed
    except socket.timeout:
        return None
    except ConnectionRefusedError:
        # A RST came back — still a valid RTT measurement.
        return (time.perf_counter() - start) * 1000.0
    except OSError:
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _measure_latency(hosts: list[str], samples: int = 3) -> float | None:
    """Try each host/port combo until one answers, then take the best of
    ``samples`` TCP handshakes to smooth out jitter."""
    for host in hosts:
        ip = _resolve(host)
        if not ip:
            continue
        for port in _TCP_PORTS:
            first = _tcp_connect_ms(ip, port)
            if first is None:
                continue
            timings = [first]
            for _ in range(samples - 1):
                t = _tcp_connect_ms(ip, port)
                if t is not None:
                    timings.append(t)
            # Best (min) is a better proxy for true RTT than average,
            # since TCP handshakes can get queued by the remote.
            return round(min(timings), 1)
    return None


def ping_valve_servers() -> dict[str, float | None]:
    """Measure TCP-handshake RTT to each Valve region. Returns ms (or None).

    Strategy per region:
      1. Try each candidate SDR relay IP on ports 27015 / 443 / 80.
      2. If every candidate times out (Valve routinely filters TCP on
         SDR relays), fall back to the global Steam endpoint so the
         before/after comparison still produces a number. That fallback
         is shared across regions, so if a region shows the same value
         as others it almost certainly hit the fallback — still useful
         for detecting changes introduced by the optimizations.
    """
    results: dict[str, float | None] = {}
    fallback_ms: float | None = None
    for label, hosts in VALVE_SERVERS.items():
        ms = _measure_latency(hosts)
        if ms is None:
            if fallback_ms is None:
                fallback_ms = _measure_latency(list(_GLOBAL_FALLBACK))
            ms = fallback_ms
        results[label] = ms
    return results


def _save_results(tag: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_RESULTS_FILE), exist_ok=True)
        all_data = {}
        if os.path.isfile(_RESULTS_FILE):
            try:
                with open(_RESULTS_FILE, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            except Exception:
                all_data = {}
        all_data[tag] = data
        with open(_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_data, f, indent=2)
    except Exception:
        pass


def _load_results(tag: str) -> dict:
    try:
        with open(_RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get(tag, {})
    except Exception:
        return {}


def run_latency_test_before() -> dict[str, float | None]:
    r = ping_valve_servers()
    _save_results("before", r)
    return r


def run_latency_test_after() -> dict[str, float | None]:
    r = ping_valve_servers()
    _save_results("after", r)
    return r


def get_latency_comparison() -> dict:
    return {"before": _load_results("before"), "after": _load_results("after")}


# -------------------- Registry of network ops for the GUI --------------------

NETWORK_OPTIMIZATIONS = [
    ("disable_nagle_adapter", "Disable Nagle (Adapter)",
     "Disable Nagle on the active network adapter.",
     disable_nagle_algorithm, check_nagle_adapter_status, "Moderate", "Low"),
    ("optimize_tcp_stack", "Optimize TCP Stack",
     "Tune RSS, DCA, ECN, and heuristics for low latency.",
     optimize_tcp_stack, check_tcp_stack_status, "Moderate", "Medium"),
    ("disable_tcp_autotuning", "Disable TCP Autotuning",
     "Reduce jitter by disabling TCP window autotuning.",
     disable_tcp_autotuning, check_tcp_autotuning_status, "Caution", "Low"),
    ("set_qos_cs2", "Prioritize CS2 Traffic (QoS)",
     "Create a QoS policy tagging CS2 packets with DSCP 46.",
     set_qos_cs2, check_qos_cs2_status, "Safe", "Medium"),
    ("optimize_network_adapter", "Optimize Network Adapter",
     "Disable power saving and interrupt moderation on the active adapter.",
     optimize_network_adapter, check_network_adapter_status, "Safe", "Medium"),
]
