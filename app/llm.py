"""
LLM operator-note interpreter.

Architecture boundary (Section I of refactor spec):
    interpret_operator_notes(operator_notes, battery_context)
        -> List[DirectiveInterpretation]

The LLM returns raw JSON; deterministic guardrails normalise it into
canonical DirectiveInterpretation objects before the optimizer sees it.

NOTE: This module uses OpenAI / OpenRouter as the LLM provider.
A separate agent will migrate the _call_llm implementation to Gemini.
The public interface (interpret_operator_notes) must not change.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from app.models import BatterySpec, DirectiveInterpretation

load_dotenv()


# ---------------------------------------------------------------------------
# System prompt — aligned with canonical Section 04 directive types
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an energy operator directive parser for a 24-hour battery scheduling system.
Hours are integers 0-23. Time windows are start-inclusive, end-exclusive.

Parse each operator note into exactly one of these directive types:
- solar_reduction: Reduce usable solar during specific hours.
    structured_adjustment: {"hours": [...], "factor": <float 0-1>}
    factor = usable fraction REMAINING (e.g., 80% reduction -> factor=0.2)
- minimum_battery_reserve: Keep battery energy >= a required level during hours.
    structured_adjustment: {"hours": [...], "minimum_energy_kwh": <float>}
- no_charge_window: Forbid battery charging during specific hours.
    structured_adjustment: {"hours": [...]}
- no_discharge_window: Forbid battery discharging during specific hours.
    structured_adjustment: {"hours": [...]}
- max_grid_window: Cap grid import during specific hours.
    structured_adjustment: {"hours": [...], "max_grid_kwh": <float>}
- no_op: The note does not affect the current 24-hour energy schedule.
    structured_adjustment: null, applies: false

Rules:
- If a directive does not apply, set directive_type="no_op", applies=false, structured_adjustment=null.
- If it applies, set applies=true and include the correct structured_adjustment.
- Time windows must be unique integers 0-23 in ascending order.
- For solar_reduction, factor is the usable fraction REMAINING (e.g., 80% reduction means factor=0.2).
- Every hours array must contain unique integers from 0 through 23 in ascending order.
- Return ONLY valid JSON: an array of objects with keys:
    note_index, directive_type, applies, structured_adjustment, explanation
"""


# ---------------------------------------------------------------------------
# LLM call (provider: OpenAI / OpenRouter) — do NOT redesign this section
# ---------------------------------------------------------------------------

def _call_llm(notes: List[str]) -> List[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    # Support OpenRouter keys (sk-or-v1-...) and direct OpenAI keys
    if api_key.startswith("sk-or-v1-"):
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        model = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    else:
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    payload = [{"note_index": i, "note": n} for i, n in enumerate(notes)]
    user_content = json.dumps(payload)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        timeout=25,
    )

    raw = resp.choices[0].message.content
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        # LLM may wrap the array; unwrap common keys
        for key in ("directives", "results", "items", "interpretations"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
    return parsed  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Deterministic guardrails
# ---------------------------------------------------------------------------

VALID_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _make_no_op(idx: int, explanation: str = "No energy schedule impact.") -> DirectiveInterpretation:
    return DirectiveInterpretation(
        note_index=idx,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=explanation,
    )


def _guardrail(item: Dict[str, Any], idx: int) -> DirectiveInterpretation:
    """Validate one raw LLM item and return a canonical DirectiveInterpretation."""
    note_index = int(item.get("note_index", idx))
    dtype = item.get("directive_type") or item.get("type")  # tolerate old key name
    applies = item.get("applies", False)
    adj = item.get("structured_adjustment")
    explanation = str(item.get("explanation", "")).strip() or "Parsed by LLM."

    if dtype not in VALID_TYPES:
        return _make_no_op(note_index, "Invalid directive type from LLM; treated as no_op.")

    if dtype == "no_op" or not applies:
        return _make_no_op(note_index, explanation)

    if not isinstance(adj, dict):
        return _make_no_op(note_index, "Missing structured_adjustment; treated as no_op.")

    # -- solar_reduction --
    if dtype == "solar_reduction":
        hours = _clean_hours(adj.get("hours"))
        factor = adj.get("factor")
        if hours is None:
            return _make_no_op(note_index, "solar_reduction missing valid hours; treated as no_op.")
        if not isinstance(factor, (int, float)) or not (0.0 <= factor <= 1.0):
            return _make_no_op(note_index, "solar_reduction factor out of range; treated as no_op.")
        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": hours, "factor": float(factor)},
            explanation=explanation,
        )

    # -- minimum_battery_reserve --
    if dtype == "minimum_battery_reserve":
        hours = _clean_hours(adj.get("hours"))
        # Accept both canonical key and legacy key from old prompt
        reserve = adj.get("minimum_energy_kwh") or adj.get("reserve_kwh")
        if hours is None:
            return _make_no_op(note_index, "minimum_battery_reserve missing valid hours; treated as no_op.")
        if not isinstance(reserve, (int, float)) or reserve < 0:
            return _make_no_op(note_index, "minimum_battery_reserve invalid value; treated as no_op.")
        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment={"hours": hours, "minimum_energy_kwh": float(reserve)},
            explanation=explanation,
        )

    # -- no_charge_window / no_discharge_window --
    if dtype in ("no_charge_window", "no_discharge_window"):
        hours = _clean_hours(adj.get("hours"))
        if hours is None:
            return _make_no_op(note_index, f"{dtype} missing valid hours; treated as no_op.")
        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type=dtype,  # type: ignore[arg-type]
            structured_adjustment={"hours": hours},
            explanation=explanation,
        )

    # -- max_grid_window --
    if dtype == "max_grid_window":
        hours = _clean_hours(adj.get("hours"))
        max_grid = adj.get("max_grid_kwh")
        if hours is None:
            return _make_no_op(note_index, "max_grid_window missing valid hours; treated as no_op.")
        if not isinstance(max_grid, (int, float)) or max_grid < 0:
            return _make_no_op(note_index, "max_grid_window invalid max_grid_kwh; treated as no_op.")
        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment={"hours": hours, "max_grid_kwh": float(max_grid)},
            explanation=explanation,
        )

    return _make_no_op(note_index)


def _clean_hours(raw: Any) -> Optional[List[int]]:
    """Validate and normalise a raw hours list; return None on failure."""
    if not isinstance(raw, list) or len(raw) == 0:
        return None
    cleaned = []
    for h in raw:
        if isinstance(h, int) and 0 <= h <= 23 and h not in cleaned:
            cleaned.append(h)
    if not cleaned:
        return None
    cleaned.sort()
    return cleaned


# ---------------------------------------------------------------------------
# Public interface — canonical boundary for the optimizer
# ---------------------------------------------------------------------------

def interpret_operator_notes(
    operator_notes: List[str],
    battery_context: BatterySpec,  # noqa: ARG001 — available for future use / Gemini migration
) -> List[DirectiveInterpretation]:
    """
    Parse operator notes via LLM and apply deterministic guardrails.

    Returns one DirectiveInterpretation per note in note_index order.
    The optimizer must never consume raw natural language; only this output.
    """
    if not operator_notes:
        return []

    try:
        raw = _call_llm(operator_notes)
    except Exception:
        # LLM unavailable: all notes become no_op (safe fallback)
        return [_make_no_op(i, "LLM unavailable; note treated as no_op.") for i in range(len(operator_notes))]

    if not isinstance(raw, list):
        return [_make_no_op(i, "LLM returned non-list; treated as no_op.") for i in range(len(operator_notes))]

    result: List[DirectiveInterpretation] = []
    for i in range(len(operator_notes)):
        item = raw[i] if i < len(raw) else {}
        if not isinstance(item, dict):
            result.append(_make_no_op(i))
        else:
            result.append(_guardrail(item, i))

    return result


# ---------------------------------------------------------------------------
# Legacy compatibility shim (used by old tests/callers if any)
# ---------------------------------------------------------------------------

def parse_and_guardrail_notes(
    notes: List[str],
    battery_context: Optional[BatterySpec] = None,
) -> List[DirectiveInterpretation]:
    """Deprecated shim — prefer interpret_operator_notes."""
    from app.models import BatterySpec as BS

    dummy_battery = battery_context or BS(
        capacity_kwh=0,
        initial_energy_kwh=0,
        minimum_energy_kwh=0,
        max_charge_kwh_per_hour=0,
        max_discharge_kwh_per_hour=0,
    )
    return interpret_operator_notes(notes, dummy_battery)