import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('8.156.35.98', username='root', password='yxf20041231yxf.', timeout=15)

def r(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    code = stdout.channel.recv_exit_status()
    return code, stdout.read().decode() + stderr.read().decode()

# Step 1: git pull
print('=== git pull ===')
code, out = r('cd /srv/novel-deconstructor && git pull origin main 2>&1')
print(out[-800:])

# Step 2: docker compose rebuild
print('=== docker compose down ===')
code, out = r('cd /srv/novel-deconstructor && docker compose down 2>&1')
print(out[-400:])

print('=== docker compose build (this takes time) ===')
code, out = r('cd /srv/novel-deconstructor && docker compose build --no-cache 2>&1')
# Print last 1000 chars of build output
if len(out) > 1000:
    print('...(build output truncated)...')
    print(out[-1000:])
else:
    print(out)

print('=== docker compose up ===')
code, out = r('cd /srv/novel-deconstructor && docker compose up -d 2>&1')
print(out[-400:])

# Wait for services
time.sleep(5)

# Step 3: verify
print('=== verify ===')
_, out = r('docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"')
print(out)
_, out = r('curl -s http://localhost:8000/api/config/public')
print('Backend:', out[:300])

ssh.close()
print('\nDone!')
