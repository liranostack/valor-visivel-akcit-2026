.PHONY: setup lint format typecheck test check test-integration card run-mcp run-chat try-turn simulate synth

setup:
	uv sync --all-packages

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run pyright

test:
	uv run pytest

check: lint typecheck test

test-integration:
	uv run pytest -m integration -o addopts="-q --import-mode=importlib"

run-mcp:
	uv run --package vv-mcp python -m vv_mcp

run-chat:
	TOOL_GATEWAY=inprocess uv run --package vv-chat python -m vv_chat.app

try-turn:
	uv run python scripts/try_turn.py $(ARGS)

demo-local:  ## agents + WebSocket on ws://localhost:8765 (AWS credentials with Bedrock)
	uv run python scripts/local_ws.py

simulate:
	uv run python -m vv_it.run_suite $(ARGS)

synth:
	cd infra && CDK_DEFAULT_ACCOUNT=000000000000 npx --yes aws-cdk@2 synth --quiet
