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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Refresh */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 900, color: '#ffffff', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
            REACTOR HUD & TELEMETRY 
            <Activity style={{ width: '1.25rem', height: '1.25rem', color: '#22d3ee' }} />
          </h2>
          <p style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'var(--font-mono)', margin: '0.25rem 0 0 0' }}>
            REAL-TIME COMMAND CENTER REACTOR & SYSTEM METRICS
          </p>
        </div>
        <button
          onClick={fetchHUDData}
          disabled={loading}
          className="btn-neon-cyan"
          style={{ fontSize: '0.75rem', padding: '0.5rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>REFRESH HUD</span>
        </button>
      </div>

      {/* Top Stat HUD Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '1.5rem' }}>
        {/* Raw Prometheus / System Metrics Panel */}
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem' }}>
            <h3 style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '0.1em', color: '#22d3ee', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              <Activity style={{ width: '1rem', height: '1rem' }} /> PROMETHEUS TELEMETRY METRICS
            </h3>
            <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>ENDPOINT /metrics</span>
          </div>
          <pre style={{ width: '100%', height: '16rem', backgroundColor: 'rgba(2,6,23,0.8)', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#67e8f9', overflow: 'auto', margin: 0, boxSizing: 'border-box' }}>
            {metricsText || '# Loading metrics stream...'}
          </pre>
        </div>

        {/* Live System Log Stream Panel */}
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem' }}>
            <h3 style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '0.1em', color: '#34d399', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              <Terminal style={{ width: '1rem', height: '1rem' }} /> RECENT SYSTEM LOGS
            </h3>
            <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>ENDPOINT /admin/logs</span>
          </div>
          <div style={{ width: '100%', height: '16rem', backgroundColor: 'rgba(2,6,23,0.8)', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#cbd5e1', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: '0.25rem', boxSizing: 'border-box' }}>
            {logsList.length === 0 ? (
              <p style={{ color: '#64748b', fontStyle: 'italic', margin: 0 }}>No log entries reported.</p>
            ) : (
              logsList.map((logItem, idx) => (
                <div key={idx} style={{ borderBottom: '1px solid #0f172a', paddingBottom: '0.25rem' }}>
                  <span style={{ color: '#64748b', fontFamily: 'var(--font-mono)' }}>[{new Date().toLocaleTimeString()}]</span>{' '}
                  <span style={{ color: '#e2e8f0' }}>{typeof logItem === 'string' ? logItem : JSON.stringify(logItem)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
