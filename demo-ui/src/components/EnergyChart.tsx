import React from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
  ReferenceArea
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import { HourEntry, HourlyPlanEntry, DirectiveInterpretation } from '../types';

interface EnergyChartProps {
  hours: HourEntry[];
  plan: HourlyPlanEntry[] | null;
  directives: DirectiveInterpretation[] | null;
}

export const EnergyChart: React.FC<EnergyChartProps> = ({
  hours,
  plan,
  directives,
}) => {
  // Merge input hours with solved plan entries
  const chartData = hours.map((h, i) => {
    const planEntry = plan ? plan[i] : null;
    return {
      hourLabel: `${h.hour.toString().padStart(2, '0')}:00`,
      hour: h.hour,
      demand: h.demand_kwh,
      solarAvailable: h.solar_kwh,
      solarUsed: planEntry ? planEntry.solar_used_kwh : 0,
      grid: planEntry ? planEntry.grid_kwh : 0,
      tariff: h.tariff_bdt_per_kwh,
    };
  });

  // Extract active directive hour ranges for subtle background highlights
  const activeWindows: { start: number; end: number; type: string; label: string }[] = [];
  if (directives) {
    directives.filter(d => d.applies && d.structured_adjustment?.hours).forEach(d => {
      const hrs: number[] = d.structured_adjustment!.hours;
      if (hrs.length > 0) {
        const minH = Math.min(...hrs);
        const maxH = Math.max(...hrs);
        activeWindows.push({
          start: minH,
          end: maxH,
          type: d.directive_type,
          label: d.directive_type.replace(/_/g, ' ')
        });
      }
    });
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-slate-900/95 border border-slate-700/80 rounded-xl p-3 shadow-2xl backdrop-blur-md text-xs font-mono">
          <div className="flex items-center justify-between border-b border-slate-800 pb-1.5 mb-2">
            <span className="font-bold text-slate-200">Hour {data.hourLabel}</span>
            <span className="text-amber-400 font-semibold">{data.tariff} BDT/kWh</span>
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-4 text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-slate-400"></span> Campus Demand:
              </span>
              <span className="font-bold text-white">{data.demand.toFixed(1)} kWh</span>
            </div>
            <div className="flex items-center justify-between gap-4 text-cyan-300">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-cyan-400"></span> Grid Import:
              </span>
              <span className="font-bold text-cyan-200">{data.grid.toFixed(1)} kWh</span>
            </div>
            <div className="flex items-center justify-between gap-4 text-amber-300">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-amber-400"></span> Solar Used:
              </span>
              <span className="font-bold text-amber-200">{data.solarUsed.toFixed(1)} kWh</span>
            </div>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-5 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800/70 pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              24-Hour Energy Dispatch Profile
            </h2>
            <p className="text-[11px] text-slate-400">
              Demand fulfillment via solar dispatch, battery arbitrage, and grid draw
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-mono">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="w-2.5 h-0.5 border-t-2 border-dashed border-slate-300"></span> Demand
          </span>
          <span className="flex items-center gap-1.5 text-cyan-400">
            <span className="w-2.5 h-2.5 rounded-sm bg-cyan-500/50"></span> Grid Draw
          </span>
          <span className="flex items-center gap-1.5 text-amber-400">
            <span className="w-2.5 h-2.5 rounded-sm bg-amber-500/50"></span> Solar Used
          </span>
        </div>
      </div>

      <div className="h-[280px] w-full pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
            <defs>
              <linearGradient id="gridGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="solarGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.0} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis 
              dataKey="hourLabel" 
              stroke="#64748b" 
              tick={{ fontSize: 10, fill: '#64748b' }} 
              interval={2} 
            />
            <YAxis 
              stroke="#64748b" 
              tick={{ fontSize: 10, fill: '#64748b' }} 
              unit=" kWh" 
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Directive Window Translucent Highlights */}
            {activeWindows.map((win, idx) => (
              <ReferenceArea
                key={idx}
                x1={`${win.start.toString().padStart(2, '0')}:00`}
                x2={`${win.end.toString().padStart(2, '0')}:00`}
                strokeOpacity={0.3}
                fill="#a855f7"
                fillOpacity={0.12}
                label={{
                  value: `Directive Window`,
                  position: 'insideTop',
                  fill: '#c084fc',
                  fontSize: 10,
                  fontFamily: 'monospace'
                }}
              />
            ))}

            {/* Demand Reference Line */}
            <Line
              type="monotone"
              dataKey="demand"
              stroke="#94a3b8"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
              name="Demand"
            />

            {/* Solar Used Area */}
            <Area
              type="monotone"
              dataKey="solarUsed"
              stroke="#f59e0b"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#solarGrad)"
              name="Solar Used"
            />

            {/* Grid Draw Area */}
            <Area
              type="monotone"
              dataKey="grid"
              stroke="#06b6d4"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#gridGrad)"
              name="Grid Draw"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
