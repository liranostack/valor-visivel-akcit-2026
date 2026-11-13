# AGENTS.md

Monorepo (uv workspace + Next.js). Each package has its own AGENTS.md.

- `packages/vv-contracts`: Pydantic contracts shared by every package (WebSocket, agents, tools).
- `chat-service`: the turn loop and the agents; prompts in `chat-service/prompts`.
- `mcp-server`: MCP tools over the state (memory or DynamoDB) and the method (`knowledge-base`).
- `knowledge-base`: example method content (layer, guide, map template).
- `backend`: WebSocket Lambdas; `infra`: CDK; `frontend`: Next.js; `integration-tests`: simulation.

Code, identifiers and prompts in English; text shown to the user in pt-BR. `make check` must pass.
