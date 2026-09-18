from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class ScenarioData(BaseModel):
    tariff_bdt_per_kwh: List[float] = Field(..., min_length=24, max_length=24, description="24-hour electricity tariffs (BDT/kWh)")
    effective_solar_kwh: List[float] = Field(..., min_length=24, max_length=24, description="24-hour solar generation profile (kWh)")
    demand_kwh: List[float] = Field(..., min_length=24, max_length=24, description="24-hour load demand (kWh)")
    battery_capacity: float = Field(..., ge=0, description="Total battery capacity (kWh)")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Max battery charge rate (kWh/h)")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Max battery discharge rate (kWh/h)")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at hour 0 (kWh)")


class OptimizeRequest(BaseModel):
    scenario: ScenarioData
    operator_notes: Optional[List[str]] = Field(default=[], description="Natural-language operator notes")


class Directive(BaseModel):
    note_index: int
    type: str
    applies: bool
    structured_adjustment: Optional[Dict[str, Any]] = None


class OptimizeResponse(BaseModel):
    directives: List[Directive]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    schedule: List[Dict[str, Any]]