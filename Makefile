.PHONY: setup pg world test lint dev e2e

setup:
	pip install -e "api[dev]"
	cd web && npm ci
	scripts/pg.sh start

pg:
	scripts/pg.sh start

world:
	cd api && python -m orderdesk.world.build

test:
	cd api && pytest -q
	cd web && npm test

lint:
	cd api && ruff check . && ruff format --check .
	cd web && npm run typecheck && npm run lint

dev:
	cd api && uvicorn orderdesk.web.app:app --reload --port 8000 & cd web && npm run dev

e2e:
	cd web && npm run e2e
