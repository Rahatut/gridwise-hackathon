"""
LLM operator-note interpreter using the official Google Gemini API (google-genai).

Architecture boundary:
    interpret_operator_notes(operator_notes, battery_context)
        -> List[DirectiveInterpretation]

The LLM produces structured output via SDK response_schema; deterministic guardrails
validate the output against canonical rules and battery context before the optimizer sees it.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.gemini_provider import LLMProviderError, generate_content_with_failover
from app.models import BatterySpec, DirectiveInterpretation

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured Output Models for Gemini SDK
# ---------------------------------------------------------------------------

DirectiveTypeLiteral = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class StructuredAdjustment(BaseModel):
    hours: Optional[List[int]] = Field(
        default=None,
        description="List of integer hours 0..23 during which the directive applies (start-inclusive, end-exclusive).",
    )
    factor: Optional[float] = Field(
        default=None,
        description="Usable solar fraction remaining (0.0 to 1.0) for solar_reduction. E.g. 80% reduction -> factor 0.20.",
    )
    minimum_energy_kwh: Optional[float] = Field(
        default=None,
        description="Required minimum stored battery energy in kWh for minimum_battery_reserve. Convert any percentage using battery capacity.",
    )
    max_grid_kwh: Optional[float] = Field(
        default=None,
        description="Maximum permitted grid import in kWh per hour for max_grid_window.",
    )


class RawDirectiveInterpretation(BaseModel):
    note_index: int = Field(
        description="Zero-based index of the corresponding operator note (0 to N-1).",
    )
    applies: bool = Field(
        description="True if directive applies to 24h schedule constraints; False only for no_op.",
    )
    directive_type: DirectiveTypeLiteral = Field(
        description="Canonical directive type: solar_reduction, minimum_battery_reserve, no_charge_window, no_discharge_window, max_grid_window, or no_op.",
    )
    structured_adjustment: Optional[StructuredAdjustment] = Field(
        default=None,
        description="Adjustment payload for applicable directives; null for no_op.",
    )
    explanation: str = Field(
        description="Brief concise rationale for the interpretation.",
    )


class InterpretationsResponse(BaseModel):
    interpretations: List[RawDirectiveInterpretation] = Field(
        description="List containing exactly one interpretation per input note, in note_index order.",
    )


# ---------------------------------------------------------------------------
# Semantic System Instruction
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """You are an expert energy scheduling operator directive interpreter for a 24-hour campus microgrid system.
Your job is to interpret natural-language operator notes into precise, structured energy constraints.

Rules and conventions:
1. Return exactly one interpretation per input note, preserving its note_index (0 to N-1).
2. Time windows are start-inclusive, end-exclusive integer hours from 0 through 23 in strictly ascending order:
   - "noon to 2 PM" -> hours [12, 13]
   - "6 PM until 9 PM" / "6 PM to 9 PM" -> hours [18, 19, 20]
   - "2 AM to 5 AM" -> hours [2, 3, 4]
   - "6 PM to 8 PM" -> hours [18, 19]
   - "11 AM to 2 PM" -> hours [11, 12, 13]
   - Noon is hour 12; Midnight is hour 0.
3. Supported directives only:
   - solar_reduction: usable solar generation is reduced. factor is the USABLE FRACTION REMAINING (0.0 to 1.0).
     * "80% reduction" -> factor = 0.20
     * "25% of forecast remains" / "25% solar" -> factor = 0.25
     * "solar reduced by 50%" -> factor = 0.50
   - minimum_battery_reserve: keep battery energy >= minimum_energy_kwh during specified hours.
     * When expressed as a percentage of battery capacity, compute numeric kWh using the provided battery capacity_kwh.
     * Example: for a 200 kWh battery, "Keep at least 50% of battery capacity" -> minimum_energy_kwh = 100.0.
   - no_charge_window: battery must not charge during specified hours. structured_adjustment contains {"hours": [...]}.
   - no_discharge_window: battery must not discharge during specified hours. structured_adjustment contains {"hours": [...]}.
   - max_grid_window: grid import must not exceed max_grid_kwh during specified hours.
   - no_op: any note that is purely administrative, general commentary, maintenance notices without schedule impact, or irrelevant.
4. Exact semantics:
   - For "no_op": applies MUST be false, structured_adjustment MUST be null.
   - For every other directive: applies MUST be true, structured_adjustment MUST have non-empty unique sorted hours and the required field.
5. Do NOT invent demand profiles, tariff values, solar numbers, or unsupported directive types.
"""


def build_user_prompt(notes: List[str], battery: BatterySpec) -> str:
    """Format operator notes with explicit indexes and battery metadata."""
    lines = [
        "Battery Context:",
        f"- capacity_kwh: {battery.capacity_kwh}",
        f"- initial_energy_kwh: {battery.initial_energy_kwh}",
        f"- minimum_energy_kwh: {battery.minimum_energy_kwh}",
        f"- max_charge_kwh_per_hour: {battery.max_charge_kwh_per_hour}",
        f"- max_discharge_kwh_per_hour: {battery.max_discharge_kwh_per_hour}",
        "",
        f"Operator Notes to interpret ({len(notes)} notes):",
    ]
    for idx, note in enumerate(notes):
        lines.append(f"[{idx}] {note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic Guardrails & Canonical Validation
# ---------------------------------------------------------------------------

VALID_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _validate_and_canonicalize(
    raw_directives: List[RawDirectiveInterpretation],
    num_notes: int,
    battery: BatterySpec,
) -> Tuple[bool, List[str], List[DirectiveInterpretation]]:
    """
    Validate raw directives against strict deterministic guardrails.
    Returns (is_valid, list_of_error_strings, canonical_directives).
    """
    errors: List[str] = []

    if len(raw_directives) != num_notes:
        errors.append(
            f"Expected {num_notes} interpretations, but got {len(raw_directives)}."
        )

    seen_indexes = set()
    for item in raw_directives:
        if item.note_index in seen_indexes:
            errors.append(f"Duplicate note_index: {item.note_index}.")
        seen_indexes.add(item.note_index)

    expected_indexes = set(range(num_notes))
    if seen_indexes != expected_indexes:
        missing = expected_indexes - seen_indexes
        extra = seen_indexes - expected_indexes
        if missing:
            errors.append(f"Missing note_index: {sorted(missing)}.")
        if extra:
            errors.append(f"Unexpected extra note_index: {sorted(extra)}.")

    # Sort items by note_index for canonical evaluation
    sorted_items = sorted(raw_directives, key=lambda x: x.note_index)
    canonical_list: List[DirectiveInterpretation] = []

    for expected_idx, item in enumerate(sorted_items):
        idx = item.note_index
        dtype = item.directive_type
        applies = item.applies
        adj = item.structured_adjustment
        explanation = (item.explanation or "").strip() or "Interpreted directive."

        if dtype not in VALID_DIRECTIVE_TYPES:
            errors.append(f"Note [{idx}]: unsupported directive_type '{dtype}'.")
            continue

        if dtype == "no_op":
            if applies is not False:
                errors.append(f"Note [{idx}]: no_op directive must have applies=false, got {applies}.")
            canonical_list.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=False,
                    directive_type="no_op",
                    structured_adjustment=None,
                    explanation=explanation,
                )
            )
            continue

        # Applicable directives must have applies=True
        if applies is not True:
            errors.append(f"Note [{idx}]: directive '{dtype}' must have applies=true, got {applies}.")

        if adj is None:
            errors.append(f"Note [{idx}]: directive '{dtype}' requires structured_adjustment, but got null.")
            continue

        # Validate hours array
        hours = adj.hours
        if not isinstance(hours, list) or len(hours) == 0:
            errors.append(f"Note [{idx}]: directive '{dtype}' requires non-empty hours array.")
            continue

        # Ensure hours are unique, in range 0..23, and strictly ascending
        invalid_hours = False
        for h in hours:
            if not isinstance(h, int) or isinstance(h, bool) or not (0 <= h <= 23):
                errors.append(f"Note [{idx}]: invalid hour value {h}; must be integer 0..23.")
                invalid_hours = True
                break

        if invalid_hours:
            continue

        if len(hours) != len(set(hours)):
            errors.append(f"Note [{idx}]: hours array contains duplicates: {hours}.")
            continue

        if hours != sorted(hours):
            errors.append(f"Note [{idx}]: hours array must be sorted ascending: {hours}.")
            continue

        # Directive-specific adjustment validation
        if dtype == "solar_reduction":
            factor = adj.factor
            if factor is None or not isinstance(factor, (int, float)) or math.isnan(factor) or math.isinf(factor):
                errors.append(f"Note [{idx}]: solar_reduction requires finite numeric factor.")
            elif not (0.0 <= factor <= 1.0):
                errors.append(f"Note [{idx}]: solar_reduction factor must be in [0.0, 1.0], got {factor}.")
            else:
                canonical_list.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=True,
                        directive_type="solar_reduction",
                        structured_adjustment={"hours": list(hours), "factor": round(float(factor), 6)},
                        explanation=explanation,
                    )
                )

        elif dtype == "minimum_battery_reserve":
            reserve = adj.minimum_energy_kwh
            if reserve is None or not isinstance(reserve, (int, float)) or math.isnan(reserve) or math.isinf(reserve):
                errors.append(f"Note [{idx}]: minimum_battery_reserve requires finite numeric minimum_energy_kwh.")
            elif reserve < 0.0:
                errors.append(f"Note [{idx}]: minimum_battery_reserve must be non-negative, got {reserve}.")
            elif reserve > battery.capacity_kwh:
                errors.append(
                    f"Note [{idx}]: minimum_battery_reserve ({reserve} kWh) exceeds battery capacity ({battery.capacity_kwh} kWh)."
                )
            else:
                canonical_list.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=True,
                        directive_type="minimum_battery_reserve",
                        structured_adjustment={"hours": list(hours), "minimum_energy_kwh": round(float(reserve), 6)},
                        explanation=explanation,
                    )
                )

        elif dtype == "no_charge_window":
            canonical_list.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=True,
                    directive_type="no_charge_window",
                    structured_adjustment={"hours": list(hours)},
                    explanation=explanation,
                )
            )

        elif dtype == "no_discharge_window":
            canonical_list.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=True,
                    directive_type="no_discharge_window",
                    structured_adjustment={"hours": list(hours)},
                    explanation=explanation,
                )
            )

        elif dtype == "max_grid_window":
            max_grid = adj.max_grid_kwh
            if max_grid is None or not isinstance(max_grid, (int, float)) or math.isnan(max_grid) or math.isinf(max_grid):
                errors.append(f"Note [{idx}]: max_grid_window requires finite numeric max_grid_kwh.")
            elif max_grid < 0.0:
                errors.append(f"Note [{idx}]: max_grid_window max_grid_kwh must be non-negative, got {max_grid}.")
            else:
                canonical_list.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=True,
                        directive_type="max_grid_window",
                        structured_adjustment={"hours": list(hours), "max_grid_kwh": round(float(max_grid), 6)},
                        explanation=explanation,
                    )
                )

    if errors or len(canonical_list) != num_notes:
        return False, errors, []

    return True, [], canonical_list


def _extract_raw_directives(response: Any) -> List[RawDirectiveInterpretation]:
    """Extract list of RawDirectiveInterpretation objects from Gemini response."""
    # 1. Direct parsed model from response.parsed
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, InterpretationsResponse):
        return parsed.interpretations
    if isinstance(parsed, list):
        items: List[RawDirectiveInterpretation] = []
        for x in parsed:
            if isinstance(x, RawDirectiveInterpretation):
                items.append(x)
            else:
                items.append(RawDirectiveInterpretation.model_validate(x))
        return items

    # 2. Text payload fallback
    raw_text = getattr(response, "text", "") or ""
    if raw_text:
        try:
            resp_obj = InterpretationsResponse.model_validate_json(raw_text)
            return resp_obj.interpretations
        except Exception:
            data = json.loads(raw_text)
            if isinstance(data, dict):
                for k in ("interpretations", "directives", "results", "items"):
                    if k in data and isinstance(data[k], list):
                        return [RawDirectiveInterpretation.model_validate(x) for x in data[k]]
            elif isinstance(data, list):
                return [RawDirectiveInterpretation.model_validate(x) for x in data]

    raise LLMProviderError("Unable to extract structured interpretations from Gemini response.")


# ---------------------------------------------------------------------------
# Public Interface — Canonical Boundary for the Optimizer
# ---------------------------------------------------------------------------

def interpret_operator_notes(
    operator_notes: List[str],
    battery_context: BatterySpec,
) -> List[DirectiveInterpretation]:
    """
    Parse operator notes via Google Gemini structured output and apply deterministic guardrails.

    Workflow:
    1. Fast return empty list if no notes.
    2. Format battery context and indexed notes prompt.
    3. Call Gemini via thread-safe multi-key failover pool with structured response_schema.
    4. Deterministically validate structure and constraints.
    5. If validation fails and total time budget permits, attempt one bounded repair prompt.
    6. If still invalid or provider fails, raise LLMProviderError (never silent no_op).
    """
    num_notes = len(operator_notes)
    if num_notes == 0:
        return []

    user_prompt = build_user_prompt(operator_notes, battery_context)

    # Record start time here; share a single wall-clock deadline across the initial
    # call and any repair attempt so total latency stays within the 30s hard limit.
    total_budget_sec = float(os.getenv("GEMINI_TOTAL_BUDGET_SECONDS", "25.0"))
    shared_deadline = time.monotonic() + total_budget_sec

    # 1. Primary structured generation attempt
    response = generate_content_with_failover(
        contents=user_prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        response_schema=InterpretationsResponse,
        temperature=0.0,
        deadline=shared_deadline,
    )

    raw_directives = _extract_raw_directives(response)
    is_valid, validation_errors, canonical_directives = _validate_and_canonicalize(
        raw_directives, num_notes, battery_context
    )

    if is_valid:
        return canonical_directives

    logger.warning(
        "Initial Gemini interpretation failed validation with %d error(s): %s; evaluating repair attempt",
        len(validation_errors),
        validation_errors,
    )

    # 2. Bounded repair attempt — use remaining budget from the SAME shared_deadline
    #    so that initial + repair combined cannot exceed the configured total budget.
    repair_prompt = (
        f"{user_prompt}\n\n"
        f"CRITICAL: The previous interpretation failed deterministic validation with these errors:\n"
        + "\n".join(f"- {err}" for err in validation_errors)
        + "\n\nPlease output the complete corrected interpretation fixing all listed errors strictly following the rules."
    )

    try:
        repair_response = generate_content_with_failover(
            contents=repair_prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            response_schema=InterpretationsResponse,
            temperature=0.0,
            deadline=shared_deadline,
        )
        repair_raw = _extract_raw_directives(repair_response)
        rep_valid, rep_errors, rep_canonical = _validate_and_canonicalize(
            repair_raw, num_notes, battery_context
        )
        if rep_valid:
            logger.info("Gemini repair attempt succeeded in resolving validation errors.")
            return rep_canonical

        logger.error("Gemini repair attempt also failed validation: %s", rep_errors)
        raise LLMProviderError(
            f"Directive interpretation validation failed after repair attempt: {'; '.join(rep_errors)}"
        )

    except LLMProviderError:
        raise
    except Exception as exc:
        raise LLMProviderError(
            f"Directive interpretation failed validation: {'; '.join(validation_errors)}"
        ) from exc


# ---------------------------------------------------------------------------
# Legacy Compatibility Shim
# ---------------------------------------------------------------------------

def parse_and_guardrail_notes(
    notes: List[str],
    battery_context: Optional[BatterySpec] = None,
) -> List[DirectiveInterpretation]:
    """Deprecated shim for compatibility with legacy test invocations."""
    dummy_battery = battery_context or BatterySpec(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=20.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    return interpret_operator_notes(notes, dummy_battery)