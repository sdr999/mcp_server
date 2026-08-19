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
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              ARCHMAGE PROMPT VAULT
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              SYSTEM PROMPT TEMPLATES & VARIANT MANAGEMENT (/admin/prompts*)
            </p>
          </div>
        </div>

        <button onClick={fetchPrompts} className="btn-neon-cyan text-xs py-1.5 px-3">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {statusMsg && (
        <div className="p-3 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 text-xs font-mono">
          {statusMsg}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Form */}
        <form onSubmit={handleRegisterPrompt} className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-purple-400 uppercase border-b border-slate-800 pb-2">
            REGISTER NEW PROMPT TEMPLATE
          </h4>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              PROMPT TEMPLATE NAME
            </label>
            <input
              type="text"
              required
              value={promptName}
              onChange={e => setPromptName(e.target.value)}
              placeholder="e.g. system_analyst_persona"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
            />
          </div>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              PROMPT TEXT (SUPPORT {'{variables}'})
            </label>
            <textarea
              required
              value={promptText}
              onChange={e => setPromptText(e.target.value)}
              rows={8}
              placeholder="You are an expert system analyst. Analyze the following inputs: {input_data}..."
              className="w-full bg-slate-950 border border-slate-700 rounded p-3 text-xs text-white font-mono focus:outline-none focus:border-cyan-400"
            />
          </div>

          <button type="submit" disabled={actionLoading} className="w-full btn-neon-cyan justify-center py-2.5 text-xs">
            SAVE PROMPT TEMPLATE (+150 EXP)
          </button>
        </form>

        {/* List */}
        <div className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-cyan-400 uppercase border-b border-slate-800 pb-2">
            SAVED PROMPT TEMPLATES ({prompts.length})
          </h4>

          {loading ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              Loading prompt vault...
            </div>
          ) : prompts.length === 0 ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              No prompt templates registered yet.
            </div>
          ) : (
            <div className="space-y-3 max-h-[500px] overflow-y-auto">
              {prompts.map(p => (
                <div key={p.name} className="p-4 rounded bg-slate-900 border border-slate-800 space-y-2 font-mono text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 text-purple-400" />
                      {p.name}
                    </span>
                    <span className="text-[10px] text-cyan-400">TEMPLATE</span>
                  </div>
                  <p className="text-slate-400 text-[11px] line-clamp-3 bg-slate-950 p-2 rounded border border-slate-800">
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
