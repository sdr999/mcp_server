import React, { useState } from 'react';
import { Hammer, Sparkles, CheckCircle2, AlertTriangle, Code, ShieldAlert, ArrowLeftRight } from 'lucide-react';
import { api } from '../../services/api';

export const ToolFoundry: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [mode, setMode] = useState<'prompt' | 'code'>('prompt');
  const [toolName, setToolName] = useState('');
  const [promptText, setPromptText] = useState('');
  const [sourceCode, setSourceCode] = useState(`@tool\ndef my_new_mcp_tool(x: int) -> int:\n    """Calculates square of input x."""\n    return x * x\n`);
  const [loading, setLoading] = useState(false);
  const [proposal, setProposal] = useState<any | null>(null);
  const [validationResult, setValidationResult] = useState<any | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleOnboardSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusMsg(null);
    setProposal(null);

    try {
      const payload = {
        name: toolName,
        mode,
        prompt: promptText,
        source_code: mode === 'code' ? sourceCode : undefined
      };
      const res = await api.onboardTool(payload);
      if (res.data?.proposal) {
        setProposal(res.data.proposal);
        setStatusMsg({ type: 'success', text: 'AI Tool proposal generated! Review code below before forging.' });
      } else {
        setStatusMsg({ type: 'success', text: `MCP Tool '${toolName}' successfully forged and loaded!` });
        if (onExpGain) onExpGain(250);
      }
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.detail || 'Tool onboarding failed.' });
    } finally {
      setLoading(false);
    }
  };

  const handleValidateSource = async () => {
    try {
      setLoading(true);
      const res = await api.validateSource({ source_code: sourceCode });
      setValidationResult(res.data);
    } catch (err: any) {
      setValidationResult({ valid: false, error: err.response?.data?.detail || 'Validation failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleAcceptProposal = async () => {
    if (!proposal) return;
    try {
      setLoading(true);
      await api.acceptProposal({ proposal_id: proposal.id || proposal.name || toolName });
      setStatusMsg({ type: 'success', text: 'Proposal accepted! Tool forged into runtime spellbook.' });
      setProposal(null);
      if (onExpGain) onExpGain(500);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to accept proposal.' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Hammer className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider flex items-center gap-2">
              THE TOOL FOUNDRY <Sparkles className="w-4 h-4 text-amber-400 animate-spin" />
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              AI-POWERED TOOL FORGE & SYNTAX VALIDATOR (/admin/tools/onboard)
            </p>
          </div>
        </div>

        {/* Mode Selector */}
        <div className="flex items-center gap-2 bg-slate-900 p-1 rounded-lg border border-slate-700 font-mono text-xs">
          <button
            onClick={() => setMode('prompt')}
            className={`px-3 py-1.5 rounded transition-all ${
              mode === 'prompt' ? 'bg-cyan-500 text-black font-bold' : 'text-slate-400 hover:text-white'
            }`}
          >
            PROMPT TO TOOL
          </button>
          <button
            onClick={() => setMode('code')}
            className={`px-3 py-1.5 rounded transition-all ${
              mode === 'code' ? 'bg-cyan-500 text-black font-bold' : 'text-slate-400 hover:text-white'
            }`}
          >
            RAW PYTHON CODE
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className={`p-4 rounded-lg border text-xs font-mono flex items-center gap-2 ${
          statusMsg.type === 'success'
            ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'
            : 'bg-rose-500/10 border-rose-500/40 text-rose-400'
        }`}>
          {statusMsg.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          <span>{statusMsg.text}</span>
        </div>
      )}

      {/* Onboarding Form */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <form onSubmit={handleOnboardSubmit} className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-amber-400 tracking-wider uppercase border-b border-slate-800 pb-2">
            1. ONBOARD NEW MCP TOOL SPELL
          </h4>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              TOOL NAME (UNIQUE IDENTIFIER)
            </label>
            <input
              type="text"
              required
              value={toolName}
              onChange={e => setToolName(e.target.value)}
              placeholder="e.g. calculate_crypto_yield"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
            />
          </div>

          {mode === 'prompt' ? (
            <div>
              <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
                AI TOOL PROMPT DESCRIPTION
              </label>
              <textarea
                required
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                rows={6}
                placeholder="Describe what the tool should do (e.g., 'A tool that fetches stock prices and returns 7-day volatility analysis')..."
                className="w-full bg-slate-950 border border-slate-700 rounded p-3 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-mono font-bold text-slate-300">
                  PYTHON SOURCE CODE (@tool)
                </label>
                <button
                  type="button"
                  onClick={handleValidateSource}
                  className="text-[11px] font-mono text-cyan-400 hover:underline flex items-center gap-1"
                >
                  <Code className="w-3 h-3" /> Validate Syntax
                </button>
              </div>
              <textarea
                required
                value={sourceCode}
                onChange={e => setSourceCode(e.target.value)}
                rows={10}
                className="w-full bg-slate-950 border border-slate-700 rounded p-3 text-xs text-emerald-400 font-mono focus:outline-none focus:border-cyan-400"
              />
            </div>
          )}

          {validationResult && (
            <div className={`p-3 rounded text-xs font-mono ${
              validationResult.valid ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
            }`}>
              Validation Status: {validationResult.valid ? 'PASSED SYNTAX CHECK' : `FAILED: ${validationResult.error}`}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full btn-neon-cyan justify-center py-3 text-xs tracking-widest"
          >
            {loading ? 'FORGING TOOL...' : 'FORGE & REGISTER TOOL ⚡ (+250 EXP)'}
          </button>
        </form>

        {/* AI Proposal Code Inspector & Accept Box */}
        <div className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-cyan-400 tracking-wider uppercase border-b border-slate-800 pb-2">
            2. AI GENERATED CODE PROPOSAL INSPECTOR
          </h4>

          {proposal ? (
            <div className="space-y-4">
              <div>
                <span className="text-xs font-mono text-slate-400">PROPOSAL NAME:</span>
                <p className="text-sm font-bold text-white font-mono">{proposal.name || toolName}</p>
              </div>

              <div>
                <span className="text-xs font-mono text-slate-400">GENERATED PYTHON CODE:</span>
                <pre className="w-full bg-slate-950 border border-slate-800 rounded p-3 font-mono text-xs text-emerald-400 overflow-auto max-h-64 mt-1">
                  {proposal.code || proposal.source_code || JSON.stringify(proposal, null, 2)}
                </pre>
              </div>

              <button
                onClick={handleAcceptProposal}
                disabled={loading}
                className="w-full btn-neon-magenta justify-center py-3 text-xs tracking-widest"
              >
                ACCEPT & APPROVE PROPOSAL 🛡️ (+500 EXP)
              </button>
            </div>
          ) : (
            <div className="text-center py-20 text-slate-500 font-mono text-xs">
              <Sparkles className="w-10 h-10 text-slate-700 mx-auto mb-3 animate-bounce" />
              Submit an AI prompt on the left to generate and inspect code proposals.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
