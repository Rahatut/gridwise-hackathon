import os
from fastapi import FastAPI, HTTPException

from app.models import HealthResponse, OptimizeRequest, OptimizeResponse
from app.llm import parse_and_guardrail_notes
from app.optimizer import run_energy_optimization

app = FastAPI(title="GridWise Hackathon Service")


@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(payload: OptimizeRequest):
    try:
        # Step 1: Parse and validate operator notes via LLM + guardrails
        directives = parse_and_guardrail_notes(payload.operator_notes)

        # Step 2: Compute optimal 24-hour energy plan
        results = run_energy_optimization(payload.scenario.model_dump(), directives)

        return {
            "directives": directives,
            "total_grid_kwh": results["total_grid_kwh"],
            "total_cost_bdt": results["total_cost_bdt"],
            "peak_grid_kwh": results["peak_grid_kwh"],
            "schedule": results["schedule"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")