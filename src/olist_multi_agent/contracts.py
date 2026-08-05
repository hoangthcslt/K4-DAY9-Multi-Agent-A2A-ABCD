"""Typed contracts shared by coordinator, agents, policy and verifier."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    customer_request: dict[str, Any]
    investigation_scope: dict[str, bool]
    policy_version: str

    @property
    def claimed_order_id(self) -> str:
        return str(self.customer_request["claimed_order_id"])


class AgentHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    agent: str
    status: Literal["ok", "pending", "error"] = "pending"
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CaseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: CaseInput
    handoffs: dict[str, AgentHandoff] = Field(default_factory=dict)
    candidate: dict[str, Any] | None = None


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_issue: str | None = None
    secondary_issues: list[str] = Field(default_factory=list)
    case_status: Literal["action_required", "no_action"] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    root_causes: list[dict[str, Any]] = Field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = Field(default_factory=list)
    recommended_refund_brl: float | None = None
    resolution_actions: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    candidate: dict[str, Any] | None = None
