#!/bin/sh
set -e

# auto-detect CPUs, respect overrides
# --- Auto-detect CPU count ---
CPU_COUNT=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)

# --- Processes: default = CPU count, min 1, max 32 ---
UWSGI_PROCESSES=${UWSGI_PROCESSES:-$CPU_COUNT}
UWSGI_PROCESSES=$(( UWSGI_PROCESSES < 1  ? 1  : UWSGI_PROCESSES ))
UWSGI_PROCESSES=$(( UWSGI_PROCESSES > 32 ? 32 : UWSGI_PROCESSES ))

# --- Threads: default = 2 ---
UWSGI_THREADS=${UWSGI_THREADS:-2}

export UWSGI_PROCESSES UWSGI_THREADS

echo "[entrypoint] CPUs detected : $CPU_COUNT"
echo "[entrypoint] uWSGI processes: $UWSGI_PROCESSES"
echo "[entrypoint] uWSGI threads  : $UWSGI_THREADS"

exec uwsgi --ini /app/hedwig.ini "$@"
