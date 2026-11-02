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
migration_log="$(mktemp)"
if .venv/bin/python -m alembic upgrade head >"$migration_log" 2>&1; then
  cat "$migration_log"
  rm -f -- "$migration_log"
else
  if grep -Fq "Can't locate revision identified by" "$migration_log"; then
    echo 'The SQLite database belongs to a different branch; saving it and creating a fresh local database.' >&2
    migration_paths="$(PYTHONPATH=backend .venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings

url = make_url(Settings().database_url)
if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
    raise SystemExit("Automatic recovery is only available for file-based SQLite databases.")

database = Path(url.database)
if not database.is_absolute():
    database = Path.cwd() / database
database = database.resolve()
if not database.is_file():
    raise SystemExit(f"SQLite database file not found: {database}")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = database.with_name(f"{database.stem}.backup-{stamp}{database.suffix or '.db'}")
with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
    source.backup(target)
backup.chmod(0o600)
print(database)
print(backup)
PY
)" || {
      cat "$migration_log" >&2
      echo 'Could not back up the SQLite database; servers were not started.' >&2
      rm -f -- "$migration_log"
      exit 1
    }
    mapfile -t migration_paths <<<"$migration_paths"
    migration_database="${migration_paths[0]}"
    migration_backup="${migration_paths[1]}"
    printf 'Saved the previous database to %s\n' "$migration_backup" >&2
    rm -f -- "$migration_database" "$migration_database-wal" "$migration_database-shm"
    if .venv/bin/python -m alembic upgrade head >"$migration_log" 2>&1; then
      cat "$migration_log"
      rm -f -- "$migration_log"
    else
      cat "$migration_log" >&2
      echo 'Fresh database migration failed; restoring the previous database.' >&2
      rm -f -- "$migration_database" "$migration_database-wal" "$migration_database-shm"
      cp -- "$migration_backup" "$migration_database"
      rm -f -- "$migration_log"
      exit 1
    fi
  else
    cat "$migration_log" >&2
    echo 'Database migration failed; servers were not started.' >&2
    rm -f -- "$migration_log"
    exit 1
  fi
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

TABLESIGNUP_LOCAL_AUTO_MIGRATE=1 .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload --reload-dir backend &
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
