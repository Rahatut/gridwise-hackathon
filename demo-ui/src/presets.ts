import { BatterySpec, HourEntry, ScenarioPreset } from './types';

const defaultBattery: BatterySpec = {
  capacity_kwh: 200,
  initial_energy_kwh: 100,
  minimum_energy_kwh: 20,
  max_charge_kwh_per_hour: 50,
  max_discharge_kwh_per_hour: 50,
};

const makeHours = (solarMultiplier: number = 1.0): HourEntry[] => {
  const baseDemand = [
    100, 95, 90, 85, 85, 90, 110, 130, 150, 165, 175, 180,
    185, 180, 170, 160, 155, 165, 210, 230, 220, 190, 145, 115
  ];
  const baseSolar = [
    0, 0, 0, 0, 0, 0, 10, 30, 65, 100, 125, 140,
    145, 135, 115, 80, 45, 15, 0, 0, 0, 0, 0, 0
  ];
  const baseTariff = [
    8, 8, 8, 8, 8, 8, 10, 10, 12, 12, 12, 14,
    14, 14, 14, 14, 12, 12, 16, 16, 16, 14, 10, 8
  ];

  return Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    demand_kwh: baseDemand[h],
    solar_kwh: Math.round(baseSolar[h] * solarMultiplier),
    tariff_bdt_per_kwh: baseTariff[h],
  }));
};

export const PRESETS: ScenarioPreset[] = [
  {
    id: 'emergency_reserve',
    name: 'Emergency Battery Reserve',
    subtitle: 'Preserve battery energy for evening operations',
    scenario_id: 'PRESET-EMERGENCY-RESERVE-01',
    battery: { ...defaultBattery },
    hours: makeHours(1.0),
    operator_notes: [
      'Keep at least 50% of the battery capacity stored from 6 PM until 9 PM for emergency operations.',
      'Control room climate control set to standard eco-mode.'
    ],
  },
  {
    id: 'solar_maintenance',
    name: 'Solar Maintenance',
    subtitle: 'Midday panel cleaning reduces PV output',
    scenario_id: 'PRESET-SOLAR-MAINT-02',
    battery: { ...defaultBattery },
    hours: makeHours(1.0),
    operator_notes: [
      'Technicians will be testing the solar inverter from noon until 2 PM — treat solar output as zero during that window.'
    ],
  },
  {
    id: 'peak_grid_restriction',
    name: 'Peak Grid Restriction',
    subtitle: 'Limit grid import during peak hours',
    scenario_id: 'PRESET-PEAK-GRID-LIMIT-03',
    battery: { ...defaultBattery },
    hours: makeHours(1.0),
    operator_notes: [
      'Regional feeder bottleneck alert: cap grid import at 160 kWh between 18:00 and 21:00.'
    ],
  },
  {
    id: 'battery_maintenance',
    name: 'Battery Maintenance',
    subtitle: 'Charging temporarily unavailable',
    scenario_id: 'PRESET-BATTERY-MAINT-04',
    battery: { ...defaultBattery },
    hours: makeHours(1.0),
    operator_notes: [
      'Do not charge the battery between 1 PM and 4 PM due to thermal sensor calibration.'
    ],
  },
  {
    id: 'mixed_operations',
    name: 'Mixed Operations',
    subtitle: 'Multiple directives + irrelevant operator note',
    scenario_id: 'PRESET-MIXED-OPS-05',
    battery: { ...defaultBattery },
    hours: makeHours(1.0),
    operator_notes: [
      'Maintain at least 40% battery reserve from 6 PM to 10 PM for emergency outages.',
      'Technicians will be cleaning solar arrays from 11 AM to 1 PM — reduce solar generation by 50% during that time.',
      'Shift handover completed and safety log signed off by engineer on duty.'
    ],
  },
];
