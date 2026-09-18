import React from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import { BatteryCharging, ShieldCheck } from 'lucide-react';
import { BatterySpec, HourlyPlanEntry } from '../types';

interface BatteryChartProps {
  battery: BatterySpec;
  plan: HourlyPlanEntry[] | null;
}

export const BatteryChart: React.FC<BatteryChartProps> = ({ battery, plan }) => {
  const chartData = (plan || []).map(p => {
    const chargeVal = p.battery_action === 'charge' ? p.battery_kwh : 0;
    const dischargeVal = p.battery_action === 'discharge' ? -p.battery_kwh : 0;
    return {
      hourLabel: `${p.hour.toString().padStart(2, '0')}:00`,
      hour: p.hour,
      soc: p.battery_energy_after_kwh,
      charge: chargeVal,
      discharge: dischargeVal,
      action: p.battery_action,
      amount: p.battery_kwh,
    };
  });

  const finalSoC = plan && plan.length > 0 
    ? plan[plan.length - 1].battery_energy_after_kwh 
    : battery.initial_energy_kwh;
  const isNeutral = Math.abs(finalSoC - battery.initial_energy_kwh) < 0.05;

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div className="bg-slate-900/95 border border-slate-700 rounded-xl p-3 shadow-2xl backdrop-blur-md text-xs font-mono">
          <div className="border-b border-slate-800 pb-1 mb-1.5 font-bold text-slate-200">
            Hour {d.hourLabel}
          </div>
          <div className="space-y-1">
            <div className="text-purple-300">
              State of Charge: <span className="font-bold">{d.soc.toFixed(1)} kWh</span>
            </div>
            <div className="text-slate-400">
              Action:{' '}
              <span className={`font-semibold uppercase ${
                d.action === 'charge' ? 'text-emerald-400' : d.action === 'discharge' ? 'text-cyan-400' : 'text-slate-400'
              }`}>
                {d.action} {d.amount > 0 ? `(${d.amount.toFixed(1)} kWh)` : ''}
              </span>
            </div>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-5 shadow-xl space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/70 pb-2.5">
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <BatteryCharging className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Battery Strategy & Arbitrage
            </h2>
            <p className="text-[11px] text-slate-400">
              Hourly State of Charge curve & bidirectional energy dispatch
            </p>
          </div>
        </div>

        {isNeutral && plan && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-mono font-bold tracking-wide">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>NEUTRALITY VERIFIED ✓</span>
          </div>
        )}
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-4 gap-2 text-center text-xs font-mono py-1 border-b border-slate-800/60">
        <div>
          <span className="text-[10px] text-slate-500 block">Initial</span>
          <span className="text-slate-300 font-semibold">{battery.initial_energy_kwh} kWh</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 block">Min Floor</span>
          <span className="text-slate-300 font-semibold">{battery.minimum_energy_kwh} kWh</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 block">Capacity</span>
          <span className="text-slate-300 font-semibold">{battery.capacity_kwh} kWh</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 block">Final SoC</span>
          <span className={`font-semibold ${isNeutral ? 'text-emerald-400' : 'text-slate-300'}`}>
            {finalSoC.toFixed(1)} kWh
          </span>
        </div>
      </div>

      {/* Recharts Chart */}
      <div className="h-[200px] w-full pt-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis 
              dataKey="hourLabel" 
              stroke="#64748b" 
              tick={{ fontSize: 9, fill: '#64748b' }} 
              interval={2} 
            />
            <YAxis 
              stroke="#64748b" 
              tick={{ fontSize: 9, fill: '#64748b' }} 
              domain={[0, battery.capacity_kwh]}
              unit=" kWh" 
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Minimum battery bound line */}
            <ReferenceLine 
              y={battery.minimum_energy_kwh} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={{ value: 'Min Limit', fill: '#ef4444', fontSize: 9, position: 'insideBottomLeft' }} 
            />

            {/* Initial / Neutrality Reference Line */}
            <ReferenceLine 
              y={battery.initial_energy_kwh} 
              stroke="#10b981" 
              strokeDasharray="2 2" 
              strokeOpacity={0.6}
            />

            {/* State of Charge curve */}
            <Line
              type="monotone"
              dataKey="soc"
              stroke="#a855f7"
              strokeWidth={2.5}
              dot={{ r: 2, fill: '#c084fc' }}
              activeDot={{ r: 5 }}
              name="Battery SoC"
            />

            {/* Charge bars (positive emerald/amber) */}
            <Bar dataKey="charge" fill="#10b981" opacity={0.6} />

            {/* Discharge bars (negative cyan) */}
            <Bar dataKey="discharge" fill="#06b6d4" opacity={0.6} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
