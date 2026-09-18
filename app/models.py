"""
Canonical Pydantic v2 models aligned with the GridWise Problem Statement.
Canonical source: BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.pdf
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finite_non_negative(v: float, field: str) -> float:
    if not isinstance(v, (int, float)):
        raise ValueError(f"{field} must be a number")
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{field} must be finite (got {v})")
    if v < 0:
        raise ValueError(f"{field} must be non-negative (got {v})")
    return float(v)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class HourEntry(BaseModel):
    """One entry in the hours array (Section 7.2)."""

    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float

    @model_validator(mode="after")
    def _validate_numbers(self) -> "HourEntry":
        _finite_non_negative(self.demand_kwh, "demand_kwh")
        _finite_non_negative(self.solar_kwh, "solar_kwh")
        _finite_non_negative(self.tariff_bdt_per_kwh, "tariff_bdt_per_kwh")
        return self


class BatterySpec(BaseModel):
    """Battery object (Section 7.3)."""

    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float

    @model_validator(mode="after")
    def _validate_battery(self) -> "BatterySpec":
        for name in (
            "capacity_kwh",
            "initial_energy_kwh",
            "minimum_energy_kwh",
            "max_charge_kwh_per_hour",
            "max_discharge_kwh_per_hour",
        ):
            _finite_non_negative(getattr(self, name), name)

        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError(
                f"minimum_energy_kwh ({self.minimum_energy_kwh}) "
                f"must be <= capacity_kwh ({self.capacity_kwh})"
            )
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError(
                f"initial_energy_kwh ({self.initial_energy_kwh}) "
                f"must be <= capacity_kwh ({self.capacity_kwh})"
            )
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError(
                f"initial_energy_kwh ({self.initial_energy_kwh}) "
                f"must be >= minimum_energy_kwh ({self.minimum_energy_kwh})"
            )
        return self


class OptimizeRequest(BaseModel):
    """Canonical POST /optimize-energy request (Section 07)."""

    scenario_id: str
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24)
    battery: BatterySpec

    @model_validator(mode="after")
    def _validate_hours(self) -> "OptimizeRequest":
        # Every operator note must be non-empty
        for i, note in enumerate(self.operator_notes):
            if not note.strip():
                raise ValueError(f"operator_notes[{i}] must be a non-empty string")

        # Exactly 24 unique hours 0..23
        seen = set()
        for entry in self.hours:
            if entry.hour in seen:
                raise ValueError(f"Duplicate hour {entry.hour} in hours array")
            seen.add(entry.hour)
        missing = set(range(24)) - seen
        if missing:
            raise ValueError(f"Missing hours in hours array: {sorted(missing)}")

        # Sort by hour internally (canonical)
        self.hours = sorted(self.hours, key=lambda h: h.hour)
        return self


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]

BatteryAction = Literal["charge", "discharge", "idle"]


class DirectiveInterpretation(BaseModel):
    """One machine-checkable interpretation entry (Section 10.2)."""

    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str


class HourlyPlanEntry(BaseModel):
    """One entry in the hourly_plan array (Section 10.3)."""

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeResponse(BaseModel):
    """Canonical POST /optimize-energy response (Section 10.1)."""

    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str