"""ApiStack (ERD 'Infraestrutura e deploy'): API Gateway WebSocket in front of the chat-service.

Routes: $connect, $disconnect, sendMessage. sendMessage validates and hands off to the worker
(async), because API Gateway waits at most 29 s per route and a turn can take longer; the worker
calls the chat-service runtime and relays its events with post_to_connection.
"""

from pathlib import Path
from typing import cast

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[4]
STAGE = "prod"


def backend_code() -> lambda_.Code:
    """vv-backend + vv-contracts (and their deps) bundled with pip in the Lambda build image."""
    return lambda_.Code.from_asset(
        str(REPO_ROOT),
        exclude=[
            "**/node_modules",
            "**/.venv",
            "**/cdk.out",
            "reference",
            "frontend",
            "docs",
            ".git",
        ],
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            command=[
                "bash",
                "-c",
                "pip install --no-cache-dir ./packages/vv-contracts ./backend -t /asset-output",
            ],
        ),
    )


def _fn(f: lambda_.Function) -> lambda_.IFunction:
    return cast(lambda_.IFunction, f)  # jsii protocol, for the type checker


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        chat_runtime_arn: str,
        code: lambda_.Code | None = None,
        access_code_sha256: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        code = code or backend_code()

        def fn(name: str, handler: str, timeout: int = 10) -> lambda_.Function:
            return lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.X86_64,
                handler=handler,
                code=code,
                timeout=cdk.Duration.seconds(timeout),
                memory_size=256,
            )

        connect = fn("Connect", "vv_backend.connection.on_connect")
        disconnect = fn("Disconnect", "vv_backend.connection.on_disconnect")
        message = fn("Message", "vv_backend.message.handle")
        worker = fn("Worker", "vv_backend.worker.handle", timeout=120)

        api = apigw.WebSocketApi(
            self,
            "WebSocket",
            api_name="valor-visivel",
            connect_route_options=apigw.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "ConnectIntegration", _fn(connect)
                )
            ),
            disconnect_route_options=apigw.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "DisconnectIntegration", _fn(disconnect)
                )
            ),
        )
        api.add_route(
            "sendMessage",
            integration=integrations.WebSocketLambdaIntegration("MessageIntegration", _fn(message)),
        )
        # Cost protection (A.04.10): a few messages per second is plenty for a conversation.
        stage = apigw.WebSocketStage(
            self,
            "Stage",
            web_socket_api=api,
            stage_name=STAGE,
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )
        if access_code_sha256:
            connect.add_environment("ACCESS_CODE_SHA256", access_code_sha256)

        message.add_environment("WORKER_FUNCTION_NAME", worker.function_name)
        worker.grant_invoke(message)
        worker.add_environment("CHAT_RUNTIME_ARN", chat_runtime_arn)
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[chat_runtime_arn, f"{chat_runtime_arn}/*"],
            )
        )
        manage = self.format_arn(
            service="execute-api",
            resource=api.api_id,
            resource_name=f"{STAGE}/POST/@connections/*",
        )
        for f in (message, worker):
            f.add_to_role_policy(
                iam.PolicyStatement(actions=["execute-api:ManageConnections"], resources=[manage])
            )

        cdk.CfnOutput(self, "WebSocketUrl", value=stage.url)
        self.ws_url = stage.url
