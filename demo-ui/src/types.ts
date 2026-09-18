export type DirectiveType =
  | 'solar_reduction'
  | 'minimum_battery_reserve'
  | 'no_charge_window'
  | 'no_discharge_window'
  | 'max_grid_window'
  | 'no_op';

export type BatteryAction = 'charge' | 'discharge' | 'idle';

export interface BatterySpec {
  capacity_kwh: number;
  initial_energy_kwh: number;
  minimum_energy_kwh: number;
  max_charge_kwh_per_hour: number;
  max_discharge_kwh_per_hour: number;
}

export interface HourEntry {
  hour: number;
  demand_kwh: number;
  solar_kwh: number;
  tariff_bdt_per_kwh: number;
}

export interface OptimizeRequest {
  scenario_id: string;
  battery: BatterySpec;
  hours: HourEntry[];
  operator_notes: string[];
}

export interface DirectiveInterpretation {
  note_index: number;
  applies: boolean;
  directive_type: DirectiveType;
  structured_adjustment?: Record<string, any> | null;
  explanation: string;
}

export interface HourlyPlanEntry {
  hour: number;
  grid_kwh: number;
  solar_used_kwh: number;
  battery_action: BatteryAction;
  battery_kwh: number;
  battery_energy_after_kwh: number;
}

export interface OptimizeResponse {
  scenario_id: string;
  directive_interpretation: DirectiveInterpretation[];
  hourly_plan: HourlyPlanEntry[];
  total_grid_kwh: number;
  total_cost_bdt: number;
  peak_grid_kwh: number;
  plan_summary: string;
}

export interface ScenarioPreset {
  id: string;
  name: string;
  subtitle: string;
  scenario_id: string;
  battery: BatterySpec;
  hours: HourEntry[];
  operator_notes: string[];
}
