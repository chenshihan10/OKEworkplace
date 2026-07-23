"""Debug entry point - print to diagnose issues"""
import sys
print(f"Python: {sys.version}", flush=True)
print(f"Frozen: {getattr(sys, 'frozen', False)}", flush=True)
print(f"sys.argv: {sys.argv}", flush=True)

try:
    from fastapi import FastAPI
    print("✓ fastapi imported", flush=True)
except Exception as e:
    print(f"✗ fastapi import error: {e}", flush=True)
    sys.exit(1)

try:
    from app.routes import coins, monitor, network, analysis
    print("✓ routes imported", flush=True)
except Exception as e:
    print(f"✗ routes import error: {e}", flush=True)
    sys.exit(1)

try:
    from app.core.scheduler import start_scheduler
    print("✓ scheduler imported", flush=True)
except Exception as e:
    print(f"✗ scheduler import error: {e}", flush=True)
    sys.exit(1)

try:
    import uvicorn
    print("✓ uvicorn imported, starting server...", flush=True)
    app = FastAPI()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
except Exception as e:
    print(f"✗ server error: {e}", flush=True)
    sys.exit(1)
