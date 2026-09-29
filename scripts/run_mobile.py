"""
CrowdSense One-Command Mobile Edge Camera Streamer.
Validates environment tokens, forces VIDEO_SRC=mobile and REQUIRE_AUTH_READS=true,
launches the dashboard server, establishes a secure tunnel (pyngrok / ngrok / cloudflared),
renders an ASCII terminal QR code, and handles graceful shutdown.

Usage:
    python scripts/run_mobile.py
"""

import os
import sys
import time
import shutil
import signal
import subprocess
import urllib.request
import json
from dotenv import load_dotenv

# Ensure root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

def mask_secret(s: str) -> str:
    """Masks secret token for display in logs."""
    if not s or len(s) < 4:
        return "***"
    return s[:2] + ("*" * (len(s) - 4)) + s[-2:]

def print_banner():
    print("=" * 70)
    print(" [CROWDSENSE] ONE-COMMAND MOBILE STREAMER LAUNCHER")
    print("=" * 70)

def validate_environment():
    api_key = os.getenv("CROWDSENSE_API_KEY", os.getenv("API_AUTH_KEY", "")).strip()
    mobile_token = os.getenv("MOBILE_CAM_TOKEN", "").strip()

    missing_vars = []
    if not api_key:
        missing_vars.append("CROWDSENSE_API_KEY")
    if not mobile_token:
        missing_vars.append("MOBILE_CAM_TOKEN")

    if missing_vars:
        print("\n[ERROR] Missing required security environment variables:")
        for var in missing_vars:
            print(f"   -> Please set '{var}' in your local .env file.")
        print("\nExample .env configuration:")
        print("   CROWDSENSE_API_KEY=your_secure_operator_api_key")
        print("   MOBILE_CAM_TOKEN=your_secure_mobile_streamer_token")
        sys.exit(1)

    return api_key, mobile_token


def start_tunnel():
    """
    Attempts to start a secure tunnel using:
    1. pyngrok (if pyngrok is installed and NGROK_AUTHTOKEN is configured)
    2. ngrok CLI (if 'ngrok' is in PATH)
    3. cloudflared (if 'cloudflared' is in PATH)
    """
    ngrok_token = os.getenv("NGROK_AUTHTOKEN", "").strip()

    # 1. Try pyngrok
    try:
        from pyngrok import ngrok, conf
        if ngrok_token:
            ngrok.set_auth_token(ngrok_token)
        tunnel = ngrok.connect(8000, "http")
        public_url = tunnel.public_url.replace("http://", "https://")
        print(f"[*] Established pyngrok secure tunnel: {public_url}")
        return public_url, ("pyngrok", ngrok)
    except Exception as e:
        # Fallback to CLI tools
        pass

    # 2. Try ngrok CLI
    if shutil.which("ngrok"):
        print("[*] Starting ngrok CLI tunnel on port 8000...")
        cmd = ["ngrok", "http", "8000", "--log=stdout"]
        if ngrok_token:
            cmd.extend(["--authtoken", ngrok_token])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=ROOT_DIR
        )
        time.sleep(2.5)
        # Fetch public url from local ngrok web inspection API
        try:
            req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3.0)
            data = json.loads(req.read().decode())
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    public_url = t.get("public_url")
                    return public_url, ("subprocess", proc)
            if tunnels:
                return tunnels[0].get("public_url").replace("http://", "https://"), ("subprocess", proc)
        except Exception:
            pass

    # 3. Try cloudflared CLI
    if shutil.which("cloudflared"):
        print("[*] Starting cloudflared tunnel on port 8000...")
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=ROOT_DIR
        )
        time.sleep(3.5)
        # Read tunnel URL from stderr / stdout
        # Cloudflared prints https://*.trycloudflare.com to stderr
        for _ in range(10):
            line = proc.stderr.readline() if proc.stderr else ""
            if "trycloudflare.com" in line:
                import re
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if match:
                    public_url = match.group(0)
                    return public_url, ("subprocess", proc)
            time.sleep(0.5)

    # If no tunnel found:
    print("\n⚠️ [WARNING] No tunnel provider found.")
    print("To stream from a real phone over the internet, install ngrok or pyngrok:")
    print("   pip install pyngrok  (and set NGROK_AUTHTOKEN in .env)")
    print("   or download ngrok / cloudflared and place it in your PATH.")
    print("Falling back to local network URL...\n")
    return "http://localhost:8000", ("none", None)

def render_qr_code(url: str):
    """Renders an ASCII QR Code directly in the terminal."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2
        )
        qr.add_data(url)
        qr.make(fit=True)
        print("\n📱 Scan this QR code on your phone to open the camera streamer:\n")
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f"[*] (QR Code render note: {e})")

def main():
    print_banner()
    api_key, mobile_token = validate_environment()

    # Force environment overrides for mobile streamer run
    env_overrides = os.environ.copy()
    env_overrides["VIDEO_SRC"] = "mobile"
    env_overrides["REQUIRE_AUTH_READS"] = "true"
    env_overrides["CROWDSENSE_API_KEY"] = api_key
    env_overrides["MOBILE_CAM_TOKEN"] = mobile_token

    print(f"[*] Validated credentials (MOBILE_CAM_TOKEN: {mask_secret(mobile_token)})")
    print("[*] Configured forced settings: VIDEO_SRC=mobile, REQUIRE_AUTH_READS=true")

    # Start dashboard server subprocess
    print("[*] Starting CrowdSense Dashboard Server on http://localhost:8000 ...")
    server_proc = subprocess.Popen(
        [sys.executable, "dashboard.py"],
        env=env_overrides,
        cwd=ROOT_DIR
    )

    tunnel_info = None
    try:
        # Wait for server startup
        time.sleep(2.5)

        public_base_url, tunnel_info = start_tunnel()
        phone_url = f"{public_base_url}/mobile?token={mobile_token}"

        print("\n" + "=" * 70)
        print(" 🚀 MOBILE STREAMER READY TO CONNECT")
        print("=" * 70)
        print(f" 📱 Phone Camera URL   : {phone_url}")
        print(f" 💻 Laptop Dashboard   : http://localhost:8000")
        print("=" * 70)

        render_qr_code(phone_url)

        print("\n📋 Instructions:")
        print(" 1. Scan the QR code or open the Phone URL on your mobile browser.")
        print(" 2. Grant camera permissions and mount phone on a stand/tripod.")
        print(" 3. Tap 'Start Camera Stream' to stream live frames to CrowdSense.")
        print(" 4. Press Ctrl+C in this terminal to shut down server and tunnels.\n")

        # Keep running until Ctrl+C
        while True:
            if server_proc.poll() is not None:
                print("Server stopped unexpectedly.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[*] Received shutdown signal (Ctrl+C). Cleaning up...")
    finally:
        # Clean shutdown of server
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3)
            except Exception:
                server_proc.kill()
            print("[*] Dashboard server stopped.")

        # Clean shutdown of tunnel
        if tunnel_info:
            t_type, t_obj = tunnel_info
            if t_type == "pyngrok" and t_obj:
                try:
                    t_obj.kill()
                    print("[*] pyngrok tunnel closed.")
                except Exception:
                    pass
            elif t_type == "subprocess" and t_obj:
                try:
                    t_obj.terminate()
                    t_obj.wait(timeout=2)
                    print("[*] Tunnel process closed.")
                except Exception:
                    t_obj.kill()

        print("[*] CrowdSense mobile streamer session ended cleanly.")

if __name__ == "__main__":
    main()
