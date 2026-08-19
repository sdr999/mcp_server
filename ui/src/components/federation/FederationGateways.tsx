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
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
            <Globe2 className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              REALM GATEWAYS (FEDERATED MCP SERVERS)
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              FEDERATED REMOTE UPSTREAM NODES & PROXY CALL PIPELINES (/mcp/upstreams*)
            </p>
          </div>
        </div>

        <button
          onClick={fetchUpstreams}
          disabled={loading}
          className="btn-neon-cyan text-xs py-1.5 px-3 flex items-center gap-2"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>REFRESH GATEWAYS</span>
        </button>
      </div>

      {statusMsg && (
        <div className="p-3 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 text-xs font-mono">
          {statusMsg}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Register Form & Node List */}
        <div className="lg:col-span-5 space-y-6">
          {/* Form */}
          <form onSubmit={handleAddUpstream} className="hud-panel p-5 space-y-3">
            <h4 className="text-xs font-mono font-bold text-emerald-400 tracking-wider uppercase border-b border-slate-800 pb-2">
              JOIN REMOTE MCP SERVER NODE
            </h4>

            <div>
              <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
                NODE NAME
              </label>
              <input
                type="text"
                required
                value={serverName}
                onChange={e => setServerName(e.target.value)}
                placeholder="e.g. calculator_upstream"
                className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>

            <div>
              <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
                REMOTE SSE / HTTP URL
              </label>
              <input
                type="url"
                required
                value={serverUrl}
                onChange={e => setServerUrl(e.target.value)}
                placeholder="http://remote-mcp.internal:8000/sse"
                className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>

            <button
              type="submit"
              disabled={actionLoading}
              className="w-full btn-neon-cyan justify-center py-2.5 text-xs tracking-widest"
            >
              {actionLoading ? 'CONNECTING NODE...' : 'JOIN FEDERATION GATEWAY ⚡ (+250 EXP)'}
            </button>
          </form>

          {/* Node List */}
          <div className="hud-panel p-5 space-y-3">
            <h4 className="text-xs font-mono font-bold text-cyan-400 tracking-wider uppercase border-b border-slate-800 pb-2">
              ACTIVE FEDERATION NODES ({upstreams.length})
            </h4>

            {loading ? (
              <div className="text-center py-8 text-slate-500 font-mono text-xs">
                Loading upstream gateways...
              </div>
            ) : upstreams.length === 0 ? (
              <div className="text-center py-8 text-slate-500 font-mono text-xs">
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
                      <div className="text-xs font-bold text-white font-mono flex items-center gap-2">
                        <Server className="w-3.5 h-3.5 text-emerald-400" />
                        {name}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                        {up.url || 'http://localhost:8000/sse'}
                      </div>
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveUpstream(name);
                      }}
                      className="p-1.5 rounded text-slate-500 hover:text-rose-400"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Node Details & Remote Tool Inspection */}
        <div className="lg:col-span-7 hud-panel p-6 space-y-4">
          <h4 className="text-xs font-mono font-bold text-emerald-400 tracking-wider uppercase border-b border-slate-800 pb-2">
            REMOTE NODE TOOL CATALOG & PROXY EXECUTOR
          </h4>

          {selectedServer ? (
            <div className="space-y-4">
              <div>
                <span className="text-xs font-mono text-slate-400">FEDERATED NODE NAME:</span>
                <p className="text-base font-black text-white font-mono">{selectedServer.name || selectedServer.server_name}</p>
              </div>

              <div>
                <span className="text-xs font-mono text-slate-400">REMOTE TOOLS EXPOSED:</span>
                {serverTools.length === 0 ? (
                  <p className="text-xs text-slate-500 font-mono italic mt-1">No tools reported by remote node.</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    {serverTools.map(t => (
                      <div key={t.name} className="p-3 rounded bg-slate-900 border border-slate-800">
                        <div className="text-xs font-bold text-cyan-400 font-mono flex items-center gap-1.5">
                          <Cpu className="w-3.5 h-3.5" />
                          {t.name}
                        </div>
                        <div className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">
                          {t.description || 'Remote proxied tool.'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="text-center py-20 text-slate-500 font-mono text-xs">
              Select a federated gateway node on the left to inspect proxied tools.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
