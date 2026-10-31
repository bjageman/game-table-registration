#!/usr/bin/env bash
# Run the API and frontend together; Ctrl+C stops both.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -f .env ]]; then
  echo 'Missing .env. Copy .env.example to .env and configure Discord first.' >&2
  exit 1
fi
for tool in node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install Node.js and npm first." >&2
    exit 1
  fi
done

if command -v uv >/dev/null 2>&1; then
  uv sync --frozen
elif [[ ! -x .venv/bin/python ]]; then
  echo 'Install uv and rerun ./run.sh to create the Python environment.' >&2
  exit 1
else
  echo 'uv is unavailable; using the existing .venv.'
fi

if [[ ! -f frontend/node_modules/vite/bin/vite.js ]]; then
  (cd frontend && npm ci)
fi
if ! .venv/bin/python -m alembic upgrade head; then
  cat >&2 <<'EOF'
Database migration failed; servers were not started.
If Alembic says "Can't locate revision", the database may belong to a different
branch. Use the branch containing that migration, or choose an UNUSED database
filename. A previously used alternative may have the same migration mismatch:
  DATABASE_URL="sqlite:///./dev-$(date +%s).db" ./run.sh
A fresh database starts without your existing events.
Keep the existing database intact; do not reset or stamp it to bypass this error.
EOF
  exit 1
fi

pids=()
cleanup() {
  trap - EXIT INT TERM
  if (( ${#pids[@]} )); then
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload --reload-dir backend &
pids+=("$!")
(
  cd frontend
  exec node node_modules/vite/bin/vite.js
) &
pids+=("$!")

echo 'Starting API and frontend. Open the Local/Network URL printed by Vite.'
echo 'Press Ctrl+C to stop both servers.'
# If either server exits (including a startup failure), stop the other too.
wait -n "${pids[@]}"
