from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class HealthResponse(BaseModel):
    status: str = "ok"

class ScenarioData(BaseModel):
    # Adjust schema fields based on exact hackathon sample JSON
    grid_prices: List[float] = Field(..., description="24-hour electricity prices")
    solar_generation: List[float] = Field(..., description="24-hour solar profile")
    load_demand: List[float] = Field(..., description="24-hour load profile")
    battery_capacity: float
    max_charge_rate: float
    max_discharge_rate: float
    initial_battery_energy: float

class OptimizeRequest(BaseModel):
    scenario: ScenarioData
    operator_notes: Optional[List[str]] = Field(default=[], description="1-3 natural language notes")

class Directive(BaseModel):
    note_index: int
    type: str
    applies: bool
    details: Optional[Dict[str, Any]] = None

class OptimizeResponse(BaseModel):
    directives: List[Directive]
    total_cost_bdt: float
    schedule: List[Dict[str, float]]