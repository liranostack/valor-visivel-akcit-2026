"""MCP tools. Convention: one argument `req: <XIn>`, returns `<XOut>` (vv_contracts.tools)."""

from collections.abc import Callable

from mcp.server.fastmcp.exceptions import ToolError


def guarded[T](fn: Callable[[], T]) -> T:
    """Run a repository call and turn lookup/validation failures into MCP tool errors."""
    try:
        return fn()
    except KeyError as exc:
        raise ToolError(str(exc).strip("'\"")) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
