"""DataStack (ERD 'Infraestrutura e deploy'): single table with TTL + versioned KB bucket."""

from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from vv_infra.stacks.data_stack import DataStack, read_kb_version

ENV = cdk.Environment(account="000000000000", region="us-east-1")


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    return Template.from_stack(DataStack(app, "Data", env=ENV))


def test_single_table_pk_sk_ttl_on_demand(template: Template) -> None:
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
            "SSESpecification": {"SSEEnabled": True},
        },
    )


def test_no_secondary_indexes(template: Template) -> None:
    template.has_resource_properties(
        "AWS::DynamoDB::Table", {"GlobalSecondaryIndexes": Match.absent()}
    )


def test_kb_bucket_versioned_private_encrypted(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "VersioningConfiguration": {"Status": "Enabled"},
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.object_like({}),
        },
    )


def test_bucket_enforces_ssl(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_kb_uploaded_under_versioned_prefix(template: Template) -> None:
    version = read_kb_version()
    template.has_resource_properties(
        "Custom::CDKBucketDeployment", {"DestinationBucketKeyPrefix": f"kb/{version}/"}
    )


def test_outputs_for_other_stacks(template: Template) -> None:
    outputs = template.find_outputs("*")
    assert {"TableName", "KbBucketName", "KbVersion"} <= set(outputs)


def test_read_kb_version(tmp_path: Path) -> None:
    (tmp_path / "kb_version.txt").write_text("v3\n")
    assert read_kb_version(tmp_path) == "v3"
    assert read_kb_version(tmp_path / "missing") == "v1"


def test_app_synthesizes() -> None:
    from vv_infra.app import build_app

    # No Docker bundling in unit tests (CI's `cdk synth` job bundles for real).
    assembly = build_app(cdk.App(context={"aws:cdk:bundling-stacks": []})).synth()
    names = [s.stack_name for s in assembly.stacks]
    assert any(n.endswith("Data") for n in names) and any(n.endswith("Api") for n in names)
