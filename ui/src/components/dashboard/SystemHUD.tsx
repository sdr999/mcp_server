import React, { useEffect, useState } from 'react';
import { 
  Activity, 
  Cpu, 
  ShieldCheck, 
  Database, 
  HardDrive, 
  RefreshCw, 
  Wand2, 
  Hammer, 
  Clock, 
  Globe2, 
  Swords, 
  ScrollText, 
  Users2, 
  Radio,
  Zap,
  CheckCircle2,
  ChevronRight,
  Trophy,
  Award
} from 'lucide-react';
import { api } from '../../services/api';
import { StatCard } from '../common/StatCard';
import { sfx } from '../../services/soundEffects';
import { toolUsageTracker, ToolMastery } from '../../services/toolUsageTracker';

interface SystemHUDProps {
  onNavigateTab?: (tab: string) => void;
}

export const SystemHUD: React.FC<SystemHUDProps> = ({ onNavigateTab }) => {
  const [statusData, setStatusData] = useState<any>(null);
  const [healthStatus, setHealthStatus] = useState<string>('UNKNOWN');
  const [readyStatus, setReadyStatus] = useState<string>('UNKNOWN');
  const [metricsText, setMetricsText] = useState<string>('');
  const [logsList, setLogsList] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [rankedTools, setRankedTools] = useState<ToolMastery[]>([]);

  const fetchHUDData = async () => {
    try {
      setLoading(true);
      sfx.playTapSound();
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
    setRankedTools(toolUsageTracker.getRankedTools());

    const unsub = toolUsageTracker.subscribe(() => {
      setRankedTools(toolUsageTracker.getRankedTools());
    });

    const interval = setInterval(fetchHUDData, 15000);
    return () => {
      clearInterval(interval);
      unsub();
    };
  }, []);

  const handleActionClick = (tab: string) => {
    sfx.playCardSelectSound();
    if (onNavigateTab) {
      onNavigateTab(tab);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Refresh */}
      <div className="hud-panel" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
          <div style={{
            padding: '0.6rem',
            borderRadius: '0.375rem',
            background: 'rgba(0, 240, 255, 0.12)',
            border: '1px solid rgba(0, 240, 255, 0.4)',
            color: '#00f0ff'
          }}>
            <Activity style={{ width: '1.4rem', height: '1.4rem' }} />
          </div>
          <div>
            <h2 className="font-title" style={{ fontSize: '1.2rem', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              TACTICAL OPERATIONS HUD
            </h2>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
              REAL-TIME MISSION CONTROL TELEMETRY & RAPID DEPLOYMENT ACTIONS
            </p>
          </div>
        </div>

        <button
          onClick={fetchHUDData}
          disabled={loading}
          className="btn-sc btn-sc-cyan"
          style={{ fontSize: '0.75rem', padding: '0.45rem 0.85rem' }}
        >
          <RefreshCw className={loading ? 'animate-spin' : ''} style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>{loading ? 'POLLING SENSORS...' : 'REFRESH TELEMETRY'}</span>
        </button>
      </div>

      {/* Top Stat HUD Cards with Clickable Navigation */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        <StatCard
          title="REACTOR HEALTH"
          value={healthStatus}
          subtext={`Readiness: ${readyStatus}`}
          icon={ShieldCheck}
          color={healthStatus === 'OK' ? 'green' : 'magenta'}
          trend="STABLE"
          onClick={fetchHUDData}
        />
        <StatCard
          title="LOADED MCP TOOLS"
          value={statusData?.total_tools ?? statusData?.tools_count ?? 12}
          subtext="Click to Arm / Deploy"
          icon={Cpu}
          color="cyan"
          onClick={() => handleActionClick('spellbook')}
        />
        <StatCard
          title="UPSTREAM NODES"
          value={statusData?.active_upstreams ?? statusData?.upstreams_count ?? 3}
          subtext="Federated Gateways"
          icon={Database}
          color="gold"
          onClick={() => handleActionClick('federation')}
        />
        <StatCard
          title="SYSTEM MEMORY"
          value={statusData?.memory_used || '128 MB'}
          subtext="FastMCP Event Loop"
          icon={HardDrive}
          color="green"
          onClick={() => handleActionClick('chaos')}
        />
      </div>

      {/* Top Ranked Tools Leaderboard Widget */}
      {rankedTools.length > 0 && (
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem', borderBottom: '1px solid #1e2c45', paddingBottom: '0.5rem' }}>
            <h3 className="font-title" style={{ fontSize: '0.85rem', color: '#fbbf24', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Trophy style={{ width: '1rem', height: '1rem' }} /> TOP RANKED TACTICAL PROTOCOLS (LEADERBOARD)
            </h3>
            <button
              onClick={() => handleActionClick('spellbook')}
              className="font-mono"
              style={{ fontSize: '0.7rem', color: '#00f0ff', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.25rem' }}
            >
              View Full Armory <ChevronRight style={{ width: '0.75rem', height: '0.75rem' }} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.75rem' }}>
            {rankedTools.slice(0, 4).map((tool, idx) => (
              <div
                key={tool.name}
                onClick={() => handleActionClick('spellbook')}
                style={{
                  background: '#0a0f1a',
                  border: `1px solid ${idx === 0 ? '#fbbf24' : idx === 1 ? '#94a3b8' : idx === 2 ? '#fdba74' : '#1e2c45'}`,
                  borderRadius: '0.375rem',
                  padding: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  transition: 'transform 0.12s ease'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span className="font-title" style={{
                    fontSize: '11px',
                    padding: '0.15rem 0.4rem',
                    borderRadius: '0.25rem',
                    background: idx === 0 ? '#fbbf24' : idx === 1 ? '#e2e8f0' : idx === 2 ? '#fdba74' : '#334155',
                    color: idx <= 2 ? '#000000' : '#ffffff',
                    fontWeight: 700
                  }}>
                    #{idx + 1}
                  </span>
                  <div>
                    <div className="font-title" style={{ fontSize: '0.85rem', color: '#ffffff' }}>
                      {tool.name}
                    </div>
                    <div className="font-mono" style={{ fontSize: '0.65rem', color: '#94a3b8' }}>
                      {tool.levelTitle}
                    </div>
                  </div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div className="font-title" style={{ fontSize: '0.8rem', color: '#ff9f1c' }}>
                    {tool.calls} ⚡
                  </div>
                  <div className="font-mono" style={{ fontSize: '0.65rem', color: '#00f0ff' }}>
                    LVL {tool.level}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tactical Quick Action Deck */}
      <div className="hud-panel" style={{ padding: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem', borderBottom: '1px solid #1e2c45', paddingBottom: '0.5rem' }}>
          <h3 className="font-title" style={{ fontSize: '0.85rem', color: '#00f0ff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Zap style={{ width: '1rem', height: '1rem' }} /> QUICK TACTICAL ACTION PROTOCOLS
          </h3>
          <span className="font-mono" style={{ fontSize: '10px', color: '#64748b' }}>CLICK PROTOCOL TO EXECUTE</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          <button
            onClick={() => handleActionClick('spellbook')}
            className="btn-sc btn-sc-cyan"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Wand2 style={{ width: '1rem', height: '1rem' }} /> DEPLOY & TEST MODULES
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('foundry')}
            className="btn-sc btn-sc-orange"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Hammer style={{ width: '1rem', height: '1rem' }} /> SYNTHESIZE MODULE (AI)
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('queue')}
            className="btn-sc btn-sc-emerald"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Clock style={{ width: '1rem', height: '1rem' }} /> SECURITY REVIEW QUEUE
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('firehose')}
            className="btn-sc btn-sc-cyan"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Radio style={{ width: '1rem', height: '1rem' }} /> LIVE TELEMETRY FEED
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('federation')}
            className="btn-sc btn-sc-cyan"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Globe2 style={{ width: '1rem', height: '1rem' }} /> RELAY GATEWAYS
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('chaos')}
            className="btn-sc btn-sc-crimson"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Swords style={{ width: '1rem', height: '1rem' }} /> CHAOS STRESS SIMULATION
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('openapi')}
            className="btn-sc btn-sc-orange"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ScrollText style={{ width: '1rem', height: '1rem' }} /> OPENAPI SPEC VAULT
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>

          <button
            onClick={() => handleActionClick('tenancy')}
            className="btn-sc btn-sc-cyan"
            style={{ width: '100%', padding: '0.65rem', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Users2 style={{ width: '1rem', height: '1rem' }} /> FLEET CITADEL (RBAC)
            </span>
            <ChevronRight style={{ width: '0.875rem', height: '0.875rem' }} />
          </button>
        </div>
      </div>

      {/* Metrics & System Logs Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '1.5rem' }}>
        {/* Raw Prometheus / System Metrics Panel */}
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', borderBottom: '1px solid #1e2c45', paddingBottom: '0.5rem' }}>
            <h3 className="font-title" style={{ fontSize: '0.75rem', color: '#00f0ff', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              <Activity style={{ width: '1rem', height: '1rem' }} /> PROMETHEUS TELEMETRY METRICS
            </h3>
            <span className="font-mono" style={{ fontSize: '10px', color: '#64748b' }}>ENDPOINT /metrics</span>
          </div>
          <pre className="font-mono" style={{ width: '100%', height: '16rem', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '11px', color: '#38bdf8', overflow: 'auto', margin: 0, boxSizing: 'border-box' }}>
            {metricsText || '# Loading metrics telemetry stream...'}
          </pre>
        </div>

        {/* Live System Log Stream Panel */}
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', borderBottom: '1px solid #1e2c45', paddingBottom: '0.5rem' }}>
            <h3 className="font-title" style={{ fontSize: '0.75rem', color: '#34d399', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              <CheckCircle2 style={{ width: '1rem', height: '1rem' }} /> ORBITAL SYSTEM LOGS
            </h3>
            <span className="font-mono" style={{ fontSize: '10px', color: '#64748b' }}>ENDPOINT /logs</span>
          </div>
          <div className="font-mono" style={{ width: '100%', height: '16rem', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '11px', color: '#94a3b8', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: '0.25rem', boxSizing: 'border-box' }}>
            {logsList.length === 0 ? (
              <span style={{ color: '#64748b' }}># No system logs recorded. Reactor operating nominally.</span>
            ) : (
              logsList.map((log, idx) => (
                <div key={idx} style={{ color: log.includes('ERR') || log.includes('40') ? '#fb7185' : '#e2e8f0' }}>
                  {log}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
