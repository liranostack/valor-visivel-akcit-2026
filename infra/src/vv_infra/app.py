"""CDK app: one demo environment (ERD 'Infraestrutura e deploy'). Deployed by humans (H.D1–H.D3)."""

import hashlib
import os

import aws_cdk as cdk

from vv_infra.stacks.agentcore_stack import AgentCoreStack
from vv_infra.stacks.api_stack import ApiStack
from vv_infra.stacks.data_stack import DataStack
from vv_infra.stacks.frontend_stack import SITE_DIR, FrontendStack, SiteDomain
from vv_infra.stacks.guardrail_stack import GuardrailRef, GuardrailStack

DEFAULT_PREFIX = "ValorVisivel"


def get_prefix(app: cdk.App) -> str:
    """Override stack prefix: cdk deploy -c prefix=ValorVisivelV2"""
    return str(app.node.try_get_context("prefix") or DEFAULT_PREFIX)


def site_domain(app: cdk.App) -> SiteDomain | None:
    """Optional custom domain: cdk deploy -c siteDomain=vv.example.com.br
    -c hostedZoneId=Z... -c hostedZoneName=example.com.br"""
    name = app.node.try_get_context("siteDomain")
    if not name:
        return None
    zone_id = app.node.try_get_context("hostedZoneId")
    zone_name = app.node.try_get_context("hostedZoneName")
    if not zone_id or not zone_name:
        raise ValueError("siteDomain needs hostedZoneId and hostedZoneName in the CDK context")
    return SiteDomain(name=str(name), zone_id=str(zone_id), zone_name=str(zone_name))


def access_code_sha256(app: cdk.App) -> str | None:
    """Optional access code for the WebSocket: cdk deploy -c accessCode=<code>. Only its hash
    reaches the template (same normalisation as vv_backend.connection.code_hash)."""
    code = app.node.try_get_context("accessCode")
    if not code:
        return None
    return hashlib.sha256(str(code).strip().lower().encode()).hexdigest()


def existing_guardrail(app: cdk.App) -> GuardrailRef | None:
    """Reuse a deployed guardrail instead of creating one (its name is unique per account):
    cdk deploy -c guardrailId=abc123example -c guardrailVersion=1"""
    guardrail_id = app.node.try_get_context("guardrailId")
    if not guardrail_id:
        return None
    version = app.node.try_get_context("guardrailVersion")
    if not version:
        raise ValueError("guardrailId needs guardrailVersion in the CDK context")
    return GuardrailRef(guardrail_id=str(guardrail_id), guardrail_version=str(version))


def build_app(app: cdk.App) -> cdk.App:
    prefix = get_prefix(app)
    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    )
    data = DataStack(app, f"{prefix}-Data", env=env)
    guardrail = existing_guardrail(app) or GuardrailStack(app, f"{prefix}-Guardrail", env=env)
    # cdk deploy -c toolGateway=inprocess: fallback without the MCP hop (fewer moving parts).
    agentcore = AgentCoreStack(
        app,
        f"{prefix}-AgentCore",
        env=env,
        name_prefix=prefix.lower(),
        data=data,
        guardrail=guardrail,
        tool_gateway=str(app.node.try_get_context("toolGateway") or "mcp"),
    )
    api = ApiStack(
        app,
        f"{prefix}-Api",
        env=env,
        chat_runtime_arn=agentcore.chat_runtime_arn,
        access_code_sha256=access_code_sha256(app),
    )
    # The site is added only when the static export exists (cd frontend && npm run build), so the
    # other stacks still synth without Node.
    if (SITE_DIR / "index.html").exists():
        FrontendStack(
            app, f"{prefix}-Frontend", env=env, ws_url=api.ws_url, domain=site_domain(app)
        )
    cdk.Tags.of(app).add("project", "valor-visivel")
    return app


def main() -> None:  # pragma: no cover - CDK entry point
    build_app(cdk.App()).synth()


if __name__ == "__main__":  # pragma: no cover
    main()
