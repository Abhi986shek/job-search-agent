#!/usr/bin/env bash
# Start the backend (http://127.0.0.1:8001) and the frontend (http://localhost:8501) together.
# Ctrl+C stops both. Run from anywhere:  bash run.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_URL="http://127.0.0.1:8001"
FRONTEND_PORT=8501

# Windows venv (Git Bash) or Linux/macOS venv
if [ -x "$ROOT/Myenv/Scripts/python.exe" ]; then
  PY="$ROOT/Myenv/Scripts/python.exe"
elif [ -x "$ROOT/Myenv/bin/python" ]; then
  PY="$ROOT/Myenv/bin/python"
else
  echo "Virtual environment 'Myenv' not found. Run setup first (see README)." >&2
  exit 1
fi

if [ ! -f "$ROOT/job_agent/.env" ]; then
  echo "job_agent/.env is missing. Copy job_agent/.env.example and fill it in." >&2
  exit 1
fi

BACK_PID=""
FRONT_PID=""
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping..."
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null
  wait 2>/dev/null
  echo "Stopped."
}
trap cleanup INT TERM EXIT

echo "Starting backend..."
(cd "$ROOT/job_agent" && exec "$PY" app.py) &
BACK_PID=$!

# Wait up to 60 seconds for /health before starting the UI.
for _ in $(seq 1 60); do
  if "$PY" -c "import urllib.request; urllib.request.urlopen('$BACKEND_URL/health', timeout=2)" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$BACK_PID" 2>/dev/null; then
    echo "Backend failed to start. See job_agent/app.log" >&2
    exit 1
  fi
  sleep 1
done

echo "Starting frontend..."
(cd "$ROOT/frontend" && exec "$PY" -m streamlit run app.py \
    --server.address 127.0.0.1 --server.port "$FRONTEND_PORT" --browser.gatherUsageStats false) &
FRONT_PID=$!

echo
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo "  Backend:  $BACKEND_URL  (API docs: $BACKEND_URL/docs)"
echo "  Press Ctrl+C to stop both."
echo

# Exit when either one stops; cleanup stops the other.
wait -n "$BACK_PID" "$FRONT_PID"
