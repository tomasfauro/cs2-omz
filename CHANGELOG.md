# Changelog

All notable changes to CS2 OMZ are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-04-13

First public release.

### System Optimizations
- `disable_hpet()` — remove `useplatformclock`, set `disabledynamictick yes`.
- `disable_core_parking()` — Intel & AMD, forces `ValueMax=0`.
- `set_high_performance_plan()` — activates the High Performance power scheme.
- `enable_msi_mode_nvidia()` — MSI mode on NVIDIA GPUs only (no-op otherwise).
- `disable_nagle_algorithm()` — system-wide Nagle disable.
- `optimize_ssd_trim()` — enable NTFS TRIM.
- `disable_fullscreen_optimizations_cs2()` — AppCompat flag on `cs2.exe`.
- `disable_xbox_dvr()` — 7 registry keys across HKCU/HKLM.
- `disable_unnecessary_services()` — SysMain, DiagTrack, WSearch, Spooler.
- `optimize_ram_settings()` — Memory Management tuning for gaming.
- `clear_cs2_shader_cache()` — wipe CS2 + NVIDIA shader caches.
- `reduce_visual_effects()` — Windows "Best performance" preset.
- Auto-detection of applied status on startup via `check_*_status()` helpers.
- Every registry write is preceded by a timestamped `.reg` backup.
- One-click **Revert Changes** imports the most recent backup.

### Network Optimizations
- `disable_nagle_algorithm()` — active-adapter Nagle disable.
- `optimize_tcp_stack()` — RSS on, DCA on, chimney/ECN/heuristics off.
- `disable_tcp_autotuning()` — reduces jitter.
- `set_qos_cs2()` — QoS policy tagging CS2 traffic as DSCP 46.
- `optimize_network_adapter()` — disables power saving, interrupt moderation,
  Energy-Efficient Ethernet, flow control on the active adapter.
- `set_dns(provider)` — Cloudflare / Google / revert-to-DHCP switcher.
- `ping_valve_servers()` — Stockholm, Frankfurt, Warsaw, Madrid.
- `run_latency_test_before()` / `run_latency_test_after()` comparison.
- Active adapter auto-detection — never hardcoded.

### Launch Options Generator
- Personalized string built from detected monitor Hz, CPU threads, RAM, resolution.
- GUI explanation for every flag.
- One-click **Copy to Clipboard**.

### GUI
- CustomTkinter dark theme, 900x650, three tabs: System / Network / Launch Options.
- Version badge (`v1.0.0`) in the header.
- Real-time log panels on System and Network tabs.
- Admin-required dialog on launch if not elevated.
