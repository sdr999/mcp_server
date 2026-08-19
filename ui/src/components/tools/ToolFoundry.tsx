import React, { useState } from 'react';
import { Hammer, Sparkles, CheckCircle2, AlertTriangle, Code, ShieldAlert, ArrowLeftRight } from 'lucide-react';
import { api } from '../../services/api';

export const ToolFoundry: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [mode, setMode] = useState<'prompt' | 'code'>('prompt');
  const [toolName, setToolName] = useState('calculator');
  const [promptText, setPromptText] = useState('Performs arithmetic calculations (addition, subtraction).');
  const [sourceCode, setSourceCode] = useState(`from tools_sdk import tool\n\n@tool()\ndef add(a: int, b: int) -> int:\n    return a + b\n`);
  const [requirementsStr, setRequirementsStr] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [autoHeal, setAutoHeal] = useState(true);
  const [loading, setLoading] = useState(false);
  const [proposal, setProposal] = useState<any | null>(null);
  const [validationResult, setValidationResult] = useState<any | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const getRequirementsArray = () => {
    return requirementsStr
      .split(',')
      .map(r => r.trim())
      .filter(r => r.length > 0);
  };

  const buildSourceCode = () => {
    if (mode === 'code') return sourceCode;
    const safeName = (toolName.trim().replace(/\s+/g, '_') || 'custom_tool');
    const safeDesc = promptText.replace(/"/g, '\\"');
    return `from tools_sdk import tool\n\n@tool()\ndef ${safeName}(a: int = 1, b: int = 2) -> int:\n    """${safeDesc}"""\n    return a + b\n`;
  };

  const getPayload = () => {
    return {
      name: toolName.trim().replace(/\s+/g, '_') || 'calculator',
      source: buildSourceCode(),
      requirements: getRequirementsArray(),
      overwrite,
      auto_heal: autoHeal
    };
  };

  const handleLoadSample = () => {
    setMode('code');
    setToolName('calculator');
    setSourceCode(`from tools_sdk import tool\n\n@tool()\ndef add(a: int, b: int) -> int:\n    return a + b\n`);
    setRequirementsStr('');
    setOverwrite(false);
    setAutoHeal(true);
  };

  const handleOnboardSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusMsg(null);
    setProposal(null);

    try {
      const payload = getPayload();
      const res = await api.onboardTool(payload);
      if (res.data?.status === 'pending') {
        setProposal(res.data);
        setStatusMsg({ type: 'success', text: 'Tool held in pending queue for approval.' });
      } else {
        setStatusMsg({ type: 'success', text: `MCP Tool '${payload.name}' successfully forged and loaded!` });
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
        source: buildSourceCode(),
        requirements: getRequirementsArray()
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
        source: proposal.code || proposal.source_code || proposal.source || buildSourceCode(),
        requirements: proposal.requirements || getRequirementsArray(),
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

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            onClick={handleLoadSample}
            style={{ fontSize: '11px', color: '#34d399', fontFamily: 'var(--font-mono)', background: 'rgba(52, 211, 153, 0.1)', border: '1px solid rgba(52, 211, 153, 0.3)', borderRadius: '0.25rem', padding: '0.35rem 0.65rem', cursor: 'pointer' }}
          >
            ⚡ Load Sample Tool
          </button>
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
      </div>

      {statusMsg && (
        <div className="font-mono" style={{ padding: '1rem', borderRadius: '0.5rem', border: '1px solid', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)', borderColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)', color: statusMsg.type === 'success' ? '#34d399' : '#fb7185' }}>
          {statusMsg.type === 'success' ? <CheckCircle2 style={{ width: '1rem', height: '1rem' }} /> : <AlertTriangle style={{ width: '1rem', height: '1rem' }} />}
          <span>{statusMsg.text}</span>
        </div>
      )}

      {/* Onboarding Form */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
        <form onSubmit={handleOnboardSubmit} className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#fbbf24', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', margin: 0 }}>
            1. ONBOARD NEW MCP TOOL SPELL
          </h4>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              TOOL NAME ("name") <span style={{ color: '#fb7185' }}>*</span>
            </label>
            <input
              type="text"
              required
              value={toolName}
              onChange={e => setToolName(e.target.value)}
              placeholder="e.g. calculator"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              REQUIREMENTS ("requirements") <span style={{ fontSize: '10px', color: '#64748b', fontWeight: 400 }}>(comma-separated)</span>
            </label>
            <input
              type="text"
              value={requirementsStr}
              onChange={e => setRequirementsStr(e.target.value)}
              placeholder="e.g. requests, pydantic (optional)"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          {/* Options: Overwrite & Auto Heal */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            <label className="font-mono" style={{ fontSize: '0.75rem', color: '#cbd5e1', display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={overwrite}
                onChange={e => setOverwrite(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              <span>OVERWRITE ("overwrite")</span>
            </label>

            <label className="font-mono" style={{ fontSize: '0.75rem', color: '#cbd5e1', display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoHeal}
                onChange={e => setAutoHeal(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              <span>AUTO HEAL ("auto_heal")</span>
            </label>
          </div>

          {mode === 'prompt' ? (
            <div>
              <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
                TOOL DESCRIPTION PROMPT ("source")
              </label>
              <textarea
                required
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                rows={5}
                placeholder="Describe what the tool should do..."
                className="font-mono"
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
              />
            </div>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1' }}>
                  PYTHON SOURCE CODE ("source") (@tool)
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
                rows={8}
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
            className="btn-cr btn-cr-gold"
            style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.75rem 0', fontSize: '0.9rem' }}
          >
            {loading ? '🔨 FORGING TOOL IN WORKSHOP...' : '⚡ FORGE & DEPLOY CARD (+250 EXP)'}
          </button>
        </form>

        {/* Live Payload Preview & Proposal Inspector */}
        <div className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-title" style={{ fontSize: '0.9rem', color: '#fde047', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '2px solid #2a3e66', paddingBottom: '0.5rem', margin: 0 }}>
            2. ONBOARD REQUEST PAYLOAD PREVIEW
          </h4>

          <div>
            <div className="font-game" style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '0.25rem' }}>
              TARGET ENDPOINT: <span style={{ color: '#38bdf8', fontWeight: 700 }}>POST /admin/tools/onboard</span>
            </div>
            <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070e1e', border: '1px solid #2a3e66', borderRadius: '0.5rem', padding: '0.75rem', fontSize: '0.75rem', color: '#86efac', overflow: 'auto', maxHeight: '16rem', margin: 0 }}>
              {JSON.stringify(getPayload(), null, 2)}
            </pre>
          </div>

          {proposal && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', paddingTop: '1rem', borderTop: '2px solid #2a3e66' }}>
              <div>
                <span className="font-title" style={{ fontSize: '0.8rem', color: '#fde047' }}>PENDING PROPOSAL GENERATED:</span>
                <p className="font-game" style={{ fontSize: '0.9rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>{proposal.name || toolName}</p>
              </div>

              <button
                onClick={handleAcceptProposal}
                disabled={loading}
                className="btn-cr btn-cr-green"
                style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.75rem 0', fontSize: '0.85rem' }}
              >
                ACCEPT & APPROVE CARD 🛡️ (+500 EXP)
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
