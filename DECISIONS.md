# Architectural & Design Decisions (`DECISIONS.md`)

> **How to Maintain This Document:**
> 1. **Read the Table of Contents first** to quickly locate relevant context without reading the entire file if only working on a specific subsystem.
> 2. **Append by default:** When a new feature, fix, or architectural decision is made, append a new numbered section at the bottom and add a corresponding row to the **Table of Contents**.
> 3. **Overwrite when superseded:** If a new decision changes or replaces an existing behavior documented here, **overwrite/update the existing section and its Table of Contents entry** in place rather than leaving conflicting historical rules.

---

## Table of Contents

| Section | Area | Summary | Key Files |
| :--- | :--- | :--- | :--- |
| [1. Monorepo & Raspberry Pi Deployment Architecture](#1-monorepo--raspberry-pi-deployment-architecture) | Infrastructure / Pi | Dual-mode hosting (GitHub Pages + local Express server on Raspberry Pi `192.168.4.50`), PM2 services (`lights` & `printer`), daily 4:00 AM reboot, and dual-NIC ARP sysctls. | `deploy.py`, `server.js`, `index.html` |
| [2. Tuya v3.5 Bulb Communication & Reliability](#2-tuya-v35-bulb-communication--reliability) | Lights (`listener.py`) | Single-socket-at-a-time constraint on port 6668, 350ms per-bulb socket cooldowns, 80ms group stagger, latest-command-wins superseding, in-memory DPS caching, and auto-IP discovery. | `lights/listener/listener.py` |
| [3. Smooth Color & Brightness Transitions](#3-smooth-color--brightness-transitions) | Lights (`listener.py`) | 5-step HSV/brightness interpolation over a single persistent TCP connection (`set_socketPersistent(True)`) per command, interruptible mid-fade. | `lights/listener/listener.py` |
| [4. Pure White Mode & Grayscale White-LED Routing](#4-pure-white-mode--grayscale-white-led-routing) | Lights (`listener.py`, `lights/index.html`) | Dedicated White LEDs (`DP 21 = 'white'`) for both Warm Daylight (`DP 23 = 300`) and Pure White (`DP 23 = 1000`), plus automatic routing of all grayscale hex colors (`s <= 8%`) to the White LEDs instead of RGB. | `lights/listener/listener.py`, `lights/index.html` |
| [5. Windows 98 UI Styling & Clean Chrome](#5-windows-98-ui-styling--clean-chrome) | Frontend UI | Classic Windows 98 SE beveled dialog aesthetic across Hub, Lights, and Printer pages; no protocol/version clutter in the menu bars. | `index.html`, `lights/index.html`, `printer/index.html`, `printer/style.css` |

---

## Detailed Decision Entries

### 1. Monorepo & Raspberry Pi Deployment Architecture
- **Updated:** 2026-11-16
- **Files:** `deploy.py`, `server.js`, `index.html`, `lights/start_listener.sh`
- **Context & Decision:**
  - This repository powers **Adam's Apartment Hub**, which is served statically on GitHub Pages (`g-arcy.com`) and locally via Express (`server.js` on port `3000`) on a Raspberry Pi (`192.168.4.50` / `192.168.4.51`).
  - Two long-running services are managed by **PM2** on the Raspberry Pi:
    1. `printer` (`server.js`): Handles 80mm USB thermal receipt printing (`/dev/usb/lp0` with WebUSB fallback) via both local HTTP `POST /print` and a Firebase Firestore cloud queue (`print_jobs`).
    2. `lights` (`lights/listener/listener.py`): Subscribes to HiveMQ MQTT (`adam/lights/candle_controller/cmd`), controls the 3 local Tuya smart candle bulbs over LAN TCP port `6668`, publishes status to `adam/lights/candle_controller/status`, and runs the daily schedule (turns ON 1 hour before the monthly earliest sunset; turns OFF at 2:30 AM).
  - **Pi Stability & Dual-NIC Networking:**
    - `deploy.py` configures a daily `4:00 AM` cron reboot (`/etc/cron.d/daily-pi-reboot`) and a 15-second systemd hardware watchdog.
    - Because the Raspberry Pi has both `eth0` (`192.168.4.51`) and `wlan0` (`192.168.4.50`) active on the same `192.168.4.0/24` subnet, `deploy.py` sets `/etc/sysctl.d/99-dual-nic-arp.conf` (`arp_ignore=1`, `arp_announce=2`, `rp_filter=2`) to prevent ARP flux with the 2.4GHz Wi-Fi bulbs.

---

### 2. Tuya v3.5 Bulb Communication & Reliability
- **Updated:** 2026-11-16
- **Files:** `lights/listener/listener.py`
- **Context & Problem:**
  - The room uses 3 Tuya v3.5 RGBCW smart candle bulbs (`candle_1`, `candle_2`, `candle_3`, `productKey: keytfesxxsqewnqy`, Tuya Lighting v2 schema).
  - Each bulb's embedded Beken BK7231 lwIP stack only supports **one active local TCP connection on port 6668 at a time** and requires ~300–400ms to clean up a closed socket.
  - Previously, opening back-to-back TCP connections (`turn_on()` followed 150ms later by `status()`, plus simultaneous `status` polls on web UI load and 30-second background polling) caused 1 of the 3 bulbs to drop connections, queue up dozens of stale command threads on `device_locks[name]`, or exhaust its internal lwIP TCP PCB table until power-cycled.
- **Decision & Implementation:**
  - **Per-Bulb Socket Cooldown (`MIN_SOCKET_GAP = 0.35s`):** `wait_for_bulb_cooldown()` enforces a minimum 350ms gap between consecutive TCP operations on the same bulb.
  - **Staggered Group Dispatch (`80ms`):** `execute_group_command()` staggers thread starts by `80ms` across the 3 bulbs so they do not collide on 2.4GHz Wi-Fi DTIM power-save wakeups at the exact same millisecond.
  - **Latest-Command-Wins Superseding (`command_seq`):** Each bulb tracks a monotonically increasing sequence number. If a new command arrives while a previous command is waiting or mid-retry, the older command immediately aborts (`is_superseded()`) so commands never pile up or replay out of order.
  - **In-Memory DPS Cache (`cached_dps`):** Bulb state (`DP 20` power, `DP 21` mode, `DP 22` white brightness, `DP 23` color temp, `DP 24` HSV) is cached in memory. Status requests from newly connected web clients (`action == "status"`) and post-command broadcasts read from `cached_dps` (`prefer_cache=True`) instead of opening redundant TCP connections. Background idle polling runs every `180s` instead of `30s`.
  - **Socket Reset & Auto-IP Discovery (`refresh_bulb_ip_if_changed`):** On any socket error, `listener.py` recreates the `tinytuya.BulbDevice` instance (without firing a pointless `d.status()` on a failed send) and runs a rate-limited `tinytuya.deviceScan()` to automatically update `config.json` if DHCP reassigns a bulb's IP.

---

### 3. Smooth Color & Brightness Transitions
- **Updated:** 2026-11-16
- **Files:** `lights/listener/listener.py`
- **Context & Problem:**
  - Standard Tuya local commands snap immediately to the target color/brightness, while naive Python fade loops that open a new TCP socket on every step overwhelm Tuya v3.5 bulbs.
- **Decision & Implementation:**
  - During `toggle_light()`, `d.set_socketPersistent(True)` is enabled for the duration of the command so only **one TCP connection and one v3.5 cryptographic handshake** occur per transition, then closed (`d.close()`) in the `finally` block.
  - `build_transition_steps(cur_dps, expected_dps, steps=5)` generates 5 interpolated steps (~`130–170ms` round-trip per step on the open socket, ~`0.7s` total fade) that blend with the bulb firmware's internal PWM smoothing:
    - **Color $\leftrightarrow$ Color:** Interpolates Hue along the shortest 360° arc, Saturation (`0–1000`), and Value (`10–1000`).
    - **Brightness Changes:** Smoothly ramps HSV Value (`DP 24`) in `'colour'` mode or White Brightness (`DP 22`) in `'white'` mode.
    - **Interruptible Mid-Fade:** Every intermediate step updates `cached_dps[name]` and checks `is_superseded(name, seq)`. If the user taps a new color or brightness mid-fade, the bulb immediately transitions from its exact intermediate color/brightness to the new target.

---

### 4. Pure White Mode & Grayscale White-LED Routing
- **Updated:** 2026-11-16
- **Files:** `lights/listener/listener.py`, `lights/index.html`
- **Context & Problem:**
  - The candle bulbs have dedicated Warm White (~2700K) and Cool White (~6500K) SMD LEDs (`DP 21 = 'white'`), which are significantly brighter than mixing R+G+B in `'colour'` mode.
  - Previously, `Reset to Daylight` used `DP 23 = 300` (a warm ~3500K white that throttles the high-output Cool White LEDs), and picking `#FFFFFF` or any grayscale shade in the color picker kept the bulb in `'colour'` mode (`DP 21 = 'colour'`) using the dim RGB LEDs to approximate white/gray.
- **Decision & Implementation:**
  - **Two White Presets in `Power & Mode`:**
    - **Reset to Daylight (`action: "reset"`):** Sets `{'20': True, '21': 'white', '22': 1000, '23': 300}` (warm/soft daylight at 100% brightness).
    - **Pure White (`action: "white"`):** Sets `{'20': True, '21': 'white', '22': 1000, '23': 1000}` (drives the Cool/Pure White LEDs at 100% brightness and `1000` color temperature for maximum lumen output).
  - **Grayscale Color Picker Routing (`parse_grayscale_white_dps`):**
    - Any hex color sent via `color` or `apply` with HSV saturation `s <= 0.08` or `max(R,G,B) - min(R,G,B) <= 18` (such as `#FFFFFF`, `#CCCCCC`, `#808080`, `#333333`) automatically routes to the dedicated **White LEDs** (`'21': 'white'`, `'23': 1000`) with white brightness `'22'` scaled directly by the grayscale shade's lightness (`v * 1000`).
    - Color $\rightarrow$ White transitions switch immediately to `'21': 'white'` and ramp White LED brightness (`'22'`) rather than stepping through desaturated RGB.

---

### 5. Windows 98 UI Styling & Clean Chrome
- **Updated:** 2026-11-16
- **Files:** `index.html`, `lights/index.html`, `printer/index.html`, `printer/style.css`
- **Context & Decision:**
  - All pages use a cohesive Windows 98 SE retro desktop aesthetic (beveled 3D borders, Tahoma/MS Sans Serif typography, classic title bars, and sunken status monitors).
  - Keep the UI chrome clean and focused on user controls—do not display technical protocol version strings (such as `Tuya Local Control v3.5`) in the menu bar.
