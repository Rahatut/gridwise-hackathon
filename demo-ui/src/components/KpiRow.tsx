import React from 'react';
import { CircleDollarSign, Zap, Activity, BatteryCharging, Check } from 'lucide-react';
import { OptimizeResponse, BatterySpec } from '../types';

interface KpiRowProps {
  response: OptimizeResponse | null;
  battery: BatterySpec;
  presentationMode: boolean;
}

export const KpiRow: React.FC<KpiRowProps> = ({ response, battery, presentationMode }) => {
  const totalCost = response ? response.total_cost_bdt : null;
  const totalGrid = response ? response.total_grid_kwh : null;
  const peakGrid = response ? response.peak_grid_kwh : null;
  const finalBattery = response && response.hourly_plan.length > 0 
    ? response.hourly_plan[response.hourly_plan.length - 1].battery_energy_after_kwh 
    : null;

  const isRestored = finalBattery !== null && Math.abs(finalBattery - battery.initial_energy_kwh) < 0.05;

  const cardBaseClass = `relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-4 lg:p-5 transition-all duration-300 hover:border-slate-700/80 hover:shadow-lg`;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
      {/* 1. Total Cost */}
      <div className={`${cardBaseClass} hover:shadow-emerald-500/5`}>
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
            Total Grid Cost
          </span>
          <div className="w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <CircleDollarSign className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className="text-xs text-slate-400 font-semibold">৳</span>
          <span className={`font-mono font-bold tracking-tight text-white ${
            presentationMode ? 'text-2xl lg:text-3xl' : 'text-xl lg:text-2xl'
          }`}>
            {totalCost !== null ? totalCost.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--'}
          </span>
          <span className="text-[11px] text-slate-400 font-mono">BDT</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-emerald-400">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          <span>LP Cost Minimised</span>
        </div>
      </div>

      {/* 2. Total Grid Energy */}
      <div className={`${cardBaseClass} hover:shadow-cyan-500/5`}>
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
            Total Grid Import
          </span>
          <div className="w-8 h-8 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
            <Zap className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className={`font-mono font-bold tracking-tight text-white ${
            presentationMode ? 'text-2xl lg:text-3xl' : 'text-xl lg:text-2xl'
          }`}>
            {totalGrid !== null ? totalGrid.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '--'}
          </span>
          <span className="text-[11px] text-slate-400 font-mono">kWh</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-cyan-400">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
          <span>Net 24h Consumption</span>
        </div>
      </div>

      {/* 3. Peak Grid Import */}
      <div className={`${cardBaseClass} hover:shadow-blue-500/5`}>
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
            Peak Grid Draw
          </span>
          <div className="w-8 h-8 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
            <Activity className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className={`font-mono font-bold tracking-tight text-white ${
            presentationMode ? 'text-2xl lg:text-3xl' : 'text-xl lg:text-2xl'
          }`}>
            {peakGrid !== null ? peakGrid.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '--'}
          </span>
          <span className="text-[11px] text-slate-400 font-mono">kWh/h</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400"></span>
          <span>Substation Peak Load</span>
        </div>
      </div>

      {/* 4. Final Battery State */}
      <div className={`${cardBaseClass} hover:shadow-purple-500/5`}>
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
            End-of-Day SoC
          </span>
          <div className="w-8 h-8 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <BatteryCharging className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className={`font-mono font-bold tracking-tight text-white ${
            presentationMode ? 'text-2xl lg:text-3xl' : 'text-xl lg:text-2xl'
          }`}>
            {finalBattery !== null ? finalBattery.toFixed(1) : '--'}
          </span>
          <span className="text-xs text-slate-400 font-mono">/ {battery.capacity_kwh} kWh</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px]">
          {isRestored ? (
            <span className="text-emerald-400 font-medium flex items-center gap-1">
              <Check className="w-3 h-3" /> RESTORED ({battery.initial_energy_kwh} kWh)
            </span>
          ) : finalBattery !== null ? (
            <span className="text-amber-400">Shifted from {battery.initial_energy_kwh} kWh</span>
          ) : (
            <span className="text-slate-500">Target: {battery.initial_energy_kwh} kWh</span>
          )}
        </div>
      </div>
    </div>
  );
};
