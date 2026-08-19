import React, { useEffect, useState } from 'react';
import { Globe2, Plus, Trash2, CheckCircle2, AlertTriangle, RefreshCw, Cpu, Server } from 'lucide-react';
import { api } from '../../services/api';

export const FederationGateways: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [upstreams, setUpstreams] = useState<any[]>([]);
  const [serverName, setServerName] = useState('');
  const [serverUrl, setServerUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [selectedServer, setSelectedServer] = useState<any | null>(null);
  const [serverTools, setServerTools] = useState<any[]>([]);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchUpstreams = async () => {
    try {
      setLoading(true);
      const res = await api.getUpstreams();
      const raw = res.data;
      if (Array.isArray(raw)) setUpstreams(raw);
      else if (raw?.upstreams) setUpstreams(raw.upstreams);
      else if (typeof raw === 'object') {
        const list = Object.entries(raw).map(([name, val]: [string, any]) => ({
          name,
          ...val
        }));
        setUpstreams(list);
      }
    } catch (e) {
      console.error('Failed to load upstreams', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUpstreams();
  }, []);

  const handleAddUpstream = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    setStatusMsg(null);

    try {
      await api.addUpstream({ server_name: serverName, url: serverUrl });
      setStatusMsg(`Upstream MCP server '${serverName}' joined to Citadel federation!`);
      setServerName('');
      setServerUrl('');
      fetchUpstreams();
      if (onExpGain) onExpGain(250);
    } catch (err: any) {
      setStatusMsg(`Failed to add upstream: ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleRemoveUpstream = async (name: string) => {
    try {
      setActionLoading(true);
      await api.removeUpstream(name);
      setStatusMsg(`Upstream node '${name}' evicted.`);
      if (selectedServer?.name === name) setSelectedServer(null);
      fetchUpstreams();
    } catch (err: any) {
      setStatusMsg(`Failed to remove upstream: ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleSelectServer = async (server: any) => {
    setSelectedServer(server);
    setServerTools([]);
    try {
      const res = await api.getUpstreamTools(server.name || server.server_name);
      const raw = res.data;
      if (Array.isArray(raw)) setServerTools(raw);
      else if (raw?.tools) setServerTools(raw.tools);
    } catch (e) {
      console.error('Failed to load upstream tools', e);
    }
  };

  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
      {/* Header */}
      <div className="hud-panel" style={{padding: '1.0rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: '0.75rem'}}>
          <div style={{padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(16, 185, 129, 0.1)', border: '1px solid #1e293b', borderColor: 'rgba(16, 185, 129, 0.3)', color: '#34d399'}}>
            <Globe2 style={{width: '1.25rem', height: '1.25rem'}} />
          </div>
          <div>
            <h3 style={{fontSize: '1rem', fontWeight: '700', color: '#ffffff', letterSpacing: '0.05em'}}>
              REALM GATEWAYS (FEDERATED MCP SERVERS)
            </h3>
            <p className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>
              FEDERATED REMOTE UPSTREAM NODES & PROXY CALL PIPELINES (/mcp/upstreams*)
            </p>
          </div>
        </div>

        <button
          onClick={fetchUpstreams}
          disabled={loading}
          className="btn-neon-cyan" style={{fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem'}}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>REFRESH GATEWAYS</span>
        </button>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: 'rgba(8, 51, 68, 0.6)', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.4)', color: '#67e8f9', fontSize: '0.75rem'}}>
          {statusMsg}
        </div>
      )}

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: '1.5rem'}}>
        {/* Left Column: Register Form & Node List */}
        <div style={{gridColumn: 'span 5 / span 5', display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
          {/* Form */}
          <form onSubmit={handleAddUpstream} className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
            <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#34d399', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem'}}>
              JOIN REMOTE MCP SERVER NODE
            </h4>

            <div>
              <label className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>
                NODE NAME
              </label>
              <input
                type="text"
                required
                value={serverName}
                onChange={e => setServerName(e.target.value)}
                placeholder="e.g. calculator_upstream"
                className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
              />
            </div>

            <div>
              <label className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>
                REMOTE SSE / HTTP URL
              </label>
              <input
                type="url"
                required
                value={serverUrl}
                onChange={e => setServerUrl(e.target.value)}
                placeholder="http://remote-mcp.internal:8000/sse"
                className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
              />
            </div>

            <button
              type="submit"
              disabled={actionLoading}
              className="btn-neon-cyan" style={{width: '100%', justifyContent: 'center', paddingTop: '0.625rem', paddingBottom: '0.625rem', fontSize: '0.75rem', letterSpacing: '0.1em'}}
            >
              {actionLoading ? 'CONNECTING NODE...' : 'JOIN FEDERATION GATEWAY ⚡ (+250 EXP)'}
            </button>
          </form>

          {/* Node List */}
          <div className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
            <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#22d3ee', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem'}}>
              ACTIVE FEDERATION NODES ({upstreams.length})
            </h4>

            {loading ? (
              <div className="font-mono" style={{textAlign: 'center', paddingTop: '2.0rem', paddingBottom: '2.0rem', color: '#64748b', fontSize: '0.75rem'}}>
                Loading upstream gateways...
              </div>
            ) : upstreams.length === 0 ? (
              <div className="font-mono" style={{textAlign: 'center', paddingTop: '2.0rem', paddingBottom: '2.0rem', color: '#64748b', fontSize: '0.75rem'}}>
                No active upstream nodes connected.
              </div>
            ) : (
              upstreams.map(up => {
                const name = up.name || up.server_name;
                const isSelected = selectedServer?.name === name || selectedServer?.server_name === name;

                return (
                  <div
                    key={name}
                    onClick={() => handleSelectServer(up)}
                    className={`p-3.5 rounded border transition-all cursor-pointer flex items-center justify-between ${
                      isSelected
                        ? 'bg-emerald-950/40 border-emerald-400 shadow-[0_0_15px_rgba(0,255,102,0.15)]'
                        : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div>
                      <div className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
                        <Server style={{width: '0.875rem', height: '0.875rem', color: '#34d399'}} />
                        {name}
                      </div>
                      <div className="font-mono" style={{fontSize: '10px', color: '#94a3b8', marginTop: '0.125rem'}}>
                        {up.url || 'http://localhost:8000/sse'}
                      </div>
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveUpstream(name);
                      }}
                      style={{padding: '0.375rem', borderRadius: '0.25rem', color: '#64748b'}}
                    >
                      <Trash2 style={{width: '1rem', height: '1rem'}} />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Node Details & Remote Tool Inspection */}
        <div className="hud-panel" style={{gridColumn: 'span 7 / span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#34d399', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem'}}>
            REMOTE NODE TOOL CATALOG & PROXY EXECUTOR
          </h4>

          {selectedServer ? (
            <div style={{display: 'flex', flexDirection: 'column', gap: '1rem'}}>
              <div>
                <span className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>FEDERATED NODE NAME:</span>
                <p className="font-mono" style={{fontSize: '1rem', fontWeight: '900', color: '#ffffff'}}>{selectedServer.name || selectedServer.server_name}</p>
              </div>

              <div>
                <span className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>REMOTE TOOLS EXPOSED:</span>
                {serverTools.length === 0 ? (
                  <p className="font-mono" style={{fontSize: '0.75rem', color: '#64748b', fontStyle: 'italic', marginTop: '0.25rem'}}>No tools reported by remote node.</p>
                ) : (
                  <div style={{display: 'grid', gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', gap: '0.5rem', marginTop: '0.5rem'}}>
                    {serverTools.map(t => (
                      <div key={t.name} style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b'}}>
                        <div className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#22d3ee', display: 'flex', alignItems: 'center', gap: '0.375rem'}}>
                          <Cpu style={{width: '0.875rem', height: '0.875rem'}} />
                          {t.name}
                        </div>
                        <div style={{fontSize: '11px', color: '#94a3b8', WebkitLineClamp: '1', display: '-webkit-box', WebkitBoxOrient: 'vertical', overflow: 'hidden', marginTop: '0.125rem'}}>
                          {t.description || 'Remote proxied tool.'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="font-mono" style={{textAlign: 'center', paddingTop: '5.0rem', paddingBottom: '5.0rem', color: '#64748b', fontSize: '0.75rem'}}>
              Select a federated gateway node on the left to inspect proxied tools.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
