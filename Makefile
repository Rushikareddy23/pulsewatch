.PHONY: up down test test-backend test-web bench seed
up:           ; docker compose up --build
down:         ; docker compose down
test: test-backend test-web
test-backend: ; cd backend && python -m pytest -q
test-web:     ; cd web && npm test && npm run build
seed:         ; cd backend && python scripts/seed_demo.py
bench:        ; cd backend && DATABASE_URL=$${BENCH_DATABASE_URL:?set BENCH_DATABASE_URL to a dedicated *bench* database} python scripts/bench_worker.py --monitors 2000 --workers 4
