# AGENTS.md — integration-tests

Simulated journeys: a model plays a client (persona in `scenarios/<slug>.yaml`), talks to the real
turn loop in process (in-memory MCP tools and state), and two LLM judges evaluate the run.

- **Personas** (`scenarios/*.yaml`, pt-BR): who she is, how she writes, onboarding, baseline,
  scripted answers (offline mode) and `truths` (`hidden`, `external`, `routine`, `contradiction`):
  the ground truth the judge checks the journey against. `pastelaria` comes from a real session.
- **Simulator** (`vv_it/simulator.py` + `simulator.md`): small model by default; tells hidden facts
  only to concrete questions; clicks A/B like the UI (sends the option text).
- **Behavior** (`behavior:` in each persona): `confidence` (low hedges and undervalues, high
  overclaims), `verbosity`, and per-answer chances of `confusion` (misreads, "como assim?"),
  `digression` and `irritation` (only when a question feels repeated). Drawn with a seed per run
  (`--runs 2` = seeds 1 and 2), recorded per turn as `events`, shown to the judge, scored as
  `difficulty_handling` (0 = no difficulty in the run, not applicable).
- **Journey** (`vv_it/journey.py`): layer 1 (demo scope) until the synthesis, silence or max turns;
  records every agent step (`on_step`).
- **Checks**: deterministic (`vv_it/fidelity.py`) and judges (`vv_it/judges/`): the conversation
  judge scores the ERD metrics + `insight` and which truths surfaced; the reasoning auditor reads
  the agents' steps and the files that drive them and proposes file-level improvements.
  Judge prompts in English, evaluating pt-BR; they read the method guide's pitfalls (single source
  with the Moderator). Limits in `config/thresholds.yaml`.
- **Report**: `docs/e2e-runs/sim-<timestamp>/report.md` + `report.json` (gitignored).

```bash
make simulate ARGS="--persona pastelaria"            # real mode (Bedrock), exit 1 below a limit
make simulate ARGS="--all --runs 2 --concurrency 3"   # every persona, twice
make simulate ARGS="--offline --all"                  # no network: scripted answers, heuristic agents
```

Offline mode never fails (heuristic agents rarely close a layer); it proves the wiring in CI.
An improvement proposed by the auditor is a suggestion: prompts follow `change-agent-prompt`,
KB content follows `change-kb-content` and the lead reviews it.

Read the root `AGENTS.md` and `.agents/constitution.md` first.
