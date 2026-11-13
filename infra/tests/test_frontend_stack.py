"""FrontendStack: static export on a private S3 bucket behind CloudFront, with the WebSocket URL
written as config.json at deploy time (A.03.15)."""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from vv_infra.stacks.frontend_stack import FrontendStack

ENV = cdk.Environment(account="000000000000", region="us-east-1")
WS = "wss://abc.execute-api.us-east-1.amazonaws.com/prod"


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Template:
    site = tmp_path_factory.mktemp("out")
    (site / "index.html").write_text("<html></html>", encoding="utf-8")
    # A token, as in the app (ApiStack output), so the URL is resolved at deploy time.
    ws_url = cdk.Fn.import_value("ApiWebSocketUrl")
    stack = FrontendStack(cdk.App(), "Frontend", env=ENV, ws_url=ws_url, site_dir=Path(site))
    return Template.from_stack(stack)


def test_bucket_is_private(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_cloudfront_serves_index_over_https_through_oac(template: Template) -> None:
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultRootObject": "index.html",
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    ),
                }
            )
        },
    )
    template.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_site_and_config_are_deployed(template: Template) -> None:
    deployments = list(template.find_resources("Custom::CDKBucketDeployment").values())
    assert len(deployments) == 1
    props = deployments[0]["Properties"]
    assert len(props["SourceObjectKeys"]) == 2  # the site and config.json
    assert "ApiWebSocketUrl" in json.dumps(props["SourceMarkers"])


def test_site_url_output(template: Template) -> None:
    assert template.find_outputs("SiteUrl")


def test_missing_build_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="npm run build"):
        FrontendStack(cdk.App(), "F", env=ENV, ws_url=WS, site_dir=tmp_path / "nope")


class TestCustomDomain:
    """Optional custom domain in a Route 53 zone of the same account (A.03.17)."""

    @pytest.fixture(scope="class")
    def domain_template(self, tmp_path_factory: pytest.TempPathFactory) -> Template:
        from vv_infra.stacks.frontend_stack import SiteDomain

        site = tmp_path_factory.mktemp("out")
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        stack = FrontendStack(
            cdk.App(),
            "FrontendDomain",
            env=ENV,
            ws_url=WS,
            site_dir=Path(site),
            domain=SiteDomain(name="vv.example.com.br", zone_id="Z123", zone_name="example.com.br"),
        )
        return Template.from_stack(stack)

    def test_certificate_validated_by_dns(self, domain_template: Template) -> None:
        domain_template.has_resource_properties(
            "AWS::CertificateManager::Certificate",
            {"DomainName": "vv.example.com.br", "ValidationMethod": "DNS"},
        )

    def test_distribution_answers_for_the_domain(self, domain_template: Template) -> None:
        domain_template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {"DistributionConfig": Match.object_like({"Aliases": ["vv.example.com.br"]})},
        )

    def test_alias_records_point_to_cloudfront(self, domain_template: Template) -> None:
        records = domain_template.find_resources("AWS::Route53::RecordSet")
        types = sorted(r["Properties"]["Type"] for r in records.values())
        assert types == ["A", "AAAA"]
        assert all(r["Properties"]["HostedZoneId"] == "Z123" for r in records.values())

    def test_site_url_uses_the_domain(self, domain_template: Template) -> None:
        assert "https://vv.example.com.br" in json.dumps(domain_template.find_outputs("SiteUrl"))

    def test_domain_must_be_inside_the_zone(self, tmp_path: Path) -> None:
        from vv_infra.stacks.frontend_stack import SiteDomain

        with pytest.raises(ValueError, match="zone"):
            SiteDomain(name="vv.other.com", zone_id="Z1", zone_name="example.com.br")


def test_no_domain_means_no_certificate_or_records(template: Template) -> None:
    template.resource_count_is("AWS::CertificateManager::Certificate", 0)
    template.resource_count_is("AWS::Route53::RecordSet", 0)
