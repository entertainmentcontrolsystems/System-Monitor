# SysMon Overlay v2.1

A lightweight, always-on-top system monitor for Windows 11.
Frameless dark overlay — CPU avg, per-core heatmap grid, RAM, GPU, VRAM, temperatures.

---

## Package Contents

```
SysMon/
├── install.bat          ← Run this first — one-click setup
├── uninstall.bat        ← Removes startup entry, shortcut, and packages
├── run_sysmon.bat       ← Launch SysMon (rewritten by install.bat)
├── sysmon.py            ← Main application
├── requirements.txt     ← Python dependencies (psutil, nvidia-ml-py)
└── README.md            ← This file
```

---

## Installation

### Requirements
- Windows 10 or 11
- Python 3.9+ — https://www.python.org/downloads/
  - During install, check **"Add Python to PATH"**
- Internet connection (to download two small packages)

### Steps

1. **Install Python** if you haven't already (link above)
2. **Double-click `install.bat`**

The installer will:
- Detect your Python installation automatically
- Verify Python 3.9+
- Uninstall the deprecated `pynvml` package if present
- Install `psutil` and `nvidia-ml-py`
- Write `run_sysmon.bat` with the correct Python path
- Offer to create a **Desktop shortcut** (optional)
- Offer to add a **Windows startup entry** (optional)
- Offer to **launch SysMon immediately**

---

## Running

After installation, double-click:
```
run_sysmon.bat
```
No console window appears. SysMon shows as a small overlay in the top-left corner.

---

## Controls

| Action | How |
|--------|-----|
| Move overlay | Left-click drag anywhere |
| Toggle metrics | Right-click → check/uncheck |
| Toggle average mode | Right-click → Average Mode |
| Toggle click-through | Right-click → Click-Through Mode |
| Apply preset | Right-click → Presets → Minimal / Full / Gaming |
| Settings | Right-click → Settings… |
| Quit | Right-click → Quit SysMon, or click ✕ |

---

## Settings

Access via right-click → Settings…

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| Refresh Rate | 1000 ms | ≥ 100 ms | How often data updates |
| Average Window | 5 sec | ≥ 1 sec | Seconds to average in Average Mode |
| Opacity | 0.92 | 0.1 – 1.0 | Window transparency |

All settings persist to `sysmon_settings.json` next to the script.

---

## Metrics

| Metric | Colour coding |
|--------|--------------|
| CPU avg % | Cyan < 60% · Amber 60–80% · Red > 80% |
| CPU per-core grid | Heatmap: near-black (idle) → full colour (loaded) |
| CPU temp | Cyan < 65°C · Amber 65–80°C · Red > 80°C |
| RAM | Usage % + used/total GB |
| Disk I/O | Read/write rates (MB/s) — disabled by default |
| Network I/O | Upload/download rates (MB/s) — disabled by default |
| GPU usage % | Same thresholds as CPU % |
| GPU temp | Same thresholds as CPU temp |
| VRAM | Usage % + used/total GB |

---

## CPU Temperature (Windows)

`psutil` cannot read CPU temperatures on most Windows systems without a helper.

**Option A — OpenHardwareMonitor (recommended, free)**
1. Download from https://openhardwaremonitor.org
2. Run as Administrator
3. Options → Remote Web Server → Start (enables WMI)
4. Run: `pip install wmi`
5. Restart SysMon

**Option B — HWiNFO64**
1. Run HWiNFO64 in Sensors-only mode
2. Settings → Enable "Support OpenHardwareMonitor WMI"
3. Run: `pip install wmi`
4. Restart SysMon

Without either, CPU temp shows as `--` (all other metrics work normally).

---

## GPU Support

- **NVIDIA** — works automatically via `nvidia-ml-py` (reads NVML directly, no extra software).
- **AMD / Intel** — not currently supported; GPU/VRAM section is hidden automatically.

---

## Presets

Access via right-click → Presets:

| Preset | Shows |
|--------|-------|
| **Minimal** | CPU avg + RAM only |
| **Full** | All metrics including disk and network |
| **Gaming** | CPU + cores + temp + RAM + GPU + VRAM + GPU temp (no disk/network) |

## Click-Through Mode

Enable via right-click → Click-Through Mode.
The overlay becomes transparent to mouse events — clicks pass through to windows
behind it. Use when the overlay is in the way of something you're working on.

## Average Mode

Enable via right-click → Average Mode.
All values become rolling averages over the configured window length.
The badge switches from `● LIVE` to `⌀ 5s`.

---

## Uninstall

Double-click `uninstall.bat` to remove:
- The Windows startup registry entry (if added)
- The Desktop shortcut (if created)
- The `psutil` and `nvidia-ml-py` pip packages

Then delete the SysMon folder manually.

---

## Troubleshooting

**"Python was not found"**
Install Python 3.9+ from python.org and check "Add Python to PATH".

**SysMon doesn't appear after launch**
It starts in the top-left corner. It may be behind other windows — check your taskbar or use Alt+Tab.

**FutureWarning about pynvml**
Run `install.bat` again — it will remove the old `pynvml` package.

**GPU section missing**
Only NVIDIA GPUs are supported. AMD/Intel cards cause the section to hide automatically.

**Settings file won't load**
Delete `sysmon_settings.json` next to `sysmon.py` and relaunch. It will be recreated with defaults.
