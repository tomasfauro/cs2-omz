# CS2 OMZ

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()

**CS2 OMZ** is a one-click optimizer for Counter-Strike 2 on Windows.
It detects your hardware, applies safe system and network tweaks, generates
personalized CS2 launch options, and writes a tuned `autoexec.cfg` — all
without asking you to touch the registry, `netsh`, or `powercfg` yourself.

## Origin story

CS2 OMZ was born from a real stuttering problem on an **i7-6700 + GTX 1060**
running CS2. The usual "disable this, tweak that" guides scattered across
Reddit and forums worked, but they required hours of reading and a lot of
trust in random `.reg` files. This tool packages the ones that actually
moved the needle into a single, reversible, auditable app.

## Features

### System Optimizations
- **Disable HPET** — removes `useplatformclock`, sets `disabledynamictick yes`. `Caution` `Low impact`
- **Disable Core Parking** — forces `ValueMax=0` on all cores (Intel & AMD). `Safe` `Medium impact`
- **High Performance Power Plan** — activates the classic high-perf scheme. `Safe` `High impact`
- **Enable NVIDIA MSI Mode** — message-signaled interrupts on NVIDIA GPUs only. `Safe` `High impact`
- **Disable Nagle (System)** — sets `TcpAckFrequency=1`, `TCPNoDelay=1` on every interface. `Safe` `Medium impact`
- **Enable SSD TRIM** — `fsutil behavior set DisableDeleteNotify 0`. `Safe` `Low impact`
- **Disable CS2 Fullscreen Optimizations** — forces exclusive fullscreen on `cs2.exe`. `Safe` `Medium impact`
- **Disable Xbox Game DVR** — 7 registry keys across HKCU/HKLM. `Safe` `Medium impact`
- **Disable Background Services** — SysMain, DiagTrack, WSearch, PrintSpooler. `Safe` `Medium impact`
- **Optimize Memory Settings** — `DisablePagingExecutive=1`, `LargeSystemCache=0`. `Safe` `Low impact`
- **Clear CS2 Shader Cache** — wipes CS2 + NVIDIA DX/GL caches for a clean rebuild. `Safe` `Low impact`
- **Reduce Visual Effects** — Windows "Best performance" preset. `Safe` `Low impact`

![Main Window](assets/screenshots/main.png)

### Network Optimizations
- **Disable Nagle (Adapter)** — applied to the auto-detected active adapter. `Safe` `Medium impact`
- **Optimize TCP Stack** — RSS on, DCA on, chimney offload off, ECN off, heuristics disabled. `Safe` `Medium impact`
- **Disable TCP Autotuning** — reduces jitter on unstable links. `Safe` `Medium impact`
- **Prioritize CS2 Traffic (QoS)** — DSCP-46 QoS policy for `cs2.exe` covering TCP and UDP. `Safe` `Medium impact`
- **Optimize Network Adapter** — disables power saving, interrupt moderation, EEE, flow control. `Safe` `Medium impact`
- **DNS switcher** — Cloudflare (`1.1.1.1`) / Google (`8.8.8.8`) / revert to DHCP with one click.
- **Valve server ping test** — ping Stockholm, Frankfurt, Warsaw, Madrid before/after and compare.

> **Killer NIC auto-detection:** if a Killer (Intel/Rivet Networks) NIC is detected, TCP-level
> tweaks that are unsupported on that hardware (Nagle adapter, TCP stack) are automatically
> skipped. Adapter power/interrupt properties that *do* work on Killer hardware are applied
> normally.

![Network Tab](assets/screenshots/network.png)

### CS2 UDP Optimizations
- **Increase UDP Socket Buffers** — raises `SO_RCVBUF`/`SO_SNDBUF` for smoother packet flow. `Safe` `Medium impact`
- **UDP QoS (port 27005)** — DSCP-46 QoS policy scoped to CS2's default game port. `Safe` `Medium impact`

### Game Config tab

#### Launch Options Generator
Generates a launch string personalized to your detected hardware:

| Flag | Purpose |
|---|---|
| `-mainthreadpriority 2` | Raise CS2 main thread priority for smoother frametimes |
| `+thread_pool_option 4` | Use the Source 2 worker thread pool tuned for gameplay |
| `+fps_max <Hz×2>` | Cap FPS at 2× your detected monitor refresh rate |
| `-allow_third_party_software` | Allow RivaTuner / MSI Afterburner overlay |

Resolution (`-w`/`-h`) is intentionally excluded — it is a personal preference and should be
set inside CS2 video settings. Outdated flags (`-novid`, `+mat_queue_mode 2`, `-high`) have
been removed as they have no effect or are counterproductive in modern CS2.

Click **Copy to Clipboard** and paste into Steam → right-click CS2 → Properties → Launch Options.

#### autoexec.cfg Generator
Writes a `autoexec.cfg` tuned to your hardware directly to your CS2 `cfg/` folder. Sections:

- **Network** — `rate`, `cl_updaterate`, `cl_cmdrate` matched to your connection.
- **Performance** — `fps_max` set to `monitor Hz × 2` (auto-detected via `GetDeviceCaps`).
- **Mouse** — raw input, no acceleration.
- **HUD** — clean competitive HUD layout.
- **Competitive** — radar scale, crosshair spread, buy binds.
- **Audio** — low-latency audio settings.

![Game Config Tab](assets/screenshots/launch.png)

## How to use

1. Download the latest `CS2OMZ.exe` from the Releases page.
2. Right-click it and choose **Run as administrator**.
3. On the **System** tab, review each optimization's risk and impact badge. Pick what you
   want and click **Optimize Selected**, or just click **Apply All**.
4. Switch to the **Network** tab. Click **Test Ping** to establish a baseline, then
   **Optimize Network**, then **Test Ping** again to see the before/after.
5. On the **CS2 UDP** tab, apply UDP buffer and QoS tweaks specific to CS2's game traffic.
6. On the **Game Config** tab:
   - Click **Copy to Clipboard** and paste the launch options into Steam → CS2 → Properties → Launch Options.
   - Click **Generate autoexec.cfg** to write a tuned config to your CS2 `cfg/` folder.
7. Restart your PC so every change takes effect.

Every registry change is backed up to `backups/<tag>_<timestamp>.reg` before being applied.
**Revert Changes** restores the backup taken at the start of the current session.

## Build from source

```bash
git clone https://github.com/tomasfauro/cs2-omz
cd cs2-omz
pip install -r requirements.txt
python main.py
```

To build a single-file executable:

```bash
build.bat
```

Output: `dist\CS2OMZ.exe`.

## Contributing

PRs welcome — especially from players on AMD hardware or unusual monitor setups. Good first issues:

- New optimizations with clear before/after evidence
- Localization (Spanish, Portuguese, Russian first)
- Additional Valve region servers for the ping test

Please keep each optimization:
- Independent (its own function).
- Reversible (registry change → backup first).
- Safe to run twice (idempotent).
- Covered by a `check_*_status()` helper.

## VAC Safe?

**Yes — CS2 OMZ is 100% VAC safe.**

CS2 OMZ only modifies **Windows system settings**: registry keys, services,
power plans, TCP stack parameters, and network adapter properties. It does
**not**:

- Read, write, or modify any CS2 game file.
- Attach to, inject into, or read memory from the `cs2.exe` process.
- Hook DirectX, OpenGL, or any Source 2 API.
- Load drivers or kernel modules.
- Touch anything inside your Steam or CS2 install directory (except for
  the optional **Clear CS2 Shader Cache** action, which deletes Valve's
  own regeneratable shader cache folder — never game code or assets).

The `autoexec.cfg` generator writes only standard CS2 console commands — the
same commands any player types manually. It does not modify game binaries or
inject code.

Valve Anti-Cheat inspects the CS2 process and its loaded modules. Because
CS2 OMZ runs entirely outside that boundary and exits before you launch
the game, there is nothing for VAC to flag. The launch options it generates
use only documented Source 2 engine flags.

## VirusTotal / Antivirus

A scan of `CS2OMZ.exe` on VirusTotal shows **4 / 72 vendors** flagging the
file. This is a well-known false positive associated with any
[PyInstaller](https://pyinstaller.org/) executable that requests
administrator privileges via `--uac-admin` — the PyInstaller bootloader
is a common template that a handful of heuristic scanners fingerprint,
regardless of what the bundled Python code actually does.

CS2 OMZ is **fully open source**. If you don't want to trust the
prebuilt binary, verify it yourself:

- Read every line of source in this repository.
- Build your own `CS2OMZ.exe` from source with `build.bat`.
- Compare the SHA-256 hash published on the GitHub Release page with
  the hash of the file you downloaded.

If any vendor outside the usual PyInstaller-bootloader set flags the
binary, please open an issue.

## Disclaimer

CS2 OMZ modifies Windows registry keys, services, and network settings.
Although every change is backed up and reversible, you run this tool
**at your own risk**. Creating a system restore point before first use
is recommended. The authors are not affiliated with Valve, Steam, or
Counter-Strike 2.

## License

[MIT](LICENSE)
