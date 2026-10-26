# Browser tests (dev only)

Playwright is NOT a dependency of the app: install it outside the repo and
point the specs at it.

```sh
# once: a scratch folder with the runner (1.60 matches chromium-1223)
mkdir /tmp/pw && cd /tmp/pw && npm init -y && npm i -D @playwright/test@1.60
# (no browser on the machine? npx playwright install chromium)

# a throwaway stack: stub model, new SQLite + storage in the workdir
python scripts/e2e/stack.py --workdir /tmp/e2e-run      # prints STACK READY

# the specs (frontend/e2e/*.spec.cjs)
E2E_PW=/tmp/pw E2E_CREDS=/tmp/e2e-run/creds.json E2E_OUT=/tmp/e2e-run sh frontend/e2e/run.sh
```

The stack never touches another database: it creates `<workdir>/e2e.db`
(refusing a workdir that already has one) and uses `PRIMARY_LLM=stub`
(docs/OFFLINE-DEMO.md). Two firms (`e2e_a`, `e2e_b`) and a one-time-password
user are seeded; their passwords are in `creds.json` (test data only).
