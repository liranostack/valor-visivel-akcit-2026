"""App wiring: the site domain comes from CDK context (A.03.17)."""

import aws_cdk as cdk
import pytest
from vv_infra.app import existing_guardrail, site_domain
from vv_infra.stacks.guardrail_stack import GuardrailRef


def test_no_context_no_domain() -> None:
    assert site_domain(cdk.App()) is None


def test_domain_from_context() -> None:
    app = cdk.App(
        context={
            "siteDomain": "vv.example.com.br",
            "hostedZoneId": "Z1",
            "hostedZoneName": "example.com.br",
        }
    )
    domain = site_domain(app)
    assert domain is not None and domain.name == "vv.example.com.br"


def test_no_context_creates_guardrail() -> None:
    assert existing_guardrail(cdk.App()) is None


def test_guardrail_reused_from_context() -> None:
    app = cdk.App(context={"guardrailId": "abc123example", "guardrailVersion": "1"})
    assert existing_guardrail(app) == GuardrailRef("abc123example", "1")


def test_guardrail_id_without_version_is_an_error() -> None:
    with pytest.raises(ValueError, match="guardrailVersion"):
        existing_guardrail(cdk.App(context={"guardrailId": "abc123example"}))


def test_partial_context_is_an_error() -> None:
    with pytest.raises(ValueError, match="hostedZoneId"):
        site_domain(cdk.App(context={"siteDomain": "vv.example.com.br"}))
