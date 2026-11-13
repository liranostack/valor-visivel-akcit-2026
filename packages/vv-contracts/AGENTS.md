# AGENTS.md — packages/vv-contracts

Single source of truth for every type shared across packages: agent outputs, MCP tool I/O,
  session state and DynamoDB keys, KB schema, WebSocket protocol, model pricing, and the Protocols
  `StateRepository`, `KnowledgeBase`, `ToolGateway`.

  **Does not:** perform I/O, call models, or hold business logic beyond pure key/price helpers.

  - Any change here is its own PR titled `[contracts] ...`, because every other card depends on it.
  - Every model in `agents.py` and `tools.py` has a docstring and every field a `description` (enforced by
  `tests/test_descriptions.py`). Agent-output descriptions are part of the prompt: Strands sends the JSON
  Schema to the model. Write them in English, short, say when content must be pt-BR, and explain the
  meaning of every `Literal` value.
- pyright runs in **strict** mode for this package. Target ≥ 90% coverage.
  - Spec: ERD sections "Contratos dos agentes", "Ferramentas MCP", "Modelo de dados", "Schema da knowledge base".
  - Tests: `uv run pytest packages/vv-contracts -q`

Read the root `AGENTS.md` and `.agents/constitution.md` first.
