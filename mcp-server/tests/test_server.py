from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import Deps, build_server


async def test_ping_through_mcp_client() -> None:
    server = build_server(InMemoryStateRepository())
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert "ping" in [t.name for t in tools.tools]
        result = await client.call_tool("ping", {})
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "pong"


def test_server_settings_match_agentcore_contract() -> None:
    server = build_server(InMemoryStateRepository())
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8000
    assert server.settings.streamable_http_path == "/mcp"
    assert server.settings.stateless_http is True


def test_dependencies_are_exposed_to_tools() -> None:
    repo = InMemoryStateRepository()
    server = build_server(repo)
    deps = server.deps
    assert isinstance(deps, Deps)
    assert deps.repo is repo
    assert deps.kb is None
