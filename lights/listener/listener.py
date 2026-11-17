import tinytuya
import paho.mqtt.client as mqtt
import json
import threading
import os
import sys
import time
import colorsys
from datetime import datetime
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# --- LOAD CONFIG FROM FILE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

if not os.path.exists(CONFIG_FILE):
    print(f"Error: {CONFIG_FILE} not found. Please create it first.")
    exit(1)

print("Loading configuration...")
with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

CANDLE_LIGHTS_CONFIG = config["LIGHTS"]
MQTT_TOPIC = config["MQTT_TOPIC"]
STATUS_TOPIC = config.get("STATUS_TOPIC", "adam/lights/candle_controller/status")

# --- SCHEDULER CONFIG ---
LATITUDE = config.get("LATITUDE")
LONGITUDE = config.get("LONGITUDE")
TIMEZONE = config.get("TIMEZONE", "America/Los_Angeles")
TZ = ZoneInfo(TIMEZONE)

# --- MQTT CONFIG ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

# --- PERSISTENT DEVICE OBJECTS, STATE CACHE & LOCKS ---
devices = {}
device_locks = {}
cached_dps = {}
last_io_time = {}
last_cache_time = {}
command_seq = {}
seq_lock = threading.Lock()
scan_lock = threading.Lock()
last_scan_time = 0.0

MIN_SOCKET_GAP = 0.35
VERIFY_SOCKET_GAP = 0.45
CACHE_TTL_SECONDS = 120.0

def create_device(cfg):
    d = tinytuya.BulbDevice(
        dev_id=cfg['id'],
        address=cfg['ip'],
        local_key=cfg['key'],
        version=cfg['version']
    )
    d.set_socketTimeout(2.5)
    d.set_socketRetryLimit(1)
    d.set_socketPersistent(False)
    return d

for name, cfg in CANDLE_LIGHTS_CONFIG.items():
    devices[name] = create_device(cfg)
    device_locks[name] = threading.Lock()
    cached_dps[name] = {}
    last_io_time[name] = 0.0
    last_cache_time[name] = 0.0
    command_seq[name] = 0

def wait_for_bulb_cooldown(name, min_gap=MIN_SOCKET_GAP):
    elapsed = time.monotonic() - last_io_time.get(name, 0.0)
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)

def mark_bulb_io(name):
    last_io_time[name] = time.monotonic()

def update_cached_dps(name, dps):
    if isinstance(dps, dict) and dps:
        merged = dict(cached_dps.get(name) or {})
        merged.update(dps)
        cached_dps[name] = merged
        last_cache_time[name] = time.monotonic()

def refresh_bulb_ip_if_changed(target_name=None):
    global last_scan_time
    if not scan_lock.acquire(blocking=False):
        return False
    try:
        now = time.monotonic()
        if now - last_scan_time < 60.0:
            return False
        last_scan_time = now
        found = tinytuya.deviceScan(verbose=False, maxretry=3)
        if not isinstance(found, dict):
            return False
        updated = False
        for ip, info in found.items():
            if not isinstance(info, dict):
                continue
            gw_id = info.get("gwId") or info.get("id")
            if not gw_id:
                continue
            for name, cfg in CANDLE_LIGHTS_CONFIG.items():
                if cfg.get("id") == gw_id and ip and cfg.get("ip") != ip:
                    print(f"  [SCAN] {name} IP changed {cfg.get('ip')} -> {ip}, updating...")
                    cfg["ip"] = ip
                    devices[name] = create_device(cfg)
                    updated = True
        if updated:
            try:
                with open(CONFIG_FILE, "w") as f:
                    json.dump(config, f, indent=4)
            except Exception as e:
                print(f"  [SCAN] Failed to save updated config.json: {e}")
        return updated
    except Exception as e:
        print(f"  [SCAN] Error scanning for bulb IPs: {e}")
        return False
    finally:
        scan_lock.release()

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_tuya_hsv(hex_color, brightness_pct=100):
    r, g, b = hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hue = int(round(h * 360)) % 360
    sat = max(0, min(1000, int(round(s * 1000))))
    val = max(10, min(1000, int(round(v * (float(brightness_pct) / 100.0) * 1000))))
    return f"{hue:04x}{sat:04x}{val:04x}"

def parse_tuya_hsv(hsv_hex):
    if not isinstance(hsv_hex, str) or len(hsv_hex) != 12:
        return None
    try:
        h = int(hsv_hex[0:4], 16)
        s = int(hsv_hex[4:8], 16)
        v = int(hsv_hex[8:12], 16)
        return (h, s, v)
    except Exception:
        return None

def format_tuya_hsv(h, s, v):
    hue = int(round(h)) % 360
    sat = max(0, min(1000, int(round(s))))
    val = max(10, min(1000, int(round(v))))
    return f"{hue:04x}{sat:04x}{val:04x}"

def build_transition_steps(cur_dps, expected_dps, steps=5):
    if not isinstance(expected_dps, dict) or not expected_dps:
        return []
    # Simple power on/off: single step
    if len(expected_dps) == 1 and '20' in expected_dps:
        return [expected_dps]
    if not isinstance(cur_dps, dict) or not cur_dps:
        return [expected_dps]

    was_on = bool(cur_dps.get('20', False))
    cur_mode = cur_dps.get('21', 'white')
    target_mode = expected_dps.get('21', cur_mode)

    # Case 1: Transitioning to colour mode
    if target_mode == 'colour' and '24' in expected_dps:
        target_hsv = parse_tuya_hsv(expected_dps['24'])
        if not target_hsv:
            return [expected_dps]
        h2, s2, v2 = target_hsv

        if not was_on:
            h1, s1, v1 = h2, s2, 10
        elif cur_mode == 'colour' and parse_tuya_hsv(cur_dps.get('24')):
            h1, s1, v1 = parse_tuya_hsv(cur_dps.get('24'))
        else:
            # Transitioning from white -> colour: start at low saturation with current white brightness
            h1, s1, v1 = h2, min(150, s2), max(10, min(1000, int(cur_dps.get('22', v2))))

        dh = ((h2 - h1 + 180) % 360) - 180
        ds = s2 - s1
        dv = v2 - v1

        if abs(dh) < 4 and abs(ds) < 25 and abs(dv) < 30:
            return [expected_dps]

        seq_steps = []
        for i in range(1, steps):
            frac = i / float(steps)
            hi = (h1 + dh * frac) % 360
            si = s1 + ds * frac
            vi = v1 + dv * frac
            step_dps = {'20': True, '21': 'colour', '24': format_tuya_hsv(hi, si, vi)}
            if not seq_steps or seq_steps[-1] != step_dps:
                seq_steps.append(step_dps)
        seq_steps.append(expected_dps)
        return seq_steps

        # Case 2: Transitioning to white mode (always use dedicated white LEDs, never fake white with RGB)
    if target_mode == 'white' and '22' in expected_dps:
        b2 = int(expected_dps['22'])
        t2 = int(expected_dps.get('23', cur_dps.get('23', 300)))

        if not was_on:
            b1 = 10
            t1 = t2
        elif cur_mode == 'colour':
            # Switching from RGB colour -> White LEDs: start white LEDs from low/matched brightness and ramp smoothly
            cur_hsv = parse_tuya_hsv(cur_dps.get('24'))
            b1 = max(10, min(1000, int(round((cur_hsv[2] if cur_hsv else 300) * 0.35))))
            t1 = t2
        else:
            b1 = int(cur_dps.get('22', 1000))
            t1 = int(cur_dps.get('23', t2))

        db = b2 - b1
        dt = t2 - t1

        if cur_mode == 'white' and abs(db) < 35 and abs(dt) < 35:
            return [expected_dps]

        seq_steps = []
        for i in range(1, steps):
            frac = i / float(steps)
            bi = max(10, min(1000, int(round(b1 + db * frac))))
            step_dps = {'20': True, '21': 'white', '22': bi}
            if '23' in expected_dps:
                step_dps['23'] = max(0, min(1000, int(round(t1 + dt * frac))))
            if not seq_steps or seq_steps[-1] != step_dps:
                seq_steps.append(step_dps)
        seq_steps.append(expected_dps)
        return seq_steps

    return [expected_dps]

def dps_matches(actual_dps, expected_dps):
    if not isinstance(actual_dps, dict):
        return False
    for k, exp_v in expected_dps.items():
        if k not in actual_dps:
            return False
        act_v = actual_dps[k]
        if isinstance(exp_v, str) and isinstance(act_v, str):
            if act_v.lower() != exp_v.lower():
                return False
        elif act_v != exp_v:
            return False
    return True

def parse_grayscale_white_dps(hex_color):
    """If hex_color is grayscale (zero/very low saturation), return white-LED DPS instead of RGB."""
    if not isinstance(hex_color, str):
        return None
    try:
        r, g, b = hex_to_rgb(hex_color.strip())
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        # Treat any color with saturation <= 8% (or max-min channel delta <= 18) as grayscale white LED
        if s <= 0.08 or (max(r, g, b) - min(r, g, b)) <= 18:
            white_bright = max(10, min(1000, int(round(v * 1000))))
            return {'20': True, '21': 'white', '22': white_bright, '23': 1000}
    except Exception:
        pass
    return None

def build_expected_dps(name, d, action, value=None, extra=None):
    extra = extra or {}
    if action == "on":
        return {'20': True}
    elif action == "off":
        return {'20': False}
    elif action == "white":
        return {'20': True, '21': 'white', '22': 1000, '23': 1000}
    elif action == "reset":
        return {'20': True, '21': 'white', '22': 1000, '23': 300}
    elif action == "color":
        gray_dps = parse_grayscale_white_dps(value)
        if gray_dps:
            return gray_dps
        brightness_pct = max(1, min(100, int(extra.get("brightness", 100))))
        return {'20': True, '21': 'colour', '24': rgb_to_tuya_hsv(value, brightness_pct)}
    elif action in ("brightness", "dim", "apply"):
        brightness_pct = max(1, min(100, int(extra.get("brightness", value if value is not None else 100))))
        color_hex = extra.get("color")
        if color_hex:
            gray_dps = parse_grayscale_white_dps(color_hex)
            if gray_dps:
                return gray_dps
            return {'20': True, '21': 'colour', '24': rgb_to_tuya_hsv(color_hex, brightness_pct)}

        # Dim / adjust brightness of the bulb's current color or white mode
        scaled_val = max(10, min(1000, int(round(brightness_pct * 10))))
        cur_dps = cached_dps.get(name) or {}
        if '21' not in cur_dps:
            cur_status = d.status()
            mark_bulb_io(name)
            if isinstance(cur_status, dict) and isinstance(cur_status.get('dps'), dict):
                cur_dps = cur_status['dps']
                update_cached_dps(name, cur_dps)

        if cur_dps.get('21') == 'colour' and isinstance(cur_dps.get('24'), str) and len(cur_dps['24']) == 12:
            hue_sat = cur_dps['24'][:8]
            return {'20': True, '21': 'colour', '24': f"{hue_sat}{scaled_val:04x}"}
        else:
            return {'20': True, '21': 'white', '22': scaled_val}
    return {}

def is_superseded(name, seq):
    with seq_lock:
        return command_seq.get(name, 0) != seq

def toggle_light(name, seq, stagger_delay, action, value=None, extra=None):
    if stagger_delay > 0:
        time.sleep(stagger_delay)
    if is_superseded(name, seq):
        return

    lock = device_locks[name]
    with lock:
        if is_superseded(name, seq):
            return

        expected_dps = None
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            if is_superseded(name, seq):
                return

            d = devices[name]
            try:
                wait_for_bulb_cooldown(name, MIN_SOCKET_GAP)
                d.set_socketPersistent(True)
                try:
                    # Ensure we have current bulb mode/brightness/color cached before building transition steps
                    if '21' not in (cached_dps.get(name) or {}) and action not in ("on", "off"):
                        init_status = d.status()
                        mark_bulb_io(name)
                        if isinstance(init_status, dict) and isinstance(init_status.get('dps'), dict):
                            update_cached_dps(name, init_status['dps'])

                    if expected_dps is None:
                        expected_dps = build_expected_dps(name, d, action, value, extra)
                    if not expected_dps:
                        return

                    # Only run multi-step smooth transition on attempt 1; retries go straight to final target
                    if attempt == 1:
                        step_list = build_transition_steps(cached_dps.get(name), expected_dps, steps=5)
                    else:
                        step_list = [expected_dps]

                    res = None
                    for step_idx, step_dps in enumerate(step_list):
                        if is_superseded(name, seq):
                            return
                        t_step = time.monotonic()
                        if len(step_dps) == 1 and '20' in step_dps:
                            res = d.turn_on() if step_dps['20'] else d.turn_off()
                        else:
                            res = d.set_multiple_values(step_dps)
                        mark_bulb_io(name)

                        if not isinstance(res, dict) or 'Error' in res or 'Err' in res:
                            # If an intermediate fade step errors, break and let retry handle final target
                            break

                        step_ret_dps = res.get('dps') if isinstance(res.get('dps'), dict) else None
                        if step_ret_dps:
                            update_cached_dps(name, step_dps)
                            update_cached_dps(name, step_ret_dps)

                        if step_idx < len(step_list) - 1:
                            elapsed = time.monotonic() - t_step
                            if elapsed < 0.06:
                                time.sleep(0.06 - elapsed)

                    # Check final step result
                    if not isinstance(res, dict) or 'Error' in res or 'Err' in res:
                        err_msg = res.get('Error', res) if isinstance(res, dict) else 'No response'
                        print(f"  [RETRY] {name} -> {action} error on attempt {attempt}: {err_msg}")
                        if attempt == 2:
                            refresh_bulb_ip_if_changed(name)
                        devices[name] = create_device(CANDLE_LIGHTS_CONFIG[name])
                    else:
                        res_dps = res.get('dps') if isinstance(res.get('dps'), dict) else None
                        if res_dps:
                            # Tuya v3.5 only returns changed DPs in ACK; merge with known state if power/mode was already set
                            merged_check = dict(cached_dps.get(name) or {})
                            merged_check.update(res_dps)
                            if dps_matches(merged_check, expected_dps):
                                update_cached_dps(name, expected_dps)
                                print(f"  [CMD] {name} -> {action} OK (attempt {attempt}, {len(step_list)} step(s))")
                                return

                        if not dps_matches(res_dps, expected_dps):
                            if is_superseded(name, seq):
                                return
                            time.sleep(0.15)
                            verify = d.status()
                            mark_bulb_io(name)
                            if isinstance(verify, dict) and isinstance(verify.get('dps'), dict):
                                res_dps = verify['dps']
                                update_cached_dps(name, res_dps)

                        if dps_matches(res_dps, expected_dps):
                            update_cached_dps(name, expected_dps)
                            print(f"  [CMD] {name} -> {action} OK (attempt {attempt}, {len(step_list)} step(s))")
                            return

                        print(f"  [RETRY] {name} -> {action} mismatch on attempt {attempt} (wanted {expected_dps}, got {res_dps})")
                        devices[name] = create_device(CANDLE_LIGHTS_CONFIG[name])
                finally:
                    try:
                        d.set_socketPersistent(False)
                        d.close()
                    except Exception:
                        pass
                    mark_bulb_io(name)
            except Exception as e:
                mark_bulb_io(name)
                print(f"  [CMD] Error on {name} (attempt {attempt}): {e}")
                devices[name] = create_device(CANDLE_LIGHTS_CONFIG[name])

            if attempt < max_attempts:
                backoff = 0.45 * attempt
                time.sleep(backoff)

        print(f"  [WARN] {name} -> {action} failed verification after {max_attempts} attempts")
        threading.Thread(target=refresh_bulb_ip_if_changed, args=(name,), daemon=True).start()

def format_dps_status(name, dps):
    if not isinstance(dps, dict) or not dps:
        return None
    mode = dps.get('21', 'white')
    brightness = int(dps.get('22', 1000) / 10)
    if mode == 'colour' and isinstance(dps.get('24'), str) and len(dps['24']) == 12:
        try:
            brightness = max(1, min(100, int(round(int(dps['24'][8:12], 16) / 10.0))))
        except Exception:
            pass
    return {
        "name": name,
        "state": "on" if dps.get('20', False) else "off",
        "brightness": brightness,
        "mode": mode
    }

def get_light_status(name, prefer_cache=False):
    now = time.monotonic()
    cached = cached_dps.get(name)
    if cached and (prefer_cache or (now - last_cache_time.get(name, 0.0) < CACHE_TTL_SECONDS)):
        return format_dps_status(name, cached)

    lock = device_locks[name]
    if not lock.acquire(blocking=False):
        return format_dps_status(name, cached) if cached else None
    try:
        wait_for_bulb_cooldown(name, MIN_SOCKET_GAP)
        d = devices[name]
        status = d.status()
        mark_bulb_io(name)
        if isinstance(status, dict) and isinstance(status.get('dps'), dict):
            dps = status['dps']
            update_cached_dps(name, dps)
            return format_dps_status(name, dps)
    except Exception:
        mark_bulb_io(name)
    finally:
        lock.release()
    return format_dps_status(name, cached) if cached else None

def publish_all_status(client, prefer_cache=False):
    results = []
    for idx, name in enumerate(devices):
        if idx > 0 and not prefer_cache:
            time.sleep(0.08)
        status = get_light_status(name, prefer_cache=prefer_cache)
        if status:
            results.append(status)
    
    if results:
        is_on = any(r['state'] == 'on' for r in results)
        summary = {
            "room_state": "on" if is_on else "off",
            "devices": results
        }
        client.publish(STATUS_TOPIC, json.dumps(summary))

def execute_group_command(targets, action, value, extra):
    threads = []
    valid_targets = [name for name in targets if name in devices]
    for idx, name in enumerate(valid_targets):
        with seq_lock:
            command_seq[name] = command_seq.get(name, 0) + 1
            seq = command_seq[name]
        stagger_delay = idx * 0.08
        t = threading.Thread(
            target=toggle_light,
            args=(name, seq, stagger_delay, action, value, extra),
            daemon=True
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=15)
    publish_all_status(client, prefer_cache=True)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
        threading.Thread(target=publish_all_status, args=(client,), daemon=True).start()

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        action = payload.get("action")
        target = payload.get("target", "all")
        value = payload.get("value")

        if action == "status":
            threading.Thread(target=publish_all_status, args=(client, True), daemon=True).start()
            return
        
        targets = list(devices.keys()) if target == "all" else [target]
        threading.Thread(target=execute_group_command, args=(targets, action, value, payload), daemon=True).start()
            
    except Exception as e:
        print(f"Error: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.reconnect_delay_set(min_delay=1, max_delay=30)

# Earliest sunset time (hour, minute) by month (1-12) in local time (America/Los_Angeles)
EARLIEST_SUNSET_BY_MONTH = {
    1:  (17, 1),   # Jan: 5:01 PM -> ON at 4:01 PM
    2:  (17, 33),  # Feb: 5:33 PM -> ON at 4:33 PM
    3:  (18, 3),   # Mar: 6:03 PM -> ON at 5:03 PM
    4:  (19, 32),  # Apr: 7:32 PM -> ON at 6:32 PM
    5:  (20, 0),   # May: 8:00 PM -> ON at 7:00 PM
    6:  (20, 25),  # Jun: 8:25 PM -> ON at 7:25 PM
    7:  (20, 19),  # Jul: 8:19 PM -> ON at 7:19 PM
    8:  (19, 40),  # Aug: 7:40 PM -> ON at 6:40 PM
    9:  (18, 54),  # Sep: 6:54 PM -> ON at 5:54 PM
    10: (18, 12),  # Oct: 6:12 PM -> ON at 5:12 PM
    11: (16, 51),  # Nov: 4:51 PM -> ON at 3:51 PM
    12: (16, 50),  # Dec: 4:50 PM -> ON at 3:50 PM
}

def scheduler_loop():
    print(f"Scheduler started using static monthly earliest sunset table ({TIMEZONE})")
    last_off_date = None
    last_on_date = None
    
    while True:
        try:
            now = datetime.now(TZ)
            today = now.date()
            
            # --- OFF EVENT: 2:30 AM ---
            if now.hour == 2 and 30 <= now.minute <= 31 and last_off_date != today:
                print(f"Scheduled Event: Turning off lights (2:30 AM)")
                last_off_date = today
                execute_group_command(list(devices.keys()), "off", None, None)

            # --- ON EVENT: 1 hour before earliest monthly sunset ---
            sunset_hour, sunset_min = EARLIEST_SUNSET_BY_MONTH[now.month]
            on_hour = sunset_hour - 1
            on_min = sunset_min
            if now.hour == on_hour and on_min <= now.minute <= on_min + 1 and last_on_date != today:
                print(f"Scheduled Event: Turning on lights (Month {now.month} earliest sunset {sunset_hour:02d}:{sunset_min:02d}, triggering at {on_hour:02d}:{on_min:02d})")
                last_on_date = today
                execute_group_command(list(devices.keys()), "on", None, None)
            
        except Exception as e:
            print(f"Scheduler Error: {e}")
        
        time.sleep(30) 

def poll_loop():
    while True:
        time.sleep(180)
        publish_all_status(client)

threading.Thread(target=refresh_bulb_ip_if_changed, daemon=True).start()
threading.Thread(target=scheduler_loop, daemon=True).start()
threading.Thread(target=poll_loop, daemon=True).start()
print("Starting Listener (Room Mode)...")

while True:
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"MQTT connection error, retrying in 5s: {e}")
        time.sleep(5)
