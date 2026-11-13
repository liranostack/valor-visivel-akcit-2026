"""AgentCoreStack (ERD 'Infraestrutura e deploy'): two AgentCore Runtimes and one Memory.

- Runtime `valorvisivel_mcp` (MCP protocol): the tools; only it reads/writes DynamoDB and the KB.
- Runtime `valorvisivel_chat` (HTTP): the turn loop; calls the models, the guardrail and the MCP
  runtime. With `tool_gateway="inprocess"` (fallback, cdk -c toolGateway=inprocess) the chat
  runtime runs the tools in process and receives the data permissions instead.
- Memory: raw conversation history, 30-day expiry (LGPD retention).

Images are ARM64 container assets built from the monorepo (chat-service/Dockerfile,
mcp-server/Dockerfile), unless prebuilt image URIs are passed (tests).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import aws_cdk as cdk
import yaml
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from constructs import Construct

from vv_infra.stacks.data_stack import DataStack
from vv_infra.stacks.guardrail_stack import GuardrailRef, GuardrailStack

REPO_ROOT = Path(__file__).resolve().parents[4]
MODELS_YAML = REPO_ROOT / "chat-service" / "config" / "models.yaml"
METRICS_NAMESPACE = "ValorVisivel"
# Regions a US geo inference profile can route to (Bedrock 'Geo: US' from us-east-1).
US_PROFILE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


@dataclass(frozen=True)
class ModelIds:
    large: str
    small: str

    @classmethod
    def from_config(cls, path: Path = MODELS_YAML) -> "ModelIds":
        sizes = yaml.safe_load(path.read_text(encoding="utf-8"))["sizes"]
        return cls(large=sizes["large"], small=sizes["small"])


def _foundation_id(profile_id: str) -> str:
    for prefix in ("us.", "eu.", "apac.", "au.", "global."):
        if profile_id.startswith(prefix):
            return profile_id[len(prefix) :]
    return profile_id


class AgentCoreStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data: DataStack,
        guardrail: GuardrailStack | GuardrailRef,
        models: ModelIds | None = None,
        images: dict[str, str] | None = None,
        tool_gateway: str = "mcp",
        name_prefix: str = "valorvisivel",
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        if tool_gateway not in ("mcp", "inprocess"):
            raise ValueError("tool_gateway must be 'mcp' or 'inprocess'")
        models = models or ModelIds.from_config()
        inprocess = tool_gateway == "inprocess"
        # Memory/Runtime names are unique per account: each -c prefix=... deploy needs its own.
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]{0,39}", name_prefix):
            raise ValueError("name_prefix must be alphanumeric, start with a letter, max 40 chars")

        chat_image = self._image("chat", "chat-service/Dockerfile", images)
        mcp_image = self._image("mcp", "mcp-server/Dockerfile", images)

        memory = agentcore.CfnMemory(
            self,
            "History",
            name=f"{name_prefix}_history",
            description="Raw conversation history of each session (30-day retention).",
            event_expiry_duration=30,
        )

        mcp_role = self._runtime_role("McpRuntimeRole", mcp_image[1])
        chat_role = self._runtime_role("ChatRuntimeRole", chat_image[1])

        data_env = {
            "STATE_BACKEND": "dynamodb",
            "TABLE_NAME": data.table.table_name,
            "KB_SOURCE": "s3",
            "KB_BUCKET": data.kb_bucket.bucket_name,
            "KB_VERSION": data.kb_version,
        }
        mcp_runtime = agentcore.CfnRuntime(
            self,
            "McpRuntime",
            agent_runtime_name=f"{name_prefix}_mcp",
            description="Valor Visível MCP tools (state, facts, method content).",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=mcp_image[0]
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="MCP",
            role_arn=mcp_role.role_arn,
            environment_variables=data_env,
        )
        mcp_runtime.node.add_dependency(mcp_role)
        self._grant_data(mcp_role, data)

        chat_env = {
            "TOOL_GATEWAY": tool_gateway,
            "MCP_RUNTIME_ARN": mcp_runtime.attr_agent_runtime_arn,
            "GUARDRAIL_ID": guardrail.guardrail_id,
            "GUARDRAIL_VERSION": guardrail.guardrail_version,
            "MODEL_LARGE": models.large,
            "MODEL_SMALL": models.small,
            "AGENTCORE_MEMORY_ID": memory.attr_memory_id,
        } | (data_env if inprocess else {})
        chat_runtime = agentcore.CfnRuntime(
            self,
            "ChatRuntime",
            agent_runtime_name=f"{name_prefix}_chat",
            description="Valor Visível turn loop (guardrails, Conductor and agents).",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=chat_image[0]
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            role_arn=chat_role.role_arn,
            environment_variables=chat_env,
        )
        chat_runtime.node.add_dependency(chat_role)

        self._grant_models(chat_role, models)
        chat_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"],
                resources=[
                    self.format_arn(
                        service="bedrock",
                        resource="guardrail",
                        resource_name=guardrail.guardrail_id,
                    )
                ],
            )
        )
        chat_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    mcp_runtime.attr_agent_runtime_arn,
                    f"{mcp_runtime.attr_agent_runtime_arn}/*",
                ],
            )
        )
        chat_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:ListEvents",
                ],
                resources=[memory.attr_memory_arn],
            )
        )
        if inprocess:
            self._grant_data(chat_role, data)

        cdk.CfnOutput(self, "ChatRuntimeArn", value=chat_runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "McpRuntimeArn", value=mcp_runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "MemoryId", value=memory.attr_memory_id)
        cdk.CfnOutput(self, "ToolGateway", value=tool_gateway)
        self.chat_runtime_arn = chat_runtime.attr_agent_runtime_arn

    def _image(
        self, name: str, dockerfile: str, images: dict[str, str] | None
    ) -> tuple[str, ecr_assets.DockerImageAsset | None]:
        if images and name in images:
            return images[name], None
        asset = ecr_assets.DockerImageAsset(
            self,
            f"{name.capitalize()}Image",
            directory=str(REPO_ROOT),
            file=dockerfile,
            platform=ecr_assets.Platform.LINUX_ARM64,
        )
        return asset.image_uri, asset

    def _runtime_role(
        self, construct_id: str, asset: ecr_assets.DockerImageAsset | None
    ) -> iam.Role:
        """Execution role with what every AgentCore Runtime needs (image, logs, traces)."""
        role = iam.Role(
            self,
            construct_id,
            assumed_by=cast(
                iam.IPrincipal,
                iam.ServicePrincipal(
                    "bedrock-agentcore.amazonaws.com",
                    conditions={
                        "StringEquals": {"aws:SourceAccount": self.account},
                        "ArnLike": {
                            "aws:SourceArn": self.format_arn(
                                service="bedrock-agentcore", resource="*"
                            )
                        },
                    },
                ),
            ),
        )
        if asset is not None:
            asset.repository.grant_pull(role)
        else:
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                    resources=[self.format_arn(service="ecr", resource="repository/*")],
                )
            )
        # ECR auth tokens and X-Ray do not support resource-level permissions.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # scoped by namespace; PutMetricData has no resource ARNs
                conditions={"StringEquals": {"cloudwatch:namespace": METRICS_NAMESPACE}},
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    self.format_arn(
                        service="logs",
                        resource="log-group",
                        resource_name="/aws/bedrock-agentcore/runtimes/*",
                        arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                    )
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                resources=[
                    self.format_arn(
                        service="bedrock-agentcore",
                        resource="workload-identity-directory",
                        resource_name="default/*",
                    ),
                    self.format_arn(
                        service="bedrock-agentcore",
                        resource="workload-identity-directory",
                        resource_name="default",
                    ),
                ],
            )
        )
        return role

    def _grant_models(self, role: iam.Role, models: ModelIds) -> None:
        resources: list[str] = []
        for profile in (models.large, models.small):
            resources.append(
                self.format_arn(
                    service="bedrock", resource="inference-profile", resource_name=profile
                )
            )
            foundation = _foundation_id(profile)
            resources += [
                f"arn:{self.partition}:bedrock:{region}::foundation-model/{foundation}"
                for region in US_PROFILE_REGIONS
            ]
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=resources,
            )
        )

    def _grant_data(self, role: iam.Role, data: DataStack) -> None:
        data.table.grant_read_write_data(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[data.kb_bucket.arn_for_objects("kb/*")],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[data.kb_bucket.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["kb/*"]}},
            )
        )
