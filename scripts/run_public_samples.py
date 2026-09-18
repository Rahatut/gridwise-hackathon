#!/usr/bin/env python3
"""
Official Public Sample Cases Runner for GridWise Energy Optimizer.

Usage:
    python scripts/run_public_samples.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Add project root to path so we can import validator models
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models import BatterySpec, HourEntry, HourlyPlanEntry, OptimizeResponse
from app.validator import validate_plan


def find_samples_file(custom_path: Optional[str] = None) -> Path:
    candidates = []
    if custom_path:
        candidates.append(Path(custom_path))
    candidates.extend([
        PROJECT_ROOT / "docs" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
        PROJECT_ROOT / "tests" / "data" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
        PROJECT_ROOT.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
    ])
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    raise FileNotFoundError(f"Could not locate BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json in: {candidates}")


def compare_adjustments(adj1: Any, adj2: Any, tol: float = 0.01) -> bool:
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


def evaluate_interpretations(actual_dirs: List[Any], expected_dirs: List[Any]) -> Tuple[bool, str]:
    if len(actual_dirs) != len(expected_dirs):
        return False, f"Count mismatch: got {len(actual_dirs)}, expected {len(expected_dirs)}"
    for idx, exp in enumerate(expected_dirs):
        act = actual_dirs[idx]
        if act.get("note_index") != exp.get("note_index"):
            return False, f"Note {idx}: index mismatch"
        if act.get("applies") != exp.get("applies"):
            return False, f"Note {idx}: applies mismatch (got {act.get('applies')}, exp {exp.get('applies')})"
        if act.get("directive_type") != exp.get("directive_type"):
            return False, f"Note {idx}: type mismatch (got {act.get('directive_type')}, exp {exp.get('directive_type')})"
        if not compare_adjustments(act.get("structured_adjustment"), exp.get("structured_adjustment")):
            return False, f"Note {idx}: adjustment mismatch"
    return True, "Match"


def main():
    parser = argparse.ArgumentParser(description="Run official public sample cases against GridWise server.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL of running GridWise service")
    parser.add_argument("--samples-file", default=None, help="Path to sample cases JSON")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds")
    parser.add_argument("--offline", action="store_true", help="Run in offline verification mode using internal test client (no live server or API key required)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    samples_path = find_samples_file(args.samples_file)

    print("=" * 80)
    print(f"GridWise Official Public Sample Cases Verification")
    if args.offline:
        print(f"Mode:          OFFLINE TESTCLIENT VERIFICATION")
    else:
        print(f"Target URL:    {base_url}")
    print(f"Sample File:   {samples_path}")
    print("=" * 80)

    if args.offline:
        from fastapi.testclient import TestClient
        from unittest.mock import MagicMock, patch
        from app.main import app
        from app.llm import InterpretationsResponse, RawDirectiveInterpretation, StructuredAdjustment
        client = TestClient(app)
        print("[INFO] Running in offline mode against FastAPI application...")
    else:
        # 1. Health check
        client = httpx.Client(timeout=args.timeout)
        try:
            health_resp = client.get(f"{base_url}/health")
            if health_resp.status_code != 200:
                print(f"[ERROR] /health check returned HTTP {health_resp.status_code}: {health_resp.text}")
                sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] Unable to reach GridWise service at {base_url}/health: {exc}")
            print("Please start the server first, e.g.: uvicorn app.main:app --port 8000")
            print("Or use --offline to run without a running server: python scripts/run_public_samples.py --offline")
            sys.exit(1)
        print("[INFO] Server is healthy. Running 10 public test cases...\n")

    with open(samples_path, "r", encoding="utf-8") as f:
        cases_data = json.load(f)["cases"]

    schema_passes = 0
    interp_passes = 0
    valid_passes = 0
    cost_matches = 0
    durations: List[float] = []

    print(f"{'Case ID':<11} | {'Status':<6} | {'Cost (BDT)':<18} | {'Grid (kWh)':<18} | {'Directives':<10} | {'Plan':<7} | {'Duration'}")
    print("-" * 90)

    for case in cases_data:
        cid = case["id"]
        req_body = case["input"]
        exp = case["expected_output"]

        t0 = time.perf_counter()
        try:
            if args.offline:
                raw_interpretations = []
                for d in exp.get("directive_interpretation", []):
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
                    resp = client.post("/optimize-energy", json=req_body)
            else:
                resp = client.post(f"{base_url}/optimize-energy", json=req_body)
            duration_ms = (time.perf_counter() - t0) * 1000.0
            durations.append(duration_ms)
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            print(f"{cid:<11} | FAIL   | Connection error: {exc}")
            continue

        if resp.status_code != 200:
            print(f"{cid:<11} | FAIL   | HTTP {resp.status_code}: {resp.text[:60]}")
            continue

        # 1. Schema check
        try:
            out_data = resp.json()
            resp_obj = OptimizeResponse.model_validate(out_data)
            schema_ok = True
            schema_passes += 1
        except Exception as err:
            schema_ok = False
            print(f"{cid:<11} | FAIL   | Schema validation error: {err}")
            continue

        # 2. Directive check
        interp_ok, interp_msg = evaluate_interpretations(
            out_data.get("directive_interpretation", []),
            exp.get("directive_interpretation", []),
        )
        if interp_ok:
            interp_passes += 1

        # 3. Independent plan validation
        try:
            hours = [HourEntry.model_validate(h) for h in req_body["hours"]]
            battery = BatterySpec.model_validate(req_body["battery"])
            directives = resp_obj.directive_interpretation
            plan = resp_obj.hourly_plan

            vr = validate_plan(
                hours=hours,
                battery=battery,
                directives=directives,
                plan=plan,
                reported_total_grid_kwh=resp_obj.total_grid_kwh,
                reported_total_cost_bdt=resp_obj.total_cost_bdt,
                reported_peak_grid_kwh=resp_obj.peak_grid_kwh,
            )
            plan_valid = vr.valid
            if plan_valid:
                valid_passes += 1
        except Exception:
            plan_valid = False

        # 4. Cost comparison
        calc_cost = resp_obj.total_cost_bdt
        exp_cost = exp["total_cost_bdt"]
        cost_diff = abs(calc_cost - exp_cost)
        if cost_diff <= 0.01:
            cost_matches += 1

        calc_grid = resp_obj.total_grid_kwh
        exp_grid = exp["total_grid_kwh"]

        overall_status = "PASS" if (schema_ok and plan_valid and cost_diff <= 0.01) else "FAIL"
        cost_str = f"{calc_cost:.2f} (ref {exp_cost:.2f})"
        grid_str = f"{calc_grid:.2f} (ref {exp_grid:.2f})"
        interp_str = "OK" if interp_ok else "Diff"
        plan_str = "Valid" if plan_valid else "Invalid"

        print(f"{cid:<11} | {overall_status:<6} | {cost_str:<18} | {grid_str:<18} | {interp_str:<10} | {plan_str:<7} | {duration_ms:.1f}ms")

    print("=" * 90)
    total_cases = len(cases_data)
    durations.sort()
    avg_lat = sum(durations) / len(durations) if durations else 0.0
    p95_index = int(0.95 * len(durations)) if durations else 0
    p95_lat = durations[min(p95_index, len(durations) - 1)] if durations else 0.0

    print("SUMMARY RESULTS:")
    print(f"  Schema Valid:               {schema_passes}/{total_cases}")
    print(f"  Directive Interpretations:  {interp_passes}/{total_cases}")
    print(f"  Independent Plan Validity:  {valid_passes}/{total_cases}")
    print(f"  Optimal Cost Reference:     {cost_matches}/{total_cases}")
    print(f"  Latency: Avg = {avg_lat:.1f}ms | P95 = {p95_lat:.1f}ms | Min = {durations[0]:.1f}ms | Max = {durations[-1]:.1f}ms")
    print("=" * 90)

    if schema_passes == total_cases and valid_passes == total_cases and cost_matches == total_cases:
        print("[SUCCESS] All official public sample regression benchmarks passed perfectly.")
        sys.exit(0)
    else:
        print("[WARNING] Some tests did not meet 100% criteria.")
        sys.exit(1)


if __name__ == "__main__":
    main()
