"""
FastAPI application entry point.

Endpoints (Section 06 of the Problem Statement):
    GET  /health         -> HealthResponse
    POST /optimize-energy -> OptimizeResponse

HTTP behaviour:
    200  successful response
    400  malformed/structurally invalid request  (FastAPI handles JSON parse errors)
    422  semantically invalid well-formed request (Pydantic validation)
    500  controlled internal error — no stack traces / secrets exposed
"""
from __future__ import annotations

import logging

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.llm import interpret_operator_notes
from app.models import (
    HealthResponse,
    HourlyPlanEntry,
    OptimizeRequest,
    OptimizeResponse,
)
from app.optimizer import OptimizationError, run_energy_optimization
from app.validator import validate_plan

logger = logging.getLogger(__name__)

app = FastAPI(title="GridWise Energy Optimiser")


# ---------------------------------------------------------------------------
# Custom 400 handler for malformed JSON
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
    # Let FastAPI's built-in validation errors (422) propagate normally;
    # only catch truly unexpected errors here.
    logger.exception("Unhandled exception in %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(payload: OptimizeRequest) -> OptimizeResponse:
    try:
        # Step 1: Parse and guardrail operator notes via LLM
        directives = interpret_operator_notes(
            payload.operator_notes,
            payload.battery,
        )

        # Step 2: Run cost-minimisation LP
        hourly_plan: list[HourlyPlanEntry] = run_energy_optimization(
            hours=payload.hours,
            battery=payload.battery,
            directives=directives,
        )

        # Step 3: Compute aggregates from plan
        grid_values = [p.grid_kwh for p in hourly_plan]
        tariff_values = [h.tariff_bdt_per_kwh for h in payload.hours]

        total_grid_kwh = round(float(sum(grid_values)), 6)
        total_cost_bdt = round(
            float(sum(g * t for g, t in zip(grid_values, tariff_values))), 6
        )
        peak_grid_kwh = round(float(max(grid_values)), 6)

        # Step 4: Independent final validation (must pass before HTTP 200)
        vr = validate_plan(
            hours=payload.hours,
            battery=payload.battery,
            directives=directives,
            plan=hourly_plan,
            reported_total_grid_kwh=total_grid_kwh,
            reported_total_cost_bdt=total_cost_bdt,
            reported_peak_grid_kwh=peak_grid_kwh,
        )
        if not vr.valid:
            logger.error("Post-solve validation failed: %s", vr.errors)
            raise HTTPException(status_code=500, detail="Internal server error")

        # Step 5: Generate deterministic plan_summary
        plan_summary = _generate_plan_summary(directives, hourly_plan, payload)

        return OptimizeResponse(
            scenario_id=payload.scenario_id,
            directive_interpretation=directives,
            hourly_plan=hourly_plan,
            total_grid_kwh=total_grid_kwh,
            total_cost_bdt=total_cost_bdt,
            peak_grid_kwh=peak_grid_kwh,
            plan_summary=plan_summary,
        )

    except HTTPException:
        raise
    except OptimizationError as exc:
        logger.error("Optimisation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    except Exception as exc:
        logger.exception("Unexpected error during optimize-energy")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Deterministic plan_summary generation (no LLM call)
# ---------------------------------------------------------------------------

def _generate_plan_summary(
    directives,
    hourly_plan: list[HourlyPlanEntry],
    payload: OptimizeRequest,
) -> str:
    """
    Build a concise plan summary from applicable directive categories,
    battery shifting behaviour, and end-of-day restoration.
    No LLM call is made.
    """
    parts: list[str] = []

    active_types = {d.directive_type for d in directives if d.applies}

    if "solar_reduction" in active_types:
        parts.append("Solar availability reduced during specified hours per operator directive.")
    if "minimum_battery_reserve" in active_types:
        parts.append("Elevated battery reserve enforced during specified hours.")
    if "no_charge_window" in active_types:
        parts.append("Battery charging suspended during restricted window.")
    if "no_discharge_window" in active_types:
        parts.append("Battery discharging suspended during restricted window.")
    if "max_grid_window" in active_types:
        parts.append("Grid import capped during high-load window.")

    # Battery shifting
    charge_hours = [p.hour for p in hourly_plan if p.battery_action == "charge"]
    discharge_hours = [p.hour for p in hourly_plan if p.battery_action == "discharge"]
    if charge_hours and discharge_hours:
        parts.append(
            f"Battery charged during cheap hours {charge_hours} "
            f"and discharged during expensive hours {discharge_hours} "
            "to minimise grid cost."
        )
    elif not charge_hours and not discharge_hours:
        parts.append("Battery remained idle throughout (no cost-saving shift opportunity).")

    # End-of-day neutrality
    initial = payload.battery.initial_energy_kwh
    final = hourly_plan[-1].battery_energy_after_kwh if hourly_plan else initial
    if abs(final - initial) < 0.02:
        parts.append(
            f"Battery returned to initial state ({initial} kWh) at end of day."
        )

    return " ".join(parts) if parts else "Optimal 24-hour schedule produced."