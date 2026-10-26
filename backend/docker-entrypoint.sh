#!/bin/sh
# PID 1 is tini (Dockerfile.backend). This only expands ${PORT} and replaces
# itself with uvicorn, so SIGTERM from the platform reaches uvicorn directly.
set -e
# --no-access-log: uvicorn's access line includes the query string, which can
# carry a token; the app writes its own (path only, request id).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"      --timeout-graceful-shutdown "${GRACEFUL_SHUTDOWN_SECONDS:-60}" --no-access-log
