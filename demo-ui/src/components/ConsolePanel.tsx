import React, { useState } from 'react';
import { 
  Terminal, 
  Sparkles, 
  Plus, 
  Trash2, 
  Layers, 
  Sliders, 
  Play, 
  Loader2,
  Bookmark
} from 'lucide-react';
import { OptimizeRequest, ScenarioPreset } from '../types';
import { PRESETS } from '../presets';

interface ConsolePanelProps {
  request: OptimizeRequest;
  setRequest: React.Dispatch<React.SetStateAction<OptimizeRequest>>;
  onOptimize: () => void;
  isLoading: boolean;
  activePresetId: string | null;
  onSelectPreset: (preset: ScenarioPreset) => void;
  loadingStage: string;
}

export const ConsolePanel: React.FC<ConsolePanelProps> = ({
  request,
  setRequest,
  onOptimize,
  isLoading,
  activePresetId,
  onSelectPreset,
  loadingStage,
}) => {
  const [showBatteryDetails, setShowBatteryDetails] = useState(false);

  const handleAddNote = () => {
    if (request.operator_notes.length >= 3) return;
    setRequest(prev => ({
      ...prev,
      operator_notes: [...prev.operator_notes, '']
    }));
  };

  const handleRemoveNote = (index: number) => {
    if (request.operator_notes.length <= 1) return;
    setRequest(prev => ({
      ...prev,
      operator_notes: prev.operator_notes.filter((_, i) => i !== index)
    }));
  };

  const handleUpdateNote = (index: number, text: string) => {
    setRequest(prev => {
      const updated = [...prev.operator_notes];
      updated[index] = text;
      return { ...prev, operator_notes: updated };
    });
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md p-5 space-y-4 shadow-xl">
      {/* Panel Header */}
      <div className="flex items-center justify-between border-b border-slate-800/70 pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <Terminal className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Operator Directive Console
            </h2>
            <p className="text-[11px] text-slate-400">
              Input natural language shift notes or select an operational challenge preset
            </p>
          </div>
        </div>

        {/* Preset Selector Chips */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-mono text-slate-500 hidden sm:inline mr-1 flex items-center gap-1">
            <Bookmark className="w-3 h-3" /> Presets:
          </span>
          {PRESETS.map(preset => (
            <button
              key={preset.id}
              onClick={() => onSelectPreset(preset)}
              disabled={isLoading}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-all ${
                activePresetId === preset.id
                  ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300 shadow-sm shadow-emerald-500/20'
                  : 'bg-slate-800/60 border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600'
              }`}
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>

      {/* Scenario ID & Battery Configuration Strip */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between text-xs">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <span className="text-slate-400 font-mono text-[11px]">SCENARIO_ID:</span>
          <input
            type="text"
            value={request.scenario_id}
            onChange={(e) => setRequest(p => ({ ...p, scenario_id: e.target.value }))}
            className="bg-slate-950/80 border border-slate-800 rounded-lg px-2.5 py-1 font-mono text-slate-200 text-xs w-full sm:w-56 focus:outline-none focus:border-emerald-500/50"
            placeholder="e.g. SCENARIO-LIVE-01"
          />
        </div>

        <button
          type="button"
          onClick={() => setShowBatteryDetails(v => !v)}
          className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-800 hover:border-slate-700 transition-colors w-full sm:w-auto justify-center"
        >
          <Sliders className="w-3 h-3" />
          <span>Battery: {request.battery.capacity_kwh} kWh ({request.battery.initial_energy_kwh} init)</span>
        </button>
      </div>

      {/* Collapsible Battery Spec */}
      {showBatteryDetails && (
        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-xl grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs font-mono">
          <div>
            <span className="text-[10px] text-slate-500 block uppercase">Capacity</span>
            <span className="text-slate-200 font-semibold">{request.battery.capacity_kwh} kWh</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 block uppercase">Initial SoC</span>
            <span className="text-slate-200 font-semibold">{request.battery.initial_energy_kwh} kWh</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 block uppercase">Min Reserve</span>
            <span className="text-slate-200 font-semibold">{request.battery.minimum_energy_kwh} kWh</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 block uppercase">Max Charge</span>
            <span className="text-slate-200 font-semibold">{request.battery.max_charge_kwh_per_hour} kW</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 block uppercase">Max Dischg</span>
            <span className="text-slate-200 font-semibold">{request.battery.max_discharge_kwh_per_hour} kW</span>
          </div>
        </div>
      )}

      {/* Operator Notes Inputs */}
      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
            <span>Natural Language Operator Directives</span>
            <span className="text-[11px] text-slate-500 font-normal">
              ({request.operator_notes.length}/3 notes)
            </span>
          </label>
          {request.operator_notes.length < 3 && (
            <button
              type="button"
              onClick={handleAddNote}
              disabled={isLoading}
              className="text-[11px] text-emerald-400 hover:text-emerald-300 flex items-center gap-1 px-2 py-0.5 rounded border border-emerald-500/20 hover:border-emerald-500/40 transition-colors"
            >
              <Plus className="w-3 h-3" /> Add Note
            </button>
          )}
        </div>

        {request.operator_notes.map((note, idx) => (
          <div key={idx} className="relative group">
            <div className="absolute left-2.5 top-2.5 flex items-center justify-center w-5 h-5 rounded bg-slate-800 text-[10px] font-mono text-slate-400 font-semibold">
              {idx + 1}
            </div>
            <textarea
              rows={2}
              value={note}
              onChange={(e) => handleUpdateNote(idx, e.target.value)}
              placeholder={`Enter operational instruction (e.g. "Keep at least 40% battery reserve from 6 PM to 10 PM")`}
              disabled={isLoading}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-xl pl-10 pr-10 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/20 transition-all font-sans leading-relaxed resize-none"
            />
            {request.operator_notes.length > 1 && (
              <button
                type="button"
                onClick={() => handleRemoveNote(idx)}
                disabled={isLoading}
                title="Remove this note"
                className="absolute right-2.5 top-2.5 p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Prominent Action Button & Multi-stage loading */}
      <div className="pt-2">
        <button
          onClick={onOptimize}
          disabled={isLoading}
          className={`w-full py-3 px-4 rounded-xl font-semibold text-sm tracking-wide flex items-center justify-center gap-2.5 transition-all shadow-lg ${
            isLoading
              ? 'bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700'
              : 'bg-gradient-to-r from-emerald-600 via-teal-600 to-emerald-500 hover:from-emerald-500 hover:to-teal-500 text-white shadow-emerald-500/20 border border-emerald-400/30 hover:scale-[1.008] active:scale-[0.995]'
          }`}
        >
          {isLoading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
              <span>{loadingStage || 'Processing Optimization...'}</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4 text-emerald-200 fill-emerald-200/20" />
              <span>OPTIMIZE 24-HOUR PLAN</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
