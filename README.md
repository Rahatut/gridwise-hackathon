# GridWise Hackathon Service

Automated microgrid dispatcher that translates human operator notes into mathematical rules to minimize a facility's 24-hour electricity bill.

## Architecture

```
POST /optimize-energy
        │
        ▼
  Pydantic Input Validation
        │
        ▼
  LLM Directive Parser (operator_notes → structured JSON)
        │
        ▼
  Deterministic Guardrail Validator
        │
        ▼
  Directive Normalizer (→ 24h constraint arrays)
        │
        ▼
  LP Optimizer (scipy/HiGHS — minimize Σ grid[h] × tariff[h])
        │
        ▼
  Independent Solution Auditor
        │
        ▼
  Validated JSON Response
```

**Core principle:** LLM = semantic parser. Guardrails = authority. Optimizer = mathematics. Auditor = final authority.

## Requirements

- Python 3.11+
- Docker (optional, for containerized deployment)

## Environment Variables

| `GEMINI_API_KEYS` | Yes* | — | Comma-separated Gemini API keys for failover |
| `GEMINI_API_KEY` | Yes* | — | Single-key fallback if `GEMINI_API_KEYS` unset |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model for structured directive interpretation |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | No | `8.0` | Per-request timeout in seconds |
| `GEMINI_TOTAL_BUDGET_SECONDS` | No | `25.0` | Total time budget for Gemini calls including failover |
| `GEMINI_KEY_COOLDOWN_SECONDS` | No | `60.0` | Cooldown duration for rate-limited (429) keys |

## Local Setup

```bash
cp .env.example .env
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Service will be available at `http://127.0.0.1:8000`.

## API

### GET /health

Readiness endpoint. Returns HTTP 200 with `{"status": "ok"}` within 60 seconds of service start.

```bash
curl http://127.0.0.1:8000/health
```

### POST /optimize-energy

Primary endpoint. Accepts a 24-hour scenario JSON object and returns structured note interpretations plus the hourly schedule.

```bash
curl -X POST http://127.0.0.1:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @request.json
```

**Request body:**

```json
{
  "scenario": {
    "tariff_bdt_per_kwh": [2.0, 2.0, ..., 5.0],
    "effective_solar_kwh": [0, 0, ..., 8.0],
    "demand_kwh": [3.0, 3.0, ..., 4.0],
    "battery_capacity": 10.0,
    "max_charge_kwh_per_hour": 3.0,
    "max_discharge_kwh_per_hour": 3.0,
    "initial_energy_kwh": 5.0
  },
  "operator_notes": ["Keep at least 4 kWh in reserve during the evening peak"]
}
```

**Response body:**

```json
{
  "directives": [
    {
      "note_index": 0,
      "type": "minimum_battery_reserve",
      "applies": true,
      "structured_adjustment": {"reserve_kwh": 4.0}
    }
  ],
  "total_grid_kwh": 65.5,
  "total_cost_bdt": 356.5,
  "peak_grid_kwh": 7.0,
  "schedule": [
    {
      "hour": 0,
      "grid_kwh": 5.0,
      "solar_used_kwh": 0.0,
      "solar_curtailed_kwh": 0.0,
      "battery_charge_kwh": 2.0,
      "battery_discharge_kwh": 0.0,
      "battery_soc_kwh": 7.0
    }
  ]
}
```

## LLM

- **Model:** `gemini-2.5-flash` (configurable via `GEMINI_MODEL`)
- **SDK:** Official Google GenAI SDK (`google-genai`)
- **Structured Output:** Pydantic response schema with strict deterministic guardrails
- **Failover:** Thread-safe multi-key pool with cooldown and transient error retry

## Optimizer

- **Solver:** scipy `linprog` with HiGHS interior-point method
- **Formulation:** Continuous LP over 120 decision variables (grid, solar_used, charge, discharge, soc_after per hour)
- **Guarantees:** Global optimality for continuous constraints; handles all 6 directive types via bound transformations

## Docker

```bash
docker build -t gridwise-service .
docker run -d -p 8000:8000 --env-file .env gridwise-service
```

Image binds to `0.0.0.0:8000`. No baked-in credentials.

## Testing

```bash
# Health check
curl http://127.0.0.1:8000/health

# Run test suite
python -m pytest tests/ -v
```

## Limitations

- Simultaneous charge/discharge is not explicitly forbidden (LP naturally sets both to zero in optimal solutions)
- LLM interpretation uses structured output + deterministic guardrails; malformed outputs trigger a bounded repair before controlled failure
- End-of-day neutrality enforced via explicit LP equality constraint