"""CLI testing tool for GridWise natural language operator notes.

Usage:
    python scripts/test_prompt.py "Keep at least 30% battery reserve from 6pm to 9pm"
    python scripts/test_prompt.py --interactive
    python scripts/test_prompt.py --file test_request.json
"""
import sys
import os
import json
import argparse
import requests

DEFAULT_URL = "http://127.0.0.1:8000/optimize-energy"

SAMPLE_PAYLOAD = {
    "scenario_id": "CLI-TEST-01",
    "operator_notes": [],
    "battery": {
        "capacity_kwh": 200,
        "initial_energy_kwh": 100,
        "minimum_energy_kwh": 20,
        "max_charge_kwh_per_hour": 50,
        "max_discharge_kwh_per_hour": 50
    },
    "hours": [
        {"hour": 0,  "demand_kwh": 100, "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 1,  "demand_kwh": 95,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 2,  "demand_kwh": 90,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 3,  "demand_kwh": 90,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 4,  "demand_kwh": 90,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 5,  "demand_kwh": 95,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0},
        {"hour": 6,  "demand_kwh": 110, "solar_kwh": 0,   "tariff_bdt_per_kwh": 10.0},
        {"hour": 7,  "demand_kwh": 130, "solar_kwh": 10,  "tariff_bdt_per_kwh": 10.0},
        {"hour": 8,  "demand_kwh": 150, "solar_kwh": 30,  "tariff_bdt_per_kwh": 12.0},
        {"hour": 9,  "demand_kwh": 160, "solar_kwh": 60,  "tariff_bdt_per_kwh": 12.0},
        {"hour": 10, "demand_kwh": 170, "solar_kwh": 90,  "tariff_bdt_per_kwh": 12.0},
        {"hour": 11, "demand_kwh": 175, "solar_kwh": 110, "tariff_bdt_per_kwh": 14.0},
        {"hour": 12, "demand_kwh": 180, "solar_kwh": 120, "tariff_bdt_per_kwh": 14.0},
        {"hour": 13, "demand_kwh": 175, "solar_kwh": 115, "tariff_bdt_per_kwh": 14.0},
        {"hour": 14, "demand_kwh": 170, "solar_kwh": 100, "tariff_bdt_per_kwh": 14.0},
        {"hour": 15, "demand_kwh": 160, "solar_kwh": 70,  "tariff_bdt_per_kwh": 14.0},
        {"hour": 16, "demand_kwh": 150, "solar_kwh": 40,  "tariff_bdt_per_kwh": 12.0},
        {"hour": 17, "demand_kwh": 160, "solar_kwh": 15,  "tariff_bdt_per_kwh": 12.0},
        {"hour": 18, "demand_kwh": 200, "solar_kwh": 0,   "tariff_bdt_per_kwh": 16.0},
        {"hour": 19, "demand_kwh": 220, "solar_kwh": 0,   "tariff_bdt_per_kwh": 16.0},
        {"hour": 20, "demand_kwh": 210, "solar_kwh": 0,   "tariff_bdt_per_kwh": 16.0},
        {"hour": 21, "demand_kwh": 190, "solar_kwh": 0,   "tariff_bdt_per_kwh": 14.0},
        {"hour": 22, "demand_kwh": 150, "solar_kwh": 0,   "tariff_bdt_per_kwh": 10.0},
        {"hour": 23, "demand_kwh": 120, "solar_kwh": 0,   "tariff_bdt_per_kwh": 8.0}
    ]
}

def run_test(notes, url=DEFAULT_URL):
    payload = dict(SAMPLE_PAYLOAD)
    payload["operator_notes"] = notes
    
    print(f"\n[+] Sending request to {url} with {len(notes)} note(s)...")
    for i, n in enumerate(notes):
        print(f"    Note [{i}]: \"{n}\"")
        
    try:
        resp = requests.post(url, json=payload, timeout=35)
        if resp.status_code != 200:
            print(f"[!] Server returned {resp.status_code}: {resp.text}")
            return
            
        data = resp.json()
        print("\n========================================================")
        print("                 GEMINI INTERPRETATION                  ")
        print("========================================================")
        for d in data.get("directive_interpretation", []):
            status = "APPLIED" if d.get("applies") else "IGNORED"
            print(f"Note [{d.get('note_index')}]: [{status}] {d.get('directive_type')}")
            print(f"  Adjustment : {d.get('structured_adjustment')}")
            print(f"  Explanation: {d.get('explanation')}")
            print()
            
        print("========================================================")
        print("                  OPTIMIZATION SUMMARY                  ")
        print("========================================================")
        print(f"Total Cost : {data.get('total_cost_bdt'):.2f} BDT")
        print(f"Total Grid : {data.get('total_grid_kwh'):.2f} kWh")
        print(f"Peak Grid  : {data.get('peak_grid_kwh'):.2f} kWh")
        print(f"\nPlan Summary:\n{data.get('plan_summary')}")
        print("========================================================")
    except Exception as e:
        print(f"[!] Error connecting to server: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test natural language operator notes")
    parser.add_argument("notes", nargs="*", help="One or more operator note strings")
    parser.add_argument("--url", default=DEFAULT_URL, help="GridWise endpoint URL")
    parser.add_argument("--file", help="Path to a full request JSON file")
    parser.add_argument("--interactive", action="store_true", help="Interactive prompt mode")
    
    args = parser.parse_args()
    
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            full_payload = json.load(f)
        notes = full_payload.get("operator_notes", [])
        run_test(notes, args.url)
    elif args.interactive:
        print("--- GridWise Natural Language Interactive Test ---")
        print("Enter notes one by one. Press Enter on an empty line to run. Type 'exit' to quit.\n")
        while True:
            collected = []
            while True:
                line = input(f"Note #{len(collected)} > ").strip()
                if line.lower() == "exit":
                    sys.exit(0)
                if not line:
                    break
                collected.append(line)
            if collected:
                run_test(collected, args.url)
                print("\n" + "-"*50 + "\n")
    elif args.notes:
        run_test(args.notes, args.url)
    else:
        # Default demo test
        default_notes = [
            "Keep at least 40% battery reserve from 6 PM to 10 PM for emergency outages.",
            "Technicians will be testing the solar inverter from noon until 2 PM — treat solar output as zero.",
            "Reminder: Tomorrow's shift handover is at 8 AM."
        ]
        print("No notes provided. Running with sample natural language notes:")
        run_test(default_notes, args.url)
