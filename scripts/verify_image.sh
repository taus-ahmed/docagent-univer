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
curl -fsS "http://127.0.0.1:$PORT/health"; echo; check "/health answers" $?
curl -sS "http://127.0.0.1:$PORT/ready"; echo
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/ready"); [ "$code" = "200" ]; check "/ready is 200" $?
n=$(docker top "$CID" -eo comm | grep -c uvicorn || true); echo "uvicorn processes: $n"
docker exec "$CID" sh -c 'cat /proc/1/comm' | grep -q tini; check "PID 1 is tini" $?
docker stop -t 30 "$CID" >/dev/null; check "stops on SIGTERM within 30 s" $?
docker rm "$CID" >/dev/null 2>&1
[ $fail = 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit $fail
