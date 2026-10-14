"""FR-036 / constitution Principle V - the credential never appears anywhere.

A leaked key ends access for everyone sharing it, and the failure is unrecoverable after the
fact. A diagnostic may name the variable and whether it is set; never its value.
"""
from __future__ import annotations

import logging

import pytest

from claim_triage.settings import REDACTED, CredentialScrubber, Settings
from tests.conftest import TEST_CREDENTIAL

pytestmark = pytest.mark.unit


def test_repr_and_str_redact_the_key(settings):
    assert TEST_CREDENTIAL not in repr(settings)
    assert TEST_CREDENTIAL not in str(settings)
    assert REDACTED in repr(settings)


def test_the_key_is_wrapped_so_an_accidental_format_cannot_leak_it(settings):
    assert TEST_CREDENTIAL not in f"{settings}"
    assert TEST_CREDENTIAL not in f"{settings.portkey_api_key}"
    # It is still retrievable deliberately, which is the only way it should ever be read.
    assert settings.portkey_api_key.get_secret_value() == TEST_CREDENTIAL


@pytest.mark.parametrize(
    "message,args",
    [
        ("key is " + TEST_CREDENTIAL, ()),
        ("key is %s", (TEST_CREDENTIAL,)),
        ("key is %(k)s", {"k": TEST_CREDENTIAL}),
    ],
)
def test_the_scrubber_rewrites_log_records(caplog, message, args):
    logger = logging.getLogger("claim_triage.test.redaction")
    logger.addFilter(CredentialScrubber(TEST_CREDENTIAL))

    with caplog.at_level(logging.INFO):
        logger.info(message, *args) if isinstance(args, tuple) else logger.info(message, args)

    assert caplog.records
    for record in caplog.records:
        assert TEST_CREDENTIAL not in record.getMessage()
        assert REDACTED in record.getMessage()


def test_the_scrubber_is_a_no_op_without_a_configured_key(caplog):
    logger = logging.getLogger("claim_triage.test.redaction.empty")
    logger.addFilter(CredentialScrubber(""))

    with caplog.at_level(logging.INFO):
        logger.info("nothing to hide")

    assert caplog.records[0].getMessage() == "nothing to hide"


def test_the_route_is_split_without_exposing_the_key():
    settings = Settings(
        portkey_api_key="secret-value",
        portkey_base_url="https://gateway.example/v1",
        claude_model_route="@anthropic---abc123/claude-opus-5",
    )

    # research D1: root without /v1, provider header, unprefixed model.
    assert settings.gateway_root == "https://gateway.example"
    assert settings.provider_route == "@anthropic---abc123"
    assert settings.model_id == "claude-opus-5"
    assert "secret-value" not in repr(settings)


def test_llm_configured_reports_presence_not_value():
    configured = Settings(
        portkey_api_key="x", claude_model_route="@anthropic---a/claude-opus-5"
    )
    missing = Settings(portkey_api_key="", claude_model_route="@anthropic---a/claude-opus-5")

    assert configured.llm_configured is True
    assert missing.llm_configured is False
