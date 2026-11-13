# MCP server image for Amazon Bedrock AgentCore Runtime (MCP protocol, ARM64).
# Build from the repository root:  docker build --platform linux/arm64 -f mcp-server/Dockerfile .
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# Workspace manifests first for layer caching, then sources.
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY chat-service/pyproject.toml chat-service/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY infra/pyproject.toml infra/pyproject.toml
COPY integration-tests/pyproject.toml integration-tests/pyproject.toml
COPY mcp-server ./mcp-server

RUN uv sync --frozen --no-dev --package vv-mcp

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "--package", "vv-mcp", "python", "-m", "vv_mcp"]
