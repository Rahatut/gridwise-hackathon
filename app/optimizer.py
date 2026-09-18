from typing import List, Dict, Any
import numpy as np
from scipy.optimize import linprog


EPS = 1e-6


def run_energy_optimization(scenario: Dict[str, Any], directives: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Solve 24-hour cost-minimization battery scheduling via linear programming.

    Decision variables per hour h (0..23):
        grid[h], solar_used[h], battery_charge[h], battery_discharge[h], soc_after[h]

    Objective: minimize sum(grid[h] * tariff[h])
    """
    tariff = np.array(scenario["tariff_bdt_per_kwh"], dtype=float)
    solar = np.array(scenario["effective_solar_kwh"], dtype=float)
    demand = np.array(scenario["demand_kwh"], dtype=float)
    battery_capacity = float(scenario["battery_capacity"])
    max_charge = float(scenario["max_charge_kwh_per_hour"])
    max_discharge = float(scenario["max_discharge_kwh_per_hour"])
    initial_energy = float(scenario["initial_energy_kwh"])

    # --- Apply directives to build normalized 24h constraint arrays ---
    solar_factor = np.ones(24)
    reserve_kwh = 0.0
    no_charge = np.zeros(24, dtype=bool)
    no_discharge = np.zeros(24, dtype=bool)
    max_grid_limit = np.full(24, np.inf)

    for d in directives:
        if not d.get("applies"):
            continue
        adj = d.get("structured_adjustment") or {}
        t = d.get("type")
        if t == "solar_reduction":
            solar_factor = solar_factor * float(adj["factor"])
        elif t == "minimum_battery_reserve":
            reserve_kwh = max(reserve_kwh, float(adj["reserve_kwh"]))
        elif t == "no_charge_window":
            for h in adj["hours"]:
                no_charge[h] = True
        elif t == "no_discharge_window":
            for h in adj["hours"]:
                no_discharge[h] = True
        elif t == "max_grid_window":
            for h in adj["hours"]:
                max_grid_limit[h] = min(max_grid_limit[h], float(adj["max_grid_kwh"]))

    effective_solar = solar * solar_factor
    min_reserve = max(0.0, reserve_kwh)

    # --- LP formulation ---
    # Variables: [grid(24), solar_used(24), charge(24), discharge(24), soc_after(24)]
    n = 24
    n_vars = 4 * n + n  # 120

    # Objective: minimize sum(grid * tariff)
    c = np.zeros(n_vars)
    c[:n] = tariff

    A_eq = []
    b_eq = []

    # Energy balance: grid + solar_used + discharge - charge = demand
    for h in range(n):
        row = np.zeros(n_vars)
        row[h] = 1.0          # grid
        row[n + h] = 1.0      # solar_used
        row[3 * n + h] = 1.0  # discharge
        row[2 * n + h] = -1.0 # charge
        A_eq.append(row)
        b_eq.append(demand[h])

    # Battery state transition: soc_after[h] - soc_after[h-1] - charge[h] + discharge[h] = 0
    # with soc_after[-1] = initial_energy
    for h in range(n):
        row = np.zeros(n_vars)
        row[4 * n + h] = 1.0   # soc_after[h]
        if h > 0:
            row[4 * n + h - 1] = -1.0  # -soc_after[h-1]
        row[2 * n + h] = -1.0  # -charge[h]
        row[3 * n + h] = 1.0   # +discharge[h]
        A_eq.append(row)
        b_eq.append(initial_energy if h == 0 else 0.0)

    # End-of-day neutrality: soc_after[23] == initial_energy
    row = np.zeros(n_vars)
    row[4 * n + 23] = 1.0
    A_eq.append(row)
    b_eq.append(initial_energy)

    # Bounds
    bounds = []
    # grid >= 0, <= max_grid_limit
    for h in range(n):
        bounds.append((0, max_grid_limit[h] if np.isfinite(max_grid_limit[h]) else None))
    # solar_used in [0, effective_solar[h]]
    for h in range(n):
        bounds.append((0, effective_solar[h]))
    # charge
    for h in range(n):
        if no_charge[h]:
            bounds.append((0, 0))
        else:
            bounds.append((0, max_charge))
    # discharge
    for h in range(n):
        if no_discharge[h]:
            bounds.append((0, 0))
        else:
            bounds.append((0, max_discharge))
    # soc_after in [min_reserve, capacity]
    for h in range(n):
        bounds.append((min_reserve, battery_capacity))

    result = linprog(
        c,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
        options={"time_limit": 10},
    )

    if not result.success:
        # Fallback: naive solution that respects neutrality trivially
        grid = np.maximum(demand - effective_solar, 0)
        solar_used = np.minimum(demand, effective_solar)
        charge = np.zeros(n)
        discharge = np.zeros(n)
    else:
        grid = result.x[:n]
        solar_used = result.x[n:2 * n]
        charge = result.x[2 * n:3 * n]
        discharge = result.x[3 * n:4 * n]

    # --- Post-solve audit ---
    def clean(val: float) -> float:
        v = round(float(val), 6)
        return 0.0 if abs(v) < 1e-6 else v

    schedule = []
    soc_prev = initial_energy
    for h in range(n):
        soc_after = soc_prev + charge[h] - discharge[h]
        # Clamp for numerical safety (should already be within bounds)
        soc_after = max(min_reserve, min(battery_capacity, soc_after))
        schedule.append({
            "hour": int(h),
            "grid_kwh": clean(grid[h]),
            "solar_used_kwh": clean(solar_used[h]),
            "solar_curtailed_kwh": clean(max(0.0, effective_solar[h] - solar_used[h])),
            "battery_charge_kwh": clean(charge[h]),
            "battery_discharge_kwh": clean(discharge[h]),
            "battery_soc_kwh": clean(soc_after),
        })
        soc_prev = soc_after

    total_grid = clean(np.sum(grid))
    total_cost = clean(np.sum(grid * tariff))
    peak_grid = clean(np.max(grid))

    return {
        "total_grid_kwh": total_grid,
        "total_cost_bdt": total_cost,
        "peak_grid_kwh": peak_grid,
        "schedule": schedule,
    }