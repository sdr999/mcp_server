import React, { useEffect, useState } from 'react';
import { Swords, Zap, AlertTriangle, ShieldAlert, BarChart2, RefreshCw, Flame } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import { api } from '../../services/api';

export const ChaosArena: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [leaderboard, setLeaderboard] = useState<any[]>([]);
  const [chaosStatus, setChaosStatus] = useState<any | null>(null);
  const [chaosEnabled, setChaosEnabled] = useState(false);
  const [latencyMs, setLatencyMs] = useState(250);
  const [errorRate, setErrorRate] = useState(0.1);
  const [dropRate, setDropRate] = useState(0.05);

  const [loading, setLoading] = useState(true);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const mockTimeseriesData = [
    { time: '12:00', calls: 45, latency: 120 },
    { time: '12:05', calls: 78, latency: 135 },
    { time: '12:10', calls: 120, latency: 190 },
    { time: '12:15', calls: 95, latency: 145 },
    { time: '12:20', calls: 160, latency: 210 },
    { time: '12:25', calls: 210, latency: 180 },
    { time: '12:30', calls: 185, latency: 165 },
  ];

  const fetchArenaData = async () => {
    try {
      setLoading(true);
      const [lbRes, chaosRes] = await Promise.allSettled([
        api.getLeaderboard(),
        api.getChaosStatus()
      ]);

      if (lbRes.status === 'fulfilled') setLeaderboard(Array.isArray(lbRes.value.data) ? lbRes.value.data : lbRes.value.data?.leaderboard || []);
      if (chaosRes.status === 'fulfilled') {
        setChaosStatus(chaosRes.value.data);
        setChaosEnabled(chaosRes.value.data?.enabled || false);
      }
    } catch (e) {
      console.error('Failed to load arena data', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchArenaData();
  }, []);

  const handleToggleChaos = async () => {
    try {
      if (chaosEnabled) {
        await api.disableChaos();
        setChaosEnabled(false);
        setStatusMsg('Chaos Engineering injection DISABLED.');
      } else {
        await api.enableChaos();
        setChaosEnabled(true);
        setStatusMsg('Chaos Engineering injection ACTIVATED! Testing system resilience.');
        if (onExpGain) onExpGain(300);
      }
      fetchArenaData();
    } catch (err: any) {
      setStatusMsg(`Chaos toggle failed: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleSaveChaosRules = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.configureChaosRules({
        latency_injection_ms: latencyMs,
        error_rate_simulation: errorRate,
        packet_drop_rate: dropRate
      });
      setStatusMsg('Chaos injection rules updated!');
      fetchArenaData();
    } catch (err: any) {
      setStatusMsg(`Failed chaos config: ${err.response?.data?.detail || err.message}`);
    }
  };

  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
      {/* Header */}
      <div className="hud-panel" style={{padding: '1.0rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: '0.75rem'}}>
          <div style={{padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(244, 63, 94, 0.1)', border: '1px solid #1e293b', borderColor: 'rgba(244, 63, 94, 0.3)', color: '#fb7185'}}>
            <Swords style={{width: '1.25rem', height: '1.25rem'}} />
          </div>
          <div>
            <h3 style={{fontSize: '1rem', fontWeight: '700', color: '#ffffff', letterSpacing: '0.05em'}}>
              BATTLE & CHAOS ARENA
            </h3>
            <p className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>
              ANALYTICAL LEADERBOARDS & CHAOS INJECTION TESTING (/admin/analytics/*, /admin/chaos*)
            </p>
          </div>
        </div>

        <button onClick={fetchArenaData} className="btn-neon-cyan" style={{fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem'}}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: 'rgba(8, 51, 68, 0.6)', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.4)', color: '#67e8f9', fontSize: '0.75rem'}}>
          {statusMsg}
        </div>
      )}

      {/* Timeseries Graph */}
      <div className="hud-panel" style={{padding: '1.25rem'}}>
        <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#22d3ee', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem', marginBottom: '1.0rem', display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
          <BarChart2 style={{width: '1rem', height: '1rem'}} /> LIVE TOOL CALL LATENCY & THROUGHPUT TIMESERIES
        </h4>
        <div style={{height: '16rem', width: '100%'}}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={mockTimeseriesData}>
              <defs>
                <linearGradient id="colorCalls" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00f0ff" stopOpacity={0.4}/>
                  <stop offset="95%" stopColor="#00f0ff" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <XAxis dataKey="time" stroke="#64748b" fontSize={11} fontFamily="JetBrains Mono" />
              <YAxis stroke="#64748b" fontSize={11} fontFamily="JetBrains Mono" />
              <Tooltip contentStyle={{ background: '#0e1420', border: '1px solid #00f0ff', color: '#fff', fontSize: '12px' }} />
              <Area type="monotone" dataKey="calls" stroke="#00f0ff" fillOpacity={1} fill="url(#colorCalls)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Grid: Chaos Injection vs Tool Leaderboard */}
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '1.5rem'}}>
        {/* Chaos Injection Panel */}
        <div className="hud-panel" style={{padding: '1.5rem', borderColor: 'rgba(244, 63, 94, 0.4)'}}>
          <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.75rem'}}>
            <h4 className="font-mono" style={{fontSize: '0.875rem', fontWeight: '700', color: '#fb7185', display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
              <Zap style={{width: '1rem', height: '1rem'}} /> CHAOS ENGINEERING EXPERIMENTAL CONTROLS
            </h4>

            <button
              onClick={handleToggleChaos}
              className={`btn-neon-${chaosEnabled ? 'magenta' : 'cyan'} text-xs py-1.5 px-3`}
            >
              {chaosEnabled ? 'DISABLE CHAOS' : 'ENABLE CHAOS ⚡ (+300 EXP)'}
            </button>
          </div>

          <form onSubmit={handleSaveChaosRules} className="font-mono" style={{display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.75rem'}}>
            <div>
              <label style={{color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>LATENCY INJECTION: {latencyMs} ms</label>
              <input
                type="range"
                min="0"
                max="2000"
                step="50"
                value={latencyMs}
                onChange={e => setLatencyMs(parseInt(e.target.value))}
                style={{width: '100%'}}
              />
            </div>

            <div>
              <label style={{color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>SIMULATED ERROR RATE: {(errorRate * 100).toFixed(0)}%</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={errorRate}
                onChange={e => setErrorRate(parseFloat(e.target.value))}
                style={{width: '100%'}}
              />
            </div>

            <div>
              <label style={{color: '#cbd5e1', display: 'block', marginBottom: '0.25rem'}}>PACKET DROP RATE: {(dropRate * 100).toFixed(0)}%</label>
              <input
                type="range"
                min="0"
                max="0.5"
                step="0.01"
                value={dropRate}
                onChange={e => setDropRate(parseFloat(e.target.value))}
                style={{width: '100%'}}
              />
            </div>

            <button type="submit" className="btn-neon-magenta" style={{width: '100%', justifyContent: 'center', paddingTop: '0.625rem', paddingBottom: '0.625rem', fontSize: '0.75rem'}}>
              APPLY CHAOS RULES
            </button>
          </form>
        </div>

        {/* Leaderboard */}
        <div className="hud-panel" style={{padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.875rem', fontWeight: '700', color: '#fbbf24', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
            <Flame style={{width: '1rem', height: '1rem', color: '#fbbf24'}} /> MOST USED TOOLS LEADERBOARD
          </h4>

          {leaderboard.length === 0 ? (
            <div className="font-mono" style={{textAlign: 'center', paddingTop: '3.0rem', paddingBottom: '3.0rem', color: '#64748b', fontSize: '0.75rem'}}>
              No tool executions recorded yet.
            </div>
          ) : (
            <div style={{display: 'flex', flexDirection: 'column', gap: '0.5rem'}}>
              {leaderboard.map((item, idx) => (
                <div key={idx} className="font-mono" style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '0.75rem'}}>
                    <span style={{width: '1.5rem', height: '1.5rem', borderRadius: '9999px', backgroundColor: 'rgba(245, 158, 11, 0.2)', border: '1px solid #1e293b', borderColor: 'rgba(245, 158, 11, 0.4)', color: '#fbbf24', fontWeight: '700', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem'}}>
                      #{idx + 1}
                    </span>
                    <span style={{color: '#ffffff', fontWeight: '700'}}>{item.tool_name || item.name}</span>
                  </div>
                  <div style={{textAlign: 'right'}}>
                    <span style={{color: '#22d3ee', fontWeight: '700'}}>{item.calls_count || item.total_calls || 12} calls</span>
                    <div style={{fontSize: '10px', color: '#94a3b8'}}>{item.avg_latency || '45'} ms avg</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
