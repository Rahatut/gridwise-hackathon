import React, { useState } from 'react';
import { Code2, Copy, Check, ChevronDown, ChevronUp } from 'lucide-react';
import { OptimizeRequest, OptimizeResponse } from '../types';

interface TechnicalInspectorProps {
  request: OptimizeRequest;
  response: OptimizeResponse | null;
}

export const TechnicalInspector: React.FC<TechnicalInspectorProps> = ({
  request,
  response,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'request' | 'response'>('response');
  const [copied, setCopied] = useState<boolean>(false);

  const jsonString = activeTab === 'request'
    ? JSON.stringify(request, null, 2)
    : response
    ? JSON.stringify(response, null, 2)
    : '// No response payload available yet. Run an optimization scenario to inspect output.';

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-md shadow-xl overflow-hidden transition-all">
      {/* Header */}
      <button
        type="button"
        onClick={() => setIsOpen(o => !o)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-center space-x-2.5">
          <div className="w-7 h-7 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <Code2 className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Technical API Inspector (Judge Verification)
            </h2>
            <p className="text-[11px] text-slate-400">
              Live inspection of canonical POST /optimize-energy input and output JSON
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>{isOpen ? 'Hide JSON' : 'Inspect JSON'}</span>
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {isOpen && (
        <div className="border-t border-slate-800/70 p-4 pt-0 space-y-3">
          <div className="flex items-center justify-between pt-3">
            {/* Tabs */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setActiveTab('request')}
                className={`px-3 py-1 rounded-lg text-xs font-mono font-medium border transition-colors ${
                  activeTab === 'request'
                    ? 'bg-slate-800 border-slate-700 text-white'
                    : 'bg-slate-950 border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                REQUEST JSON (POST /optimize-energy)
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('response')}
                className={`px-3 py-1 rounded-lg text-xs font-mono font-medium border transition-colors ${
                  activeTab === 'response'
                    ? 'bg-slate-800 border-slate-700 text-white'
                    : 'bg-slate-950 border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                RESPONSE JSON (200 OK)
              </button>
            </div>

            {/* Copy Button */}
            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-mono text-slate-300 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy JSON</span>
                </>
              )}
            </button>
          </div>

          {/* Code Viewer */}
          <pre className="p-4 bg-slate-950 rounded-xl border border-slate-800/80 font-mono text-xs text-emerald-400/90 max-h-[350px] overflow-y-auto scrollbar-thin whitespace-pre-wrap leading-relaxed">
            {jsonString}
          </pre>
        </div>
      )}
    </div>
  );
};
