import React, { useEffect, useState } from 'react';
import { ShieldCheck, Plus, RefreshCw, MessageSquare, Copy, CheckCircle2 } from 'lucide-react';
import { api } from '../../services/api';

export const PromptVault: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [prompts, setPrompts] = useState<any[]>([]);
  const [promptName, setPromptName] = useState('');
  const [promptText, setPromptText] = useState('');
  const [selectedPrompt, setSelectedPrompt] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchPrompts = async () => {
    try {
      setLoading(true);
      const res = await api.getPrompts();
      const raw = res.data;
      if (Array.isArray(raw)) setPrompts(raw);
      else if (raw?.prompts) setPrompts(raw.prompts);
      else if (typeof raw === 'object') {
        const list = Object.entries(raw).map(([name, val]: [string, any]) => ({
          name,
          ...val
        }));
        setPrompts(list);
      }
    } catch (e) {
      console.error('Failed to load prompts', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, []);

  const handleRegisterPrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.registerPrompt({ name: promptName, template: promptText });
      setStatusMsg(`Prompt template '${promptName}' saved to Archmage Vault!`);
      setPromptName('');
      setPromptText('');
      fetchPrompts();
      if (onExpGain) onExpGain(150);
    } catch (err: any) {
      setStatusMsg(`Failed to save prompt: ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
      {/* Header */}
      <div className="hud-panel" style={{padding: '1.0rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: '0.75rem'}}>
          <div style={{padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(168, 85, 247, 0.1)', border: '1px solid #1e293b', borderColor: 'rgba(168, 85, 247, 0.3)', color: '#c084fc'}}>
            <ShieldCheck style={{width: '1.25rem', height: '1.25rem'}} />
          </div>
          <div>
            <h3 style={{fontSize: '1rem', fontWeight: '700', color: '#ffffff', letterSpacing: '0.05em'}}>
              ARCHMAGE PROMPT VAULT
            </h3>
            <p className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>
              SYSTEM PROMPT TEMPLATES & VARIANT MANAGEMENT (/admin/prompts*)
            </p>
          </div>
        </div>

        <button onClick={fetchPrompts} className="btn-neon-cyan" style={{fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem'}}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: 'rgba(8, 51, 68, 0.6)', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.4)', color: '#67e8f9', fontSize: '0.75rem'}}>
          {statusMsg}
        </div>
      )}

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '1.5rem'}}>
        {/* Form */}
        <form onSubmit={handleRegisterPrompt} className="hud-panel" style={{padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#c084fc', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem'}}>
            REGISTER NEW PROMPT TEMPLATE
          </h4>

          <div>
            <label className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>
              PROMPT TEMPLATE NAME
            </label>
            <input
              type="text"
              required
              value={promptName}
              onChange={e => setPromptName(e.target.value)}
              placeholder="e.g. system_analyst_persona"
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
          </div>

          <div>
            <label className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>
              PROMPT TEXT (SUPPORT {'{variables}'})
            </label>
            <textarea
              required
              value={promptText}
              onChange={e => setPromptText(e.target.value)}
              rows={8}
              placeholder="You are an expert system analyst. Analyze the following inputs: {input_data}..."
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
          </div>

          <button type="submit" disabled={actionLoading} className="btn-neon-cyan" style={{width: '100%', justifyContent: 'center', paddingTop: '0.625rem', paddingBottom: '0.625rem', fontSize: '0.75rem'}}>
            SAVE PROMPT TEMPLATE (+150 EXP)
          </button>
        </form>

        {/* List */}
        <div className="hud-panel" style={{padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#22d3ee', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem'}}>
            SAVED PROMPT TEMPLATES ({prompts.length})
          </h4>

          {loading ? (
            <div className="font-mono" style={{textAlign: 'center', paddingTop: '3.0rem', paddingBottom: '3.0rem', color: '#64748b', fontSize: '0.75rem'}}>
              Loading prompt vault...
            </div>
          ) : prompts.length === 0 ? (
            <div className="font-mono" style={{textAlign: 'center', paddingTop: '3.0rem', paddingBottom: '3.0rem', color: '#64748b', fontSize: '0.75rem'}}>
              No prompt templates registered yet.
            </div>
          ) : (
            <div style={{display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '500px', overflowY: 'auto'}}>
              {prompts.map(p => (
                <div key={p.name} className="font-mono" style={{padding: '1.0rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b', display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.75rem'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                    <span style={{fontWeight: '700', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
                      <MessageSquare style={{width: '1rem', height: '1rem', color: '#c084fc'}} />
                      {p.name}
                    </span>
                    <span style={{fontSize: '10px', color: '#22d3ee'}}>TEMPLATE</span>
                  </div>
                  <p style={{color: '#94a3b8', fontSize: '11px', WebkitLineClamp: '3', display: '-webkit-box', WebkitBoxOrient: 'vertical', overflow: 'hidden', backgroundColor: '#020617', padding: '0.5rem', borderRadius: '0.25rem', border: '1px solid #1e293b', borderColor: '#1e293b'}}>
                    {p.template || p.text || JSON.stringify(p)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
