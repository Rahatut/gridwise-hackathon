import os
import json
from typing import List, Dict, Any
from openai import OpenAI


SYSTEM_PROMPT = """You are an energy operator directive parser for a 24-hour battery scheduling system.
Hours are integers 0-23. Time windows are start-inclusive, end-exclusive.

Parse each operator note into exactly one of these directive types:
- solar_reduction: Reduce usable solar by a factor. Structured: {"factor": <float 0-1>}
- minimum_battery_reserve: Reserve minimum energy. Structured: {"reserve_kwh": <float>}
- no_charge_window: Forbid battery charging during hours. Structured: {"hours": [<int>, ...]}
- no_discharge_window: Forbid battery discharging during hours. Structured: {"hours": [<int>, ...]}
- max_grid_window: Cap grid import during hours. Structured: {"hours": [<int>, ...], "max_grid_kwh": <float>}
- no_op: Directive does not apply. Structured: null

Rules:
- If a directive does not apply, set type="no_op", applies=false, structured_adjustment=null.
- If it applies, set applies=true and include the structured_adjustment.
- Time windows must be unique integers 0-23 in ascending order.
- Solar factor is the usable fraction remaining (e.g., 80% reduction -> factor=0.2).
- Return ONLY valid JSON: an array of objects with keys: note_index, type, applies, structured_adjustment.
"""


def _call_llm(notes: List[str]) -> List[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

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
        for key in ("directives", "results", "items"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
    return parsed


VALID_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _no_op(idx: int) -> Dict[str, Any]:
    return {
        "note_index": idx,
        "type": "no_op",
        "applies": False,
        "structured_adjustment": None,
    }


def _guardrail(item: Dict[str, Any], idx: int) -> Dict[str, Any]:
    note_index = item.get("note_index", idx)
    dtype = item.get("type")
    applies = item.get("applies", False)
    adj = item.get("structured_adjustment")

    if dtype not in VALID_TYPES:
        return _no_op(note_index)

    if dtype == "no_op":
        return _no_op(note_index)

    if not applies:
        return _no_op(note_index)

    if not isinstance(adj, dict):
        return _no_op(note_index)

    if dtype == "solar_reduction":
        factor = adj.get("factor")
        if not isinstance(factor, (int, float)) or not (0.0 <= factor <= 1.0):
            return _no_op(note_index)
        return {
            "note_index": note_index,
            "type": dtype,
            "applies": True,
            "structured_adjustment": {"factor": float(factor)},
        }

    if dtype == "minimum_battery_reserve":
        reserve = adj.get("reserve_kwh")
        if not isinstance(reserve, (int, float)) or reserve < 0:
            return _no_op(note_index)
        return {
            "note_index": note_index,
            "type": dtype,
            "applies": True,
            "structured_adjustment": {"reserve_kwh": float(reserve)},
        }

    if dtype in ("no_charge_window", "no_discharge_window", "max_grid_window"):
        hours = adj.get("hours")
        if not isinstance(hours, list) or len(hours) == 0:
            return _no_op(note_index)
        cleaned = []
        for h in hours:
            if isinstance(h, int) and 0 <= h <= 23 and h not in cleaned:
                cleaned.append(h)
        if not cleaned:
            return _no_op(note_index)
        cleaned.sort()
        result_adj = {"hours": cleaned}
        if dtype == "max_grid_window":
            max_grid = adj.get("max_grid_kwh")
            if not isinstance(max_grid, (int, float)) or max_grid < 0:
                return _no_op(note_index)
            result_adj["max_grid_kwh"] = float(max_grid)
        return {
            "note_index": note_index,
            "type": dtype,
            "applies": True,
            "structured_adjustment": result_adj,
        }

    return _no_op(note_index)


def parse_and_guardrail_notes(notes: List[str]) -> List[Dict[str, Any]]:
    if not notes:
        return []

    try:
        raw = _call_llm(notes)
    except Exception:
        return [_no_op(i) for i in range(len(notes))]

    if not isinstance(raw, list):
        return [_no_op(i) for i in range(len(notes))]

    directives = []
    for i in range(len(notes)):
        item = raw[i] if i < len(raw) else {}
        if not isinstance(item, dict):
            directives.append(_no_op(i))
        else:
            directives.append(_guardrail(item, i))

    return directives