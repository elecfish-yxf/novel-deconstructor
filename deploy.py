"""Deploy to ECS server via SSH."""
import paramiko
import sys

HOST = "8.156.35.98"
USER = "root"
PASS = "yxf20041231yxf."
REPO_URL = "git@github.com:elecfish-yxf/novel-deconstructor.git"
SRC_DIR = "/root/src"

def run(ssh: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, out, err

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    print("Connected!")

    # 1. Check current state
    print("\n--- Checking current state ---")
    _, out, _ = run(ssh, f"ls {SRC_DIR}/")
    print(f"src/: {out.strip()}")

    _, out, _ = run(ssh, "docker ps --format 'table {{.Names}}\t{{.Status}}'")
    print(f"Docker:\n{out}")

    # 2. Git pull or clone
    print("\n--- Updating code ---")
    _, out, err = run(ssh, f"cd {SRC_DIR} && git remote -v 2>/dev/null || echo 'NOT_A_GIT_REPO'")
    if "NOT_A_GIT_REPO" in out:
        print("Not a git repo. Cloning...")
        code, out, err = run(ssh, f"cd /root && git clone {REPO_URL} src 2>&1")
        print(out[-500:] if len(out) > 500 else out)
        if err: print("ERR:", err[-300:])
    else:
        print("Pulling latest...")
        code, out, err = run(ssh, f"cd {SRC_DIR} && git pull origin main 2>&1")
        print(out[-500:] if len(out) > 500 else out)
        if err: print("ERR:", err[-300:])

    # 3. Rebuild docker
    print("\n--- Rebuilding Docker ---")
    code, out, err = run(ssh, f"cd {SRC_DIR} && docker compose down 2>&1 && docker compose build --no-cache 2>&1 && docker compose up -d 2>&1")
    print(out[-800:] if len(out) > 800 else out)
    if err: print("ERR:", err[-400:])

    # 4. Verify
    print("\n--- Verification ---")
    _, out, _ = run(ssh, "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
    print(out)
    _, out, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/config/public 2>/dev/null || echo 'backend not ready'")
    print(f"Backend status: {out.strip()}")

    ssh.close()
    print("\nDone!")

if __name__ == "__main__":
    main()
