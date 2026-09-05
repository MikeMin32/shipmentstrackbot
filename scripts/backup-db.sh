#!/usr/bin/env bash
# Copy the SQLite database to a timestamped backup.
# Prefer stopping shipment-bot first so WAL is checkpointed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

DB="${DATABASE_PATH:-$ROOT/data/shipments.db}"
if [[ "$DB" != /* ]]; then
  DB="$ROOT/$DB"
fi

if [[ ! -f "$DB" ]]; then
  echo "Database not found: $DB" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${1:-$DB.bak.$STAMP}"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$DEST'"
else
  cp -a "$DB" "$DEST"
  [[ -f "$DB-wal" ]] && cp -a "$DB-wal" "$DEST-wal"
  [[ -f "$DB-shm" ]] && cp -a "$DB-shm" "$DEST-shm"
fi

echo "Backup written to $DEST"
