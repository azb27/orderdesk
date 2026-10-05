#!/usr/bin/env bash
# Local Postgres for dev and tests: a throwaway cluster in .pg/ on port 5433.
#   scripts/pg.sh start | stop | status | reset
# In CI a Postgres service container is used instead (see .github/workflows/ci.yml).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/.pg"
PORT="${ORDERDESK_PG_PORT:-5433}"
BIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
[ -n "$BIN" ] || BIN="$(dirname "$(command -v pg_ctl)")"
run() {  # postgres refuses to run as root; drop to the postgres user when needed
  if [ "$(id -u)" = "0" ]; then su postgres -s /bin/bash -c "$*"; else bash -c "$*"; fi
}
init() {
  mkdir -p "$DIR"
  [ "$(id -u)" = "0" ] && chown postgres "$DIR"
  run "$BIN/initdb -D '$DIR/data' -U orderdesk --auth=trust -E UTF8 --locale=C.UTF-8 >/dev/null"
}
case "${1:-start}" in
  start)
    [ -d "$DIR/data" ] || init
    run "$BIN/pg_ctl -D '$DIR/data' -l '$DIR/log' -o '-p $PORT -k /tmp' -w start >/dev/null"
    for db in orderdesk orderdesk_test; do
      psql -h 127.0.0.1 -p "$PORT" -U orderdesk -d postgres -tAc "select 1 from pg_database where datname='$db'" | grep -q 1 \
        || psql -h 127.0.0.1 -p "$PORT" -U orderdesk -d postgres -qc "create database $db"
    done
    echo "postgres on 127.0.0.1:$PORT (databases orderdesk, orderdesk_test)";;
  stop)   run "$BIN/pg_ctl -D '$DIR/data' -w stop" ;;
  status) run "$BIN/pg_ctl -D '$DIR/data' status" ;;
  reset)  "$0" stop || true; rm -rf "$DIR"; "$0" start ;;
esac
