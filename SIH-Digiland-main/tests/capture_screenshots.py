import subprocess
import os
import time

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

SCREENSHOTS_DIR = os.path.abspath(os.path.join("tests", "screenshots"))
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def capture_url(url, output_filename, window_size="1366,768"):
    out_path = os.path.join(SCREENSHOTS_DIR, output_filename)
    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={window_size}",
        f"--screenshot={out_path}",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=20)
        if os.path.exists(out_path):
            size = os.path.getsize(out_path)
            print(f"[OK] Captured {output_filename} ({size:,} bytes, {window_size})")
            return True
        else:
            print(f"[ERR] Failed to save {output_filename}: {res.stderr.decode('utf-8', errors='ignore')}")
            return False
    except Exception as e:
        print(f"[EXC] Error capturing {output_filename}: {e}")
        return False

def main():
    print(f"Executing automated screenshot capture suite using browser:\n{CHROME_PATH}\n")
    
    # 1. Desktop Dashboard View
    capture_url("http://localhost:5173", "01_desktop_dashboard.png", "1440,900")

    # 2. Tablet Viewport (768 x 1024)
    capture_url("http://localhost:5173", "02_tablet_view.png", "768,1024")

    # 3. Mobile Viewport (390 x 844)
    capture_url("http://localhost:5173", "03_mobile_view.png", "390,844")

    # 4. OpenAPI Interactive Swagger Documentation
    capture_url("http://localhost:8000/docs", "04_backend_swagger_docs.png", "1366,768")

    # 5. FastApi Health JSON response
    capture_url("http://localhost:8000/health", "05_backend_health.png", "1024,600")

if __name__ == "__main__":
    main()
