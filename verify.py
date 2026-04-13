"""Command-line verifier for CS2 OMZ.

Iterates every optimization registered in optimizer.OPTIMIZATIONS,
network.NETWORK_OPTIMIZATIONS, and network.UDP_OPTIMIZATIONS and calls
its check_* function to report the current system state. Also verifies
that monitor Hz is detected correctly. Does not modify anything.

Usage:
    python verify.py
"""
from __future__ import annotations

import sys

import hardware_detect
import optimizer
import network

# Force UTF-8 output so emoji in status icons survive Windows cp1252 terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Per-key verbs: the GUI phrases each check as "is it applied?" — but on
# the command line we want a word that matches the change direction, so
# "Disable HPET" applied reads as "HPET: DISABLED" rather than "APPLIED".
_APPLIED_WORDS = {
    "disable_hpet":                       ("DISABLED",  "ENABLED"),
    "disable_core_parking":               ("DISABLED",  "PARKED"),
    "set_high_performance_plan":          ("ACTIVE",    "INACTIVE"),
    "enable_msi_mode_nvidia":             ("ENABLED",   "DISABLED"),
    "disable_nagle_algorithm":            ("DISABLED",  "ENABLED"),
    "optimize_ssd_trim":                  ("ENABLED",   "DISABLED"),
    "disable_fullscreen_optimizations_cs2": ("DISABLED", "ENABLED"),
    "disable_xbox_dvr":                   ("DISABLED",  "ENABLED"),
    "disable_unnecessary_services":       ("DISABLED",  "RUNNING"),
    "optimize_ram_settings":              ("TUNED",     "DEFAULT"),
    "clear_cs2_shader_cache":             ("CLEARED",   "PRESENT"),
    "reduce_visual_effects":              ("REDUCED",   "DEFAULT"),
    "disable_nagle_adapter":              ("DISABLED",  "ENABLED"),
    "optimize_tcp_stack":                 ("TUNED",     "DEFAULT"),
    "disable_tcp_autotuning":             ("DISABLED",  "ENABLED"),
    "set_qos_cs2":                        ("ACTIVE",    "INACTIVE"),
    "optimize_network_adapter":           ("TUNED",     "DEFAULT"),
    # UDP / CS2-direct
    "optimize_udp_buffer":                ("TUNED",     "DEFAULT"),
    "generate_cs2_autoexec":              ("WRITTEN",   "NOT WRITTEN"),
    "optimize_qos_udp_cs2":              ("ACTIVE",    "INACTIVE"),
}


def _status(key: str, applied: bool) -> str:
    on_word, off_word = _APPLIED_WORDS.get(key, ("APPLIED", "NOT APPLIED"))
    word = on_word if applied else off_word
    icon = "✅" if applied else "❌"
    return f"{word} {icon}"


def _run_section(title: str, entries) -> tuple[int, int]:
    print(f"\n=== {title} ===")
    applied_count = 0
    total = 0
    name_width = max(len(entry[1]) for entry in entries) + 2
    for entry in entries:
        key, title_str, _desc, _apply_fn, check_fn = entry[:5]
        total += 1
        try:
            applied = bool(check_fn())
        except Exception as e:
            print(f"  {title_str:<{name_width}} ERROR: {e}")
            continue
        if applied:
            applied_count += 1
        print(f"  {title_str:<{name_width}} {_status(key, applied)}")
    return applied_count, total


def _check_monitor_hz() -> None:
    print("\n=== Hardware detection ===")
    try:
        hw = hardware_detect.detect_all()
        hz = hw.monitor_hz
        ok = isinstance(hz, int) and hz > 0
        icon = "✅" if ok else "❌"
        print(f"  monitor_hz detection   {hz} Hz {icon}")
        if not ok:
            print("    WARNING: monitor_hz is 0 or invalid — "
                  "fps_max will fall back to 240")
    except Exception as e:
        print(f"  monitor_hz detection   ERROR: {e}")


def main() -> int:
    print("CS2 OMZ — system verification")
    print("=" * 60)

    _check_monitor_hz()

    sys_ok, sys_total = _run_section("System optimizations",
                                     optimizer.OPTIMIZATIONS)
    net_ok, net_total = _run_section("Network optimizations (Windows background)",
                                     network.NETWORK_OPTIMIZATIONS)
    udp_ok, udp_total = _run_section("CS2 direct optimizations (UDP)",
                                     network.UDP_OPTIMIZATIONS)

    total_ok = sys_ok + net_ok + udp_ok
    total = sys_total + net_total + udp_total
    print("\n" + "=" * 60)
    print(f"Summary: {total_ok}/{total} applied  "
          f"(system {sys_ok}/{sys_total}, "
          f"network {net_ok}/{net_total}, "
          f"udp {udp_ok}/{udp_total})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
