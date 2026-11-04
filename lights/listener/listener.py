import tinytuya
import paho.mqtt.client as mqtt
import json
import threading
import os
import time
import colorsys
from datetime import datetime
from zoneinfo import ZoneInfo

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

# --- PERSISTENT DEVICE OBJECTS & LOCKS ---
devices = {}
device_locks = {}
for name, cfg in CANDLE_LIGHTS_CONFIG.items():
    d = tinytuya.BulbDevice(dev_id=cfg['id'], address=cfg['ip'], local_key=cfg['key'], version=cfg['version'])
    d.set_socketTimeout(3)
    d.set_socketRetryLimit(2)
    devices[name] = d
    device_locks[name] = threading.Lock()

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

def build_expected_dps(d, action, value=None, extra=None):
    extra = extra or {}
    if action == "on":
        return {'20': True}
    elif action == "off":
        return {'20': False}
    elif action == "white":
        return {'20': True, '21': 'white', '22': 1000}
    elif action == "reset":
        return {'20': True, '21': 'white', '22': 1000, '23': 300}
    elif action == "color":
        brightness_pct = max(1, min(100, int(extra.get("brightness", 100))))
        return {'20': True, '21': 'colour', '24': rgb_to_tuya_hsv(value, brightness_pct)}
    elif action in ("brightness", "dim", "apply"):
        brightness_pct = max(1, min(100, int(extra.get("brightness", value if value is not None else 100))))
        color_hex = extra.get("color")
        if color_hex:
            return {'20': True, '21': 'colour', '24': rgb_to_tuya_hsv(color_hex, brightness_pct)}

        # Dim / adjust brightness of the bulb's current color or white mode
        scaled_val = max(10, min(1000, int(round(brightness_pct * 10))))
        cur_status = d.status()
        cur_dps = cur_status.get('dps', {}) if isinstance(cur_status, dict) else {}
        if cur_dps.get('21') == 'colour' and isinstance(cur_dps.get('24'), str) and len(cur_dps['24']) == 12:
            hue_sat = cur_dps['24'][:8]
            return {'20': True, '21': 'colour', '24': f"{hue_sat}{scaled_val:04x}"}
        else:
            return {'20': True, '21': 'white', '22': scaled_val}
    return {}

def toggle_light(name, action, value=None, extra=None):
    d = devices[name]
    lock = device_locks[name]
    with lock:
        expected_dps = None
        for attempt in range(1, 5):
            try:
                if expected_dps is None:
                    expected_dps = build_expected_dps(d, action, value, extra)
                if not expected_dps:
                    return

                if len(expected_dps) == 1 and '20' in expected_dps:
                    res = d.turn_on() if expected_dps['20'] else d.turn_off()
                else:
                    res = d.set_multiple_values(expected_dps)

                # Check returned DPS first, then explicitly query status() to confirm hardware state
                res_dps = res.get('dps') if isinstance(res, dict) else None
                if not dps_matches(res_dps, expected_dps):
                    time.sleep(0.15)
                    verify = d.status()
                    res_dps = verify.get('dps') if isinstance(verify, dict) else None

                if dps_matches(res_dps, expected_dps):
                    print(f"  [CMD] {name} -> {action} OK (attempt {attempt})")
                    return

                print(f"  [RETRY] {name} -> {action} mismatch on attempt {attempt} (wanted {expected_dps}, got {res_dps})")
            except Exception as e:
                print(f"  [CMD] Error on {name} (attempt {attempt}): {e}")

            time.sleep(0.25 * attempt)

        print(f"  [WARN] {name} -> {action} failed verification after 4 attempts")

def get_light_status(name):
    lock = device_locks[name]
    if not lock.acquire(blocking=False):
        return None
    try:
        d = devices[name]
        status = d.status()
        if status and 'dps' in status:
            dps = status['dps']
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
    except Exception:
        pass
    finally:
        lock.release()
    return None

def publish_all_status(client):
    results = []
    for name in devices:
        status = get_light_status(name)
        if status: results.append(status)
    
    if results:
        is_on = any(r['state'] == 'on' for r in results)
        summary = {
            "room_state": "on" if is_on else "off",
            "devices": results
        }
        client.publish(STATUS_TOPIC, json.dumps(summary))

def execute_group_command(targets, action, value, extra):
    threads = []
    for name in targets:
        if name in devices:
            t = threading.Thread(target=toggle_light, args=(name, action, value, extra), daemon=True)
            t.start()
            threads.append(t)
    for t in threads:
        t.join(timeout=10)
    publish_all_status(client)

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
            threading.Thread(target=publish_all_status, args=(client,), daemon=True).start()
            return
        
        targets = list(devices.keys()) if target == "all" else [target]
        threading.Thread(target=execute_group_command, args=(targets, action, value, payload), daemon=True).start()
            
    except Exception as e:
        print(f"Error: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)

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
        time.sleep(30) 
        publish_all_status(client)

threading.Thread(target=scheduler_loop, daemon=True).start()
threading.Thread(target=poll_loop, daemon=True).start()
print("Starting Listener (Room Mode)...")
client.loop_forever()
