"""Response validation against the published contract.

OpenAPI 3.1 schemas *are* JSON Schema 2020-12, so a plain validator handles
`type: [boolean, "null"]` and the nested `$ref`s with no translation layer (research D12).
The `date-time` format checker is switched on deliberately: without it the trace timestamp
requirement would be decorative.

The contract is loaded from the read-only mount inside the image. A missing file raises
loudly — a contract that cannot be found must never be mistaken for a passing suite
(finding C1).
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.conftest import contract_path

CONTRACT_URI = "https://claim-triage.test/openapi.yaml"


@functools.lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    path: Path = contract_path()
    if not path.is_file():
        raise AssertionError(
            f"openapi.yaml not found at {path}. The contract is mounted read-only into the "
            "api image at /app/api-contract; without it no response can be validated."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    resource = Resource.from_contents(_contract(), default_specification=DRAFT202012)
    return Registry().with_resource(uri=CONTRACT_URI, resource=resource)


def response_schema(path: str, method: str, status: int | str) -> dict[str, Any] | None:
    """The declared schema for one operation's response, or None when none is declared."""
    operation = _contract()["paths"][path][method.lower()]
    responses = operation.get("responses", {})
    declared = responses.get(str(status))
    if declared is None:
        raise AssertionError(
            f"{method.upper()} {path} declares no {status} response in openapi.yaml"
        )
    content = declared.get("content") or {}
    media = content.get("application/json") or {}
    return media.get("schema")


@functools.lru_cache(maxsize=1)
def _format_checker() -> FormatChecker:
    """A checker that genuinely validates date-time.

    jsonschema skips a format it has no validator for, so this fails loudly rather than
    letting every timestamp assertion pass by accident (research D12).
    """
    checker = FormatChecker()
    if "date-time" not in checker.checkers:
        raise AssertionError(
            "jsonschema cannot validate the date-time format: install rfc3339-validator. "
            "Without it the trace timestamp requirement is unchecked."
        )
    return checker


def assert_conforms(path: str, method: str, status: int, body: Any) -> None:
    """Validate a response body against its declared schema.

    `path` is the contract's templated path, e.g. `/api/v1/claims/{claim_id}`.
    """
    schema = response_schema(path, method, status)
    if schema is None:
        return  # a declared response with no JSON schema (e.g. 404) constrains nothing
    validator = Draft202012Validator(
        {"$ref": CONTRACT_URI + "#" + _pointer(schema)} if "$ref" in schema else schema,
        registry=_registry(),
        format_checker=_format_checker(),
    )
    errors = sorted(validator.iter_errors(body), key=lambda error: list(error.path))
    if errors:
        details = "\n".join(
            f"  - at {'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise AssertionError(
            f"{method.upper()} {path} -> {status} does not conform to openapi.yaml:\n{details}"
        )


def _pointer(schema: dict[str, Any]) -> str:
    """Turn `{'$ref': '#/components/schemas/X'}` into the pointer part for the registry."""
    return str(schema["$ref"]).lstrip("#")


def declared_statuses(path: str, method: str) -> list[str]:
    return sorted(_contract()["paths"][path][method.lower()].get("responses", {}))


def declared_paths() -> list[str]:
    return sorted(_contract()["paths"])
