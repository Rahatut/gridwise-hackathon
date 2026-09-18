import React from 'react';
import { Compass, CheckCircle2, ShieldCheck, Clock, DollarSign } from 'lucide-react';

interface StrategyCardProps {
  summary: string | null;
}

export const StrategyCard: React.FC<StrategyCardProps> = ({ summary }) => {
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-5 shadow-xl space-y-3">
      <div className="flex items-center justify-between border-b border-slate-800/70 pb-2.5">
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
            <Compass className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Optimization Strategy
            </h2>
            <p className="text-[11px] text-slate-400">
              Deterministic operational rationale generated from LP dispatch results
            </p>
          </div>
        </div>
      </div>

      {/* Chips */}
      <div className="flex flex-wrap gap-1.5 pt-0.5">
        <span className="inline-flex items-center gap-1 text-[10px] font-mono font-medium px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <DollarSign className="w-3 h-3" /> COST MINIMIZED
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] font-mono font-medium px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
          <Clock className="w-3 h-3" /> 24 HOURS
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] font-mono font-medium px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400">
          <ShieldCheck className="w-3 h-3" /> VALIDATED
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] font-mono font-medium px-2.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400">
          <CheckCircle2 className="w-3 h-3" /> END SOC RESTORED
        </span>
      </div>

      {/* Text summary */}
      <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 text-xs text-slate-200 leading-relaxed font-sans">
        {summary || 'Run an optimization to view the generated strategy summary.'}
      </div>
    </div>
  );
};
