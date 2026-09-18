import React, { useState, useEffect } from 'react';
import { 
  Zap, 
  Cpu, 
  Clock, 
  Monitor, 
  CheckCircle2, 
  AlertCircle
} from 'lucide-react';

interface HeaderProps {
  isHealthy: boolean | null;
  presentationMode: boolean;
  setPresentationMode: (val: boolean | ((prev: boolean) => boolean)) => void;
  onRefreshHealth: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  isHealthy,
  presentationMode,
  setPresentationMode,
  onRefreshHealth,
}) => {
  const [time, setTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-US', { hour12: false }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl sticky top-0 z-40 px-4 lg:px-8 py-3.5 transition-all">
      <div className="max-w-[1720px] mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        {/* Left: Brand Identity */}
        <div className="flex items-center space-x-3.5">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 text-emerald-400 shadow-lg shadow-emerald-500/10">
            <Zap className="w-5 h-5 fill-emerald-400/20" />
            <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                GridWise
                <span className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  Control Room
                </span>
              </h1>
            </div>
            <p className="text-xs text-slate-400 font-medium">
              AI-Assisted Smart Campus Energy Optimization
              <span className="hidden sm:inline text-slate-600 mx-1.5">·</span>
              <span className="hidden sm:inline text-slate-500 font-mono text-[11px]">BUP CSE Fest 2026</span>
            </p>
          </div>
        </div>

        {/* Right: Telemetry & Controls */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Health Status */}
          <div 
            onClick={onRefreshHealth}
            title="Click to re-check health"
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-mono font-medium cursor-pointer transition-all ${
              isHealthy === true
                ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-400 hover:bg-emerald-950/50 shadow-sm shadow-emerald-950/50'
                : isHealthy === false
                ? 'bg-red-950/30 border-red-500/30 text-red-400 hover:bg-red-950/50'
                : 'bg-slate-900 border-slate-800 text-slate-400'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${
              isHealthy === true 
                ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]' 
                : isHealthy === false
                ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]'
                : 'bg-slate-500'
            }`} />
            <span>{isHealthy === true ? 'SYSTEM ONLINE' : isHealthy === false ? 'API OFFLINE' : 'CHECKING...'}</span>
          </div>

          {/* AI Engine Status */}
          <div className="hidden lg:flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-purple-950/30 border border-purple-500/30 text-purple-300 text-xs font-mono font-medium">
            <Cpu className="w-3.5 h-3.5 text-purple-400" />
            <span>GEMINI 2.5 FLASH</span>
          </div>

          {/* Real-time Clock */}
          <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300 text-xs font-mono">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span>{time || '--:--:--'}</span>
          </div>

          {/* Presentation Mode Toggle */}
          <button
            onClick={() => setPresentationMode(p => !p)}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${
              presentationMode 
                ? 'bg-amber-500/15 border-amber-500/40 text-amber-300 shadow-sm shadow-amber-500/10'
                : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
            }`}
            title="Toggle Presentation Mode (enhances typography and streamlines layout for 1080p projectors)"
          >
            <Monitor className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Presentation Mode</span>
          </button>
        </div>
      </div>
    </header>
  );
};
