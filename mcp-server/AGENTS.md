# AGENTS.md — mcp-server

FastMCP server (streamable HTTP, stateless, `0.0.0.0:8000/mcp`, ARM64) exposing the tools in the ERD
  table: state, facts, gaps, method content (KB), deterministic guards (`check_output`) and `read_public_site`.
  The only component that touches DynamoDB, S3 and the internet.

  **Does not:** call models.

  - Repositories implement `vv_contracts.ports.StateRepository` (`InMemoryStateRepository` for tests, `DynamoStateRepository` with moto tests).
  - Tool signature: one argument `req: <XIn>` returning `<XOut>` (models in `vv_contracts.tools`); the chat-service `McpToolGateway` calls `{"req": ...}` and parses structured content.
- Every tool: contract test via the MCP client in-process + span `tool.<name>`. Use the `add-mcp-tool` skill.
  - `read_public_site`: HTTPS only, no private IPs, 10 s timeout, ~2k-token budget, cache per session, never Instagram.
  - Tests: `uv run pytest mcp-server -q`

Read the root `AGENTS.md` and `.agents/constitution.md` first.
