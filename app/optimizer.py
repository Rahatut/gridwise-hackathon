"""
Canonical 24-hour cost-minimization battery scheduler using scipy.optimize.linprog (HiGHS).

Decision variables per hour h (0..23) — total 120:
  idx  0..23   grid[h]        - grid import (kWh)
  idx 24..47   solar_used[h]  - solar consumed (kWh)
  idx 48..71   charge[h]      - battery charge (kWh)
  idx 72..95   discharge[h]   - battery discharge (kWh)
  idx 96..119  soc_after[h]   - battery energy at end of hour (kWh)

Objective: minimize  SUM( grid[h] * tariff[h] )

Canonical source: Sections 05, 09 of the Problem Statement.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.optimize import linprog

from app.models import (
    BatterySpec,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)

EPS = 1e-6
PLAN_TOL = 0.01  # official judge tolerance


class OptimizationError(RuntimeError):
    """Raised when the LP is infeasible or otherwise fails."""


# ---------------------------------------------------------------------------
# Internal: build per-hour constraint arrays from validated directives
# ---------------------------------------------------------------------------

def _build_constraint_arrays(
    base_solar: np.ndarray,
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Return:
        effective_solar      shape (24,)
        min_soc              shape (24,) — per-hour minimum SOC
        no_charge            shape (24,) bool
        no_discharge         shape (24,) bool
        max_grid_limit       shape (24,)  float, inf where uncapped
    """
    effective_solar = base_solar.copy()
    min_soc = np.full(24, battery.minimum_energy_kwh)
    no_charge = np.zeros(24, dtype=bool)
    no_discharge = np.zeros(24, dtype=bool)
    max_grid_limit = np.full(24, np.inf)

    for d in directives:
        if not d.applies:
            continue  # no_op or inapplicable
        adj = d.structured_adjustment or {}
        dt = d.directive_type

        if dt == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in adj.get("hours", []):
                effective_solar[h] = base_solar[h] * factor

        elif dt == "minimum_battery_reserve":
            reserve = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in adj.get("hours", []):
                min_soc[h] = max(battery.minimum_energy_kwh, reserve)

        elif dt == "no_charge_window":
            for h in adj.get("hours", []):
                no_charge[h] = True

        elif dt == "no_discharge_window":
            for h in adj.get("hours", []):
                no_discharge[h] = True

        elif dt == "max_grid_window":
            cap = float(adj.get("max_grid_kwh", math.inf))
            for h in adj.get("hours", []):
                max_grid_limit[h] = min(max_grid_limit[h], cap)

        # no_op: nothing to do

    return effective_solar, min_soc, no_charge, no_discharge, max_grid_limit


# ---------------------------------------------------------------------------
# Main LP solver
# ---------------------------------------------------------------------------

def run_energy_optimization(
    hours: List[HourEntry],
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
) -> List[HourlyPlanEntry]:
    """
    Solve the canonical LP and return a list of 24 HourlyPlanEntry objects.

    Raises OptimizationError if the LP fails or is infeasible.
    Does NOT silently clamp invalid results.
    """
    n = 24
    tariff = np.array([h.tariff_bdt_per_kwh for h in hours], dtype=float)
    base_solar = np.array([h.solar_kwh for h in hours], dtype=float)
    demand = np.array([h.demand_kwh for h in hours], dtype=float)

    cap = float(battery.capacity_kwh)
    max_charge = float(battery.max_charge_kwh_per_hour)
    max_discharge = float(battery.max_discharge_kwh_per_hour)
    initial_energy = float(battery.initial_energy_kwh)

    # Build per-hour constraint arrays
    effective_solar, min_soc, no_charge, no_discharge, max_grid_limit = (
        _build_constraint_arrays(base_solar, battery, directives)
    )

    # ------------------------------------------------------------------
    # LP formulation
    # Variables: [grid(24), solar_used(24), charge(24), discharge(24), soc_after(24)]
    # ------------------------------------------------------------------
    n_vars = 5 * n  # 120

    # Objective: minimize SUM(grid[h] * tariff[h])
    c = np.zeros(n_vars)
    c[:n] = tariff

    A_eq: list[list[float]] = []
    b_eq: list[float] = []

    # --- Energy balance per hour ---
    # grid[h] + solar_used[h] + discharge[h] - charge[h] = demand[h]
    for h in range(n):
        row = np.zeros(n_vars)
        row[h] = 1.0            # grid
        row[n + h] = 1.0        # solar_used
        row[3 * n + h] = 1.0   # discharge
        row[2 * n + h] = -1.0  # charge (subtracted because it consumes)
        A_eq.append(row.tolist())
        b_eq.append(demand[h])

    # --- Battery state transition per hour ---
    # soc_after[h] = soc_after[h-1] + charge[h] - discharge[h]
    # => soc_after[h] - soc_after[h-1] - charge[h] + discharge[h] = 0
    # For h=0: soc_after[-1] = initial_energy  (constant on RHS)
    for h in range(n):
        row = np.zeros(n_vars)
        row[4 * n + h] = 1.0    # soc_after[h]
        if h > 0:
            row[4 * n + h - 1] = -1.0  # -soc_after[h-1]
        row[2 * n + h] = -1.0   # -charge[h]
        row[3 * n + h] = 1.0    # +discharge[h]
        A_eq.append(row.tolist())
        b_eq.append(initial_energy if h == 0 else 0.0)

    # --- End-of-day neutrality ---
    # soc_after[23] == initial_energy
    row = np.zeros(n_vars)
    row[4 * n + 23] = 1.0
    A_eq.append(row.tolist())
    b_eq.append(initial_energy)

    # ------------------------------------------------------------------
    # Bounds
    # ------------------------------------------------------------------
    bounds: list[tuple[float, float | None]] = []

    # grid[h] in [0, max_grid_limit[h]]
    for h in range(n):
        hi = max_grid_limit[h] if np.isfinite(max_grid_limit[h]) else None
        bounds.append((0.0, hi))

    # solar_used[h] in [0, effective_solar[h]]
    for h in range(n):
        bounds.append((0.0, float(effective_solar[h])))

    # charge[h] in [0, max_charge]  (0 if no_charge hour)
    for h in range(n):
        bounds.append((0.0, 0.0 if no_charge[h] else max_charge))

    # discharge[h] in [0, max_discharge]  (0 if no_discharge hour)
    for h in range(n):
        bounds.append((0.0, 0.0 if no_discharge[h] else max_discharge))

    # soc_after[h] in [min_soc[h], cap]  — per-hour minimum!
    for h in range(n):
        bounds.append((float(min_soc[h]), cap))

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    result = linprog(
        c,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs",
        options={"time_limit": 10},
    )

    if not result.success:
        raise OptimizationError(
            f"LP solver failed: status={result.status} message={result.message}"
        )

    grid = result.x[:n]
    solar_used = result.x[n : 2 * n]
    charge = result.x[2 * n : 3 * n]
    discharge = result.x[3 * n : 4 * n]

    # ------------------------------------------------------------------
    # Post-solve: canonicalize action (net simultaneous charge/discharge)
    # ------------------------------------------------------------------
    plan: list[HourlyPlanEntry] = []
    soc_prev = initial_energy

    for h in range(n):
        raw_charge = float(charge[h])
        raw_discharge = float(discharge[h])

        # Net simultaneous flows (degenerate LP artefact)
        # Only net if the net preserves all hard constraints at this hour.
        net = raw_charge - raw_discharge
        if raw_charge > EPS and raw_discharge > EPS:
            if net >= 0:
                raw_charge = net
                raw_discharge = 0.0
            else:
                raw_charge = 0.0
                raw_discharge = -net

        raw_grid = float(grid[h])
        raw_solar = float(solar_used[h])

        # Determine action
        if raw_charge > EPS:
            action = "charge"
            batt_kwh = raw_charge
        elif raw_discharge > EPS:
            action = "discharge"
            batt_kwh = raw_discharge
        else:
            action = "idle"
            batt_kwh = 0.0

        soc_after = soc_prev + (raw_charge - raw_discharge)

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(max(0.0, raw_grid), 6),
                solar_used_kwh=round(max(0.0, raw_solar), 6),
                battery_action=action,  # type: ignore[arg-type]
                battery_kwh=round(max(0.0, batt_kwh), 6),
                battery_energy_after_kwh=round(soc_after, 6),
            )
        )
        soc_prev = soc_after

    return plan