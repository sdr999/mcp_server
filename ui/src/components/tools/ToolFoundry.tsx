import React, { useState } from 'react';
import { Hammer, Sparkles, CheckCircle2, AlertTriangle, Code, ShieldAlert, Copy, Check, Terminal, Cpu } from 'lucide-react';
import { api } from '../../services/api';
import { sfx } from '../../services/soundEffects';

export const ToolFoundry: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [mode, setMode] = useState<'prompt' | 'code'>('code');
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
  const [copied, setCopied] = useState(false);

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
    sfx.playCardSelectSound();
    setMode('code');
    setToolName('calculator');
    setSourceCode(`from tools_sdk import tool\n\n@tool()\ndef add(a: int, b: int) -> int:\n    return a + b\n`);
    setRequirementsStr('');
    setOverwrite(false);
    setAutoHeal(true);
  };

  const handleCopyPayload = () => {
    sfx.playTapSound();
    navigator.clipboard.writeText(JSON.stringify(getPayload(), null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleOnboardSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    sfx.playSpellCastSound();
    setLoading(true);
    setStatusMsg(null);
    setProposal(null);

    try {
      const payload = getPayload();
      const res = await api.onboardTool(payload);
      if (res.data?.status === 'pending') {
        setProposal(res.data);
        setStatusMsg({ type: 'success', text: 'Module held in pending queue for security review.' });
        sfx.playVictorySound();
      } else {
        setStatusMsg({ type: 'success', text: `Tactical Module '${payload.name}' successfully forged and loaded!` });
        sfx.playVictorySound();
        if (onExpGain) onExpGain(250);
      }
    } catch (err: any) {
      sfx.playErrorBuzz();
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.response?.data?.detail || 'Module onboarding failed.' });
    } finally {
      setLoading(false);
    }
  };

  const handleValidateSource = async () => {
    try {
      sfx.playTapSound();
      setLoading(true);
      const payload = {
        name: toolName || 'validate_tool',
        source: buildSourceCode(),
        requirements: getRequirementsArray()
      };
      const res = await api.validateSource(payload);
      setValidationResult(res.data);
      if (res.data?.valid) sfx.playVictorySound();
      else sfx.playErrorBuzz();
    } catch (err: any) {
      sfx.playErrorBuzz();
      setValidationResult({ valid: false, error: err.response?.data?.error || err.response?.data?.detail || 'Validation failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleAcceptProposal = async () => {
    if (!proposal) return;
    try {
      sfx.playSpellCastSound();
      setLoading(true);
      const payload = {
        name: proposal.name || toolName,
        source: proposal.code || proposal.source_code || proposal.source || buildSourceCode(),
        requirements: proposal.requirements || getRequirementsArray(),
        overwrite: true,
        auto_heal: true
      };
      await api.acceptProposal(payload);
      setStatusMsg({ type: 'success', text: 'Proposal approved! Module deployed to operational armory.' });
      setProposal(null);
      sfx.playVictorySound();
      if (onExpGain) onExpGain(500);
    } catch (err: any) {
      sfx.playErrorBuzz();
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.response?.data?.detail || 'Failed to accept proposal.' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div className="hud-panel" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
          <div style={{
            padding: '0.65rem',
            borderRadius: '0.375rem',
            background: 'rgba(255, 159, 28, 0.12)',
            border: '1px solid rgba(255, 159, 28, 0.4)',
            color: '#ff9f1c'
          }}>
            <Hammer style={{ width: '1.4rem', height: '1.4rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1.15rem', color: '#ffffff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              TACTICAL MODULE FOUNDRY
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
              AI MODULE FORGE & AST SYNTAX VALIDATOR (POST /admin/tools/onboard)
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            onClick={handleLoadSample}
            className="btn-sc btn-sc-emerald"
            style={{ fontSize: '0.7rem', padding: '0.35rem 0.75rem' }}
          >
            ⚡ LOAD SAMPLE CODE
          </button>
          
          {/* Mode Selector */}
          <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#070a10', padding: '0.25rem', borderRadius: '0.375rem', border: '1px solid #1e2c45', gap: '0.25rem' }}>
            <button
              onClick={() => { sfx.playTapSound(); setMode('code'); }}
              style={{
                padding: '0.35rem 0.75rem',
                borderRadius: '0.25rem',
                backgroundColor: mode === 'code' ? '#0284c7' : 'transparent',
                color: mode === 'code' ? '#ffffff' : '#94a3b8',
                fontWeight: 700,
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.75rem',
                fontFamily: 'var(--font-title)'
              }}
            >
              RAW PYTHON CODE
            </button>
            <button
              onClick={() => { sfx.playTapSound(); setMode('prompt'); }}
              style={{
                padding: '0.35rem 0.75rem',
                borderRadius: '0.25rem',
                backgroundColor: mode === 'prompt' ? '#0284c7' : 'transparent',
                color: mode === 'prompt' ? '#ffffff' : '#94a3b8',
                fontWeight: 700,
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.75rem',
                fontFamily: 'var(--font-title)'
              }}
            >
              PROMPT TO MODULE
            </button>
          </div>
        </div>
      </div>

      {statusMsg && (
        <div style={{
          padding: '1rem',
          borderRadius: '0.375rem',
          border: `1px solid ${statusMsg.type === 'success' ? '#10b981' : '#f43f5e'}`,
          fontSize: '0.8rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          backgroundColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
          color: statusMsg.type === 'success' ? '#34d399' : '#fb7185',
          fontFamily: 'var(--font-mono)'
        }}>
          {statusMsg.type === 'success' ? <CheckCircle2 style={{ width: '1.25rem', height: '1.25rem' }} /> : <AlertTriangle style={{ width: '1.25rem', height: '1.25rem' }} />}
          <span>{statusMsg.text}</span>
        </div>
      )}

      {/* Side-by-Side 12-column Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1.5rem' }}>
        {/* Left Column (7 cols): Module Authoring Form */}
        <form onSubmit={handleOnboardSubmit} className="hud-panel" style={{ gridColumn: 'span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e2c45', paddingBottom: '0.65rem' }}>
            <h4 className="font-title" style={{ fontSize: '0.85rem', color: '#00f0ff', letterSpacing: '0.05em', textTransform: 'uppercase', margin: 0 }}>
              1. COMPOSE TACTICAL MODULE
            </h4>
          </div>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              MODULE NAME ("name") <span style={{ color: '#fb7185' }}>*</span>
            </label>
            <input
              type="text"
              required
              value={toolName}
              onChange={e => setToolName(e.target.value)}
              placeholder="e.g. calculator"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '0.6rem 0.75rem', fontSize: '0.8rem', color: '#ffffff', outline: 'none' }}
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
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '0.6rem 0.75rem', fontSize: '0.8rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          {/* Options: Overwrite & Auto Heal */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '2rem', background: '#070a10', padding: '0.6rem 0.85rem', borderRadius: '0.375rem', border: '1px solid #1e2c45' }}>
            <label className="font-mono" style={{ fontSize: '0.75rem', color: '#cbd5e1', display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={overwrite}
                onChange={e => setOverwrite(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              <span>OVERWRITE ("overwrite")</span>
            </label>

            <label className="font-mono" style={{ fontSize: '0.75rem', color: '#cbd5e1', display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
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
                MODULE DESCRIPTION PROMPT ("source")
              </label>
              <textarea
                required
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                rows={6}
                placeholder="Describe what the tool should do..."
                className="font-mono"
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '0.75rem', fontSize: '0.8rem', color: '#ffffff', outline: 'none' }}
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
                  style={{ fontSize: '0.7rem', color: '#00f0ff', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.25rem', textDecoration: 'underline' }}
                >
                  <Code style={{ width: '0.8rem', height: '0.8rem' }} /> Validate Syntax
                </button>
              </div>
              <textarea
                required
                value={sourceCode}
                onChange={e => setSourceCode(e.target.value)}
                rows={8}
                className="font-mono"
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '0.75rem', fontSize: '0.8rem', color: '#38bdf8', outline: 'none' }}
              />
            </div>
          )}

          {validationResult && (
            <div className="font-mono" style={{ padding: '0.75rem', borderRadius: '0.375rem', fontSize: '0.75rem', backgroundColor: validationResult.valid ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)', color: validationResult.valid ? '#34d399' : '#fb7185', border: validationResult.valid ? '1px solid #10b981' : '1px solid #f43f5e' }}>
              Validation Status: {validationResult.valid ? 'PASSED SYNTAX CHECK' : `FAILED: ${validationResult.error}`}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn-sc btn-sc-orange font-title"
            style={{ width: '100%', padding: '0.75rem 0', fontSize: '0.85rem', marginTop: '0.5rem' }}
          >
            {loading ? 'SYNTHESIZING MODULE ON MCP CLUSTER...' : '⚡ SYNTHESIZE & ONBOARD MODULE'}
          </button>
        </form>

        {/* Right Column (5 cols): Live Request Payload Preview */}
        <div className="hud-panel" style={{ gridColumn: 'span 5', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e2c45', paddingBottom: '0.65rem' }}>
            <h4 className="font-title" style={{ fontSize: '0.85rem', color: '#fbbf24', letterSpacing: '0.05em', textTransform: 'uppercase', margin: 0 }}>
              2. ONBOARD REQUEST PAYLOAD
            </h4>
            <button
              onClick={handleCopyPayload}
              style={{
                background: '#0284c7',
                border: '1px solid #38bdf8',
                borderRadius: '0.25rem',
                color: '#ffffff',
                fontSize: '0.7rem',
                padding: '0.25rem 0.6rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.25rem',
                fontFamily: 'var(--font-title)'
              }}
            >
              {copied ? <Check style={{ width: '0.75rem', height: '0.75rem' }} /> : <Copy style={{ width: '0.75rem', height: '0.75rem' }} />}
              {copied ? 'COPIED!' : 'COPY PAYLOAD'}
            </button>
          </div>

          <div>
            <div className="font-mono" style={{ fontSize: '0.7rem', color: '#94a3b8', marginBottom: '0.35rem' }}>
              HTTP TARGET: <span style={{ color: '#00f0ff', fontWeight: 700 }}>POST /admin/tools/onboard</span>
            </div>
            <pre className="font-mono" style={{
              width: '100%',
              boxSizing: 'border-box',
              backgroundColor: '#070a10',
              border: '1px solid #1e2c45',
              borderRadius: '0.375rem',
              padding: '0.85rem',
              fontSize: '0.75rem',
              color: '#34d399',
              overflow: 'auto',
              maxHeight: '22rem',
              margin: 0
            }}>
              {JSON.stringify(getPayload(), null, 2)}
            </pre>
          </div>

          {proposal && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', paddingTop: '1rem', borderTop: '1px solid #1e2c45' }}>
              <div>
                <span className="font-title" style={{ fontSize: '0.75rem', color: '#fbbf24' }}>PENDING PROPOSAL GENERATED:</span>
                <p className="font-mono" style={{ fontSize: '0.85rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>{proposal.name || toolName}</p>
              </div>

              <button
                onClick={handleAcceptProposal}
                disabled={loading}
                className="btn-sc btn-sc-emerald font-title"
                style={{ width: '100%', padding: '0.75rem 0', fontSize: '0.8rem' }}
              >
                ACCEPT & APPROVE MODULE 🛡️
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
