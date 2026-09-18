"""
Tests for Gemini LLM interpretation layer, multi-key failover pool, and guardrails.
"""
from __future__ import annotations

import os
import time
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from app.gemini_provider import (
    GeminiKeyPool,
    LLMProviderError,
    generate_content_with_failover,
    parse_api_keys,
)
from app.llm import (
    InterpretationsResponse,
    RawDirectiveInterpretation,
    StructuredAdjustment,
    _validate_and_canonicalize,
    interpret_operator_notes,
)
from app.models import BatterySpec, DirectiveInterpretation


@pytest.fixture
def sample_battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=20.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )


# ---------------------------------------------------------------------------
# API Key Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_api_keys_single_and_multi(monkeypatch: pytest.MonkeyPatch):
    # Case 1: GEMINI_API_KEYS takes precedence
    monkeypatch.setenv("GEMINI_API_KEYS", " key1 , key2, key1 ,, key3 ")
    monkeypatch.setenv("GEMINI_API_KEY", "fallback_key")
    keys = parse_api_keys()
    assert keys == ["key1", "key2", "key3"]

    # Case 2: GEMINI_API_KEY fallback
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", " single_key ")
    assert parse_api_keys() == ["single_key"]

    # Case 3: Empty environment
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert parse_api_keys() == []


# ---------------------------------------------------------------------------
# Key Pool Failover & Error Classification Tests
# ---------------------------------------------------------------------------

def test_key_pool_round_robin():
    pool = GeminiKeyPool(["test_key_1", "test_key_2"])
    c1 = pool.get_candidate()
    c2 = pool.get_candidate()
    c3 = pool.get_candidate()
    assert c1.key_id == "key_1"
    assert c2.key_id == "key_2"
    assert c3.key_id == "key_1"


def test_key_pool_cooldown_and_failover(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_TOTAL_BUDGET_SECONDS", "10.0")
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "2.0")
    monkeypatch.setenv("GEMINI_KEY_COOLDOWN_SECONDS", "5.0")

    pool = GeminiKeyPool(["key_a", "key_b"])

    # Simulate key_a hitting 429 quota exhaustion, key_b succeeding
    mock_resp = MagicMock()
    mock_resp.text = '{"interpretations": []}'
    mock_resp.parsed = InterpretationsResponse(interpretations=[])

    err_429 = errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota"}})

    # First entry fails with 429, second entry succeeds
    pool._entries[0].client.models.generate_content = MagicMock(side_effect=err_429)
    pool._entries[1].client.models.generate_content = MagicMock(return_value=mock_resp)

    res = generate_content_with_failover(
        contents="test",
        system_instruction="sys",
        response_schema=InterpretationsResponse,
        pool=pool,
    )
    assert res == mock_resp
    assert pool._entries[0].cooldown_until > time.monotonic()


def test_key_pool_auth_failure_permanently_disables_key():
    pool = GeminiKeyPool(["bad_key", "good_key"])

    mock_resp = MagicMock()
    mock_resp.parsed = InterpretationsResponse(interpretations=[])

    err_401 = errors.ClientError(401, {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "Invalid API Key"}})

    pool._entries[0].client.models.generate_content = MagicMock(side_effect=err_401)
    pool._entries[1].client.models.generate_content = MagicMock(return_value=mock_resp)

    res = generate_content_with_failover(
        contents="test",
        system_instruction="sys",
        pool=pool,
    )
    assert res == mock_resp
    assert pool._entries[0].disabled is True


def test_key_pool_bad_request_does_not_rotate():
    pool = GeminiKeyPool(["key_1", "key_2"])

    err_400 = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Malformed prompt"}})
    pool._entries[0].client.models.generate_content = MagicMock(side_effect=err_400)
    pool._entries[1].client.models.generate_content = MagicMock()

    with pytest.raises(LLMProviderError) as exc_info:
        generate_content_with_failover(
            contents="test",
            system_instruction="sys",
            pool=pool,
        )

    assert "400" in str(exc_info.value)
    # Ensure key_2 was never attempted
    pool._entries[1].client.models.generate_content.assert_not_called()


def test_key_pool_503_failover_to_healthy_key():
    pool = GeminiKeyPool(["key_failing_503", "key_working"])
    mock_resp = MagicMock()
    mock_resp.parsed = InterpretationsResponse(interpretations=[])

    err_503 = errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "Backend unavailable"}})
    pool._entries[0].client.models.generate_content = MagicMock(side_effect=err_503)
    pool._entries[1].client.models.generate_content = MagicMock(return_value=mock_resp)

    res = generate_content_with_failover(
        contents="test",
        system_instruction="sys",
        pool=pool,
    )
    assert res == mock_resp
    assert pool._entries[0].cooldown_until > time.monotonic()


def test_key_pool_concurrent_thread_safety():
    """Verify thread-safe candidate selection across concurrent threads."""
    import concurrent.futures
    pool = GeminiKeyPool([f"key_{i}" for i in range(5)])

    def worker():
        entries = []
        for _ in range(50):
            cand = pool.get_candidate()
            entries.append(cand.key_id)
        return entries

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker) for _ in range(10)]
        results = [f.result() for f in futures]

    # Ensure all threads retrieved valid candidates without corruption
    assert len(results) == 10
    for r in results:
        assert len(r) == 50
        assert all(k.startswith("key_") for k in r)


def test_secret_string_never_leaks_in_exceptions():
    """Ensure raw secret key string is sanitized from error messages and exceptions."""
    from app.gemini_provider import _sanitize_message

    secret_key = "AIzaSySecretApiKey123456789"
    raw_msg = f"Failed to connect using key {secret_key} to endpoint"
    sanitized = _sanitize_message(raw_msg, [secret_key])
    assert secret_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized

    # Also verify during 400 ClientError where Gemini echoes a key in message
    pool = GeminiKeyPool([secret_key])
    err_400 = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"Invalid parameter for {secret_key}"}})
    pool._entries[0].client.models.generate_content = MagicMock(side_effect=err_400)

    with pytest.raises(LLMProviderError) as exc_info:
        generate_content_with_failover(
            contents="test",
            system_instruction="sys",
            pool=pool,
        )

    msg = str(exc_info.value)
    assert secret_key not in msg
    assert "[REDACTED_API_KEY]" in msg


# ---------------------------------------------------------------------------
# Canonical Directive Types Interpretation Tests
# ---------------------------------------------------------------------------

def test_interpret_all_canonical_examples(sample_battery: BatterySpec):
    """
    Verify interpretation of all canonical sample patterns:
    1. solar 25% noon to 2 PM -> hours [12,13], factor .25
    2. no charge 2 AM to 5 AM -> [2,3,4]
    3. 50% of 200 kWh reserve 6 PM to 9 PM -> 100 kWh, [18,19,20]
    4. no discharge 6 PM to 8 PM -> [18,19]
    5. grid <=155 6 PM to 9 PM -> [18,19,20]
    6. 80% solar reduction -> factor .2
    7. distractor administrative notes -> no_op
    """
    notes = [
        "Expect heavy cloud cover from noon to 2 PM; only 25% solar forecast remains.",
        "Grid operator forbids charging from 2 AM to 5 AM for line repairs.",
        "Keep at least 50% of battery capacity in reserve between 6 PM and 9 PM.",
        "Do not discharge the battery between 6 PM and 8 PM.",
        "Campus grid import cap is 155 kWh from 6 PM until 9 PM.",
        "Significant dust storm: expect 80% solar reduction from 11 AM to 2 PM.",
        "Scheduled routine facility meeting in hall B at 3 PM today.",
    ]

    expected_raw = InterpretationsResponse(
        interpretations=[
            RawDirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment=StructuredAdjustment(hours=[12, 13], factor=0.25),
                explanation="Solar forecast 25% usable from noon to 2 PM.",
            ),
            RawDirectiveInterpretation(
                note_index=1,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment=StructuredAdjustment(hours=[2, 3, 4]),
                explanation="Charging forbidden 2 AM to 5 AM.",
            ),
            RawDirectiveInterpretation(
                note_index=2,
                applies=True,
                directive_type="minimum_battery_reserve",
                structured_adjustment=StructuredAdjustment(hours=[18, 19, 20], minimum_energy_kwh=100.0),
                explanation="50% of 200 kWh battery is 100 kWh reserve from 6 PM to 9 PM.",
            ),
            RawDirectiveInterpretation(
                note_index=3,
                applies=True,
                directive_type="no_discharge_window",
                structured_adjustment=StructuredAdjustment(hours=[18, 19]),
                explanation="Discharge forbidden 6 PM to 8 PM.",
            ),
            RawDirectiveInterpretation(
                note_index=4,
                applies=True,
                directive_type="max_grid_window",
                structured_adjustment=StructuredAdjustment(hours=[18, 19, 20], max_grid_kwh=155.0),
                explanation="Grid import cap 155 kWh from 6 PM to 9 PM.",
            ),
            RawDirectiveInterpretation(
                note_index=5,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment=StructuredAdjustment(hours=[11, 12, 13], factor=0.20),
                explanation="80% reduction implies factor 0.20 usable solar.",
            ),
            RawDirectiveInterpretation(
                note_index=6,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Administrative meeting note; no schedule impact.",
            ),
        ]
    )

    mock_resp = MagicMock()
    mock_resp.parsed = expected_raw

    with patch("app.llm.generate_content_with_failover", return_value=mock_resp):
        directives = interpret_operator_notes(notes, sample_battery)

    assert len(directives) == 7

    # 1. Solar reduction (25% remaining)
    assert directives[0].directive_type == "solar_reduction"
    assert directives[0].applies is True
    assert directives[0].structured_adjustment == {"hours": [12, 13], "factor": 0.25}

    # 2. No charge window
    assert directives[1].directive_type == "no_charge_window"
    assert directives[1].applies is True
    assert directives[1].structured_adjustment == {"hours": [2, 3, 4]}

    # 3. Minimum battery reserve (50% of 200 kWh = 100 kWh)
    assert directives[2].directive_type == "minimum_battery_reserve"
    assert directives[2].applies is True
    assert directives[2].structured_adjustment == {"hours": [18, 19, 20], "minimum_energy_kwh": 100.0}

    # 4. No discharge window
    assert directives[3].directive_type == "no_discharge_window"
    assert directives[3].applies is True
    assert directives[3].structured_adjustment == {"hours": [18, 19]}

    # 5. Max grid window
    assert directives[4].directive_type == "max_grid_window"
    assert directives[4].applies is True
    assert directives[4].structured_adjustment == {"hours": [18, 19, 20], "max_grid_kwh": 155.0}

    # 6. Solar reduction (80% reduction -> 0.20 factor)
    assert directives[5].directive_type == "solar_reduction"
    assert directives[5].applies is True
    assert directives[5].structured_adjustment == {"hours": [11, 12, 13], "factor": 0.20}

    # 7. Administrative distractor -> no_op
    assert directives[6].directive_type == "no_op"
    assert directives[6].applies is False
    assert directives[6].structured_adjustment is None


# ---------------------------------------------------------------------------
# Deterministic Guardrails & Validation Unit Tests
# ---------------------------------------------------------------------------

def test_guardrail_rejects_duplicate_or_missing_indexes(sample_battery: BatterySpec):
    # Missing index 0, duplicate index 1
    bad_directives = [
        RawDirectiveInterpretation(
            note_index=1,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="A",
        ),
        RawDirectiveInterpretation(
            note_index=1,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="B",
        ),
    ]
    valid, errors, canonical = _validate_and_canonicalize(bad_directives, 2, sample_battery)
    assert valid is False
    assert any("Duplicate note_index" in e for e in errors)
    assert any("Missing note_index" in e for e in errors)


def test_guardrail_rejects_unsorted_or_duplicate_hours(sample_battery: BatterySpec):
    bad = [
        RawDirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment=StructuredAdjustment(hours=[5, 3, 4]),  # unsorted
            explanation="Unsorted hours",
        )
    ]
    valid, errors, _ = _validate_and_canonicalize(bad, 1, sample_battery)
    assert valid is False
    assert any("sorted ascending" in e for e in errors)


def test_guardrail_rejects_reserve_exceeding_battery_capacity(sample_battery: BatterySpec):
    bad = [
        RawDirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment=StructuredAdjustment(hours=[18, 19], minimum_energy_kwh=250.0),  # > 200 capacity
            explanation="Impossible reserve",
        )
    ]
    valid, errors, _ = _validate_and_canonicalize(bad, 1, sample_battery)
    assert valid is False
    assert any("exceeds battery capacity" in e for e in errors)


def test_guardrail_rejects_factor_out_of_range(sample_battery: BatterySpec):
    bad = [
        RawDirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=StructuredAdjustment(hours=[12, 13], factor=1.5),  # > 1.0
            explanation="Invalid factor",
        )
    ]
    valid, errors, _ = _validate_and_canonicalize(bad, 1, sample_battery)
    assert valid is False
    assert any("factor must be in [0.0, 1.0]" in e for e in errors)


def test_repair_mechanism_recovers_from_validation_error(sample_battery: BatterySpec):
    notes = ["Reduce solar noon to 2 PM by 50%"]

    # First attempt: invalid factor > 1.0
    bad_resp = MagicMock()
    bad_resp.parsed = InterpretationsResponse(
        interpretations=[
            RawDirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment=StructuredAdjustment(hours=[12, 13], factor=50.0),  # percentage instead of fraction
                explanation="50% reduction",
            )
        ]
    )

    # Second (repair) attempt: corrected factor 0.50
    good_resp = MagicMock()
    good_resp.parsed = InterpretationsResponse(
        interpretations=[
            RawDirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment=StructuredAdjustment(hours=[12, 13], factor=0.50),
                explanation="50% reduction corrected to factor 0.50",
            )
        ]
    )

    with patch("app.llm.generate_content_with_failover", side_effect=[bad_resp, good_resp]):
        directives = interpret_operator_notes(notes, sample_battery)

    assert len(directives) == 1
    assert directives[0].structured_adjustment == {"hours": [12, 13], "factor": 0.50}


def test_repair_failure_raises_llm_provider_error(sample_battery: BatterySpec):
    notes = ["Reduce solar noon to 2 PM by 50%"]

    # Both attempts invalid
    bad_resp = MagicMock()
    bad_resp.parsed = InterpretationsResponse(
        interpretations=[
            RawDirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment=StructuredAdjustment(hours=[12, 13], factor=50.0),
                explanation="Invalid",
            )
        ]
    )

    with patch("app.llm.generate_content_with_failover", side_effect=[bad_resp, bad_resp]):
        with pytest.raises(LLMProviderError) as exc_info:
            interpret_operator_notes(notes, sample_battery)

    assert "validation failed" in str(exc_info.value).lower()


def test_empty_notes_returns_empty_list_immediately(sample_battery: BatterySpec):
    with patch("app.llm.generate_content_with_failover") as mock_call:
        res = interpret_operator_notes([], sample_battery)
        assert res == []
        mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# Optional Live Smoke Test (Only runs if a real key is present in environment)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")),
    reason="GEMINI_API_KEY(S) not configured; skipping live Gemini smoke test.",
)
def test_live_gemini_smoke(sample_battery: BatterySpec):
    notes = [
        "Keep at least 50% of battery capacity in reserve from 6 PM to 9 PM.",
        "Routine fire drill completed at 10 AM.",
    ]
    res = interpret_operator_notes(notes, sample_battery)
    assert len(res) == 2
    assert res[0].directive_type == "minimum_battery_reserve"
    assert res[0].applies is True
    assert res[0].structured_adjustment["hours"] == [18, 19, 20]
    assert res[0].structured_adjustment["minimum_energy_kwh"] == 100.0
    assert res[1].directive_type == "no_op"
    assert res[1].applies is False
