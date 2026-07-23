#!/bin/bash
# OKEworkplace Startup Script for macOS/Linux
# This script sets up the environment and starts the frontend with auto-managed backend

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "========================================"
echo "  OKEworkplace - Auto-Start Manager"
echo "========================================"
echo ""

# Load .env file from backend
ENV_FILE="$SCRIPT_DIR/backend/.env"
if [ -f "$ENV_FILE" ]; then
    echo "[INFO] Loading environment from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
    echo "[OK] Environment loaded"
else
    echo "[WARN] No .env file found at $ENV_FILE"
fi

# Set default proxy if not already set
: "${HTTP_PROXY:=http://127.0.0.1:12334}"
: "${HTTPS_PROXY:=http://127.0.0.1:12334}"

export HTTP_PROXY
export HTTPS_PROXY

echo ""
echo "[CONFIG] Proxy Settings:"
echo "  HTTP_PROXY=$HTTP_PROXY"
echo "  HTTPS_PROXY=$HTTPS_PROXY"
echo ""
echo "[INFO] Starting OKEworkplace Frontend..."
echo "[INFO] Backend will auto-start on first page load"
echo "[INFO] Backend will auto-stop when you close the browser"
echo ""

# Run streamlit frontend
cd "$SCRIPT_DIR/frontend"
python -m streamlit run app.py --logger.level=warning

# If we get here, the session was closed
echo ""
echo "[INFO] Frontend closed. Backend will be terminated."
echo ""
