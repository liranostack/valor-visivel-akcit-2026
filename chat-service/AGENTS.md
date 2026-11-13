# AGENTS.md — chat-service

Turn loop for one message: guardrail in → Interpreter → Conductor → Investigator → Moderator
  (or Synthesizer) → output checks → guardrail out → persist → stream. Runs on an AgentCore Runtime
  (HTTP, port 8080, `/invocations`, `/ping`, ARM64).

  **Does not:** read or write DynamoDB/S3 directly (always via `ToolGateway`); put method content in prompts.

  - `src/vv_chat/conductor/` is pure Python: no model, no I/O, 100% line coverage.
  - `src/vv_chat/agents/` one module per agent; output = the Pydantic model from `vv_contracts.agents`;
    invalid model output falls back to heuristics.
  - `prompts/` English system prompts that instruct pt-BR output; `_base.md` is included by all. Use the
    `change-agent-prompt` skill.
  - `ToolGateway`: `mcp` (remote MCP runtime) or `inprocess` (imports `vv_mcp`), chosen by env `TOOL_GATEWAY`.
  - Model sizes in `config/models.yaml` (Interpreter, Investigator, Moderator, Synthesizer: large; PublicResearcher: small).
  - Tests use stub models and `FakeToolGateway`; no network. `uv run pytest chat-service -q`

Read the root `AGENTS.md` and `.agents/constitution.md` first.
