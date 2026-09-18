import React from 'react';
import { 
  Cpu, 
  SunMedium, 
  BatteryLow, 
  ShieldAlert, 
  Ban, 
  CheckCircle2, 
  XCircle, 
  ArrowRight,
  Info
} from 'lucide-react';
import { DirectiveInterpretation, DirectiveType } from '../types';

interface DirectivePanelProps {
  directives: DirectiveInterpretation[] | null;
  operatorNotes: string[];
  isLoading: boolean;
}

export const DirectivePanel: React.FC<DirectivePanelProps> = ({
  directives,
  operatorNotes,
  isLoading,
}) => {
  const getDirectiveBadge = (type: DirectiveType) => {
    switch (type) {
      case 'solar_reduction':
        return {
          icon: <SunMedium className="w-3.5 h-3.5" />,
          color: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
          label: 'solar_reduction',
        };
      case 'minimum_battery_reserve':
        return {
          icon: <BatteryLow className="w-3.5 h-3.5" />,
          color: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
          label: 'minimum_battery_reserve',
        };
      case 'no_charge_window':
        return {
          icon: <Ban className="w-3.5 h-3.5" />,
          color: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
          label: 'no_charge_window',
        };
      case 'no_discharge_window':
        return {
          icon: <Ban className="w-3.5 h-3.5" />,
          color: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
          label: 'no_discharge_window',
        };
      case 'max_grid_window':
        return {
          icon: <ShieldAlert className="w-3.5 h-3.5" />,
          color: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
          label: 'max_grid_window',
        };
      case 'no_op':
      default:
        return {
          icon: <Info className="w-3.5 h-3.5" />,
          color: 'text-slate-400 bg-slate-800/60 border-slate-700',
          label: 'no_op (ignored)',
        };
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-5 space-y-4 shadow-xl">
      <div className="flex items-center justify-between border-b border-slate-800/70 pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide flex items-center gap-2">
              AI Directive Interpretation
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/20">
                Gemini 2.5 Flash + Guardrails
              </span>
            </h2>
            <p className="text-[11px] text-slate-400">
              Natural language transformed into verifiable mathematical linear constraints
            </p>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 flex flex-col items-center justify-center space-y-2 text-slate-400 animate-pulse">
          <Cpu className="w-6 h-6 text-purple-400 animate-spin" />
          <span className="text-xs font-mono">Parsing semantic constraints with Gemini...</span>
        </div>
      ) : !directives || directives.length === 0 ? (
        <div className="py-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
          Run an optimization scenario to view parsed operational directives.
        </div>
      ) : (
        <div className="space-y-3">
          {directives.map((dir, idx) => {
            const badge = getDirectiveBadge(dir.directive_type);
            const rawNote = operatorNotes[dir.note_index] || operatorNotes[idx] || '';
            const adj = dir.structured_adjustment || {};
            const hours: number[] = Array.isArray(adj.hours) ? adj.hours : [];

            return (
              <div 
                key={idx} 
                className={`p-3.5 rounded-xl border transition-all ${
                  dir.applies 
                    ? 'bg-slate-950/70 border-slate-800 hover:border-slate-700' 
                    : 'bg-slate-950/40 border-slate-800/60 opacity-80'
                }`}
              >
                {/* Header row */}
                <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-bold text-slate-300 bg-slate-800 px-2 py-0.5 rounded">
                      NOTE {dir.note_index + 1}
                    </span>
                    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-mono font-medium ${badge.color}`}>
                      {badge.icon}
                      <span>{badge.label}</span>
                    </div>
                  </div>

                  {/* Applies badge */}
                  <div>
                    {dir.applies ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                        <CheckCircle2 className="w-3 h-3" /> APPLIED
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-400">
                        <XCircle className="w-3 h-3" /> IGNORED
                      </span>
                    )}
                  </div>
                </div>

                {/* Original Note Quote */}
                <div className="text-xs text-slate-300 italic mb-2.5 pl-2.5 border-l-2 border-slate-700">
                  "{rawNote}"
                </div>

                {/* Structured parameters details if applies */}
                {dir.applies && (
                  <div className="bg-slate-900/90 border border-slate-800/80 rounded-lg p-2.5 mb-2.5 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono">
                    {hours.length > 0 && (
                      <div>
                        <span className="text-[10px] text-slate-500 block uppercase">Target Window</span>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {hours.map(h => (
                            <span key={h} className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                              {h.toString().padStart(2, '0')}:00
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {adj.minimum_energy_kwh !== undefined && (
                      <div>
                        <span className="text-[10px] text-slate-500 block uppercase">Min Energy Reserve</span>
                        <span className="text-purple-300 font-semibold">{adj.minimum_energy_kwh} kWh</span>
                      </div>
                    )}

                    {adj.factor !== undefined && (
                      <div>
                        <span className="text-[10px] text-slate-500 block uppercase">Solar Output Factor</span>
                        <span className="text-amber-300 font-semibold">{(adj.factor * 100).toFixed(0)}% (x{adj.factor})</span>
                      </div>
                    )}

                    {adj.max_grid_kwh !== undefined && (
                      <div>
                        <span className="text-[10px] text-slate-500 block uppercase">Max Grid Import Cap</span>
                        <span className="text-cyan-300 font-semibold">{adj.max_grid_kwh} kWh</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Gemini Explanation */}
                <div className="text-[11px] text-slate-400 flex items-start gap-1.5 leading-relaxed">
                  <ArrowRight className="w-3 h-3 text-slate-500 mt-0.5 flex-shrink-0" />
                  <span>{dir.explanation}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
