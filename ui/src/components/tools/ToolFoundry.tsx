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
      const generatedSource = mode === 'code' 
        ? sourceCode 
        : `@tool\ndef ${toolName.trim().replace(/\s+/g, '_') || 'custom_tool'}() -> str:\n    """${promptText.replace(/"/g, '\\"')}"""\n    return "Tool executed: ${promptText.replace(/"/g, '\\"')}"\n`;

      const payload = {
        name: toolName.trim().replace(/\s+/g, '_'),
        source: generatedSource,
        requirements: [],
        overwrite: false,
        auto_heal: true
      };
      const res = await api.onboardTool(payload);
      if (res.data?.status === 'pending') {
        setProposal(res.data);
        setStatusMsg({ type: 'success', text: 'Tool held in pending queue for approval.' });
      } else {
        setStatusMsg({ type: 'success', text: `MCP Tool '${toolName}' successfully forged and loaded!` });
        if (onExpGain) onExpGain(250);
      }
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.response?.data?.detail || 'Tool onboarding failed.' });
    } finally {
      setLoading(false);
    }
  };

  const handleValidateSource = async () => {
    try {
      setLoading(true);
      const payload = {
        name: toolName || 'validate_tool',
        source: sourceCode,
        requirements: []
      };
      const res = await api.validateSource(payload);
      setValidationResult(res.data);
    } catch (err: any) {
      setValidationResult({ valid: false, error: err.response?.data?.error || err.response?.data?.detail || 'Validation failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleAcceptProposal = async () => {
    if (!proposal) return;
    try {
      setLoading(true);
      const payload = {
        name: proposal.name || toolName,
        source: proposal.code || proposal.source_code || proposal.source || sourceCode,
        requirements: proposal.requirements || [],
        overwrite: true,
        auto_heal: true
      };
      await api.acceptProposal(payload);
      setStatusMsg({ type: 'success', text: 'Proposal accepted! Tool forged into runtime spellbook.' });
      setProposal(null);
      if (onExpGain) onExpGain(500);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.response?.data?.detail || 'Failed to accept proposal.' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div className="hud-panel" style={{ padding: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', color: '#fbbf24' }}>
            <Hammer style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', letterSpacing: '0.05em', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              THE TOOL FOUNDRY <Sparkles style={{ width: '1rem', height: '1rem', color: '#fbbf24' }} />
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem' }}>
              AI-POWERED TOOL FORGE & SYNTAX VALIDATOR (/admin/tools/onboard)
            </p>
          </div>
        </div>

        {/* Mode Selector */}
        <div className="font-mono" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: '#0f172a', padding: '0.25rem', borderRadius: '0.5rem', border: '1px solid #334155', fontSize: '0.75rem' }}>
          <button
            onClick={() => setMode('prompt')}
            style={{ padding: '0.375rem 0.75rem', borderRadius: '0.25rem', transition: 'all 0.2s', backgroundColor: mode === 'prompt' ? '#22d3ee' : 'transparent', color: mode === 'prompt' ? '#000000' : '#94a3b8', fontWeight: mode === 'prompt' ? 700 : 400, border: 'none', cursor: 'pointer' }}
          >
            PROMPT TO TOOL
          </button>
          <button
            onClick={() => setMode('code')}
            style={{ padding: '0.375rem 0.75rem', borderRadius: '0.25rem', transition: 'all 0.2s', backgroundColor: mode === 'code' ? '#22d3ee' : 'transparent', color: mode === 'code' ? '#000000' : '#94a3b8', fontWeight: mode === 'code' ? 700 : 400, border: 'none', cursor: 'pointer' }}
          >
            RAW PYTHON CODE
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{ padding: '1rem', borderRadius: '0.5rem', border: '1px solid', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)', borderColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)', color: statusMsg.type === 'success' ? '#34d399' : '#fb7185' }}>
          {statusMsg.type === 'success' ? <CheckCircle2 style={{ width: '1rem', height: '1rem' }} /> : <AlertTriangle style={{ width: '1rem', height: '1rem' }} />}
          <span>{statusMsg.text}</span>
        </div>
      )}

      {/* Onboarding Form */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
        <form onSubmit={handleOnboardSubmit} className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#fbbf24', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', margin: 0 }}>
            1. ONBOARD NEW MCP TOOL SPELL
          </h4>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              TOOL NAME (UNIQUE IDENTIFIER)
            </label>
            <input
              type="text"
              required
              value={toolName}
              onChange={e => setToolName(e.target.value)}
              placeholder="e.g. calculate_crypto_yield"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          {mode === 'prompt' ? (
            <div>
              <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
                AI TOOL PROMPT DESCRIPTION
              </label>
              <textarea
                required
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                rows={6}
                placeholder="Describe what the tool should do (e.g., 'A tool that fetches stock prices and returns 7-day volatility analysis')..."
                className="font-mono"
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
              />
            </div>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1' }}>
                  PYTHON SOURCE CODE (@tool)
                </label>
                <button
                  type="button"
                  onClick={handleValidateSource}
                  className="font-mono"
                  style={{ fontSize: '0.6875rem', color: '#22d3ee', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.25rem', textDecoration: 'none' }}
                >
                  <Code style={{ width: '0.75rem', height: '0.75rem' }} /> Validate Syntax
                </button>
              </div>
              <textarea
                required
                value={sourceCode}
                onChange={e => setSourceCode(e.target.value)}
                rows={10}
                className="font-mono"
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#34d399', outline: 'none' }}
              />
            </div>
          )}

          {validationResult && (
            <div className="font-mono" style={{ padding: '0.75rem', borderRadius: '0.25rem', fontSize: '0.75rem', backgroundColor: validationResult.valid ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)', color: validationResult.valid ? '#34d399' : '#fb7185', border: validationResult.valid ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(244, 63, 94, 0.3)' }}>
              Validation Status: {validationResult.valid ? 'PASSED SYNTAX CHECK' : `FAILED: ${validationResult.error}`}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn-neon-cyan"
            style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.75rem 0', fontSize: '0.75rem', letterSpacing: '0.1em' }}
          >
            {loading ? 'FORGING TOOL...' : 'FORGE & REGISTER TOOL ⚡ (+250 EXP)'}
          </button>
        </form>

        {/* AI Proposal Code Inspector & Accept Box */}
        <div className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22d3ee', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', margin: 0 }}>
            2. AI GENERATED CODE PROPOSAL INSPECTOR
          </h4>

          {proposal ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <span className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8' }}>PROPOSAL NAME:</span>
                <p className="font-mono" style={{ fontSize: '0.875rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>{proposal.name || toolName}</p>
              </div>

              <div>
                <span className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8' }}>GENERATED PYTHON CODE:</span>
                <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#34d399', overflow: 'auto', maxHeight: '16rem', marginTop: '0.25rem', margin: 0 }}>
                  {proposal.code || proposal.source_code || JSON.stringify(proposal, null, 2)}
                </pre>
              </div>

              <button
                onClick={handleAcceptProposal}
                disabled={loading}
                className="btn-neon-magenta"
                style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.75rem 0', fontSize: '0.75rem', letterSpacing: '0.1em' }}
              >
                ACCEPT & APPROVE PROPOSAL 🛡️ (+500 EXP)
              </button>
            </div>
          ) : (
            <div className="font-mono" style={{ textAlign: 'center', padding: '5rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              <Sparkles style={{ width: '2.5rem', height: '2.5rem', color: '#334155', margin: '0 auto 0.75rem auto' }} />
              Submit an AI prompt on the left to generate and inspect code proposals.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
