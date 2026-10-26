#!/usr/bin/env sh
# Run the browser specs: E2E_PW = a folder with @playwright/test installed
# (outside the repo), E2E_CREDS = the creds.json scripts/e2e/stack.py wrote.
set -e
cd "$(dirname "$0")"
NODE_PATH="$E2E_PW/node_modules" "$E2E_PW/node_modules/.bin/playwright" test --config playwright.config.cjs "$@"
