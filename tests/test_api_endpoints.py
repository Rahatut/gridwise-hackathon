"""
API endpoint integration tests for GridWise FastAPI application.

Endpoints tested:
- GET  /health          -> 200 OK {"status": "ok"}
- POST /optimize-energy -> 200 OK for valid requests
- POST /optimize-energy -> 400 Bad Request for malformed JSON
- POST /optimize-energy -> 422 Unprocessable Entity for schema violations
- POST /optimize-energy -> 500 Internal Server Error for unhandled exceptions (sanitized)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.llm import InterpretationsResponse, RawDirectiveInterpretation
from app.gemini_provider import LLMProviderError


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def valid_payload() -> dict:
    return {
        "scenario_id": "TEST-ENDPOINT-01",
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 20.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
        "hours": [
            {
                "hour": h,
                "demand_kwh": 100.0,
                "solar_kwh": 25.0 if 8 <= h <= 16 else 0.0,
                "tariff_bdt_per_kwh": 8.0 if 17 <= h <= 22 else 4.0,
            }
            for h in range(24)
        ],
        "operator_notes": [
            "Routine maintenance notice for building A at 10 AM.",
        ],
    }


# ---------------------------------------------------------------------------
# Health Endpoint Tests
# ---------------------------------------------------------------------------

def test_health_check(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /optimize-energy Status Code Tests
# ---------------------------------------------------------------------------

def test_malformed_json_returns_400(client: TestClient):
    """Malformed unparseable JSON must return HTTP 400 per Problem Statement Section 06."""
    resp = client.post(
        "/optimize-energy",
        content="{malformed: json, missing quotes",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Malformed JSON" in resp.json().get("detail", "")


def test_schema_missing_fields_returns_422(client: TestClient):
    """Structurally missing required fields must return HTTP 422."""
    bad_payload = {
        "scenario_id": "MISSING-FIELDS",
        # missing battery, hours, operator_notes
    }
    resp = client.post("/optimize-energy", json=bad_payload)
    assert resp.status_code == 422


def test_invalid_hours_count_returns_422(client: TestClient, valid_payload: dict):
    """Payloads with != 24 hours must be rejected with HTTP 422."""
    valid_payload["hours"] = valid_payload["hours"][:20]  # Only 20 hours
    resp = client.post("/optimize-energy", json=valid_payload)
    assert resp.status_code == 422


def test_negative_demand_returns_422(client: TestClient, valid_payload: dict):
    """Negative demand values must be rejected with HTTP 422."""
    valid_payload["hours"][0]["demand_kwh"] = -15.0
    resp = client.post("/optimize-energy", json=valid_payload)
    assert resp.status_code == 422


def test_successful_optimization_contract(client: TestClient, valid_payload: dict):
    """Valid request must return HTTP 200 with complete exact schema fields."""
    mock_resp = MagicMock()
    mock_resp.parsed = InterpretationsResponse(
        interpretations=[
            RawDirectiveInterpretation(
                note_index=0,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Routine notice; no schedule impact.",
            )
        ]
    )

    with patch("app.llm.generate_content_with_failover", return_value=mock_resp):
        resp = client.post("/optimize-energy", json=valid_payload)

    assert resp.status_code == 200
    data = resp.json()

    # 1. Exact top-level fields
    assert data["scenario_id"] == valid_payload["scenario_id"]
    assert "directive_interpretation" in data
    assert "hourly_plan" in data
    assert "total_grid_kwh" in data
    assert "total_cost_bdt" in data
    assert "peak_grid_kwh" in data
    assert "plan_summary" in data

    # 2. Hourly plan structure
    plan = data["hourly_plan"]
    assert len(plan) == 24
    for idx, entry in enumerate(plan):
        assert entry["hour"] == idx
        assert entry["battery_action"] in ("charge", "discharge", "idle")
        assert entry["grid_kwh"] >= 0.0
        assert entry["solar_used_kwh"] >= 0.0
        assert entry["battery_kwh"] >= 0.0
        assert 20.0 <= entry["battery_energy_after_kwh"] <= 200.0

    # 3. Directives structure
    dirs = data["directive_interpretation"]
    assert len(dirs) == 1
    assert dirs[0]["note_index"] == 0
    assert dirs[0]["applies"] is False
    assert dirs[0]["directive_type"] == "no_op"


def test_internal_error_does_not_leak_secrets_or_traces(client: TestClient, valid_payload: dict):
    """Internal exceptions must return HTTP 500 without stack trace or API keys."""
    with patch(
        "app.llm.generate_content_with_failover",
        side_effect=LLMProviderError("Provider failure with simulated_secret_key_12345"),
    ):
        resp = client.post("/optimize-energy", json=valid_payload)

    assert resp.status_code == 500
    body = resp.text
    assert "simulated_secret_key_12345" not in body
    assert "Traceback" not in body
    assert resp.json() == {"detail": "Internal server error"}
