# chat-service image for Amazon Bedrock AgentCore Runtime (HTTP protocol, port 8080, ARM64).
# Build from the repository root:  docker build --platform linux/arm64 -f chat-service/Dockerfile .
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY mcp-server ./mcp-server
COPY backend/pyproject.toml backend/pyproject.toml
COPY infra/pyproject.toml infra/pyproject.toml
COPY integration-tests/pyproject.toml integration-tests/pyproject.toml
COPY chat-service ./chat-service

RUN uv sync --frozen --no-dev --package vv-chat

EXPOSE 8080
CMD ["uv", "run", "--no-sync", "--package", "vv-chat", "python", "-m", "vv_chat.app"]
