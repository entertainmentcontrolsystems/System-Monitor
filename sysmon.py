#!/usr/bin/env python3
"""
SysMon Overlay — Lightweight Windows 11 System Monitor
─────────────────────────────────────────────────────────
Drag   : Left-click drag anywhere
Options: Right-click → toggle metrics, settings, quit

Requirements:
    pip install psutil nvidia-ml-py

CPU Temperature (optional, one of):
    pip install wmi              ← requires OpenHardwareMonitor running
    OR use HWiNFO64 with its OHM-compatible WMI bridge.
    Without either, CPU temp shows as "--".

GPU:
    NVIDIA → reads via NVML directly (nvidia-ml-py, no extra software needed).
    AMD    → not yet supported; GPU section hidden automatically.
"""

import tkinter as tk
import psutil
import threading
import time
import json
import os
from collections import deque

# ─── NVIDIA GPU via nvidia-ml-py (import name stays pynvml) ──────────────────
GPU_AVAILABLE = False
GPU_HANDLE    = None
GPU_NAME      = "GPU"

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    raw        = pynvml.nvmlDeviceGetName(GPU_HANDLE)
    GPU_NAME   = raw.decode() if isinstance(raw, bytes) else str(raw)
    GPU_NAME   = GPU_NAME.replace("NVIDIA ", "").replace("GeForce ", "")[:18]
    GPU_AVAILABLE = True
except Exception:
    pass

# ─── CPU temperature via WMI / OpenHardwareMonitor (optional) ────────────────
_wmi_ohm = None
_wmi_std = None

def _init_wmi():
    global _wmi_ohm, _wmi_std
    try:
        import wmi as _wmi_mod
        try:
            _wmi_ohm = _wmi_mod.WMI(namespace=r"root\OpenHardwareMonitor")
        except Exception:
            pass
        try:
            _wmi_std = _wmi_mod.WMI()
        except Exception:
            pass
    except ImportError:
        pass

# ─── Colour palette ───────────────────────────────────────────────────────────
BG       = "#0b0b0f"
SURFACE  = "#111118"
BORDER   = "#1a1a26"
FG       = "#dcdcf0"
FG2      = "#3e3e58"
FG3      = "#6e6e88"
C_CPU    = "#00ccff"
C_RAM    = "#7755ff"
C_GPU    = "#00e88a"
C_VRAM   = "#ff9933"
C_WARN   = "#ffcc00"
C_CRIT   = "#ff3c50"
C_ACCENT = "#00ccff"

# ─── Layout constants ─────────────────────────────────────────────────────────
PAD     = 11          # horizontal padding
ROW_H   = 20          # height of a metric label row
BAR_H   = 5           # height of a progress bar
TITLE_H = 30          # title bar height
SEP_H   = 10          # separator between groups
FOOT_H  = 8           # bottom padding
FIXED_W = 210         # overlay is always this wide
CELL    = 17          # core grid cell size (square)
CELL_GAP = 2          # gap between core cells

# ─── Colour helpers ───────────────────────────────────────────────────────────
def _pct_col(p):
    if p < 60: return C_CPU
    if p < 80: return C_WARN
    return C_CRIT

def _temp_col(t):
    if t is None: return FG3
    if t < 65:   return C_CPU
    if t < 80:   return C_WARN
    return C_CRIT

def _fmt_mem(used, total):
    ug = used  / 1024 ** 3
    tg = total / 1024 ** 3
    return f"{ug:.0f}/{tg:.0f} GB" if tg >= 10 else f"{ug:.1f}/{tg:.0f} GB"

# ─── Persistent settings ──────────────────────────────────────────────────────
_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sysmon_settings.json"
)

DEFAULTS = {
    "refresh_ms":   1000,
    "avg_seconds":  5,
    "opacity":      0.92,
    "x": 40, "y": 40,
    "show_cpu_avg":   True,
    "show_cpu_cores": True,
    "show_cpu_temp":  True,
    "show_ram":       True,
    "show_gpu_usage": True,
    "show_gpu_vram":  True,
    "show_gpu_temp":  True,
    "show_disk":      False,
    "show_network":   False,
    "clickthrough":   False,
    "avg_mode":       False,
}

def load_cfg():
    """Load settings from JSON, clamping all values to safe ranges."""
    try:
        with open(_SETTINGS_PATH) as f:
            raw = json.load(f)
        out = DEFAULTS.copy()
        out.update(raw)
        # Clamp numeric fields so a hand-edited file can't crash the app
        out["refresh_ms"]  = max(100,  int(float(out.get("refresh_ms",  1000))))
        out["avg_seconds"] = max(1,    int(float(out.get("avg_seconds", 5))))
        out["opacity"]     = max(0.1, min(1.0, float(out.get("opacity", 0.92))))
        out["x"]           = max(0,   int(float(out.get("x", 40))))
        out["y"]           = max(0,   int(float(out.get("y", 40))))
        return out
    except Exception:
        return DEFAULTS.copy()

def save_cfg(cfg):
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# ─── Data collector (background daemon thread) ────────────────────────────────
class Collector:
    def __init__(self, cfg):
        self.cfg      = cfg
        self._lock    = threading.Lock()
        self._running = False
        self._snap    = {
            "cpu_avg": 0.0, "cpu_cores": [],
            "cpu_temp": None,
            "ram_used": 0, "ram_total": psutil.virtual_memory().total,
            "gpu_usage": None, "gpu_vram_used": None,
            "gpu_vram_total": None, "gpu_temp": None,
            "disk_r": 0, "disk_w": 0,
            "net_up": 0, "net_down": 0,
        }
        self._hist = self._make_hist()
        psutil.cpu_percent(percpu=True, interval=None)   # prime the first call

    # ── History ───────────────────────────────────────────────────────────────
    def _hist_len(self):
        secs = max(1, self.cfg["avg_seconds"])
        rate = max(0.1, self.cfg["refresh_ms"] / 1000)
        return max(2, int(secs / rate))

    def _make_hist(self):
        n = self._hist_len()
        return {k: deque(maxlen=n) for k in (
            "cpu_avg", "cpu_cores", "cpu_temp",
            "ram_used",
            "gpu_usage", "gpu_vram_used", "gpu_temp",
            "disk_r", "disk_w", "net_up", "net_down",
        )}

    def resize_history(self):
        n = self._hist_len()
        for k, dq in self._hist.items():
            data = list(dq)
            self._hist[k] = deque(data[-n:], maxlen=n)

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def snapshot(self):
        with self._lock:
            return dict(self._snap)

    # ── Collection loop ───────────────────────────────────────────────────────
    def _loop(self):
        while self._running:
            t0 = time.monotonic()
            self._collect()
            elapsed = (time.monotonic() - t0) * 1000
            time.sleep(max(50, self.cfg["refresh_ms"] - elapsed) / 1000)

    def _collect(self):
        cores = psutil.cpu_percent(percpu=True, interval=None)
        avg   = sum(cores) / len(cores) if cores else 0.0
        mem   = psutil.virtual_memory()
        ctemp = self._cpu_temp()
        gu, gvu, gvt, gt = self._gpu_data()

        # Disk I/O (cumulative counters — diff from last call)
        disk_io = psutil.disk_io_counters()
        disk_r = (disk_io.read_bytes if disk_io else 0)
        disk_w = (disk_io.write_bytes if disk_io else 0)

        # Network I/O
        net_io = psutil.net_io_counters()
        net_up   = (net_io.bytes_sent if net_io else 0)
        net_down = (net_io.bytes_recv if net_io else 0)

        h = self._hist
        h["cpu_avg"].append(avg)
        h["cpu_cores"].append(list(cores))
        if ctemp is not None:
            h["cpu_temp"].append(ctemp)
        h["ram_used"].append(mem.used)
        if gu is not None:
            h["gpu_usage"].append(gu)
            h["gpu_vram_used"].append(gvu)
            h["gpu_temp"].append(gt)

        # Compute disk/network rates from deltas
        refresh_s = self.cfg["refresh_ms"] / 1000.0
        prev_disk_r = getattr(self, "_prev_disk_r", disk_r)
        prev_disk_w = getattr(self, "_prev_disk_w", disk_w)
        prev_net_up = getattr(self, "_prev_net_up", net_up)
        prev_net_dn = getattr(self, "_prev_net_dn", net_down)

        dr = max(0, (disk_r - prev_disk_r) / refresh_s)
        dw = max(0, (disk_w - prev_disk_w) / refresh_s)
        nu = max(0, (net_up - prev_net_up) / refresh_s)
        nd = max(0, (net_down - prev_net_dn) / refresh_s)

        self._prev_disk_r = disk_r
        self._prev_disk_w = disk_w
        self._prev_net_up = net_up
        self._prev_net_dn = net_down

        h["disk_r"].append(dr)
        h["disk_w"].append(dw)
        h["net_up"].append(nu)
        h["net_down"].append(nd)

        am = self.cfg["avg_mode"]

        def _v(key, default=None):
            q = h[key]
            if not q: return default
            return (sum(q) / len(q)) if am else q[-1]

        def _cores_v():
            q = h["cpu_cores"]
            if not q: return []
            if not am: return list(q[-1])
            n = len(q[0])
            return [sum(r[i] for r in q) / len(q) for i in range(n)]

        with self._lock:
            s = self._snap
            s["cpu_avg"]        = _v("cpu_avg",    0.0)
            s["cpu_cores"]      = _cores_v()
            s["cpu_temp"]       = _v("cpu_temp")
            s["ram_used"]       = _v("ram_used",   0)
            s["ram_total"]      = mem.total
            s["gpu_usage"]      = _v("gpu_usage")
            s["gpu_vram_used"]  = _v("gpu_vram_used")
            s["gpu_vram_total"] = gvt
            s["gpu_temp"]       = _v("gpu_temp")
            s["disk_r"]         = _v("disk_r", 0)
            s["disk_w"]         = _v("disk_w", 0)
            s["net_up"]         = _v("net_up", 0)
            s["net_down"]       = _v("net_down", 0)

    # ── Hardware readers ──────────────────────────────────────────────────────
    def _cpu_temp(self):
        # psutil (works natively on Linux; rare on Windows)
        try:
            t = psutil.sensors_temperatures()
            if t:
                for entries in t.values():
                    for e in entries:
                        if e.current and e.current > 20:
                            return float(e.current)
        except Exception:
            pass
        # OpenHardwareMonitor WMI bridge
        if _wmi_ohm:
            try:
                for s in _wmi_ohm.Sensor():
                    if s.SensorType == "Temperature" and "cpu" in s.Name.lower():
                        return float(s.Value)
            except Exception:
                pass
        return None

    def _gpu_data(self):
        if not GPU_AVAILABLE or GPU_HANDLE is None:
            return None, None, None, None
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE)
            mem  = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
            temp = pynvml.nvmlDeviceGetTemperature(
                GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)
            return float(util.gpu), mem.used, mem.total, float(temp)
        except Exception:
            return None, None, None, None

# ─── Overlay window ───────────────────────────────────────────────────────────
class Overlay:
    def __init__(self):
        self.cfg = load_cfg()
        self.col = Collector(self.cfg)
        threading.Thread(target=_init_wmi, daemon=True).start()
        self.col.start()

        r = tk.Tk()
        self.root = r
        r.title("SysMon")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", self.cfg["opacity"])
        r.configure(bg=BG)

        cv = tk.Canvas(r, bg=BG, highlightthickness=0, cursor="fleur")
        cv.pack(fill=tk.BOTH, expand=True)
        self.cv = cv

        cv.bind("<ButtonPress-1>",   self._drag_start)
        cv.bind("<B1-Motion>",       self._drag_move)
        cv.bind("<ButtonRelease-1>", self._drag_end)
        cv.bind("<Button-3>",        self._context_menu)

        r.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")
        self._dragging    = False
        self._drag_origin = (0, 0)

        self._tick()
        r.protocol("WM_DELETE_WINDOW", self._quit)
        r.mainloop()

    # ── Drag ──────────────────────────────────────────────────────────────────
    def _drag_start(self, e):
        self._dragging    = True
        self._drag_origin = (e.x_root - self.root.winfo_x(),
                             e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if not self._dragging: return
        ox, oy = self._drag_origin
        self.root.geometry(f"+{e.x_root - ox}+{e.y_root - oy}")

    def _drag_end(self, e):
        self._dragging = False
        self.cfg["x"]  = self.root.winfo_x()
        self.cfg["y"]  = self.root.winfo_y()

    # ── Context menu ──────────────────────────────────────────────────────────
    def _context_menu(self, e):
        m = tk.Menu(self.root, tearoff=0,
                    bg="#14141c", fg=FG,
                    activebackground="#20202e", activeforeground=FG,
                    bd=0, font=("Consolas", 9), relief=tk.FLAT)

        m.add_command(label="─── Metrics ───────────────", state="disabled",
                      font=("Consolas", 8))

        toggles = [
            ("show_cpu_avg",   "  CPU Average"),
            ("show_cpu_cores", "  CPU Per-Core Grid"),
            ("show_cpu_temp",  "  CPU Temperature"),
            ("show_ram",       "  RAM Usage"),
            ("show_disk",      "  Disk I/O"),
            ("show_network",   "  Network I/O"),
            ("show_gpu_usage", "  GPU Usage"),
            ("show_gpu_vram",  "  GPU VRAM"),
            ("show_gpu_temp",  "  GPU Temperature"),
        ]
        for key, label in toggles:
            v = tk.BooleanVar(value=self.cfg.get(key, True))
            m.add_checkbutton(label=label, variable=v,
                              command=lambda k=key, vv=v: self._toggle(k, vv.get()))

        m.add_separator()

        # Presets
        m.add_command(label="─── Presets ────────────────", state="disabled",
                      font=("Consolas", 8))
        m.add_command(label="  Minimal (CPU + RAM)",
                      command=lambda: self._preset("minimal"))
        m.add_command(label="  Full",
                      command=lambda: self._preset("full"))
        m.add_command(label="  Gaming (GPU-focused)",
                      command=lambda: self._preset("gaming"))

        m.add_separator()
        avg_v = tk.BooleanVar(value=self.cfg.get("avg_mode", False))
        m.add_checkbutton(label="  Average Mode", variable=avg_v,
                          command=lambda: self._toggle("avg_mode", avg_v.get()))

        ct_v = tk.BooleanVar(value=self.cfg.get("clickthrough", False))
        m.add_checkbutton(label="  Click-Through Mode", variable=ct_v,
                          command=lambda: self._toggle_clickthrough(ct_v.get()))

        m.add_separator()
        m.add_command(label="  Settings…", command=self._settings_dlg)
        m.add_separator()
        m.add_command(label="  Quit SysMon", command=self._quit)
        m.tk_popup(e.x_root, e.y_root)

    def _toggle(self, key, val):
        self.cfg[key] = val

    def _toggle_clickthrough(self, enabled):
        """Toggle click-through: overlay passes mouse events to windows below."""
        self.cfg["clickthrough"] = enabled
        if enabled:
            # Make window transparent to clicks
            self.root.attributes("-transparentcolor", BG)
            self.root.wm_attributes("-disabled", True)
        else:
            self.root.attributes("-transparentcolor", "")
            self.root.wm_attributes("-disabled", False)

    def _preset(self, name):
        """Apply a metric visibility preset."""
        presets = {
            "minimal": {
                "show_cpu_avg": True, "show_cpu_cores": False, "show_cpu_temp": False,
                "show_ram": True,
                "show_disk": False, "show_network": False,
                "show_gpu_usage": False, "show_gpu_vram": False, "show_gpu_temp": False,
            },
            "full": {
                "show_cpu_avg": True, "show_cpu_cores": True, "show_cpu_temp": True,
                "show_ram": True,
                "show_disk": True, "show_network": True,
                "show_gpu_usage": True, "show_gpu_vram": True, "show_gpu_temp": True,
            },
            "gaming": {
                "show_cpu_avg": True, "show_cpu_cores": True, "show_cpu_temp": True,
                "show_ram": True,
                "show_disk": False, "show_network": False,
                "show_gpu_usage": True, "show_gpu_vram": True, "show_gpu_temp": True,
            },
        }
        settings = presets.get(name, {})
        self.cfg.update(settings)
        save_cfg(self.cfg)

    # ── Settings dialog ───────────────────────────────────────────────────────
    def _settings_dlg(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("SysMon — Settings")
        dlg.configure(bg=SURFACE)
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.geometry("330x250")

        lkw = dict(bg=SURFACE, fg=FG,  font=("Consolas", 9), anchor="w")
        dkw = dict(bg=SURFACE, fg=FG2, font=("Consolas", 8), anchor="w")
        ekw = dict(bg=BG, fg=FG, insertbackground=FG,
                   font=("Consolas", 10), relief=tk.FLAT, bd=6, width=10)

        fields = [
            ("Refresh Rate",   "refresh_ms",  "milliseconds  (min 100)"),
            ("Average Window", "avg_seconds", "seconds"),
            ("Opacity",        "opacity",     "0.1 - 1.0"),
        ]
        vars_ = {}
        for i, (label, key, hint) in enumerate(fields):
            y_off = 16 + i * 62
            tk.Label(dlg, text=label.upper(), **lkw).place(x=16, y=y_off)
            tk.Label(dlg, text=hint,          **dkw).place(x=16, y=y_off + 14)
            v = tk.StringVar(value=str(self.cfg[key]))
            vars_[key] = v
            tk.Entry(dlg, textvariable=v, **ekw).place(x=16, y=y_off + 30)

        def _apply_and_close():
            _apply()
            dlg.destroy()

        tk.Button(dlg, text="APPLY",   command=_apply,
                  bg="#1c1c2a", fg=C_ACCENT, font=("Consolas", 9, "bold"),
                  relief=tk.FLAT, padx=20, pady=5, cursor="hand2",
                  activebackground="#262638",
                  activeforeground=C_ACCENT).place(x=16, y=200)

        tk.Button(dlg, text="OK & CLOSE", command=_apply_and_close,
                  bg="#1c1c2a", fg=C_GPU, font=("Consolas", 9, "bold"),
                  relief=tk.FLAT, padx=16, pady=5, cursor="hand2",
                  activebackground="#262638",
                  activeforeground=C_GPU).place(x=108, y=200)

        tk.Button(dlg, text="CANCEL",  command=dlg.destroy,
                  bg="#1c1c2a", fg=FG3, font=("Consolas", 9),
                  relief=tk.FLAT, padx=12, pady=5, cursor="hand2",
                  activebackground="#262638",
                  activeforeground=FG).place(x=226, y=200)

    # ── Draw loop ─────────────────────────────────────────────────────────────
    def _tick(self):
        self._draw(self.col.snapshot())
        self.root.after(self.cfg["refresh_ms"], self._tick)

    def _draw(self, d):
        cv = self.cv
        s  = self.cfg
        cv.delete("all")

        # Build the ordered list of active sections
        sections = []
        if s["show_cpu_avg"] or s["show_cpu_temp"]:
            sections.append("cpu")
        if s["show_cpu_cores"] and d["cpu_cores"]:
            sections.append("cores")
        if s["show_ram"]:
            sections.append("ram")
        if s["show_disk"]:
            sections.append("disk")
        if s["show_network"]:
            sections.append("network")
        if GPU_AVAILABLE:
            if s["show_gpu_usage"] or s["show_gpu_temp"]:
                sections.append("gpu")
            if s["show_gpu_vram"]:
                sections.append("vram")

        n_cores = len(d["cpu_cores"]) if d["cpu_cores"] else 0
        W = FIXED_W

        # Height pre-pass
        H = TITLE_H
        groups = self._groups(sections)
        H += (len(groups) - 1) * SEP_H if len(groups) > 1 else 0
        for sec in sections:
            H += self._sec_h(sec, n_cores)
        H += FOOT_H

        cv.configure(width=W, height=H)
        self.root.geometry(f"{W}x{H}")

        # Background
        self._rrect(cv, 0, 0, W, H, 10, fill=BG, outline=BORDER, width=1)
        cv.create_line(PAD + 2, 1, W - PAD - 2, 1, fill=C_ACCENT, width=1)

        # Title bar
        y = 8
        cv.create_text(PAD, y + 4, text="◈ SYSMON",
                       font=("Consolas", 10, "bold"), fill=C_ACCENT, anchor="w")

        badge = (f"⌀ {s['avg_seconds']}s", C_WARN) if s["avg_mode"] \
                else ("● LIVE", FG2)
        cv.create_text(W - PAD - 14, y + 4, text=badge[0],
                       font=("Consolas", 8), fill=badge[1], anchor="e")

        # Close button
        xt = cv.create_text(W - PAD + 2, y + 4, text="✕",
                             font=("Consolas", 11, "bold"),
                             fill=FG2, anchor="e", tags=("x_btn",))
        cv.tag_bind("x_btn", "<Enter>",      lambda e: cv.itemconfig(xt, fill=C_CRIT))
        cv.tag_bind("x_btn", "<Leave>",      lambda e: cv.itemconfig(xt, fill=FG2))
        cv.tag_bind("x_btn", "<Button-1>",   lambda e: self._quit())
        cv.tag_bind("x_btn", "<ButtonPress-1>",
                    lambda e: setattr(self, "_dragging", False))

        y += TITLE_H - 8

        # Sections
        prev_grp = None
        for sec in sections:
            grp = self._grp(sec)
            if prev_grp is not None and grp != prev_grp:
                cv.create_line(PAD, y + SEP_H // 2,
                               W - PAD, y + SEP_H // 2,
                               fill=BORDER, width=1)
                y += SEP_H
            prev_grp = grp

            if sec == "cpu":
                y = self._row(cv, y, W, "CPU",
                              d["cpu_avg"], C_CPU,
                              show_pct=s["show_cpu_avg"],
                              right_val=d["cpu_temp"] if s["show_cpu_temp"] else None,
                              right_is_temp=True)

            elif sec == "cores":
                y = self._cores(cv, y, W, d["cpu_cores"])

            elif sec == "ram":
                pct = (d["ram_used"] / d["ram_total"] * 100) if d["ram_total"] else 0
                mstr = _fmt_mem(d["ram_used"], d["ram_total"]) if d["ram_total"] else None
                y = self._row(cv, y, W, "RAM",
                              pct, C_RAM,
                              show_pct=True,
                              right_val=mstr, right_is_temp=False, right_color=C_RAM)

            elif sec == "gpu":
                pct = d["gpu_usage"] if d["gpu_usage"] is not None else 0
                # Guard against transient None from NVML
                gpu_temp = d["gpu_temp"] if s["show_gpu_temp"] and d.get("gpu_temp") is not None else None
                y = self._row(cv, y, W,
                              GPU_NAME if len(GPU_NAME) <= 8 else "GPU",
                              pct, C_GPU,
                              show_pct=s["show_gpu_usage"],
                              right_val=gpu_temp,
                              right_is_temp=True)

            elif sec == "vram":
                vt = d["gpu_vram_total"]
                vu = d["gpu_vram_used"]
                pct = (vu / vt * 100) if (vt and vu) else 0
                mstr = _fmt_mem(vu, vt) if (vu and vt) else None
                y = self._row(cv, y, W, "VRAM",
                              pct, C_VRAM,
                              show_pct=True,
                              right_val=mstr, right_is_temp=False, right_color=C_VRAM)

            elif sec == "disk":
                dr = d.get("disk_r", 0) or 0
                dw = d.get("disk_w", 0) or 0
                disk_str = f"R:{self._fmt_rate(dr)} W:{self._fmt_rate(dw)}"
                # Scale: typical SSD ~500MB/s, HDD ~100MB/s
                pct = min(100, (dr + dw) / (500 * 1024 * 1024) * 100)
                y = self._row(cv, y, W, "DISK",
                              pct, "#44aacc",
                              show_pct=False,
                              right_val=disk_str, right_is_temp=False, right_color="#66ccdd")

            elif sec == "network":
                nu = d.get("net_up", 0) or 0
                nd = d.get("net_down", 0) or 0
                net_str = f"↑{self._fmt_rate(nu)} ↓{self._fmt_rate(nd)}"
                # Scale: typical gigabit ~125MB/s
                pct = max(min(100, nu / (125 * 1024 * 1024) * 100),
                          min(100, nd / (125 * 1024 * 1024) * 100))
                y = self._row(cv, y, W, "NET",
                              pct, "#cc66ff",
                              show_pct=False,
                              right_val=net_str, right_is_temp=False, right_color="#cc88ff")

    # ── Row: label + optional % + progress bar + optional right value ─────────
    def _row(self, cv, y, W,
             label, pct, bar_color,
             show_pct=True,
             right_val=None, right_is_temp=True, right_color=None):

        pct = max(0.0, min(100.0, float(pct) if pct is not None else 0))
        mid = y + ROW_H // 2

        cv.create_text(PAD, mid, text=label,
                       font=("Consolas", 9, "bold"), fill=FG3, anchor="w")

        if show_pct:
            cv.create_text(PAD + 46, mid, text=f"{pct:.0f}%",
                           font=("Consolas", 9, "bold"),
                           fill=_pct_col(pct), anchor="w")

        if right_val is not None:
            if right_is_temp:
                rtxt = f"{right_val:.0f}°C"
                rcol = _temp_col(right_val)
            else:
                rtxt = str(right_val)
                rcol = right_color or FG3
            cv.create_text(W - PAD, mid, text=rtxt,
                           font=("Consolas", 9), fill=rcol, anchor="e")

        bx, by = PAD, y + ROW_H
        bw = W - PAD * 2
        self._rrect(cv, bx, by, bx + bw, by + BAR_H, BAR_H // 2,
                    fill=SURFACE, outline="")

        fw = max(0, int(bw * pct / 100))
        if fw >= BAR_H:
            self._rrect(cv, bx, by - 1, bx + fw, by + BAR_H + 1, BAR_H // 2 + 1,
                        fill=self._dim(bar_color, 0.25), outline="")
            self._rrect(cv, bx, by, bx + fw, by + BAR_H, BAR_H // 2,
                        fill=bar_color, outline="")

        return y + ROW_H + BAR_H + 10

    # ── Per-core heatmap grid (Task Manager style) ────────────────────────────
    def _cores(self, cv, y, W, cores):
        n = len(cores)
        if n == 0: return y

        cv.create_text(PAD, y + 3, text="CORES",
                       font=("Consolas", 7, "bold"), fill=FG2, anchor="nw")
        cy = y + 14

        inner_w = W - 2 * PAD
        n_cols  = self._core_cols(n, inner_w)
        n_rows  = (n + n_cols - 1) // n_cols

        for i, pct in enumerate(cores):
            col_i = i % n_cols
            row_i = i // n_cols
            cx = PAD + col_i * (CELL + CELL_GAP)
            ry = cy  + row_i * (CELL + CELL_GAP)
            pct = max(0.0, min(100.0, float(pct)))

            # Background cell
            self._rrect(cv, cx, ry, cx + CELL, ry + CELL, 2,
                        fill=SURFACE, outline=BORDER, width=1)

            # Heat-fill: colour blended from near-black → accent colour by load
            if pct > 1.0:
                fill_col = self._blend(BG, _pct_col(pct), pct / 100.0)
                self._rrect(cv, cx, ry, cx + CELL, ry + CELL, 2,
                            fill=fill_col, outline="")
                # Shimmer line at top edge when load is significant
                if pct > 50:
                    bright = self._dim(_pct_col(pct), 1.5)
                    cv.create_line(cx + 3, ry + 1, cx + CELL - 3, ry + 1,
                                   fill=bright, width=1)

        grid_h = n_rows * CELL + (n_rows - 1) * CELL_GAP
        return cy + grid_h + 8

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _core_cols(self, n, inner_w):
        """
        Best-fit column count that fills the available width.
        Prefers divisors of n for clean grid fill, falls back to
        powers of 2 (GPU-friendly patterns) if no divisor fits.
        """
        # Try divisors first (clean fill, no dangling cells)
        for cols in sorted(range(1, n + 1), key=lambda c: (
            n % c != 0,  # penalize non-divisors
            -c if c <= (inner_w + CELL_GAP) // (CELL + CELL_GAP) else c
        )):
            needed = cols * CELL + (cols - 1) * CELL_GAP
            if needed <= inner_w:
                return cols
        return max(1, n)

    def _sec_h(self, sec, n_cores=0):
        if sec in ("cpu", "ram", "gpu", "vram", "disk", "network"):
            return ROW_H + BAR_H + 10
        if sec == "cores":
            if n_cores == 0: return 0
            inner_w = FIXED_W - 2 * PAD
            n_cols  = self._core_cols(n_cores, inner_w)
            n_rows  = (n_cores + n_cols - 1) // n_cols
            return 14 + n_rows * CELL + (n_rows - 1) * CELL_GAP + 8
        return 0

    def _groups(self, sections):
        grps, seen = [], set()
        for s in sections:
            g = self._grp(s)
            if g not in seen:
                grps.append(g); seen.add(g)
        return grps

    @staticmethod
    def _grp(sec):
        if sec in ("cpu", "cores"):          return "cpu"
        if sec in ("gpu", "vram"):           return "gpu"
        if sec in ("disk", "network"):       return "io"
        return sec

    @staticmethod
    def _fmt_rate(bytes_per_sec):
        """Format a byte rate to human-readable string."""
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024**2:
            return f"{bytes_per_sec/1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec/1024**2:.1f} MB/s"

    @staticmethod
    def _dim(hex_color, factor):
        """Scale each RGB channel by factor (>1 = brighter, <1 = darker)."""
        try:
            h = hex_color.lstrip("#")
            r = min(255, int(int(h[0:2], 16) * factor))
            g = min(255, int(int(h[2:4], 16) * factor))
            b = min(255, int(int(h[4:6], 16) * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    @staticmethod
    def _blend(hex_a, hex_b, t):
        """Linear interpolate two hex colours; t=0 → a, t=1 → b."""
        try:
            def _p(h):
                h = h.lstrip("#")
                return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            ra, ga, ba = _p(hex_a)
            rb, gb, bb = _p(hex_b)
            r = int(ra + (rb - ra) * t)
            g = int(ga + (gb - ga) * t)
            b = int(ba + (bb - ba) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_b

    def _rrect(self, cv, x1, y1, x2, y2, r, **kw):
        """Rounded rectangle drawn as a smooth polygon."""
        r = max(0, min(r, (x2 - x1) // 2, max(1, (y2 - y1) // 2)))
        pts = [
            x1+r, y1,   x2-r, y1,
            x2,   y1,   x2,   y1+r,
            x2,   y2-r, x2,   y2,
            x2-r, y2,   x1+r, y2,
            x1,   y2,   x1,   y2-r,
            x1,   y1+r, x1,   y1,
            x1+r, y1,
        ]
        cv.create_polygon(pts, smooth=True, **kw)

    # ── Quit ──────────────────────────────────────────────────────────────────
    def _quit(self):
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        save_cfg(self.cfg)
        self.col.stop()
        self.root.destroy()


if __name__ == "__main__":
    Overlay()
