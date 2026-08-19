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
      const payload: any = {
        collection_id: collectionId,
        spec: specContent || specUrl
      };
      if (specUrl) payload.base_url = specUrl;

      await api.registerOpenAPISpec(payload);
      setStatusMsg({ type: 'success', text: `OpenAPI Spec '${collectionId}' registered! Tools auto-generated.` });
      setCollectionId('');
      setSpecUrl('');
      setSpecContent('');
      fetchSpecs();
      if (onExpGain) onExpGain(200);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.response?.data?.detail || 'Failed to register OpenAPI spec.' });
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div className="hud-panel" style={{ padding: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(6, 182, 212, 0.1)', border: '1px solid rgba(6, 182, 212, 0.3)', color: '#22d3ee' }}>
            <ScrollText style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', letterSpacing: '0.05em', margin: 0 }}>
              OPENAPI SPECIFICATIONS VAULT
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem' }}>
              INGEST OPENAPI / SWAGGER SPECS & AUTO-GENERATE MCP TOOLS (/admin/openapi/*)
            </p>
          </div>
        </div>

        <button
          onClick={fetchSpecs}
          disabled={loading}
          className="btn-neon-cyan font-mono"
          style={{ fontSize: '0.75rem', padding: '0.375rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>REFRESH SPECS</span>
        </button>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{ padding: '1rem', borderRadius: '0.5rem', border: '1px solid', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)', borderColor: statusMsg.type === 'success' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)', color: statusMsg.type === 'success' ? '#34d399' : '#fb7185' }}>
          {statusMsg.type === 'success' ? <CheckCircle2 style={{ width: '1rem', height: '1rem' }} /> : <AlertTriangle style={{ width: '1rem', height: '1rem' }} />}
          <span>{statusMsg.text}</span>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
        {/* Register Form */}
        <form onSubmit={handleRegister} className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22d3ee', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', margin: 0 }}>
            REGISTER NEW OPENAPI SPECIFICATION
          </h4>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              COLLECTION ID
            </label>
            <input
              type="text"
              required
              value={collectionId}
              onChange={e => setCollectionId(e.target.value)}
              placeholder="e.g. petstore_api"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              OPENAPI SPEC URL (OPTION 1)
            </label>
            <input
              type="url"
              value={specUrl}
              onChange={e => setSpecUrl(e.target.value)}
              placeholder="https://petstore.swagger.io/v2/swagger.json"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
            />
          </div>

          <div>
            <label className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'block', marginBottom: '0.25rem' }}>
              RAW OPENAPI JSON PAYLOAD (OPTION 2)
            </label>
            <textarea
              value={specContent}
              onChange={e => setSpecContent(e.target.value)}
              rows={6}
              placeholder="{ 'openapi': '3.0.0', 'info': { ... } }"
              className="font-mono"
              style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #334155', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#34d399', outline: 'none' }}
            />
          </div>

          <button
            type="submit"
            disabled={actionLoading}
            className="btn-sc btn-sc-cyan"
            style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.75rem 0', fontSize: '0.85rem' }}
          >
            {actionLoading ? 'REGISTERING SPEC...' : 'REGISTER & DEPLOY MODULE PROTOCOLS ⚡ (+200 EXP)'}
          </button>
        </form>

        {/* Active Collections List */}
        <div className="hud-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h4 className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#34d399', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', margin: 0 }}>
            ACTIVE OPENAPI COLLECTIONS ({specs.length})
          </h4>

          {loading ? (
            <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              Loading collections...
            </div>
          ) : specs.length === 0 ? (
            <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              No registered OpenAPI spec collections.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '500px', overflowY: 'auto' }}>
              {specs.map(spec => (
                <div key={spec.collection_id || spec.id} style={{ padding: '1rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div className="font-mono" style={{ fontSize: '0.875rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                      <FileCode style={{ width: '1rem', height: '1rem', color: '#22d3ee' }} />
                      {spec.collection_id || spec.id}
                    </div>
                    <div className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '0.125rem' }}>
                      Endpoints: {spec.endpoints_count || spec.tools_count || 'Auto-generated'}
                    </div>
                  </div>

                  <button
                    onClick={() => handleRemove(spec.collection_id || spec.id)}
                    style={{ padding: '0.5rem', borderRadius: '0.25rem', backgroundColor: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.3)', color: '#fb7185', cursor: 'pointer', transition: 'all 0.2s' }}
                    title="Remove Collection"
                  >
                    <Trash2 style={{ width: '1rem', height: '1rem' }} />
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
