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
- Node.js 18+ (for frontend)
- Docker (optional, for containerized deployment)

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEYS` | Yes* | — | Comma-separated Gemini API keys for failover |
| `GEMINI_API_KEY` | Yes* | — | Single-key fallback if `GEMINI_API_KEYS` unset |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model for structured directive interpretation |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | No | `15.0` | Per-request timeout in seconds (Gemini SDK enforces ≥ 10s) |
| `GEMINI_TOTAL_BUDGET_SECONDS` | No | `25.0` | Shared time budget across initial + repair Gemini calls |
| `GEMINI_KEY_COOLDOWN_SECONDS` | No | `60.0` | Cooldown duration for rate-limited (429) keys |

> **Important — Gemini Quota:** Google Gemini API rate limits (RPM / TPM / RPD) are enforced per **Google Cloud / AI Studio project**, not per individual API key. Multiple API keys generated within the same project share the same quota. For genuine parallel failover capacity, use keys from **independent projects**. This pool provides reliable failover and cooldown handling, not quota multiplication within a single project.

## Local Setup

### Backend (Python)

```bash
cp .env.example .env
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend (Node.js)

```bash
cd demo-ui
npm install
```

## Run

### Backend

```bash
uvicorn app.main:app --reload --port 8000
```

Service will be available at `http://127.0.0.1:8000`.

### Frontend (Dev Server)

```bash
cd demo-ui && npm run dev
```

Frontend will be available at `http://localhost:3000`. The Vite dev server proxies `/optimize-energy` and `/health` to `http://127.0.0.1:8000`.

### Frontend (Production Preview)

```bash
cd demo-ui && npm run build && npm run preview
```

Preview will be available at `http://localhost:4173`.

## API Specification

### GET /health

Readiness and liveness endpoint. Returns HTTP 200 with `{"status": "ok"}` within 60 seconds of service startup.

```bash
curl http://127.0.0.1:8000/health
```

**Response:**
```json
{"status": "ok"}
```

### POST /optimize-energy

Primary optimization endpoint. Accepts a 24-hour microgrid scenario and human operator notes, interprets notes via Gemini into mathematical constraints, solves the linear program (LP), and validates the resulting schedule using the 19-point independent auditor.

```bash
curl -X POST http://127.0.0.1:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```

**Canonical Request Body:**

```json
{
  "scenario_id": "SAMPLE-01",
  "battery": {
    "capacity_kwh": 50.0,
    "max_charge_kw": 25.0,
    "max_discharge_kw": 25.0,
    "efficiency": 0.95,
    "initial_soc_kwh": 25.0,
    "min_soc_kwh": 5.0,
    "target_end_soc_kwh": 25.0
  },
  "hours": [
    {
      "hour": 0,
      "solar_generation_kwh": 0.0,
      "load_kwh": 110.0,
      "tariff_bdt_per_kwh": 8.0
    }
  ],
  "operator_notes": [
    "Keep at least 15 kWh in battery storage between 17:00 and 21:00."
  ]
}
```

**Canonical Response Body:**

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "reserve_battery",
      "structured_adjustment": {
        "start_hour": 17,
        "end_hour": 21,
        "value": 15.0
      },
      "explanation": "Reserve at least 15 kWh in battery during peak hours 17-21."
    }
  ],
  "total_cost_bdt": 38365.0,
  "total_grid_kwh": 2692.5,
  "peak_grid_kwh": 127.37,
  "hourly_plan": [
    {
      "hour": 0,
      "solar_used_kwh": 0.0,
      "solar_curtailed_kwh": 0.0,
      "grid_import_kwh": 110.0,
      "battery_charge_kwh": 0.0,
      "battery_discharge_kwh": 0.0,
      "battery_soc_kwh": 25.0
    }
  ]
}
```

## Architecture & Design

1. **Gemini Interpretation & Failover Pool (`app/gemini_provider.py` & `app/llm.py`):**
   - Implements thread-safe round-robin failover across multiple API keys (`GEMINI_API_KEYS`).
   - Handles rate limits (HTTP 429) and transient server overloads (HTTP 503) with exponential backoff and key-level cooldown tracking (`GEMINI_KEY_COOLDOWN_SECONDS`).
   - Structured JSON schema enforcement with deterministic two-pass correction: if an interpretation violates physical battery boundaries or hourly ranges, a bounded repair prompt reconciles it.
   - Fail-safe fallback: If all keys/retries fail, returns controlled `applies: false` directives rather than crashing.

2. **Deterministic Guardrail Normalizer (`app/llm.py`):**
   - Validates all 6 canonical directive types (`reserve_battery`, `force_charge`, `prevent_discharge`, `curtail_solar`, `demand_cap`, `tariff_override`).
   - Clamps intervals to `[0, 23]`, ensures `start_hour <= end_hour`, and bounds target values strictly against physical battery capacity and load limits.

3. **LP Optimizer (`app/optimizer.py`):**
   - High-performance formulation using `scipy.optimize.linprog` with the HiGHS solver engine.
   - Formulates continuous linear optimization over 120 decision variables (5 variables per hour: `solar_used`, `solar_curtailed`, `grid_import`, `battery_charge`, `battery_discharge`, `battery_soc`).
   - Objective: Minimize exact facility electricity cost `Σ (grid_import[h] × tariff[h])`.
   - Solves typical 24-hour scenarios in under 15 milliseconds.

4. **Independent 19-Point Auditor (`app/validator.py`):**
   - Verifies the full plan independently before releasing responses:
     - 24-hour sequence & indexing
     - Energy balance: `load == solar_used + grid_import + battery_discharge`
     - Solar allocation: `solar_generation == solar_used + solar_curtailed`
     - Battery dynamics: `soc[h] == soc[h-1] + charge[h]*eff - discharge[h]/eff`
     - Power and capacity constraints: `min_soc <= soc <= capacity`, `charge <= max_charge`, `discharge <= max_discharge`
     - Neutrality: `soc[23] >= target_end_soc`
     - Directives: Explicit compliance with all 6 directive bounds.

## Evaluation & Testing

### 1. Run Complete Pytest Suite

The automated test suite requires no live Gemini keys (all external calls are mocked):

```bash
python -m pytest -v
```

Tests cover:
- Request/Response schema validation
- LLM failover pool, cooldowns, and retry policies
- Directive semantic interpretation & guardrails
- High-precision optimizer correctness & HiGHS formulation
- 19-point independent validator
- Edge cases (0 solar, flat tariffs, boundary SoC, simultaneous windows)
- Official 10-sample regression tests (exact cost match within 0.01 BDT)

### 2. Run Public Sample Benchmark Runner

A dedicated evaluation harness is provided to verify the 10 official public sample cases from the competition specification:

```bash
# Offline verification mode (uses TestClient with official expectations, no API key or server needed):
python scripts/run_public_samples.py --offline

# Live verification mode (against a running server on port 8000):
python scripts/run_public_samples.py --base-url http://localhost:8000
```

Sample output:
```text
================================================================================
GridWise Official Public Sample Cases Verification
Mode:          OFFLINE TESTCLIENT VERIFICATION
================================================================================
Case ID     | Status | Cost (BDT)         | Grid (kWh)         | Directives | Plan    | Duration
------------------------------------------------------------------------------------------
SAMPLE-01   | PASS   | 38365.00 (ref 38365.00) | 2692.50 (ref 2692.50) | OK         | Valid   | 31.6ms
SAMPLE-02   | PASS   | 42885.00 (ref 42885.00) | 2915.00 (ref 2915.00) | OK         | Valid   | 11.9ms
...
==========================================================================================
SUMMARY RESULTS:
  Schema Valid:               10/10
  Directive Interpretations:  10/10
  Independent Plan Validity:  10/10
  Optimal Cost Reference:     10/10
  Latency: Avg = 14.2ms | P95 = 31.6ms
==========================================================================================
```

## Docker Containerization

### Backend

The Dockerfile in the project root builds and runs the backend service:

```bash
docker build -t gridwise-service .
docker run -d -p 8000:8000 --env-file .env gridwise-service
```

Image binds to `0.0.0.0:8000`. Health check will respond at `http://localhost:8000/health`.

The backend Dockerfile includes:
- Python 3.11-slim base image
- All dependencies from `requirements.txt`
- Uvicorn server serving `app.main:app` on port 8000

### Frontend

The frontend is deployed via **GitHub Pages** using the GitHub Actions workflow at `.github/workflows/deploy-frontend.yml`. No Docker is needed for the frontend.

To build the frontend locally for testing:

```bash
cd demo-ui && npm run build
```

The built static files are output to `demo-ui/dist/` and can be served by any static file server (e.g., `npm run preview` on port 4173).

## Demo Dashboard (Operator Control Room)

An interactive, presentation-ready web dashboard is provided for live judging demonstrations.

### Run Locally

1. Start the GridWise backend:
   ```bash
   python -m uvicorn app.main:app --port 8000
   ```
2. Start the frontend dev server:
   ```bash
   cd demo-ui && npm run dev
   ```
3. Open your browser:
   ```
   http://localhost:3000
   ```

The frontend proxies API calls to the backend at `http://127.0.0.1:8000` via the Vite dev server proxy configured in `demo-ui/vite.config.ts`.

### Features

- **Realistic Scenario Presets**: 5 one-click operational presets (*Emergency Battery Reserve*, *Solar Maintenance*, *Peak Grid Restriction*, *Battery Maintenance*, *Mixed Operations*).
- **Live Gemini Interpretation**: Visual directive cards with status badges (`[APPLIED]` vs `[IGNORED] no_op`), affected hours, numerical parameter extractions, and operator explanations.
- **Interactive 24-Hour Energy Charts**: Clean Recharts curves showing Demand, Solar Used, Grid Import, Tariff, and highlighted directive restriction windows.
- **Battery Strategy & Arbitrage**: State of Charge (SoC) trajectory curve, bidirectional charge/discharge bars, and end-of-day neutrality verification (`NEUTRALITY VERIFIED ✓`).
- **System Validation Display**: 8-point automated response consistency verification (`ALL CONSTRAINTS VALID`).
- **Technical JSON Inspector**: Collapsible tabs showing the exact canonical `REQUEST JSON` and `RESPONSE JSON` with copy-to-clipboard functionality to demonstrate that the dashboard utilizes the exact judging API.

### Frontend Architecture

The frontend source code is kept completely independent in `demo-ui/` (React + Vite + Tailwind CSS):

- **Development**: `cd demo-ui && npm run dev`
- **Build**: `cd demo-ui && npm run build` (outputs to `demo-ui/dist/`)
- **API Configuration**: The backend URL is set via the `VITE_API_BASE_URL` environment variable in `demo-ui/.env`. By default it falls back to `https://gridwise-hackathon.onrender.com`.

### Deploy to GitHub Pages

A GitHub Actions workflow (`.github/workflows/deploy-frontend.yml`) automatically builds and deploys the frontend to GitHub Pages on every push to `main`:

```yaml
# The workflow:
# 1. Installs npm dependencies
# 2. Builds the frontend with VITE_API_BASE_URL set from GitHub Secrets or default
# 3. Deploys the built static files to GitHub Pages
```

To configure a custom backend URL for the deployed frontend, add a GitHub Secret named `VITE_API_BASE_URL` in the repository settings.

### Backend Deployment (Render)

The backend is deployed on Render at `https://gridwise-hackathon.onrender.com`. CORS is pre-configured to allow cross-origin requests from any origin.