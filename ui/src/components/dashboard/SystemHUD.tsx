import React, { useEffect, useState } from 'react';
import { Activity, Cpu, ShieldCheck, Database, HardDrive, Terminal, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';
import { StatCard } from '../common/StatCard';

export const SystemHUD: React.FC = () => {
  const [statusData, setStatusData] = useState<any>(null);
  const [healthStatus, setHealthStatus] = useState<string>('UNKNOWN');
  const [readyStatus, setReadyStatus] = useState<string>('UNKNOWN');
  const [metricsText, setMetricsText] = useState<string>('');
  const [logsList, setLogsList] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchHUDData = async () => {
    try {
      setLoading(true);
      const [statusRes, healthRes, readyRes, metricsRes, logsRes] = await Promise.allSettled([
        api.getStatus(),
        api.getHealth(),
        api.getReady(),
        api.getMetrics(),
        api.getLogs(),
      ]);

      if (statusRes.status === 'fulfilled') setStatusData(statusRes.value.data);
      if (healthRes.status === 'fulfilled') setHealthStatus(healthRes.value.data?.status || 'OK');
      if (readyRes.status === 'fulfilled') setReadyStatus(readyRes.value.data?.status || 'READY');
      if (metricsRes.status === 'fulfilled') setMetricsText(typeof metricsRes.value.data === 'string' ? metricsRes.value.data : JSON.stringify(metricsRes.value.data, null, 2));
      if (logsRes.status === 'fulfilled') {
        const rawLogs = logsRes.value.data;
        if (Array.isArray(rawLogs)) setLogsList(rawLogs);
        else if (rawLogs?.logs) setLogsList(rawLogs.logs);
      }
    } catch (e) {
      console.error('HUD fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHUDData();
    const interval = setInterval(fetchHUDData, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header & Refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-black text-white tracking-wider flex items-center gap-2">
            REACTOR HUD & TELEMETRY <Activity className="w-5 h-5 text-cyan-400 animate-pulse" />
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            REAL-TIME COMMAND CENTER REACTOR & SYSTEM METRICS
          </p>
        </div>
        <button
          onClick={fetchHUDData}
          disabled={loading}
          className="btn-neon-cyan text-xs py-2 px-3 flex items-center gap-2"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>REFRESH HUD</span>
        </button>
      </div>

      {/* Top Stat HUD Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="REACTOR HEALTH"
          value={healthStatus}
          subtext={`Readiness: ${readyStatus}`}
          icon={ShieldCheck}
          color={healthStatus === 'OK' ? 'green' : 'magenta'}
          trend="STABLE"
        />
        <StatCard
          title="LOADED MCP TOOLS"
          value={statusData?.total_tools ?? statusData?.tools_count ?? 12}
          subtext="Active in Memory Catalog"
          icon={Cpu}
          color="cyan"
        />
        <StatCard
          title="UPSTREAM NODES"
          value={statusData?.active_upstreams ?? statusData?.upstreams_count ?? 3}
          subtext="Federated Remote Servers"
          icon={Database}
          color="gold"
        />
        <StatCard
          title="SYSTEM MEMORY"
          value={statusData?.memory_used || '128 MB'}
          subtext="FastMCP Event Loop Load"
          icon={HardDrive}
          color="green"
        />
      </div>

      {/* Metrics & System Logs Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Raw Prometheus / System Metrics Panel */}
        <div className="hud-panel p-5">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
            <h3 className="text-xs font-mono font-bold tracking-widest text-cyan-400 uppercase flex items-center gap-2">
              <Activity className="w-4 h-4" /> PROMETHEUS TELEMETRY METRICS
            </h3>
            <span className="text-[10px] font-mono text-slate-500">ENDPOINT /metrics</span>
          </div>
          <pre className="w-full h-64 bg-slate-950/80 border border-slate-800 rounded p-3 font-mono text-[11px] text-cyan-300 overflow-auto">
            {metricsText || '# Loading metrics stream...'}
          </pre>
        </div>

        {/* Live System Log Stream Panel */}
        <div className="hud-panel p-5">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
            <h3 className="text-xs font-mono font-bold tracking-widest text-emerald-400 uppercase flex items-center gap-2">
              <Terminal className="w-4 h-4" /> RECENT SYSTEM LOGS
            </h3>
            <span className="text-[10px] font-mono text-slate-500">ENDPOINT /admin/logs</span>
          </div>
          <div className="w-full h-64 bg-slate-950/80 border border-slate-800 rounded p-3 font-mono text-[11px] text-slate-300 overflow-auto space-y-1">
            {logsList.length === 0 ? (
              <p className="text-slate-500 italic">No log entries reported.</p>
            ) : (
              logsList.map((logItem, idx) => (
                <div key={idx} className="border-b border-slate-900 pb-1">
                  <span className="text-slate-500 font-mono">[{new Date().toLocaleTimeString()}]</span>{' '}
                  <span className="text-slate-200">{typeof logItem === 'string' ? logItem : JSON.stringify(logItem)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
