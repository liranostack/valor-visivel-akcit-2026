# AGENTS.md — knowledge-base

The Valor Visível method as data, owned by the project lead. Content in **pt-BR**, keys in English.
Uploaded to S3 under `kb/v<n>/`; the version in use is `kb_version.txt` and is recorded in every session and trace.

- `layers/<layer_id>.yaml` — validated by `vv_contracts.kb.LayerSpec` (schema test in `tests/`).
- `guide/guide.md` — headings `## open`, `## hidden`, `## blind`, `## unknown`.
- `templates/*.md` — four layer syntheses, `pre_core`, `essential_core`, `action_plan_7d`; every claim carries `[fact:<id>]`; mandatory "Lacunas e hipóteses" section.
- `motivation/sourced_facts.yaml` — only data with an auditable source.

**Does not:** hold prompts (they live in `chat-service/prompts/`, ADR-004).
Use the `change-kb-content` skill. The lead reviews every KB PR.
