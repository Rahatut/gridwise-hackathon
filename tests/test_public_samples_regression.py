"""
Regression tests against the official 10 public sample cases from
BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json.

Verifies:
1. Canonical request parsing
2. Optimizer solver correctness and exact cost tolerance (<= 0.01 BDT / kWh)
3. Full 19-check independent plan validation
4. Directive interpretation semantic equivalence
5. Full API end-to-end pipeline execution with mocked provider
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.llm import (
    InterpretationsResponse,
    RawDirectiveInterpretation,
    StructuredAdjustment,
    _validate_and_canonicalize,
)
from app.models import (
    DirectiveInterpretation,
    HourlyPlanEntry,
    OptimizeRequest,
    OptimizeResponse,
)
from app.optimizer import run_energy_optimization
from app.validator import validate_plan


# ---------------------------------------------------------------------------
# Load official public cases
# ---------------------------------------------------------------------------

SAMPLES_PATH = Path(__file__).parent / "data" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def load_cases() -> List[Dict[str, Any]]:
    if not SAMPLES_PATH.exists():
        pytest.skip(f"Public sample file missing at {SAMPLES_PATH}")
    with open(SAMPLES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


ALL_CASES = load_cases()


def id_fn(val: Dict[str, Any]) -> str:
    return val.get("id", "CASE")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compare_adjustments(adj1: Any, adj2: Any, tol: float = 0.001) -> bool:
    """Compare two structured adjustments with float tolerance."""
    if adj1 is None and adj2 is None:
        return True
    if adj1 is None or adj2 is None:
        return False
    if set(adj1.keys()) != set(adj2.keys()):
        return False
    for k in adj1:
        v1, v2 = adj1[k], adj2[k]
        if k == "hours":
            if list(v1) != list(v2):
                return False
        elif isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            if abs(v1 - v2) > tol:
                return False
        elif v1 != v2:
            return False
    return True


# ---------------------------------------------------------------------------
# 1. Deterministic Optimizer Regression on Ground-Truth Directives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=id_fn)
def test_optimizer_regression_against_official_reference(case: Dict[str, Any]):
    """
    For all 10 official public cases:
    - parse official input through canonical request model
    - use official ground truth directive_interpretation
    - solve via optimizer
    - validate via independent validator
    - verify cost and grid totals match official reference within 0.01 tolerance
    """
    case_id = case["id"]
    inp = case["input"]
    exp = case["expected_output"]

    # 1. Parse input
    req = OptimizeRequest.model_validate(inp)
    assert req.scenario_id == case_id
    assert len(req.hours) == 24

    # 2. Ground-truth directives
    directives = [
        DirectiveInterpretation.model_validate(d)
        for d in exp["directive_interpretation"]
    ]

    # 3. Optimize
    hourly_plan: List[HourlyPlanEntry] = run_energy_optimization(
        hours=req.hours,
        battery=req.battery,
        directives=directives,
    )
    assert len(hourly_plan) == 24

    # 4. Compute totals
    grid_vals = [p.grid_kwh for p in hourly_plan]
    tariffs = [h.tariff_bdt_per_kwh for h in req.hours]

    total_grid_kwh = round(sum(grid_vals), 6)
    total_cost_bdt = round(sum(g * t for g, t in zip(grid_vals, tariffs)), 6)
    peak_grid_kwh = round(max(grid_vals), 6)

    # 5. Independent validation
    vr = validate_plan(
        hours=req.hours,
        battery=req.battery,
        directives=directives,
        plan=hourly_plan,
        reported_total_grid_kwh=total_grid_kwh,
        reported_total_cost_bdt=total_cost_bdt,
        reported_peak_grid_kwh=peak_grid_kwh,
    )
    assert vr.valid, f"Validation failed for {case_id}: {vr.errors}"

    # 6. Official tolerance comparison (<= 0.01)
    ref_cost = exp["total_cost_bdt"]
    ref_grid = exp["total_grid_kwh"]
    ref_peak = exp["peak_grid_kwh"]

    cost_diff = abs(total_cost_bdt - ref_cost)
    grid_diff = abs(total_grid_kwh - ref_grid)
    peak_diff = abs(peak_grid_kwh - ref_peak)

    assert cost_diff <= 0.01, f"{case_id} cost mismatch: computed={total_cost_bdt}, ref={ref_cost} (diff={cost_diff})"
    assert grid_diff <= 0.01, f"{case_id} grid mismatch: computed={total_grid_kwh}, ref={ref_grid} (diff={grid_diff})"
    assert peak_grid_kwh == round(max(grid_vals), 6)


# ---------------------------------------------------------------------------
# 2. Semantic Interpretation Equivalence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=id_fn)
def test_interpretation_schema_and_semantics(case: Dict[str, Any]):
    """
    Test that the official expected directive interpretations satisfy the
    guardrail validation and canonical semantics.
    """
    case_id = case["id"]
    inp = case["input"]
    exp = case["expected_output"]

    req = OptimizeRequest.model_validate(inp)
    exp_dirs = exp["directive_interpretation"]

    raw_items = []
    for d in exp_dirs:
        adj = None
        if d.get("structured_adjustment") is not None:
            adj = StructuredAdjustment.model_validate(d["structured_adjustment"])
        raw_items.append(
            RawDirectiveInterpretation(
                note_index=d["note_index"],
                applies=d["applies"],
                directive_type=d["directive_type"],
                structured_adjustment=adj,
                explanation=d.get("explanation", "Official test directive"),
            )
        )

    valid, errors, canonical = _validate_and_canonicalize(
        raw_items, len(req.operator_notes), req.battery
    )
    assert valid, f"{case_id} failed canonical guardrails: {errors}"
    assert len(canonical) == len(exp_dirs)

    for i, exp_d in enumerate(exp_dirs):
        c = canonical[i]
        assert c.note_index == exp_d["note_index"]
        assert c.applies == exp_d["applies"]
        assert c.directive_type == exp_d["directive_type"]
        assert compare_adjustments(c.structured_adjustment, exp_d.get("structured_adjustment"))


# ---------------------------------------------------------------------------
# 3. End-to-End API Integration via TestClient
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=id_fn)
def test_api_optimize_energy_public_samples(case: Dict[str, Any]):
    """
    Simulate full POST /optimize-energy for each sample case with the LLM
    returning the canonical structured interpretations.
    """
    client = TestClient(app)
    case_id = case["id"]
    inp = case["input"]
    exp = case["expected_output"]

    raw_interpretations = []
    for d in exp["directive_interpretation"]:
        adj = None
        if d.get("structured_adjustment") is not None:
            adj = StructuredAdjustment.model_validate(d["structured_adjustment"])
        raw_interpretations.append(
            RawDirectiveInterpretation(
                note_index=d["note_index"],
                applies=d["applies"],
                directive_type=d["directive_type"],
                structured_adjustment=adj,
                explanation=d.get("explanation", "Expected directive"),
            )
        )

    mock_resp = MagicMock()
    mock_resp.parsed = InterpretationsResponse(interpretations=raw_interpretations)

    with patch("app.llm.generate_content_with_failover", return_value=mock_resp):
        resp = client.post("/optimize-energy", json=inp)

    assert resp.status_code == 200, f"{case_id} failed with {resp.status_code}: {resp.text}"
    out = resp.json()

    # Verify Pydantic response parsing
    res_obj = OptimizeResponse.model_validate(out)
    assert res_obj.scenario_id == case_id
    assert len(res_obj.hourly_plan) == 24
    assert len(res_obj.directive_interpretation) == len(exp["directive_interpretation"])

    assert abs(res_obj.total_cost_bdt - exp["total_cost_bdt"]) <= 0.01
    assert abs(res_obj.total_grid_kwh - exp["total_grid_kwh"]) <= 0.01
    assert res_obj.peak_grid_kwh == round(max(p.grid_kwh for p in res_obj.hourly_plan), 6)
