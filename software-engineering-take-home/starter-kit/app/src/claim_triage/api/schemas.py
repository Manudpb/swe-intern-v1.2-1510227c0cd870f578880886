"""Pydantic mirrors of `api-contract/openapi.yaml`.

The contract is the authority (constitution Principle I). These models exist to make the
contract's shape unavoidable in code; they are never the place a field is invented. Enum
members are spelled exactly as the contract spells them.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DamageType(str, Enum):
    water_damage = "water_damage"
    fire_damage = "fire_damage"
    storm_damage = "storm_damage"
    break_in = "break_in"
    vandalism = "vandalism"
    other = "other"


class Severity(str, Enum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"
    catastrophic = "catastrophic"


class Urgency(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class PolicyType(str, Enum):
    basic_homeowner = "basic_homeowner"
    standard_homeowner = "standard_homeowner"
    premium_homeowner = "premium_homeowner"
    renters = "renters"
    landlord = "landlord"


class StepKind(str, Enum):
    reason = "reason"
    act = "act"
    observe = "observe"


class IntakeValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_property_damage: bool
    # null ONLY for a submission with no image; never a claimed pass (invariant I2).
    is_valid_image: bool | None
    no_pii_detected: bool
    no_offensive_content: bool


class CostRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float
    max: float
    currency: str = "USD"


class SimilarClaimRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    resolution_summary: str


class TriageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    damage_type: DamageType
    severity: Severity
    affected_areas: list[str]
    damage_description: str
    estimated_repair_cost: CostRange
    urgency: Urgency
    recommendation: str
    similar_past_claims: list[SimilarClaimRef]


class SafetyChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_coverage_promises: bool
    no_legal_advice: bool
    no_settlement_amounts: bool
    no_liability_determination: bool
    no_emotional_language: bool

    def all_clear(self) -> bool:
        return all(getattr(self, name) for name in self.model_fields)

    def failing(self) -> list[str]:
        return [name for name in self.model_fields if not getattr(self, name)]


class TriageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    intake_validation: IntakeValidation
    triage_assessment: TriageAssessment
    safety_checks: SafetyChecks


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int
    type: StepKind
    content: str
    timestamp: str
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: dict | list | None = None


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    steps: list[TraceStep]
    total_duration_ms: int


class ValidationErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    intake_validation: IntakeValidation
    message: str


class SafetyErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    safety_checks: SafetyChecks
    message: str


class ServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_db: str
    llm: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    services: ServiceStatus
