import os
import sys
import getpass
import paramiko

# Ensure UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Target Raspberry Pi settings (can be provided via environment variables or CLI arguments)
hostname = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('PI_HOST', 'raspberrypi.local')
username = 'pi'
password = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('PI_PASSWORD')

if not password:
    try:
        password = getpass.getpass(prompt=f"Enter SSH password for {username}@{hostname}: ")
    except Exception:
        print(f"Error: SSH password required. Pass as 2nd argument or set PI_PASSWORD environment variable.")
        sys.exit(1)

print(f"==========================================")
print(f" Deploying Adam Apartment Hub to {username}@{hostname}")
print(f"==========================================")

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname, port=22, username=username, password=password, timeout=10)
    print("✓ SSH connection established!")
except Exception as e:
    print(f"✗ Failed to connect to Raspberry Pi at {hostname}: {e}")
    sys.exit(1)

sftp = ssh.open_sftp()
local_base = os.path.dirname(os.path.abspath(__file__))
remote_dir = "/home/pi/code/adam_apartment_things"

def ensure_remote_dir(path_dir):
    try:
        sftp.stat(path_dir)
    except FileNotFoundError:
        print(f"Creating remote directory: {path_dir}")
        sftp.mkdir(path_dir)

ensure_remote_dir(remote_dir)
ensure_remote_dir(f"{remote_dir}/printer")
ensure_remote_dir(f"{remote_dir}/lights")
ensure_remote_dir(f"{remote_dir}/lights/listener")

files_to_upload = [
    ("server.js", f"{remote_dir}/server.js"),
    ("package.json", f"{remote_dir}/package.json"),
    ("index.html", f"{remote_dir}/index.html"),
    ("CNAME", f"{remote_dir}/CNAME"),
    (os.path.join("printer", "index.html"), f"{remote_dir}/printer/index.html"),
    (os.path.join("printer", "script.js"), f"{remote_dir}/printer/script.js"),
    (os.path.join("printer", "style.css"), f"{remote_dir}/printer/style.css"),
    (os.path.join("printer", "firebase-config.example.js"), f"{remote_dir}/printer/firebase-config.example.js"),
    (os.path.join("lights", "index.html"), f"{remote_dir}/lights/index.html"),
    (os.path.join("lights", "start_listener.sh"), f"{remote_dir}/lights/start_listener.sh"),
    (os.path.join("lights", "listener", "listener.py"), f"{remote_dir}/lights/listener/listener.py"),
    (os.path.join("lights", "listener", "requirements.txt"), f"{remote_dir}/lights/listener/requirements.txt"),
    (os.path.join("lights", "listener", "config.example.json"), f"{remote_dir}/lights/listener/config.example.json")
]

for local_rel, remote_path in files_to_upload:
    local_path = os.path.join(local_base, local_rel)
    if os.path.exists(local_path):
        print(f"  Uploading: {local_rel} -> {remote_path}")
        sftp.put(local_path, remote_path)
    else:
        print(f"  ⚠ Skipping missing file: {local_path}")

print("✓ All files successfully uploaded!")

# Restart PM2 service on Raspberry Pi
print("\nRestarting printer service on Raspberry Pi...")
cmd = "export PATH=$PATH:/home/pi/.nvm/versions/node/$(ls /home/pi/.nvm/versions/node 2>/dev/null | tail -n 1)/bin; cd /home/pi/code/adam_apartment_things && npm install firebase --save && (pm2 restart printer || pm2 start server.js --name printer)"
stdin, stdout, stderr = ssh.exec_command(cmd)

out_text = stdout.read().decode('utf-8', errors='replace')
err_text = stderr.read().decode('utf-8', errors='replace')
print("Service restart output:\n", out_text)

sftp.close()
ssh.close()
print("==========================================")
print(" 🎉 Deployment completed successfully!")
print("==========================================")
