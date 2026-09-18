"""Quick live test: send test_request.json to the running server and print results."""
import json
import urllib.request

with open("test_request.json", "rb") as f:
    body = f.read()

req = urllib.request.Request(
    "http://localhost:8000/optimize-energy",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)

print("Sending request... (waiting for Gemini)")
with urllib.request.urlopen(req, timeout=35) as resp:
    result = json.loads(resp.read().decode())

print("\n=== DIRECTIVE INTERPRETATIONS ===")
for d in result["directive_interpretation"]:
    marker = "✓" if d["applies"] else "✗"
    print(f"  [{d['note_index']}] {marker} {d['directive_type']}")
    print(f"      {d['explanation']}")
    if d.get("structured_adjustment"):
        print(f"      adjustment: {json.dumps(d['structured_adjustment'])}")

print("\n=== TOTALS ===")
print(f"  Cost:      {result['total_cost_bdt']:,.2f} BDT")
print(f"  Grid:      {result['total_grid_kwh']:,.2f} kWh")
print(f"  Peak:      {result['peak_grid_kwh']:,.2f} kWh/hr")

print("\n=== PLAN SUMMARY ===")
print(f"  {result['plan_summary']}")

print("\n=== HOURLY PLAN (first 6 and last 6 hours) ===")
plan = result["hourly_plan"]
for p in plan[:6] + plan[-6:]:
    act = p["battery_action"][0].upper()  # C/D/I
    print(f"  h{p['hour']:02d}: grid={p['grid_kwh']:6.1f} solar={p['solar_used_kwh']:5.1f} batt={act}{p['battery_kwh']:5.1f} soc={p['battery_energy_after_kwh']:6.1f}")
