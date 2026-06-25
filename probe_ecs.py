import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('8.156.35.98', username='root', password='yxf20041231yxf.', timeout=15)
print('=== Connected ===')

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8','replace')
    err = stderr.read().decode('utf-8','replace')
    return stdout.channel.recv_exit_status(), out, err

_, out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1')
print('--- Docker ---')
print(out[:600])

_, out, _ = run('ls -la /root/src/ 2>&1')
print('--- /root/src/ ---')
print(out[:600])

_, out, _ = run('cd /root/src && git log --oneline -3 2>&1')
print('--- Git log ---')
print(out[:400])

_, out, _ = run('cd /root/src && head -3 .env 2>&1')
print('--- .env head ---')
print(out[:200])

_, out, _ = run('cd /root/src && head -20 docker-compose.yml 2>&1')
print('--- compose head ---')
print(out[:500])

ssh.close()
