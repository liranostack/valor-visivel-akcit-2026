"""DataStack: session state (DynamoDB single table) and the method (S3 knowledge base).

ERD 'Modelo de dados' and 'Infraestrutura e deploy': PK/SK, TTL on `ttl` (30-day retention),
on-demand, no secondary indexes; versioned private bucket, content uploaded to kb/<version>/.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[4]
KB_DIR = REPO_ROOT / "knowledge-base"


def read_kb_version(kb_dir: Path = KB_DIR) -> str:
    version_file = kb_dir / "kb_version.txt"
    return version_file.read_text().strip() if version_file.exists() else "v1"


class DataStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, kb_dir: Path = KB_DIR, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        # Demo environment: data is disposable (30-day retention anyway).
        self.table = dynamodb.Table(
            self,
            "SessionTable",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.kb_bucket = s3.Bucket(
            self,
            "KnowledgeBaseBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.kb_version = read_kb_version(kb_dir)
        self.kb_prefix = f"kb/{self.kb_version}/"
        s3deploy.BucketDeployment(
            self,
            "KnowledgeBaseUpload",
            sources=[s3deploy.Source.asset(str(kb_dir), exclude=["tests", "**/__pycache__"])],
            destination_bucket=self.kb_bucket,
            destination_key_prefix=self.kb_prefix,
            prune=False,  # keep previous versions' prefixes for sessions still running
        )

        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "KbBucketName", value=self.kb_bucket.bucket_name)
        cdk.CfnOutput(self, "KbVersion", value=self.kb_version)
