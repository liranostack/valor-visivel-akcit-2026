"""MCP server for the Valor Visível tools.

AgentCore Runtime (MCP protocol) contract: streamable HTTP, stateless, 0.0.0.0:8000, path /mcp.
Tools are registered by the tool cards (A.03.01–A.03.04) on top of `build_server`.
"""

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from vv_contracts.ports import KnowledgeBase, StateRepository

from vv_mcp.tools import facts as facts_tools
from vv_mcp.tools import method as method_tools
from vv_mcp.tools import state as state_tools

SERVER_NAME = "valor-visivel"
INSTRUCTIONS = (
    "Tools for the Valor Visível method: session state, facts, gaps, method content, "
    "deterministic output checks and public-site reading. Tools never call models."
)


@dataclass(frozen=True)
class Deps:
    repo: StateRepository
    kb: KnowledgeBase | None = None


class ValorVisivelServer(FastMCP):
    """FastMCP with the injected dependencies available to every tool module."""

    def __init__(self, deps: Deps) -> None:
        super().__init__(
            name=SERVER_NAME,
            instructions=INSTRUCTIONS,
            host="0.0.0.0",
            port=8000,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
        self.deps = deps


def build_server(repo: StateRepository, kb: KnowledgeBase | None = None) -> ValorVisivelServer:
    server = ValorVisivelServer(Deps(repo=repo, kb=kb))

    @server.tool(description="Health check. Returns 'pong'.")
    def ping() -> str:  # pyright: ignore[reportUnusedFunction]
        return "pong"

    state_tools.register(server, repo)
    facts_tools.register(server, repo)
    method_tools.register(server, kb)
    return server
