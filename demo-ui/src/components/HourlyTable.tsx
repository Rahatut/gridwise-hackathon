import React, { useState } from 'react';
import { Table, ChevronDown, ChevronUp } from 'lucide-react';
import { HourlyPlanEntry, HourEntry, BatteryAction } from '../types';

interface HourlyTableProps {
  plan: HourlyPlanEntry[] | null;
  hours: HourEntry[];
}

export const HourlyTable: React.FC<HourlyTableProps> = ({ plan, hours }) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);

  const getActionBadge = (action: BatteryAction) => {
    switch (action) {
      case 'charge':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
            CHARGE
          </span>
        );
      case 'discharge':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/15 border border-cyan-500/30 text-cyan-400">
            DISCHARGE
          </span>
        );
      case 'idle':
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono text-slate-500 bg-slate-800">
            IDLE
          </span>
        );
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md shadow-xl overflow-hidden transition-all">
      {/* Accordion Header */}
      <button
        type="button"
        onClick={() => setIsOpen(o => !o)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
            <Table className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              24-Hour Dispatch Schedule (Tabular View)
            </h2>
            <p className="text-[11px] text-slate-400">
              Detailed breakdown of hourly balances, solar self-consumption, and battery energy
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>{isOpen ? 'Collapse Schedule' : 'Expand Schedule'}</span>
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {isOpen && (
        <div className="border-t border-slate-800/70 p-4 pt-0">
          <div className="max-h-[360px] overflow-y-auto rounded-xl border border-slate-800 scrollbar-thin">
            <table className="w-full text-left text-xs font-mono border-collapse">
              <thead className="bg-slate-950/90 sticky top-0 z-10 text-slate-400 border-b border-slate-800 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="py-2.5 px-3">Hour</th>
                  <th className="py-2.5 px-3 text-right">Demand</th>
                  <th className="py-2.5 px-3 text-right">Solar Used</th>
                  <th className="py-2.5 px-3 text-right">Grid Import</th>
                  <th className="py-2.5 px-3 text-center">Battery Action</th>
                  <th className="py-2.5 px-3 text-right">Battery kWh</th>
                  <th className="py-2.5 px-3 text-right">Battery After</th>
                  <th className="py-2.5 px-3 text-right">Tariff (BDT)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 bg-slate-950/40 text-slate-200">
                {hours.map((h, i) => {
                  const p = plan ? plan[i] : null;
                  return (
                    <tr key={h.hour} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-2 px-3 font-bold text-slate-300">
                        {h.hour.toString().padStart(2, '0')}:00
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300">
                        {h.demand_kwh.toFixed(1)}
                      </td>
                      <td className="py-2 px-3 text-right text-amber-300">
                        {p ? p.solar_used_kwh.toFixed(1) : '--'}
                        <span className="text-[10px] text-slate-500 ml-1">/ {h.solar_kwh}</span>
                      </td>
                      <td className="py-2 px-3 text-right text-cyan-300 font-semibold">
                        {p ? p.grid_kwh.toFixed(1) : '--'}
                      </td>
                      <td className="py-2 px-3 text-center">
                        {p ? getActionBadge(p.battery_action) : '--'}
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300">
                        {p ? p.battery_kwh.toFixed(1) : '--'}
                      </td>
                      <td className="py-2 px-3 text-right text-purple-300 font-semibold">
                        {p ? p.battery_energy_after_kwh.toFixed(1) : '--'}
                      </td>
                      <td className="py-2 px-3 text-right text-amber-400">
                        ৳ {h.tariff_bdt_per_kwh.toFixed(1)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
