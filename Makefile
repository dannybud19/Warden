.PHONY: install dev web test lint types imports check schema fmt
install:
	cd backend && uv sync
	cd web && pnpm install
dev:
	cd backend && uv run uvicorn app.api.main:app --reload --port 8000
web:
	cd web && pnpm dev
fmt:
	cd backend && uv run ruff format . && uv run ruff check --fix .
lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
types:
	cd backend && uv run pyright
imports:
	cd backend && uv run lint-imports
test:
	cd backend && uv run pytest -q
check: lint types imports test
schema:
	cd backend && uv run python -m scripts.export_schema ../web/src/types/contracts.schema.json
	cd web && npx -y -p json-schema-to-typescript json2ts -i src/types/contracts.schema.json -o src/types/contracts.ts
