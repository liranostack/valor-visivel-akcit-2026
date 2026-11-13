# AGENTS.md — backend

Lambdas for the API Gateway WebSocket: `$connect`, `$disconnect`, `sendMessage` (validates and hands off
  asynchronously) and `worker` (calls `invoke_agent_runtime` on the chat-service and relays events with
  `post_to_connection`). Protocol: `vv_contracts.ws`.

  **Does not:** decide anything about the method.

  - Errors become `ServerEvent(type="error")` without stack traces.
  - Tests with botocore Stubber. `uv run pytest backend -q`

Read the root `AGENTS.md` and `.agents/constitution.md` first.
