#!/usr/bin/env python
"""
Run script: start backend and open v2 HTML frontend.
"""
import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path

HEALTH_URL = "http://127.0.0.1:8000/health"
FRONTEND_URL = "http://127.0.0.1:8000/index_v2.html"


def load_env(backend_dir: Path):
    backend_env_path = backend_dir / ".env"
    if backend_env_path.exists():
        with open(backend_env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
    return backend_env_path


def wait_for_backend(timeout=30, interval=0.5):
    """等待后端就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            import urllib.request
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def main():
    root_dir = Path(__file__).parent.resolve()
    backend_dir = root_dir / "backend"

    backend_env_path = load_env(backend_dir)

    print(f"✓ Environment loaded from {backend_env_path}")
    print(f"  HTTP_PROXY: {os.environ.get('HTTP_PROXY') or '(直连)'}")
    print(f"  HTTPS_PROXY: {os.environ.get('HTTPS_PROXY') or '(直连)'}")
    print("🚀 Starting backend server (uvicorn)...")

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
    ]

    os.chdir(backend_dir)
    proc = None
    try:
        proc = subprocess.Popen(backend_cmd)
        print(f"Started backend (pid={proc.pid})")

        print("Waiting for backend at http://127.0.0.1:8000/health ...")
        if wait_for_backend(timeout=30):
            print(f"Backend ready — opening {FRONTEND_URL}")
            webbrowser.open(FRONTEND_URL)
        else:
            print("Backend did not become ready. Open manually after it starts:")
            print(FRONTEND_URL)

        proc.wait()
    except KeyboardInterrupt:
        print("\n✓ Received KeyboardInterrupt — shutting down...")
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
