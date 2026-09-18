import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { KpiRow } from './components/KpiRow';
import { ConsolePanel } from './components/ConsolePanel';
import { DirectivePanel } from './components/DirectivePanel';
import { EnergyChart } from './components/EnergyChart';
import { BatteryChart } from './components/BatteryChart';
import { StrategyCard } from './components/StrategyCard';
import { ValidationPanel } from './components/ValidationPanel';
import { HourlyTable } from './components/HourlyTable';
import { TechnicalInspector } from './components/TechnicalInspector';
import { checkHealth, optimizeEnergy } from './api';
import { OptimizeRequest, OptimizeResponse, ScenarioPreset } from './types';
import { PRESETS } from './presets';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export const App: React.FC = () => {
  const [request, setRequest] = useState<OptimizeRequest>({
    scenario_id: PRESETS[0].scenario_id,
    battery: PRESETS[0].battery,
    hours: PRESETS[0].hours,
    operator_notes: [...PRESETS[0].operator_notes],
  });
  const [activePresetId, setActivePresetId] = useState<string | null>(PRESETS[0].id);
  const [response, setResponse] = useState<OptimizeResponse | null>(null);
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [loadingStage, setLoadingStage] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [presentationMode, setPresentationMode] = useState<boolean>(false);

  // Health check on mount
  const runHealthCheck = async () => {
    try {
      await checkHealth();
      setIsHealthy(true);
    } catch {
      setIsHealthy(false);
    }
  };

  useEffect(() => {
    runHealthCheck();
    const interval = setInterval(runHealthCheck, 20000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectPreset = (preset: ScenarioPreset) => {
    setActivePresetId(preset.id);
    setRequest({
      scenario_id: preset.scenario_id,
      battery: { ...preset.battery },
      hours: [...preset.hours],
      operator_notes: [...preset.operator_notes],
    });
    setErrorMessage(null);
  };

  const handleRunOptimization = async () => {
    if (isLoading) return;
    setIsLoading(true);
    setErrorMessage(null);
    setLoadingStage('Interpreting operator notes with Gemini...');

    // Progress animation timers
    const timer1 = setTimeout(() => {
      setLoadingStage('Applying deterministic guardrails & bounds...');
    }, 1200);
    const timer2 = setTimeout(() => {
      setLoadingStage('Executing cost-minimisation LP solver...');
    }, 2200);
    const timer3 = setTimeout(() => {
      setLoadingStage('Running independent validator checks...');
    }, 3200);

    try {
      const res = await optimizeEnergy(request);
      setResponse(res);
      setIsHealthy(true);
    } catch (err: any) {
      console.error('Optimization error:', err);
      setErrorMessage(err.message || 'GridWise optimization service returned an error.');
    } finally {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      setIsLoading(false);
      setLoadingStage('');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans flex flex-col selection:bg-emerald-500/20 selection:text-emerald-300">
      {/* Subtle Control Room Background Glow */}
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(16,185,129,0.06),rgba(255,255,255,0))]" />
      
      {/* Top Navbar */}
      <Header
        isHealthy={isHealthy}
        presentationMode={presentationMode}
        setPresentationMode={setPresentationMode}
        onRefreshHealth={runHealthCheck}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-[1720px] w-full mx-auto p-4 lg:p-6 space-y-4 lg:space-y-6 relative z-10">
        {/* Error Notification Banner */}
        {errorMessage && (
          <div className="rounded-xl border border-red-500/40 bg-red-950/40 backdrop-blur-md p-4 flex items-center justify-between gap-3 text-red-200 text-xs shadow-lg animate-fade-in">
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />
              <div>
                <span className="font-semibold block">Optimization Failed</span>
                <span className="text-red-300/90">{errorMessage}</span>
              </div>
            </div>
            <button
              onClick={handleRunOptimization}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 text-xs font-medium transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* Top KPI Cards Row */}
        <KpiRow
          response={response}
          battery={request.battery}
          presentationMode={presentationMode}
        />

        {/* Two-Column Grid: Operations (65%) and Strategy/Validation (35%) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-6">
          {/* Left Column (65%) */}
          <div className="lg:col-span-7 xl:col-span-8 space-y-4 lg:space-y-6">
            {/* Operator Directives Console */}
            <ConsolePanel
              request={request}
              setRequest={setRequest}
              onOptimize={handleRunOptimization}
              isLoading={isLoading}
              activePresetId={activePresetId}
              onSelectPreset={handleSelectPreset}
              loadingStage={loadingStage}
            />

            {/* AI Directive Interpretation */}
            <DirectivePanel
              directives={response?.directive_interpretation || null}
              operatorNotes={request.operator_notes}
              isLoading={isLoading}
            />

            {/* Main 24-Hour Energy Dispatch Chart */}
            <EnergyChart
              hours={request.hours}
              plan={response?.hourly_plan || null}
              directives={response?.directive_interpretation || null}
            />
          </div>

          {/* Right Column (35%) */}
          <div className="lg:col-span-5 xl:col-span-4 space-y-4 lg:space-y-6">
            {/* Optimization Strategy Card */}
            <StrategyCard summary={response?.plan_summary || null} />

            {/* Battery SoC & Arbitrage Chart */}
            <BatteryChart
              battery={request.battery}
              plan={response?.hourly_plan || null}
            />

            {/* System Validation Panel */}
            <ValidationPanel
              response={response}
              battery={request.battery}
              hours={request.hours}
            />
          </div>
        </div>

        {/* Full-Width Bottom Accordions */}
        <div className="space-y-4 lg:space-y-6">
          {/* 24-Hour Schedule Table */}
          <HourlyTable
            plan={response?.hourly_plan || null}
            hours={request.hours}
          />

          {/* Technical JSON Inspector for Judges */}
          <TechnicalInspector
            request={request}
            response={response}
          />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950/80 py-4 px-6 text-center text-xs text-slate-500 font-mono">
        <div className="max-w-[1720px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>GridWise Energy Optimisation Platform · Official BUP CSE Fest 2026 Submission</span>
          <span className="text-slate-600">Linear Programming (HiGHS) + Google Gemini 2.5 Flash</span>
        </div>
      </footer>
    </div>
  );
};

export default App;
