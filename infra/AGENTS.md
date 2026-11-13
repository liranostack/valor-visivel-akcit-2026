# AGENTS.md — infra

CDK app with stacks: DataStack, GuardrailStack, AgentCoreStack, ApiStack, FrontendStack, ObservabilityStack
  (see ERD "Infraestrutura e deploy"). Region us-east-1 by default.

  **Does not:** get deployed by agents. Humans deploy at checkpoints H.D1–H.D3 (skill `deploy-demo`).

  - Pin `aws-cdk-lib` and `aws-cdk.aws-bedrock-agentcore-alpha` to compatible versions.
  - Every stack has `aws_cdk.assertions.Template` tests; `cdk synth` must work without credentials.
  - Least-privilege IAM; any `Resource: "*"` needs a justification comment.
  - Tests: `uv run pytest infra -q`

Read the root `AGENTS.md` and `.agents/constitution.md` first.
