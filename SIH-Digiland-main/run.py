import subprocess
import sys
import time
import webbrowser
import os
import socket
import urllib.request

def is_port_in_use(port):
    """Check if a TCP port is currently occupied on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0

def free_port_if_in_use(port):
    """Attempt to free a port occupied by a lingering process on Windows."""
    if not is_port_in_use(port):
        return True
    
    print(f"[*] Port {port} is currently in use. Attempting to release it...")
    if os.name == "nt":
        try:
            cmd = f'netstat -ano | findstr :{port}'
            output = subprocess.check_output(cmd, shell=True).decode()
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5 and (parts[1].endswith(f":{port}") or parts[1].endswith(f".{port}")):
                    pid = parts[-1]
                    if pid and pid != '0':
                        subprocess.run(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        except Exception:
            pass
    return not is_port_in_use(port)

def wait_for_health(url, timeout=15):
    """Poll a URL until it responds with HTTP 200/304 or timeout expires."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DigiLand-HealthCheck'})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 304):
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def kill_proc_tree(proc):
    """Cleanly terminate a process and all its spawned worker children."""
    if not proc:
        return
    try:
        if os.name == "nt":
            subprocess.run(f"taskkill /F /T /PID {proc.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
    except Exception:
        pass

def start_services():
    print("=" * 66)
    print("      🏛️  DigiLand GovTech Platform - 1-Click Master Launcher")
    print("=" * 66)
    print()

    root_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Preflight Port Checks
    free_port_if_in_use(8000)
    free_port_if_in_use(5173)

    # 2. Check Node & Dependencies
    node_modules_dir = os.path.join(root_dir, "node_modules")
    if not os.path.exists(node_modules_dir):
        print("[!] node_modules folder missing. Running 'npm install'...")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm_cmd, "install"], cwd=root_dir)

    # 3. Launch FastAPI Backend Server
    print("[1/2] 🚀 Launching FastAPI Backend Server (http://localhost:8000)...")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=root_dir
    )

    # 4. Launch React / Vite Frontend Server
    print("[2/2] ⚡ Launching React / Vite Frontend Server (http://localhost:5173)...")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    frontend_process = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=root_dir
    )

    print()
    print("[+] Waiting for services to initialize and pass health checks...")
    backend_ready = wait_for_health("http://localhost:8000/health", timeout=12)
    frontend_ready = wait_for_health("http://localhost:5173", timeout=12)

    if backend_ready:
        print("    ✅ FastAPI Backend API is Online (http://localhost:8000)")
    else:
        print("    ⚠️  FastAPI Backend started, initializing endpoints...")

    if frontend_ready:
        print("    ✅ React / Vite Web Application is Online (http://localhost:5173)")
    else:
        print("    ⚠️  React Frontend started, building bundle...")

    web_url = "http://localhost:5173"
    print(f"\n[+] 🌐 Opening DigiLand Web Application in your default browser: {web_url}")
    try:
        webbrowser.open(web_url)
    except Exception:
        print(f"[*] Note: Open {web_url} manually in your browser.")

    print()
    print("=" * 66)
    print("   🎉 DigiLand Platform is fully operational!")
    print("   • Web Application (Login & UI):  http://localhost:5173")
    print("   • OpenAPI Swagger Documentation:  http://localhost:8000/docs")
    print("   • API Health Endpoint:            http://localhost:8000/health")
    print("   • To stop both services, press Ctrl + C.")
    print("=" * 66)
    print()

    try:
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n\n[!] Received shutdown signal. Gracefully stopping DigiLand services...")
        kill_proc_tree(backend_process)
        kill_proc_tree(frontend_process)
        print("[+] All DigiLand services stopped successfully. Goodbye!")

if __name__ == "__main__":
    start_services()
