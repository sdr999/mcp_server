import React, { useEffect, useState } from 'react';
import { ScrollText, Upload, Trash2, CheckCircle2, AlertTriangle, RefreshCw, FileCode } from 'lucide-react';
import { api } from '../../services/api';

export const OpenAPIVault: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [specs, setSpecs] = useState<any[]>([]);
  const [collectionId, setCollectionId] = useState('');
  const [specUrl, setSpecUrl] = useState('');
  const [specContent, setSpecContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const fetchSpecs = async () => {
    try {
      setLoading(true);
      const res = await api.getOpenAPISpecs();
      const raw = res.data;
      if (Array.isArray(raw)) setSpecs(raw);
      else if (raw?.specs) setSpecs(raw.specs);
      else if (typeof raw === 'object') {
        const list = Object.entries(raw).map(([id, val]: [string, any]) => ({
          collection_id: id,
          ...val
        }));
        setSpecs(list);
      }
    } catch (e) {
      console.error('Failed to load OpenAPI specs', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSpecs();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    setStatusMsg(null);

    try {
      const payload: any = { collection_id: collectionId };
      if (specUrl) payload.url = specUrl;
      if (specContent) payload.spec = JSON.parse(specContent);

      await api.registerOpenAPISpec(payload);
      setStatusMsg({ type: 'success', text: `OpenAPI Spec '${collectionId}' registered! Tools auto-generated.` });
      setCollectionId('');
      setSpecUrl('');
      setSpecContent('');
      fetchSpecs();
      if (onExpGain) onExpGain(200);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to register OpenAPI spec.' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRemove = async (id: string) => {
    try {
      setActionLoading(true);
      await api.removeOpenAPISpec(id);
      setStatusMsg({ type: 'success', text: `Spec collection '${id}' removed.` });
      fetchSpecs();
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to remove spec.' });
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <ScrollText className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              OPENAPI SPECIFICATIONS VAULT
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              INGEST OPENAPI / SWAGGER SPECS & AUTO-GENERATE MCP TOOLS (/admin/openapi/*)
            </p>
          </div>
        </div>

        <button
          onClick={fetchSpecs}
          disabled={loading}
          className="btn-neon-cyan text-xs py-1.5 px-3 flex items-center gap-2"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>REFRESH SPECS</span>
        </button>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Register Form */}
        <form onSubmit={handleRegister} className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-cyan-400 tracking-wider uppercase border-b border-slate-800 pb-2">
            REGISTER NEW OPENAPI SPECIFICATION
          </h4>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              COLLECTION ID
            </label>
            <input
              type="text"
              required
              value={collectionId}
              onChange={e => setCollectionId(e.target.value)}
              placeholder="e.g. petstore_api"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
            />
          </div>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              OPENAPI SPEC URL (OPTION 1)
            </label>
            <input
              type="url"
              value={specUrl}
              onChange={e => setSpecUrl(e.target.value)}
              placeholder="https://petstore.swagger.io/v2/swagger.json"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
            />
          </div>

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              RAW OPENAPI JSON PAYLOAD (OPTION 2)
            </label>
            <textarea
              value={specContent}
              onChange={e => setSpecContent(e.target.value)}
              rows={6}
              placeholder="{ 'openapi': '3.0.0', 'info': { ... } }"
              className="w-full bg-slate-950 border border-slate-700 rounded p-3 text-xs text-emerald-400 font-mono focus:outline-none focus:border-cyan-400"
            />
          </div>

          <button
            type="submit"
            disabled={actionLoading}
            className="w-full btn-neon-cyan justify-center py-3 text-xs tracking-widest"
          >
            {actionLoading ? 'REGISTERING SPEC...' : 'REGISTER & AUTO-GENERATE SPELLS ⚡ (+200 EXP)'}
          </button>
        </form>

        {/* Active Collections List */}
        <div className="hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-emerald-400 tracking-wider uppercase border-b border-slate-800 pb-2">
            ACTIVE OPENAPI COLLECTIONS ({specs.length})
          </h4>

          {loading ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              Loading collections...
            </div>
          ) : specs.length === 0 ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              No registered OpenAPI spec collections.
            </div>
          ) : (
            <div className="space-y-3 max-h-[500px] overflow-y-auto">
              {specs.map(spec => (
                <div key={spec.collection_id || spec.id} className="p-4 rounded bg-slate-900 border border-slate-800 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold text-white font-mono flex items-center gap-2">
                      <FileCode className="w-4 h-4 text-cyan-400" />
                      {spec.collection_id || spec.id}
                    </div>
                    <div className="text-xs text-slate-400 font-mono mt-0.5">
                      Endpoints: {spec.endpoints_count || spec.tools_count || 'Auto-generated'}
                    </div>
                  </div>

                  <button
                    onClick={() => handleRemove(spec.collection_id || spec.id)}
                    className="p-2 rounded bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500 hover:text-white transition-all"
                    title="Remove Collection"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
