"""
Deterministic unit tests for GridWise canonical implementation.

Tests cover:
- Canonical input model validation
- Base battery reserve enforcement
- Hourly solar reduction
- Hourly minimum reserve
- No-charge window
- No-discharge window
- Max-grid window
- End-of-day neutrality
- Independent validator accepts valid result
- Independent validator rejects corrupted results

No external LLM calls are made. Directives are constructed directly.
"""
from __future__ import annotations

import math
import pytest

from app.models import (
    BatterySpec,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
    OptimizeRequest,
)
from app.optimizer import OptimizationError, run_energy_optimization
from app.validator import validate_plan, TOLERANCE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hours(
    demand: float = 100.0,
    solar: float = 0.0,
    tariff: float = 10.0,
) -> list[HourEntry]:
    return [
        HourEntry(hour=h, demand_kwh=demand, solar_kwh=solar, tariff_bdt_per_kwh=tariff)
        for h in range(24)
    ]


def _make_battery(
    capacity: float = 200.0,
    initial: float = 100.0,
    minimum: float = 20.0,
    max_charge: float = 50.0,
    max_discharge: float = 50.0,
) -> BatterySpec:
    return BatterySpec(
        capacity_kwh=capacity,
        initial_energy_kwh=initial,
        minimum_energy_kwh=minimum,
        max_charge_kwh_per_hour=max_charge,
        max_discharge_kwh_per_hour=max_discharge,
    )


def _no_directives() -> list[DirectiveInterpretation]:
    return []


def _run(
    hours: list[HourEntry] | None = None,
    battery: BatterySpec | None = None,
    directives: list[DirectiveInterpretation] | None = None,
):
    h = hours or _make_hours()
    b = battery or _make_battery()
    d = directives if directives is not None else _no_directives()
    return run_energy_optimization(hours=h, battery=b, directives=d)


def _full_validate(
    hours: list[HourEntry],
    battery: BatterySpec,
    directives: list[DirectiveInterpretation],
    plan: list[HourlyPlanEntry],
):
    grid_vals = [p.grid_kwh for p in plan]
    tariff_vals = [h.tariff_bdt_per_kwh for h in sorted(hours, key=lambda x: x.hour)]
    total_grid = sum(grid_vals)
    total_cost = sum(g * t for g, t in zip(grid_vals, tariff_vals))
    peak_grid = max(grid_vals)
    return validate_plan(
        hours=hours,
        battery=battery,
        directives=directives,
        plan=plan,
        reported_total_grid_kwh=total_grid,
        reported_total_cost_bdt=total_cost,
        reported_peak_grid_kwh=peak_grid,
    )


# ---------------------------------------------------------------------------
# 1. Canonical input model validation
# ---------------------------------------------------------------------------

class TestRequestModel:
    def test_valid_request(self):
        hours = _make_hours()
        battery = _make_battery()
        req = OptimizeRequest(
            scenario_id="TEST-1",
            operator_notes=["note one"],
            hours=hours,
            battery=battery,
        )
        assert req.scenario_id == "TEST-1"
        assert len(req.hours) == 24

    def test_hours_sorted_canonically(self):
        # Reverse order input — must be sorted internally
        hours = list(reversed(_make_hours()))
        req = OptimizeRequest(
            scenario_id="TEST-SORT",
            operator_notes=["note"],
            hours=hours,
            battery=_make_battery(),
        )
        assert [h.hour for h in req.hours] == list(range(24))

    def test_duplicate_hour_rejected(self):
        hours = _make_hours()
        hours[5] = HourEntry(hour=0, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=10)
        with pytest.raises(Exception):
            OptimizeRequest(
                scenario_id="X",
                operator_notes=["note"],
                hours=hours,
                battery=_make_battery(),
            )

    def test_missing_hour_rejected(self):
        hours = _make_hours()[:23]  # missing hour 23
        with pytest.raises(Exception):
            OptimizeRequest(
                scenario_id="X",
                operator_notes=["note"],
                hours=hours,
                battery=_make_battery(),
            )

    def test_too_few_notes_rejected(self):
        with pytest.raises(Exception):
            OptimizeRequest(
                scenario_id="X",
                operator_notes=[],
                hours=_make_hours(),
                battery=_make_battery(),
            )

    def test_too_many_notes_rejected(self):
        with pytest.raises(Exception):
            OptimizeRequest(
                scenario_id="X",
                operator_notes=["a", "b", "c", "d"],
                hours=_make_hours(),
                battery=_make_battery(),
            )

    def test_nan_demand_rejected(self):
        with pytest.raises(Exception):
            HourEntry(hour=0, demand_kwh=float("nan"), solar_kwh=0, tariff_bdt_per_kwh=10)

    def test_inf_solar_rejected(self):
        with pytest.raises(Exception):
            HourEntry(hour=0, demand_kwh=100, solar_kwh=float("inf"), tariff_bdt_per_kwh=10)

    def test_negative_demand_rejected(self):
        with pytest.raises(Exception):
            HourEntry(hour=0, demand_kwh=-1, solar_kwh=0, tariff_bdt_per_kwh=10)

    def test_battery_initial_above_capacity_rejected(self):
        with pytest.raises(Exception):
            BatterySpec(
                capacity_kwh=100,
                initial_energy_kwh=150,  # > capacity
                minimum_energy_kwh=20,
                max_charge_kwh_per_hour=50,
                max_discharge_kwh_per_hour=50,
            )

    def test_battery_minimum_above_capacity_rejected(self):
        with pytest.raises(Exception):
            BatterySpec(
                capacity_kwh=100,
                initial_energy_kwh=100,
                minimum_energy_kwh=110,  # > capacity
                max_charge_kwh_per_hour=50,
                max_discharge_kwh_per_hour=50,
            )

    def test_battery_initial_below_minimum_rejected(self):
        with pytest.raises(Exception):
            BatterySpec(
                capacity_kwh=100,
                initial_energy_kwh=10,  # < minimum
                minimum_energy_kwh=20,
                max_charge_kwh_per_hour=50,
                max_discharge_kwh_per_hour=50,
            )


# ---------------------------------------------------------------------------
# 2. Base battery reserve enforced (SOC never below minimum_energy_kwh)
# ---------------------------------------------------------------------------

class TestBaseBatteryReserve:
    def test_soc_never_below_base_minimum(self):
        battery = _make_battery(
            capacity=200, initial=100, minimum=80, max_charge=50, max_discharge=50
        )
        # High demand forces battery use, but must not go below 80
        hours = _make_hours(demand=150, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery)
        for p in plan:
            assert p.battery_energy_after_kwh >= battery.minimum_energy_kwh - TOLERANCE, (
                f"hour {p.hour}: SOC={p.battery_energy_after_kwh} < minimum={battery.minimum_energy_kwh}"
            )

    def test_end_of_day_neutrality_base(self):
        battery = _make_battery()
        plan = _run(battery=battery)
        final_soc = plan[-1].battery_energy_after_kwh
        assert abs(final_soc - battery.initial_energy_kwh) <= TOLERANCE


# ---------------------------------------------------------------------------
# 3. Hourly solar reduction
# ---------------------------------------------------------------------------

class TestSolarReduction:
    def _solar_directive(self, hours_list: list[int], factor: float) -> list[DirectiveInterpretation]:
        return [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": hours_list, "factor": factor},
                explanation="Test solar reduction",
            )
        ]

    def test_solar_reduction_increases_grid_usage(self):
        """Reducing solar should force more grid in the affected hours."""
        base_solar = 100.0
        hours = _make_hours(demand=120, solar=base_solar, tariff=10)
        battery = _make_battery(capacity=200, initial=100, minimum=20, max_charge=50, max_discharge=50)

        plan_without = _run(hours=hours, battery=battery)
        plan_with = _run(
            hours=hours,
            battery=battery,
            directives=self._solar_directive([5, 6, 7], 0.2),
        )

        # Grid in affected hours should be >= grid without reduction (might be equal in some optimizations)
        affected_grid_without = sum(plan_without[h].grid_kwh for h in [5, 6, 7])
        affected_grid_with = sum(plan_with[h].grid_kwh for h in [5, 6, 7])
        assert affected_grid_with >= affected_grid_without - TOLERANCE

    def test_solar_reduction_only_affects_listed_hours(self):
        """Hours not in the directive should have unmodified effective solar."""
        hours = _make_hours(demand=50, solar=80, tariff=10)
        battery = _make_battery()
        directives = self._solar_directive([0, 1], 0.5)
        plan = _run(hours=hours, battery=battery, directives=directives)

        # Unaffected hours: solar_used can be up to full 80 kWh
        for p in plan:
            if p.hour not in (0, 1):
                assert p.solar_used_kwh <= 80 + TOLERANCE
            else:
                # In affected hours, effective solar = 80 * 0.5 = 40
                assert p.solar_used_kwh <= 40 + TOLERANCE

    def test_full_validate_with_solar_reduction(self):
        hours = _make_hours(demand=100, solar=60, tariff=10)
        battery = _make_battery()
        directives = self._solar_directive([10, 11, 12], 0.3)
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 4. Hourly minimum reserve
# ---------------------------------------------------------------------------

class TestHourlyReserve:
    def _reserve_directive(self, hours_list: list[int], reserve: float) -> list[DirectiveInterpretation]:
        return [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="minimum_battery_reserve",
                structured_adjustment={"hours": hours_list, "minimum_energy_kwh": reserve},
                explanation="Test reserve",
            )
        ]

    def test_reserve_enforced_in_listed_hours(self):
        battery = _make_battery(
            capacity=200, initial=150, minimum=20, max_charge=50, max_discharge=50
        )
        reserve = 100.0
        directive_hours = [18, 19, 20]
        hours = _make_hours(demand=100, solar=0, tariff=10)
        directives = self._reserve_directive(directive_hours, reserve)
        plan = _run(hours=hours, battery=battery, directives=directives)

        for h in directive_hours:
            assert plan[h].battery_energy_after_kwh >= reserve - TOLERANCE, (
                f"hour {h}: SOC={plan[h].battery_energy_after_kwh} < reserve={reserve}"
            )

    def test_reserve_not_enforced_in_unlisted_hours(self):
        """Battery can drop below operator reserve in hours outside the window."""
        battery = _make_battery(
            capacity=200, initial=150, minimum=20, max_charge=50, max_discharge=50
        )
        reserve = 100.0
        directive_hours = [18, 19, 20]
        hours = _make_hours(demand=100, solar=0, tariff=10)
        directives = self._reserve_directive(directive_hours, reserve)
        plan = _run(hours=hours, battery=battery, directives=directives)

        # In non-directive hours, the base minimum (20) applies, not 100
        non_directive_socs = [
            plan[h].battery_energy_after_kwh for h in range(24) if h not in directive_hours
        ]
        # At least some hours should be able to go below 100
        assert any(soc < reserve - TOLERANCE for soc in non_directive_socs), (
            "Reserve constraint appears to be applied globally rather than hourly"
        )

    def test_full_validate_with_reserve(self):
        battery = _make_battery(
            capacity=200, initial=150, minimum=20, max_charge=50, max_discharge=50
        )
        directives = self._reserve_directive([18, 19, 20], 100.0)
        hours = _make_hours(demand=80, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 5. No-charge window
# ---------------------------------------------------------------------------

class TestNoChargeWindow:
    def _no_charge_directive(self, hours_list: list[int]) -> list[DirectiveInterpretation]:
        return [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": hours_list},
                explanation="Test no-charge",
            )
        ]

    def test_no_charge_in_window(self):
        restricted = [2, 3, 4]
        # Use cheap tariff in restricted hours and expensive outside to incentivize charging there
        hours = []
        for h in range(24):
            tariff = 5.0 if h in restricted else 20.0
            hours.append(HourEntry(hour=h, demand_kwh=80, solar_kwh=0, tariff_bdt_per_kwh=tariff))
        battery = _make_battery(capacity=300, initial=150, minimum=20, max_charge=80, max_discharge=80)
        directives = self._no_charge_directive(restricted)
        plan = _run(hours=hours, battery=battery, directives=directives)
        for h in restricted:
            assert plan[h].battery_action != "charge", (
                f"hour {h}: battery charged despite no_charge_window"
            )

    def test_full_validate_no_charge(self):
        hours = _make_hours(demand=80, solar=0, tariff=10)
        battery = _make_battery()
        directives = self._no_charge_directive([6, 7, 8])
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 6. No-discharge window
# ---------------------------------------------------------------------------

class TestNoDischargeWindow:
    def _no_discharge_directive(self, hours_list: list[int]) -> list[DirectiveInterpretation]:
        return [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="no_discharge_window",
                structured_adjustment={"hours": hours_list},
                explanation="Test no-discharge",
            )
        ]

    def test_no_discharge_in_window(self):
        restricted = [18, 19]
        # High tariff during restricted hours — LP might want to discharge but cannot
        hours = []
        for h in range(24):
            tariff = 30.0 if h in restricted else 5.0
            hours.append(HourEntry(hour=h, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=tariff))
        battery = _make_battery(capacity=300, initial=200, minimum=20, max_charge=80, max_discharge=80)
        directives = self._no_discharge_directive(restricted)
        plan = _run(hours=hours, battery=battery, directives=directives)
        for h in restricted:
            assert plan[h].battery_action != "discharge", (
                f"hour {h}: battery discharged despite no_discharge_window"
            )

    def test_full_validate_no_discharge(self):
        hours = _make_hours(demand=100, solar=0, tariff=10)
        battery = _make_battery()
        directives = self._no_discharge_directive([17, 18])
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 7. Max-grid window
# ---------------------------------------------------------------------------

class TestMaxGridWindow:
    def _max_grid_directive(self, hours_list: list[int], max_grid: float) -> list[DirectiveInterpretation]:
        return [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="max_grid_window",
                structured_adjustment={"hours": hours_list, "max_grid_kwh": max_grid},
                explanation="Test max-grid",
            )
        ]

    def test_grid_capped_in_window(self):
        cap = 60.0
        restricted = [18, 19, 20]
        hours = _make_hours(demand=120, solar=0, tariff=10)
        battery = _make_battery(capacity=400, initial=200, minimum=20, max_charge=100, max_discharge=100)
        directives = self._max_grid_directive(restricted, cap)
        plan = _run(hours=hours, battery=battery, directives=directives)
        for h in restricted:
            assert plan[h].grid_kwh <= cap + TOLERANCE, (
                f"hour {h}: grid_kwh={plan[h].grid_kwh} > cap={cap}"
            )

    def test_full_validate_max_grid(self):
        hours = _make_hours(demand=100, solar=0, tariff=10)
        battery = _make_battery(capacity=400, initial=200, minimum=20, max_charge=100, max_discharge=100)
        directives = self._max_grid_directive([18, 19, 20], 80.0)
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 8. End-of-day neutrality
# ---------------------------------------------------------------------------

class TestEndOfDayNeutrality:
    def test_soc_returns_to_initial(self):
        battery = _make_battery(capacity=300, initial=150, minimum=30, max_charge=80, max_discharge=80)
        # Mix of cheap and expensive hours to incentivize battery shifting
        hours = []
        for h in range(24):
            tariff = 5.0 if h < 8 else (25.0 if 17 <= h <= 21 else 12.0)
            hours.append(HourEntry(hour=h, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=tariff))
        plan = _run(hours=hours, battery=battery)
        final = plan[-1].battery_energy_after_kwh
        assert abs(final - battery.initial_energy_kwh) <= TOLERANCE, (
            f"End-of-day SOC={final} != initial={battery.initial_energy_kwh}"
        )

    def test_neutrality_with_solar_and_directives(self):
        battery = _make_battery()
        hours = []
        for h in range(24):
            solar = 80.0 if 8 <= h <= 16 else 0.0
            tariff = 5.0 if h < 8 else 15.0
            hours.append(HourEntry(hour=h, demand_kwh=100, solar_kwh=solar, tariff_bdt_per_kwh=tariff))
        directives = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": [18, 19]},
                explanation="Test",
            )
        ]
        plan = _run(hours=hours, battery=battery, directives=directives)
        final = plan[-1].battery_energy_after_kwh
        assert abs(final - battery.initial_energy_kwh) <= TOLERANCE


# ---------------------------------------------------------------------------
# 9. Independent validator accepts a valid result
# ---------------------------------------------------------------------------

class TestValidatorAcceptsValid:
    def test_accepts_clean_output(self):
        battery = _make_battery()
        hours = _make_hours(demand=80, solar=30, tariff=10)
        plan = _run(hours=hours, battery=battery)
        vr = _full_validate(hours, battery, [], plan)
        assert vr.valid, f"Unexpected errors: {vr.errors}"

    def test_accepts_with_all_directive_types(self):
        battery = _make_battery(capacity=400, initial=200, minimum=30, max_charge=100, max_discharge=100)
        hours = []
        for h in range(24):
            solar = 60.0 if 8 <= h <= 16 else 0.0
            tariff = 5.0 if h < 8 else (25.0 if 17 <= h <= 21 else 12.0)
            hours.append(HourEntry(hour=h, demand_kwh=100, solar_kwh=solar, tariff_bdt_per_kwh=tariff))

        directives = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": [10, 11], "factor": 0.5},
                explanation="Solar reduction",
            ),
            DirectiveInterpretation(
                note_index=1,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": [14, 15]},
                explanation="No charge",
            ),
            DirectiveInterpretation(
                note_index=2,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Distractor",
            ),
        ]
        plan = _run(hours=hours, battery=battery, directives=directives)
        vr = _full_validate(hours, battery, directives, plan)
        assert vr.valid, f"Validation errors: {vr.errors}"


# ---------------------------------------------------------------------------
# 10. Independent validator rejects corrupted results
# ---------------------------------------------------------------------------

class TestValidatorRejectsCorrupted:
    def _base_plan(self):
        battery = _make_battery()
        hours = _make_hours(demand=80, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery)
        return hours, battery, plan

    def test_rejects_wrong_hour_count(self):
        hours, battery, plan = self._base_plan()
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=plan[:23],  # only 23 entries
            reported_total_grid_kwh=0,
            reported_total_cost_bdt=0,
            reported_peak_grid_kwh=0,
        )
        assert not vr.valid
        assert any("24" in e for e in vr.errors)

    def test_rejects_energy_balance_violation(self):
        hours, battery, plan = self._base_plan()
        corrupted = list(plan)
        p = corrupted[5]
        # Artificially inflate grid_kwh to break energy balance
        corrupted[5] = HourlyPlanEntry(
            hour=p.hour,
            grid_kwh=p.grid_kwh + 50,  # wrong
            solar_used_kwh=p.solar_used_kwh,
            battery_action=p.battery_action,
            battery_kwh=p.battery_kwh,
            battery_energy_after_kwh=p.battery_energy_after_kwh,
        )
        grid_vals = [e.grid_kwh for e in corrupted]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=corrupted,
            reported_total_grid_kwh=sum(grid_vals),
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("energy balance" in e.lower() for e in vr.errors)

    def test_rejects_solar_overuse(self):
        battery = _make_battery()
        hours = _make_hours(demand=100, solar=40, tariff=10)
        plan = _run(hours=hours, battery=battery)
        corrupted = list(plan)
        p = corrupted[0]
        # Force solar_used > effective_solar
        corrupted[0] = HourlyPlanEntry(
            hour=p.hour,
            grid_kwh=p.grid_kwh,
            solar_used_kwh=99.0,  # > 40 kWh effective solar
            battery_action=p.battery_action,
            battery_kwh=p.battery_kwh,
            battery_energy_after_kwh=p.battery_energy_after_kwh,
        )
        grid_vals = [e.grid_kwh for e in corrupted]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=corrupted,
            reported_total_grid_kwh=sum(grid_vals),
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("solar" in e.lower() for e in vr.errors)

    def test_rejects_soc_below_minimum(self):
        # To properly violate the minimum reserve, we need a discharge that
        # actually drives SOC below the base minimum. Use a large battery
        # starting at minimum+1 and discharge more than 1 kWh.
        battery = BatterySpec(
            capacity_kwh=200,
            initial_energy_kwh=51,   # just above minimum
            minimum_energy_kwh=50,
            max_charge_kwh_per_hour=50,
            max_discharge_kwh_per_hour=50,
        )
        hours = _make_hours(demand=80, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery)
        # Now manually build a corrupted plan that has a discharge at hour 0
        # that drives SOC to 40 (below minimum=50)
        corrupted = list(plan)
        p0 = corrupted[0]
        # Replace hour 0: discharge 11 kWh → SOC goes to 51-11=40 < 50
        corrupted[0] = HourlyPlanEntry(
            hour=0,
            grid_kwh=max(0, p0.grid_kwh - 11),
            solar_used_kwh=p0.solar_used_kwh,
            battery_action="discharge",
            battery_kwh=11.0,
            battery_energy_after_kwh=40.0,
        )
        grid_vals = [e.grid_kwh for e in corrupted]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=corrupted,
            reported_total_grid_kwh=sum(grid_vals),
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("minimum" in e.lower() for e in vr.errors)

    def test_rejects_end_of_day_neutrality_violation(self):
        # Validator recomputes SOC from charge/discharge amounts, so we must
        # corrupt the final action to actually leave SOC != initial.
        battery = _make_battery(
            capacity=300, initial=100, minimum=20, max_charge=80, max_discharge=80
        )
        hours = _make_hours(demand=80, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery)
        corrupted = list(plan)
        p = corrupted[23]
        # At hour 23: add an extra 30 kWh charge → SOC ends at initial+30
        corrupted[23] = HourlyPlanEntry(
            hour=23,
            grid_kwh=p.grid_kwh + 30,   # pay for extra charge
            solar_used_kwh=p.solar_used_kwh,
            battery_action="charge",
            battery_kwh=p.battery_kwh + 30,  # charge 30 more kWh
            battery_energy_after_kwh=battery.initial_energy_kwh + 30,
        )
        grid_vals = [e.grid_kwh for e in corrupted]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=corrupted,
            reported_total_grid_kwh=sum(grid_vals),
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("neutrality" in e.lower() or "initial" in e.lower() for e in vr.errors)

    def test_rejects_wrong_total_grid(self):
        hours, battery, plan = self._base_plan()
        grid_vals = [p.grid_kwh for p in plan]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=[],
            plan=plan,
            reported_total_grid_kwh=999999.0,  # deliberately wrong
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("total_grid_kwh" in e for e in vr.errors)

    def test_rejects_no_charge_window_violation(self):
        battery = _make_battery(capacity=300, initial=200, minimum=20, max_charge=100, max_discharge=100)
        hours = _make_hours(demand=80, solar=0, tariff=10)
        plan = _run(hours=hours, battery=battery)
        restricted_hour = 5

        # Manually corrupt plan to charge in a restricted hour
        corrupted = list(plan)
        p = corrupted[restricted_hour]
        corrupted[restricted_hour] = HourlyPlanEntry(
            hour=restricted_hour,
            grid_kwh=p.grid_kwh + 30,
            solar_used_kwh=p.solar_used_kwh,
            battery_action="charge",
            battery_kwh=30.0,
            battery_energy_after_kwh=p.battery_energy_after_kwh + 30,
        )
        directives = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": [restricted_hour]},
                explanation="Restricted",
            )
        ]
        grid_vals = [e.grid_kwh for e in corrupted]
        tariff_vals = [h.tariff_bdt_per_kwh for h in hours]
        vr = validate_plan(
            hours=hours,
            battery=battery,
            directives=directives,
            plan=corrupted,
            reported_total_grid_kwh=sum(grid_vals),
            reported_total_cost_bdt=sum(g * t for g, t in zip(grid_vals, tariff_vals)),
            reported_peak_grid_kwh=max(grid_vals),
        )
        assert not vr.valid
        assert any("no_charge" in e.lower() for e in vr.errors)
