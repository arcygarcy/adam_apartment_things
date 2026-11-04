import tinytuya
import paho.mqtt.client as mqtt
import json
import threading
import os
import time
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

# --- PERSISTENT DEVICE OBJECTS ---
devices = {}
for name, cfg in CANDLE_LIGHTS_CONFIG.items():
    d = tinytuya.BulbDevice(dev_id=cfg['id'], address=cfg['ip'], local_key=cfg['key'], version=cfg['version'])
    d.set_socketTimeout(3)
    d.set_socketRetryLimit(1)
    devices[name] = d

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def toggle_light(name, action, value=None):
    try:
        d = devices[name]
        if action == "on": d.turn_on()
        elif action == "off": d.turn_off()
        elif action == "brightness":
            d.set_brightness(int(value) * 10)
        elif action == "color":
            r, g, b = hex_to_rgb(value)
            d.set_mode('colour') 
            d.set_colour(r, g, b)
        elif action == "white":
            d.set_mode('white')
            d.set_brightness(1000)
        elif action == "reset":
            d.turn_on()
            time.sleep(0.1)
            d.set_mode('white')
            time.sleep(0.1)
            d.set_brightness(1000)
            d.set_colourtemp(300) 
        print(f"  [CMD] {name} -> {action}")
    except Exception as e:
        print(f"  [CMD] Error on {name}: {e}")

def get_light_status(name):
    try:
        d = devices[name]
        status = d.status()
        if status and 'dps' in status:
            dps = status['dps']
            return {
                "name": name,
                "state": "on" if dps.get('20', False) else "off",
                "brightness": int(dps.get('22', 0) / 10),
                "mode": dps.get('21', 'white')
            }
    except: pass
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
        for name in targets:
            threading.Thread(target=toggle_light, args=(name, action, value), daemon=True).start()
        
        time.sleep(1)
        threading.Thread(target=publish_all_status, args=(client,), daemon=True).start()
            
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
                for name in devices:
                    threading.Thread(target=toggle_light, args=(name, "off"), daemon=True).start()
                last_off_date = today
                time.sleep(1)
                publish_all_status(client)

            # --- ON EVENT: 1 hour before earliest monthly sunset ---
            sunset_hour, sunset_min = EARLIEST_SUNSET_BY_MONTH[now.month]
            on_hour = sunset_hour - 1
            on_min = sunset_min
            if now.hour == on_hour and on_min <= now.minute <= on_min + 1 and last_on_date != today:
                print(f"Scheduled Event: Turning on lights (Month {now.month} earliest sunset {sunset_hour:02d}:{sunset_min:02d}, triggering at {on_hour:02d}:{on_min:02d})")
                for name in devices:
                    threading.Thread(target=toggle_light, args=(name, "on"), daemon=True).start()
                last_on_date = today
                time.sleep(1)
                publish_all_status(client)
            
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
