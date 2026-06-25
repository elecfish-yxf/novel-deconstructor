import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('8.156.35.98',username='root',password='yxf20041231yxf.',timeout=15)

def r(cmd):
    _,o,e=ssh.exec_command(cmd)
    return o.read().decode()+e.read().decode()

print('--- find dirs ---')
print(r('find / -maxdepth 3 -type d -name "novel*" 2>/dev/null'))
print(r('find / -maxdepth 3 -type d -name "src" 2>/dev/null | head -10'))

print('--- docker inspect ---')
print(r('docker inspect novel-deconstructor | grep -A5 Mounts'))
print(r('docker inspect novel-deconstructor | grep Image'))

print('--- root home ---')
print(r('ls -la /root/'))

print('--- root subdirs ---')
print(r('for d in /root/*/; do echo "$d"; ls "$d" 2>/dev/null | head -5; done'))

ssh.close()
