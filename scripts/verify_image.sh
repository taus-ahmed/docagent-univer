#!/usr/bin/env sh
# Verify a built backend image (Part 2.1) — for Codex or the operator, after
#   docker build -f Dockerfile.backend -t docagent-backend .
# Usage: sh scripts/verify_image.sh [image] [port]
# Prints versions and checks, then runs the image briefly and asks /health and
# /ready. Uses a throwaway SQLite inside the container; never a real database.
set -u
IMG="${1:-docagent-backend}"
PORT="${2:-18000}"
fail=0
check() { if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1"; fail=1; fi; }
run() { docker run --rm --entrypoint "" "$IMG" sh -c "$1"; }

echo "== versions"
run 'cat /app/BUILD_TOOL_VERSIONS.txt; python --version; pip --version; pip freeze | head -100'
run 'id -u' | grep -qx 10001; check "runs as UID 10001" $?
run 'test -w /app/storage && touch /app/storage/.w && rm /app/storage/.w'; check "storage writable" $?
run 'tesseract --list-langs 2>&1 | grep -qx eng && tesseract --list-langs 2>&1 | grep -qx osd'; check "tesseract eng + osd" $?
run 'pdftoppm -v >/dev/null 2>&1'; check "pdftoppm present" $?
docker image inspect "$IMG" --format '{{json .Config.Entrypoint}}' | grep -q tini; check "tini is PID 1 (exec form)" $?

echo "== running"
CID=$(docker run -d -p "$PORT:8000" -e ENVIRONMENT=development \
      -e DATABASE_URL=sqlite:////tmp/verify.db -e SECRET_KEY=verify-only-not-a-secret-0123456789abcdef "$IMG")
i=0; until curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || [ $i -ge 60 ]; do i=$((i+1)); sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/health"; ok=$?; echo; check "/health answers" $ok
curl -sS "http://127.0.0.1:$PORT/ready"; echo
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/ready"); [ "$code" = "200" ]; check "/ready is 200" $?
docker exec "$CID" sh -c 'ls /proc | grep -E "^[0-9]+$" | while read p; do tr "\0" " " < /proc/$p/cmdline 2>/dev/null; echo; done' | grep -c "bin/uvicorn" | grep -qx 1; check "one uvicorn process (no shell between tini and it)" $?
docker exec "$CID" sh -c 'cat /proc/1/comm' | grep -q tini; check "PID 1 is tini" $?
[ "$(docker inspect -f '{{.State.Running}}' "$CID")" = "true" ]; check "still running before stop" $?
t0=$(date +%s); docker stop -t 30 "$CID" >/dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$CID"); t=$(( $(date +%s) - t0 ))
echo "stopped in ${t}s, exit code $code"
# 137 = SIGKILL after the timeout. 143 is normal: uvicorn re-raises SIGTERM
# after a clean shutdown, so the log line is what proves the lifespan drained.
[ "$code" != "137" ] && [ "$t" -lt 30 ]; check "stops on SIGTERM within 30 s" $?
docker logs "$CID" 2>&1 | grep -q "Application shutdown complete"; check "lifespan shutdown ran (jobs drained)" $?
[ $fail = 0 ] || docker logs "$CID" 2>&1 | tail -20
docker rm "$CID" >/dev/null 2>&1
[ $fail = 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit $fail
