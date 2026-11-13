"""Entry point: `python -m vv_mcp` serves MCP over streamable HTTP on 0.0.0.0:8000/mcp.

STATE_BACKEND=memory (default) keeps state in process; STATE_BACKEND=dynamodb uses TABLE_NAME.
KB_SOURCE=local (default, ./knowledge-base or KB_PATH) or s3 (KB_BUCKET, KB_VERSION).
"""

import os

from vv_contracts.ports import StateRepository

from vv_mcp.kb import load_knowledge_base
from vv_mcp.repo_dynamo import DynamoStateRepository
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import build_server


def main() -> None:  # pragma: no cover - process entry point
    backend = os.environ.get("STATE_BACKEND", "memory")
    repo: StateRepository
    if backend == "dynamodb":
        repo = DynamoStateRepository(os.environ["TABLE_NAME"])
    elif backend == "memory":
        repo = InMemoryStateRepository()
    else:
        raise SystemExit(f"unknown STATE_BACKEND={backend!r} (use memory or dynamodb)")
    build_server(repo, load_knowledge_base()).run(transport="streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
