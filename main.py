"""CS2 OMZ — GUI entry point.

CustomTkinter-based dark GUI (900x650) divided into three tabs:
  * System     — hardware info + system optimizations
  * Network    — active adapter info, network optimizations, DNS, ping test
  * Launch Options — personalized CS2 launch options from detected hardware
"""
from __future__ import annotations

import ctypes
import datetime
import os
import sys
import threading
from tkinter import messagebox

try:
    import customtkinter as ctk
except ImportError:
    print("customtkinter is required. Run: pip install -r requirements.txt")
    sys.exit(1)

import hardware_detect
import optimizer
import network as netmod
from backup import restore_latest_backup

VERSION = "1.0.0"


# -------------------- admin check --------------------

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# -------------------- small GUI helpers --------------------

STATUS_ICONS = {"applied": "✅ Applied", "not_applied": "⚠️ Not applied", "error": "❌ Error"}


RISK_COLORS = {
    "Safe":     "#2e7d32",  # green
    "Moderate": "#c9a227",  # yellow
    "Caution":  "#e67e22",  # orange
}
IMPACT_COLORS = {
    "High impact":   "#3b82f6",
    "Medium impact": "#6b7280",
    "Low impact":    "#6b7280",
}


class OptimizationRow(ctk.CTkFrame):
    """A single row: checkbox + name + description + badges + status."""

    def __init__(self, master, key, title, desc, apply_fn, check_fn,
                 risk="Safe", impact="Low"):
        super().__init__(master, fg_color="transparent")
        self.key = key
        self.apply_fn = apply_fn
        self.check_fn = check_fn

        self.var = ctk.BooleanVar(value=False)
        self.check = ctk.CTkCheckBox(self, text="", variable=self.var, width=24,
                                     onvalue=True, offvalue=False)
        self.check.grid(row=0, column=0, rowspan=2, padx=(6, 10), pady=6)

        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(title_row, text=title,
                     font=ctk.CTkFont(weight="bold")).pack(side="left")

        risk_color = RISK_COLORS.get(risk, "#6b7280")
        ctk.CTkLabel(title_row, text=f" {risk} ", text_color="white",
                     fg_color=risk_color, corner_radius=6,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).pack(side="left", padx=(8, 0))

        impact_label = f"{impact} impact"
        impact_color = IMPACT_COLORS.get(impact_label, "#6b7280")
        ctk.CTkLabel(title_row, text=f" {impact_label} ", text_color="white",
                     fg_color=impact_color, corner_radius=6,
                     font=ctk.CTkFont(size=11)
                     ).pack(side="left", padx=(6, 0))

        self.desc = ctk.CTkLabel(self, text=desc, text_color="#9aa0a6",
                                 wraplength=420, justify="left")
        self.desc.grid(row=1, column=1, sticky="w")

        self.status = ctk.CTkLabel(self, text=STATUS_ICONS["not_applied"], width=120)
        self.status.grid(row=0, column=2, rowspan=2, padx=10)

        self.grid_columnconfigure(1, weight=1)

    def refresh_status(self):
        try:
            applied = bool(self.check_fn())
            self.status.configure(text=STATUS_ICONS["applied"] if applied
                                  else STATUS_ICONS["not_applied"])
        except Exception:
            self.status.configure(text=STATUS_ICONS["error"])

    def set_status(self, key: str):
        self.status.configure(text=STATUS_ICONS.get(key, STATUS_ICONS["error"]))


# -------------------- main app --------------------

class App(ctk.CTk):
    def __init__(self, hw: hardware_detect.HardwareInfo):
        super().__init__()
        self.hw = hw
        self.title(f"CS2 OMZ v{VERSION}")
        self.geometry("900x650")
        self.minsize(900, 650)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._build_header()
        self._build_tabs()
        self._build_system_tab()
        self._build_network_tab()
        self._build_launch_tab()

        # Auto-detect applied status on startup
        self.after(100, self._refresh_all_statuses)

    # ---------- header ----------
    def _build_header(self):
        header = ctk.CTkFrame(self, height=56, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="CS2 OMZ",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=16, pady=12)
        ctk.CTkLabel(header, text=f"v{VERSION}",
                     text_color="#9aa0a6").pack(side="left", pady=12)
        admin_txt = "Administrator" if is_admin() else "NOT ADMIN"
        ctk.CTkLabel(header, text=admin_txt,
                     text_color="#7bd389" if is_admin() else "#ff6b6b").pack(side="right", padx=16)

    # ---------- tabs ----------
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_system = self.tabs.add("System")
        self.tab_network = self.tabs.add("Network")
        self.tab_launch = self.tabs.add("Launch Options")

    # ---------- system tab ----------
    def _build_system_tab(self):
        root = self.tab_system
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=2)
        root.grid_rowconfigure(0, weight=1)

        # Left: hardware info
        left = ctk.CTkFrame(root)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(left, text="Detected Hardware",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        info_lines = [
            f"CPU: {self.hw.cpu_name}",
            f"Cores / Threads: {self.hw.cpu_cores} / {self.hw.cpu_threads}",
            f"Generation: {self.hw.cpu_generation}",
            f"GPU: {self.hw.gpu_name} ({self.hw.gpu_vendor})",
            f"VRAM: {self.hw.gpu_vram_mb} MB",
            f"RAM: {self.hw.ram_total_gb} GB @ {self.hw.ram_frequency_mhz} MHz",
            f"Monitor: {self.hw.monitor_width}x{self.hw.monitor_height} @ {self.hw.monitor_hz} Hz",
            f"Steam: {self.hw.steam_path or 'Not found'}",
            f"CS2: {self.hw.cs2_path or 'Not found'}",
        ]
        for line in info_lines:
            ctk.CTkLabel(left, text=line, justify="left", anchor="w",
                         wraplength=260).pack(anchor="w", padx=12, pady=2)

        # Right: optimizations
        right = ctk.CTkFrame(root)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="System Optimizations",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        scroll = ctk.CTkScrollableFrame(right)
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        self.system_rows: list[OptimizationRow] = []
        for entry in optimizer.OPTIMIZATIONS:
            key, title, desc, apply_fn, check_fn = entry[:5]
            risk, impact = (entry[5], entry[6]) if len(entry) >= 7 else ("Safe", "Low")
            row = OptimizationRow(scroll, key, title, desc, apply_fn, check_fn,
                                  risk=risk, impact=impact)
            row.pack(fill="x", padx=4, pady=4)
            self.system_rows.append(row)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="Optimize Selected",
                      command=lambda: self._run_system(selected_only=True)).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Apply All",
                      command=lambda: self._run_system(selected_only=False)).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Revert Changes", fg_color="#b23a3a",
                      hover_color="#8c2c2c",
                      command=self._revert_changes).pack(side="left", padx=4)

        # Log
        self.system_log = ctk.CTkTextbox(root, height=110)
        self.system_log.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    # ---------- network tab ----------
    def _build_network_tab(self):
        root = self.tab_network
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=2)
        root.grid_columnconfigure(2, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # Left: adapter info + DNS selector
        left = ctk.CTkFrame(root)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(left, text="Network",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.lbl_adapter = ctk.CTkLabel(left,
            text=f"Adapter: {self.hw.active_adapter_name or 'Not detected'}",
            justify="left", anchor="w", wraplength=240)
        self.lbl_adapter.pack(anchor="w", padx=12, pady=2)
        self.lbl_dns = ctk.CTkLabel(left,
            text=f"DNS: {', '.join(self.hw.current_dns) if self.hw.current_dns else 'DHCP'}",
            justify="left", anchor="w", wraplength=240)
        self.lbl_dns.pack(anchor="w", padx=12, pady=2)

        ctk.CTkLabel(left, text="DNS Provider",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.dns_var = ctk.StringVar(value="default")
        for label, value in (("Cloudflare (1.1.1.1)", "cloudflare"),
                             ("Google (8.8.8.8)", "google"),
                             ("Default / DHCP", "default")):
            ctk.CTkRadioButton(left, text=label, variable=self.dns_var,
                               value=value).pack(anchor="w", padx=16, pady=2)
        ctk.CTkButton(left, text="Apply DNS",
                      command=self._apply_dns).pack(padx=12, pady=10, fill="x")

        # Center: network optimizations
        center = ctk.CTkFrame(root)
        center.grid(row=0, column=1, sticky="nsew")
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(center, text="Network Optimizations",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        scroll = ctk.CTkScrollableFrame(center)
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        self.network_rows: list[OptimizationRow] = []
        for entry in netmod.NETWORK_OPTIMIZATIONS:
            key, title, desc, apply_fn, check_fn = entry[:5]
            risk, impact = (entry[5], entry[6]) if len(entry) >= 7 else ("Safe", "Low")
            row = OptimizationRow(scroll, key, title, desc, apply_fn, check_fn,
                                  risk=risk, impact=impact)
            row.pack(fill="x", padx=4, pady=4)
            self.network_rows.append(row)

        btns = ctk.CTkFrame(center, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="Optimize Network",
                      command=self._run_network).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Revert Network Changes", fg_color="#b23a3a",
                      hover_color="#8c2c2c",
                      command=self._revert_changes).pack(side="left", padx=4)

        # Right: ping test + before/after
        right = ctk.CTkFrame(root)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(right, text="Valve Server Latency",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.ping_table = ctk.CTkTextbox(right, height=140, width=240)
        self.ping_table.pack(padx=12, pady=6, fill="x")
        ctk.CTkButton(right, text="Test Ping", command=self._test_ping).pack(padx=12, pady=4, fill="x")

        ctk.CTkLabel(right, text="Before vs After",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        self.compare_box = ctk.CTkTextbox(right, height=120, width=240)
        self.compare_box.pack(padx=12, pady=4, fill="x")

        # Log
        self.network_log = ctk.CTkTextbox(root, height=110)
        self.network_log.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    # ---------- launch tab ----------
    def _build_launch_tab(self):
        root = self.tab_launch
        ctk.CTkLabel(root, text="Personalized Launch Options",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=16, pady=(12, 4))

        self.launch_opts = optimizer.generate_launch_options()
        self.launch_text = ctk.CTkEntry(root, height=40,
                                        font=ctk.CTkFont(size=14))
        self.launch_text.pack(fill="x", padx=16, pady=4)
        self.launch_text.insert(0, self.launch_opts)

        explanations = {
            "-mainthreadpriority 2": "Raise CS2 main thread priority for smoother frametimes.",
            "+thread_pool_option 4": "Use the Source 2 worker thread pool tuned for gameplay.",
            "-w / -h": "Match your monitor's native resolution.",
            "+fps_max": "Cap FPS at 2x monitor refresh rate for stable frametimes.",
            "-allow_third_party_software": "Allow tools like RivaTuner/MSI Afterburner overlay.",
        }
        box = ctk.CTkScrollableFrame(root, height=320)
        box.pack(fill="both", expand=True, padx=16, pady=8)
        for k, v in explanations.items():
            fr = ctk.CTkFrame(box, fg_color="transparent")
            fr.pack(fill="x", pady=2)
            ctk.CTkLabel(fr, text=k, font=ctk.CTkFont(weight="bold"),
                         width=240, anchor="w").pack(side="left", padx=8)
            ctk.CTkLabel(fr, text=v, text_color="#9aa0a6",
                         wraplength=560, justify="left", anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkButton(root, text="Copy to Clipboard",
                      command=self._copy_launch).pack(pady=6)
        ctk.CTkLabel(root,
                     text="⚠ Remove any conflicting launch options you may already have in Steam before pasting.",
                     text_color="#e0a23c").pack(pady=(4, 12), padx=16)

    # -------------------- actions --------------------
    def _log(self, box, msg: str):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        box.insert("end", f"[{stamp}] {msg}\n")
        box.see("end")

    def _refresh_all_statuses(self):
        for row in self.system_rows:
            row.refresh_status()
        for row in self.network_rows:
            row.refresh_status()

    def _run_system(self, selected_only: bool):
        rows = [r for r in self.system_rows if (r.var.get() or not selected_only)]
        if not rows:
            messagebox.showinfo("CS2 OMZ", "No optimizations selected.")
            return
        threading.Thread(target=self._run_rows, args=(rows, self.system_log), daemon=True).start()

    def _run_network(self):
        threading.Thread(target=self._run_rows,
                         args=(self.network_rows, self.network_log),
                         daemon=True).start()

    def _run_rows(self, rows, log_box):
        for row in rows:
            try:
                ok, msg = row.apply_fn()
                self._log(log_box, f"{row.key}: {msg}")
                row.set_status("applied" if ok else "error")
            except Exception as e:
                self._log(log_box, f"{row.key}: EXCEPTION {e}")
                row.set_status("error")
        self.after(200, self._refresh_all_statuses)

    def _apply_dns(self):
        provider = self.dns_var.get()
        ok, msg = netmod.set_dns(provider)
        self._log(self.network_log, msg)
        if ok:
            # Refresh displayed DNS
            self.hw = hardware_detect.detect_all()
            self.lbl_dns.configure(text=f"DNS: {', '.join(self.hw.current_dns) if self.hw.current_dns else 'DHCP'}")

    def _test_ping(self):
        self.ping_table.delete("1.0", "end")
        self.ping_table.insert("end", "Pinging Valve servers...\n")
        def worker():
            before = netmod.get_latency_comparison().get("before") or {}
            has_before = any(v is not None for v in before.values()) if before else False
            results = netmod.run_latency_test_before() if not has_before else netmod.run_latency_test_after()
            self.ping_table.delete("1.0", "end")
            self.ping_table.insert("end", f"{'Server':<12} Latency\n")
            for server, ms in results.items():
                self.ping_table.insert("end",
                    f"{server:<12} {('%.0f ms' % ms) if ms is not None else 'timeout'}\n")
            # Comparison
            cmp = netmod.get_latency_comparison()
            self.compare_box.delete("1.0", "end")
            b, a = cmp.get("before") or {}, cmp.get("after") or {}
            if b:
                self.compare_box.insert("end", f"{'Server':<12}{'Before':>8}{'After':>8}{'Δ':>8}\n")
                for server in netmod.VALVE_SERVERS:
                    bv, av = b.get(server), a.get(server)
                    delta = (av - bv) if (bv is not None and av is not None) else None
                    self.compare_box.insert("end",
                        f"{server:<12}{('%.0f' % bv if bv is not None else '—'):>8}"
                        f"{('%.0f' % av if av is not None else '—'):>8}"
                        f"{('%+.0f' % delta if delta is not None else '—'):>8}\n")
        threading.Thread(target=worker, daemon=True).start()

    def _revert_changes(self):
        if not messagebox.askyesno(
            "Revert",
            "Restore the most recent registry backup AND re-enable any "
            "services that were disabled?"):
            return
        ok, msg = restore_latest_backup()
        self._log(self.system_log, msg)
        self._log(self.network_log, msg)
        # Services aren't in registry exports — re-enable from JSON snapshot.
        try:
            ok_svc, msg_svc = optimizer.restore_services()
            self._log(self.system_log, msg_svc)
        except Exception as e:
            self._log(self.system_log, f"restore_services error: {e}")
        self.after(300, self._refresh_all_statuses)

    def _copy_launch(self):
        text = self.launch_text.get()
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("CS2 OMZ", "Launch options copied to clipboard.")


# -------------------- entry --------------------

def main():
    if not is_admin():
        try:
            # Try to show a real dialog even without a main loop
            import tkinter as tk
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("CS2 OMZ",
                "Administrator privileges are required.\n\n"
                "Right-click CS2 OMZ and choose 'Run as administrator'.")
            r.destroy()
        except Exception:
            print("[CS2 OMZ] Administrator privileges are required.")
        sys.exit(1)

    hw = hardware_detect.detect_all()
    app = App(hw)
    app.mainloop()


if __name__ == "__main__":
    main()
