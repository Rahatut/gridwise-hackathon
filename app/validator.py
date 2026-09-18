"""
Independent final validator.

Replays the returned hourly_plan from first principles using only:
  - the original request (hours, battery)
  - the validated directives
  - the returned plan itself

Does NOT reuse optimizer internal arrays as the source of truth.

Canonical source: Section 11 of the Problem Statement.
Official tolerance: 0.01 kWh / 0.01 BDT.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List

import numpy as np

from app.models import (
    BatterySpec,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)

TOLERANCE = 0.01


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.valid = False
        self.errors.append(msg)


def validate_plan(
    hours: List[HourEntry],
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
    plan: List[HourlyPlanEntry],
    reported_total_grid_kwh: float,
    reported_total_cost_bdt: float,
    reported_peak_grid_kwh: float,
) -> ValidationResult:
    """
    Independently validate the returned plan against all canonical rules.
    Returns a ValidationResult with valid=True or a list of error messages.
    """
    vr = ValidationResult()

    # ------------------------------------------------------------------ #
    # 1. Exactly 24 unique hours 0..23
    # ------------------------------------------------------------------ #
    if len(plan) != 24:
        vr.fail(f"hourly_plan has {len(plan)} entries; expected 24")
        return vr  # Can't continue without 24 entries

    plan_hours = [p.hour for p in plan]
    if sorted(plan_hours) != list(range(24)):
        vr.fail(f"hourly_plan hours are not exactly 0..23: {sorted(plan_hours)}")
        return vr

    # Sort plan by hour for replay
    plan_sorted = sorted(plan, key=lambda p: p.hour)
    # Sort input hours by hour
    hours_sorted = sorted(hours, key=lambda h: h.hour)

    # ------------------------------------------------------------------ #
    # 2. Finite, non-negative numeric values
    # ------------------------------------------------------------------ #
    for p in plan_sorted:
        for attr in ("grid_kwh", "solar_used_kwh", "battery_kwh", "battery_energy_after_kwh"):
            v = getattr(p, attr)
            if not math.isfinite(v):
                vr.fail(f"hour {p.hour}: {attr}={v} is not finite")
            elif v < -TOLERANCE:
                vr.fail(f"hour {p.hour}: {attr}={v} is negative")

    if not vr.valid:
        return vr

    # ------------------------------------------------------------------ #
    # Build effective_solar and per-hour constraints from directives
    # ------------------------------------------------------------------ #
    base_solar = np.array([h.solar_kwh for h in hours_sorted], dtype=float)
    effective_solar = base_solar.copy()
    min_soc = np.full(24, battery.minimum_energy_kwh)
    no_charge_hours: set[int] = set()
    no_discharge_hours: set[int] = set()
    max_grid_limit = np.full(24, math.inf)

    for d in directives:
        if not d.applies:
            continue
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
                no_charge_hours.add(h)

        elif dt == "no_discharge_window":
            for h in adj.get("hours", []):
                no_discharge_hours.add(h)

        elif dt == "max_grid_window":
            cap = float(adj.get("max_grid_kwh", math.inf))
            for h in adj.get("hours", []):
                max_grid_limit[h] = min(max_grid_limit[h], cap)

    # ------------------------------------------------------------------ #
    # 3. Effective solar: solar_used <= effective_solar
    # ------------------------------------------------------------------ #
    for p in plan_sorted:
        h = p.hour
        eff = effective_solar[h]
        if p.solar_used_kwh > eff + TOLERANCE:
            vr.fail(
                f"hour {h}: solar_used_kwh={p.solar_used_kwh} "
                f"exceeds effective_solar={eff}"
            )

    # ------------------------------------------------------------------ #
    # 4-8. Battery replay: energy balance, transition, bounds, action consistency
    # ------------------------------------------------------------------ #
    soc_prev = battery.initial_energy_kwh

    for p in plan_sorted:
        h = p.hour
        hour_input = hours_sorted[h]

        # --- 4. Battery action consistency ---
        if p.battery_action == "idle" and p.battery_kwh > TOLERANCE:
            vr.fail(f"hour {h}: battery_action=idle but battery_kwh={p.battery_kwh} != 0")

        # Derive charge and discharge from action
        batt_charge = p.battery_kwh if p.battery_action == "charge" else 0.0
        batt_discharge = p.battery_kwh if p.battery_action == "discharge" else 0.0

        # --- 5. Energy balance ---
        lhs = p.grid_kwh + p.solar_used_kwh + batt_discharge
        rhs = hour_input.demand_kwh + batt_charge
        if abs(lhs - rhs) > TOLERANCE:
            vr.fail(
                f"hour {h}: energy balance violated: "
                f"grid({p.grid_kwh})+solar({p.solar_used_kwh})+discharge({batt_discharge})"
                f"={lhs:.4f} != demand({hour_input.demand_kwh})+charge({batt_charge})={rhs:.4f}"
            )

        # --- 6. Battery transition ---
        soc_after_expected = soc_prev + batt_charge - batt_discharge
        if abs(p.battery_energy_after_kwh - soc_after_expected) > TOLERANCE:
            vr.fail(
                f"hour {h}: battery_energy_after_kwh={p.battery_energy_after_kwh} "
                f"expected {soc_after_expected:.4f} "
                f"(prev={soc_prev:.4f} +charge={batt_charge} -discharge={batt_discharge})"
            )

        soc_after = soc_after_expected  # use recomputed for chain

        # --- 7-8. Capacity & base minimum ---
        if soc_after < battery.minimum_energy_kwh - TOLERANCE:
            vr.fail(
                f"hour {h}: battery_energy_after={soc_after:.4f} "
                f"below base minimum_energy_kwh={battery.minimum_energy_kwh}"
            )
        if soc_after > battery.capacity_kwh + TOLERANCE:
            vr.fail(
                f"hour {h}: battery_energy_after={soc_after:.4f} "
                f"exceeds capacity_kwh={battery.capacity_kwh}"
            )

        # --- 9. Operator minimum reserve ---
        if soc_after < min_soc[h] - TOLERANCE:
            vr.fail(
                f"hour {h}: battery_energy_after={soc_after:.4f} "
                f"below operator minimum reserve={min_soc[h]}"
            )

        # --- 10. Charge rate limit ---
        if batt_charge > battery.max_charge_kwh_per_hour + TOLERANCE:
            vr.fail(
                f"hour {h}: charge={batt_charge} exceeds "
                f"max_charge_kwh_per_hour={battery.max_charge_kwh_per_hour}"
            )

        # --- 11. Discharge rate limit ---
        if batt_discharge > battery.max_discharge_kwh_per_hour + TOLERANCE:
            vr.fail(
                f"hour {h}: discharge={batt_discharge} exceeds "
                f"max_discharge_kwh_per_hour={battery.max_discharge_kwh_per_hour}"
            )

        # --- 12. no_charge_window ---
        if h in no_charge_hours and batt_charge > TOLERANCE:
            vr.fail(
                f"hour {h}: no_charge_window directive violated "
                f"(charge={batt_charge})"
            )

        # --- 13. no_discharge_window ---
        if h in no_discharge_hours and batt_discharge > TOLERANCE:
            vr.fail(
                f"hour {h}: no_discharge_window directive violated "
                f"(discharge={batt_discharge})"
            )

        # --- 14. max_grid_window ---
        if p.grid_kwh > max_grid_limit[h] + TOLERANCE:
            vr.fail(
                f"hour {h}: grid_kwh={p.grid_kwh} exceeds "
                f"max_grid_window limit={max_grid_limit[h]}"
            )

        soc_prev = soc_after

    # ------------------------------------------------------------------ #
    # 15. End-of-day battery neutrality
    # ------------------------------------------------------------------ #
    final_soc = soc_prev
    if abs(final_soc - battery.initial_energy_kwh) > TOLERANCE:
        vr.fail(
            f"End-of-day neutrality violated: "
            f"final SOC={final_soc:.4f} != initial_energy_kwh={battery.initial_energy_kwh}"
        )

    # ------------------------------------------------------------------ #
    # 16-18. Recalculate aggregates
    # ------------------------------------------------------------------ #
    grid_values = np.array([p.grid_kwh for p in plan_sorted], dtype=float)
    tariff_values = np.array([h.tariff_bdt_per_kwh for h in hours_sorted], dtype=float)

    recalc_total_grid = float(np.sum(grid_values))
    recalc_total_cost = float(np.sum(grid_values * tariff_values))
    recalc_peak_grid = float(np.max(grid_values))

    if abs(recalc_total_grid - reported_total_grid_kwh) > TOLERANCE:
        vr.fail(
            f"total_grid_kwh={reported_total_grid_kwh} "
            f"disagrees with recalculated {recalc_total_grid:.4f}"
        )

    if abs(recalc_total_cost - reported_total_cost_bdt) > TOLERANCE:
        vr.fail(
            f"total_cost_bdt={reported_total_cost_bdt} "
            f"disagrees with recalculated {recalc_total_cost:.4f}"
        )

    if abs(recalc_peak_grid - reported_peak_grid_kwh) > TOLERANCE:
        vr.fail(
            f"peak_grid_kwh={reported_peak_grid_kwh} "
            f"disagrees with recalculated {recalc_peak_grid:.4f}"
        )

    return vr
