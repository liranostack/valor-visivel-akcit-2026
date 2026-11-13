"""FrontendStack (A.03.15): the Next.js static export (frontend/out) on a private S3 bucket behind
CloudFront (Origin Access Control, HTTPS only).

The WebSocket URL is not baked into the build: it is written as /config.json at deploy time from
the ApiStack output, and the frontend reads it on start (frontend/src/lib/config.ts). Build first:
`cd frontend && npm ci && npm run build`.

Optional custom domain (A.03.17): a Route 53 hosted zone in the same account, an ACM certificate
validated by DNS (us-east-1, as CloudFront requires) and A/AAAA alias records.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[4]
SITE_DIR = REPO_ROOT / "frontend" / "out"


@dataclass(frozen=True)
class SiteDomain:
    name: str  # e.g. vv.example.com.br
    zone_id: str  # Route 53 hosted zone id
    zone_name: str  # e.g. example.com.br

    def __post_init__(self) -> None:
        if self.name != self.zone_name and not self.name.endswith(f".{self.zone_name}"):
            raise ValueError(f"{self.name} is not inside the zone {self.zone_name}")


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        ws_url: str,
        site_dir: Path = SITE_DIR,
        domain: SiteDomain | None = None,
        **kwargs: object,
    ) -> None:
        if not (site_dir / "index.html").exists():
            raise FileNotFoundError(
                f"{site_dir}/index.html not found: run `cd frontend && npm ci && npm run build`"
            )
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        zone: route53.IHostedZone | None = None
        certificate: acm.ICertificate | None = None
        if domain is not None:
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self, "Zone", hosted_zone_id=domain.zone_id, zone_name=domain.zone_name
            )
            certificate = acm.Certificate(
                self,
                "Certificate",
                domain_name=domain.name,
                validation=acm.CertificateValidation.from_dns(zone),
            )
        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="Valor Visível frontend",
            domain_names=[domain.name] if domain else None,
            certificate=certificate,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=404, response_page_path="/404.html"
                )
            ],
        )
        s3deploy.BucketDeployment(
            self,
            "Deploy",
            destination_bucket=bucket,
            sources=[
                s3deploy.Source.asset(str(site_dir)),
                s3deploy.Source.json_data("config.json", {"wsUrl": ws_url}),
            ],
            distribution=distribution,
            distribution_paths=["/*"],
        )
        if domain is not None and zone is not None:
            alias = cast(route53.IAliasRecordTarget, targets.CloudFrontTarget(distribution))
            target = route53.RecordTarget.from_alias(alias)
            route53.ARecord(self, "Alias", zone=zone, record_name=domain.name, target=target)
            route53.AaaaRecord(self, "AliasV6", zone=zone, record_name=domain.name, target=target)
        host = domain.name if domain else distribution.distribution_domain_name
        cdk.CfnOutput(self, "SiteUrl", value=f"https://{host}")
        cdk.CfnOutput(self, "SiteBucket", value=bucket.bucket_name)
