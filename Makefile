.PHONY: sync inventory index serve test eval warm-cache demo web web-check web-e2e

web:
	npm run build --prefix web

web-check:
	npm run check --prefix web

web-e2e:
	npm run test:e2e --prefix web

sync:
	uv sync

inventory: sync
	uv run keel inventory

index: sync
	uv run keel index

serve: sync
	uv run keel serve

test: sync
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy keel
	uv run pylint --rcfile=pylintrc keel
	HF_HUB_OFFLINE=1 uv run pytest -m "not eval" -q --cov --cov-report=term-missing

eval: sync
	uv run keel eval --set eval/golden.yaml

warm-cache: sync
	uv run keel warm-cache

demo: sync web
	@test -f .env || cp .env.example .env
	@test -d index/current || uv run keel index
	uv run keel serve
