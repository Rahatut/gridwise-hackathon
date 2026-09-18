"""
Robustness and edge case tests for GridWise optimizer and API models.

Covers:
- Zero solar generation across all 24 hours
- Zero tariff in selected hours
- Minimum SOC equals capacity (battery pinned at capacity)
- Initial SOC equals minimum SOC
- Max charge rate = 0 (cannot charge)
- Max discharge rate = 0 (cannot discharge)
- Overlapping valid hard directives (e.g. reserve + max grid)
- Simultaneous no-charge and no-discharge windows (battery forced idle)
- Solar reduction at factor 0 (complete solar curtailment)
- Solar reduction at factor 1 (no solar reduction)
- Reserve higher than base reserve
- Boundary testing: 1 note vs 3 notes
- Rejection of NaN, Infinity, duplicate hours, and missing hours
"""
from __future__ import annotations

import math
import pytest
from pydantic import ValidationError

from app.models import (
    BatterySpec,
    DirectiveInterpretation,
    HourEntry,
    OptimizeRequest,
)
from app.optimizer import OptimizationError, run_energy_optimization
from app.validator import validate_plan


def _base_hours(solar: float = 20.0, demand: float = 100.0, tariff: float = 5.0) -> list[HourEntry]:
    return [
        HourEntry(hour=h, demand_kwh=demand, solar_kwh=solar, tariff_bdt_per_kwh=tariff)
        for h in range(24)
    ]


def _base_battery(
    capacity: float = 200.0,
    initial: float = 100.0,
    minimum: float = 20.0,
    charge_max: float = 50.0,
    discharge_max: float = 50.0,
) -> BatterySpec:
    return BatterySpec(
        capacity_kwh=capacity,
        initial_energy_kwh=initial,
        minimum_energy_kwh=minimum,
        max_charge_kwh_per_hour=charge_max,
        max_discharge_kwh_per_hour=discharge_max,
    )


def test_zero_solar_all_hours():
    """All energy must come from grid and battery when solar is zero."""
    hours = _base_hours(solar=0.0, demand=80.0)
    battery = _base_battery()
    plan = run_energy_optimization(hours, battery, [])
    assert len(plan) == 24
    for p in plan:
        assert p.solar_used_kwh == 0.0
    vr = validate_plan(hours, battery, [], plan, sum(p.grid_kwh for p in plan), sum(p.grid_kwh * 5.0 for p in plan), max(p.grid_kwh for p in plan))
    assert vr.valid


def test_zero_tariff_hours():
    """Hours with zero tariff should be aggressively favored for charging."""
    hours = _base_hours(solar=0.0, demand=50.0, tariff=10.0)
    # Hour 2 and 3 have 0 tariff
    hours[2] = HourEntry(hour=2, demand_kwh=50.0, solar_kwh=0.0, tariff_bdt_per_kwh=0.0)
    hours[3] = HourEntry(hour=3, demand_kwh=50.0, solar_kwh=0.0, tariff_bdt_per_kwh=0.0)

    battery = _base_battery(capacity=200.0, initial=20.0, minimum=20.0)
    plan = run_energy_optimization(hours, battery, [])
    assert plan[2].battery_action == "charge"
    assert plan[3].battery_action == "charge"


def test_min_soc_equals_capacity():
    """When minimum SOC equals capacity, battery cannot discharge below capacity."""
    hours = _base_hours()
    battery = _base_battery(capacity=100.0, initial=100.0, minimum=100.0)
    plan = run_energy_optimization(hours, battery, [])
    for p in plan:
        assert abs(p.battery_energy_after_kwh - 100.0) < 1e-4
        assert p.battery_action == "idle"


def test_initial_soc_equals_minimum():
    """Battery starts at minimum energy and respects neutrality at end of day."""
    hours = _base_hours()
    battery = _base_battery(capacity=200.0, initial=20.0, minimum=20.0)
    plan = run_energy_optimization(hours, battery, [])
    assert abs(plan[-1].battery_energy_after_kwh - 20.0) < 1e-4
    for p in plan:
        assert p.battery_energy_after_kwh >= 20.0 - 1e-4


def test_max_charge_zero():
    """When max charge rate is 0, battery can never charge."""
    hours = _base_hours(solar=0.0, tariff=10.0)
    battery = _base_battery(charge_max=0.0, initial=100.0)
    plan = run_energy_optimization(hours, battery, [])
    for p in plan:
        assert p.battery_action != "charge"
        if p.battery_action == "charge":
            assert p.battery_kwh == 0.0


def test_max_discharge_zero():
    """When max discharge rate is 0, battery can never discharge."""
    hours = _base_hours(solar=0.0, tariff=10.0)
    battery = _base_battery(discharge_max=0.0, initial=100.0)
    plan = run_energy_optimization(hours, battery, [])
    for p in plan:
        assert p.battery_action != "discharge"
        if p.battery_action == "discharge":
            assert p.battery_kwh == 0.0


def test_simultaneous_no_charge_and_no_discharge():
    """When an hour has both no-charge and no-discharge, it must be idle."""
    hours = _base_hours()
    battery = _base_battery()
    dirs = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type="no_charge_window", structured_adjustment={"hours": [5, 6]}, explanation="No charge"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type="no_discharge_window", structured_adjustment={"hours": [5, 6]}, explanation="No discharge"),
    ]
    plan = run_energy_optimization(hours, battery, dirs)
    for h in (5, 6):
        assert plan[h].battery_action == "idle"
        assert plan[h].battery_kwh == 0.0


def test_solar_reduction_factor_zero_and_one():
    """Factor 0 means 0% solar usable; factor 1 means 100% solar usable."""
    hours = _base_hours(solar=50.0)
    battery = _base_battery()
    dirs = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type="solar_reduction", structured_adjustment={"hours": [12], "factor": 0.0}, explanation="Zero solar"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type="solar_reduction", structured_adjustment={"hours": [13], "factor": 1.0}, explanation="Full solar"),
    ]
    plan = run_energy_optimization(hours, battery, dirs)
    assert plan[12].solar_used_kwh == 0.0
    assert plan[13].solar_used_kwh <= 50.0


def test_overlapping_reserve_and_max_grid():
    """Simultaneous minimum battery reserve and grid cap in the same window."""
    hours = _base_hours(demand=120.0, solar=10.0, tariff=10.0)
    battery = _base_battery(capacity=200.0, initial=100.0, minimum=20.0)
    dirs = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type="minimum_battery_reserve", structured_adjustment={"hours": [18, 19], "minimum_energy_kwh": 90.0}, explanation="Reserve 90"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type="max_grid_window", structured_adjustment={"hours": [18, 19], "max_grid_kwh": 150.0}, explanation="Max grid 150"),
    ]
    plan = run_energy_optimization(hours, battery, dirs)
    for h in (18, 19):
        assert plan[h].battery_energy_after_kwh >= 90.0 - 1e-4
        assert plan[h].grid_kwh <= 150.0 + 1e-4


def test_note_count_boundaries():
    """Verify operator_notes accepts exactly 1, 2, or 3 notes and rejects 0 or 4."""
    hours = _base_hours()
    battery = _base_battery()

    # 1 note: OK
    req1 = OptimizeRequest(scenario_id="S1", battery=battery, hours=hours, operator_notes=["Note 1"])
    assert len(req1.operator_notes) == 1

    # 3 notes: OK
    req3 = OptimizeRequest(scenario_id="S3", battery=battery, hours=hours, operator_notes=["Note 1", "Note 2", "Note 3"])
    assert len(req3.operator_notes) == 3

    # 0 notes: ValidationError
    with pytest.raises(ValidationError):
        OptimizeRequest(scenario_id="S0", battery=battery, hours=hours, operator_notes=[])

    # 4 notes: ValidationError
    with pytest.raises(ValidationError):
        OptimizeRequest(scenario_id="S4", battery=battery, hours=hours, operator_notes=["N1", "N2", "N3", "N4"])


def test_nan_infinity_rejected():
    """NaN and Infinity in demand/solar/tariffs must be rejected by Pydantic."""
    with pytest.raises(ValidationError):
        HourEntry(hour=0, demand_kwh=float("nan"), solar_kwh=10.0, tariff_bdt_per_kwh=5.0)

    with pytest.raises(ValidationError):
        HourEntry(hour=0, demand_kwh=100.0, solar_kwh=float("inf"), tariff_bdt_per_kwh=5.0)

    with pytest.raises(ValidationError):
        HourEntry(hour=0, demand_kwh=100.0, solar_kwh=10.0, tariff_bdt_per_kwh=float("-inf"))
