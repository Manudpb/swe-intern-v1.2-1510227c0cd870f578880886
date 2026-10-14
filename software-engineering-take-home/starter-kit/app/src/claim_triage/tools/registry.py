"""Tool name -> schema + handler, with a duplicate-name guard.

The registry is the single list the model is shown and the single dispatch table the loop
uses, so a tool cannot be advertised without being callable or vice versa.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from claim_triage.tools import check_coverage, estimate_repair_cost, search_past_claims, submit_triage


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        names = [spec.name for spec in specs]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate tool names in registry: {sorted(duplicates)}")
        for spec in specs:
            if spec.input_schema.get("type") != "object":
                raise ValueError(f"Tool {spec.name} input_schema must be an object schema")
        self._specs = {spec.name: spec for spec in specs}

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._specs)

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in self._specs.values()
        ]


def build_registry(deps: Any) -> ToolRegistry:
    """The triage agent's tools. Handlers close over deps; the loop passes only arguments."""
    return ToolRegistry(
        [
            ToolSpec(
                search_past_claims.NAME,
                search_past_claims.DESCRIPTION,
                search_past_claims.INPUT_SCHEMA,
                lambda args: search_past_claims.run(deps, args),
            ),
            ToolSpec(
                estimate_repair_cost.NAME,
                estimate_repair_cost.DESCRIPTION,
                estimate_repair_cost.INPUT_SCHEMA,
                lambda args: estimate_repair_cost.run(deps.cost_table, args),
            ),
            ToolSpec(
                check_coverage.NAME,
                check_coverage.DESCRIPTION,
                check_coverage.INPUT_SCHEMA,
                lambda args: check_coverage.run(deps.coverage_table, args),
            ),
            ToolSpec(
                submit_triage.NAME,
                submit_triage.DESCRIPTION,
                submit_triage.INPUT_SCHEMA,
                submit_triage.run,  # called with (args, priced=...) by the loop
            ),
        ]
    )
