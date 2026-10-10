#!/usr/bin/env bash
# Check the conformance runner against the fake add-on, valid then invalid.
set -u
cd "$(dirname "$0")/.."

PORT=8765
URL="http://localhost:$PORT"
PID=""

stop() {
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
    PID=""
  fi
}
trap stop EXIT

start() {
  python3 conformance/fake_addon.py --port "$PORT" "$@" &
  PID=$!
  for _ in $(seq 1 50); do
    curl -sf "$URL/manifest.json" >/dev/null && return 0
    sleep 0.1
  done
  echo "fake add-on did not start" >&2
  exit 1
}

start
uv run conformance/run.py "$URL" || { echo "selftest failed: valid add-on did not pass" >&2; exit 1; }
stop

start --invalid
out=$(uv run conformance/run.py "$URL")
code=$?
echo "$out"
stop
[ "$code" -eq 1 ] || { echo "selftest failed: invalid add-on exited $code, expected 1" >&2; exit 1; }
echo "$out" | grep -q '^FAIL /stream/track/' || { echo "selftest failed: no FAIL line for the stream route" >&2; exit 1; }

echo "selftest ok"
