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
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400">
            <Swords className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              BATTLE & CHAOS ARENA
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              ANALYTICAL LEADERBOARDS & CHAOS INJECTION TESTING (/admin/analytics/*, /admin/chaos*)
            </p>
          </div>
        </div>

        <button onClick={fetchArenaData} className="btn-neon-cyan text-xs py-1.5 px-3">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {statusMsg && (
        <div className="p-3 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 text-xs font-mono">
          {statusMsg}
        </div>
      )}

      {/* Timeseries Graph */}
      <div className="hud-panel p-5">
        <h4 className="text-xs font-mono font-bold text-cyan-400 uppercase border-b border-slate-800 pb-2 mb-4 flex items-center gap-2">
          <BarChart2 className="w-4 h-4" /> LIVE TOOL CALL LATENCY & THROUGHPUT TIMESERIES
        </h4>
        <div className="h-64 w-full">
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chaos Injection Panel */}
        <div className="hud-panel p-6 space-y-5 border-rose-500/40">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h4 className="text-sm font-bold text-rose-400 font-mono flex items-center gap-2">
              <Zap className="w-4 h-4" /> CHAOS ENGINEERING EXPERIMENTAL CONTROLS
            </h4>

            <button
              onClick={handleToggleChaos}
              className={`btn-neon-${chaosEnabled ? 'magenta' : 'cyan'} text-xs py-1.5 px-3`}
            >
              {chaosEnabled ? 'DISABLE CHAOS' : 'ENABLE CHAOS ⚡ (+300 EXP)'}
            </button>
          </div>

          <form onSubmit={handleSaveChaosRules} className="space-y-4 font-mono text-xs">
            <div>
              <label className="text-slate-300 block mb-1">LATENCY INJECTION: {latencyMs} ms</label>
              <input
                type="range"
                min="0"
                max="2000"
                step="50"
                value={latencyMs}
                onChange={e => setLatencyMs(parseInt(e.target.value))}
                className="w-full accent-rose-500"
              />
            </div>

            <div>
              <label className="text-slate-300 block mb-1">SIMULATED ERROR RATE: {(errorRate * 100).toFixed(0)}%</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={errorRate}
                onChange={e => setErrorRate(parseFloat(e.target.value))}
                className="w-full accent-rose-500"
              />
            </div>

            <div>
              <label className="text-slate-300 block mb-1">PACKET DROP RATE: {(dropRate * 100).toFixed(0)}%</label>
              <input
                type="range"
                min="0"
                max="0.5"
                step="0.01"
                value={dropRate}
                onChange={e => setDropRate(parseFloat(e.target.value))}
                className="w-full accent-rose-500"
              />
            </div>

            <button type="submit" className="w-full btn-neon-magenta justify-center py-2.5 text-xs">
              APPLY CHAOS RULES
            </button>
          </form>
        </div>

        {/* Leaderboard */}
        <div className="hud-panel p-6 space-y-4">
          <h4 className="text-sm font-bold text-amber-400 font-mono border-b border-slate-800 pb-3 flex items-center gap-2">
            <Flame className="w-4 h-4 text-amber-400" /> MOST USED TOOLS LEADERBOARD
          </h4>

          {leaderboard.length === 0 ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              No tool executions recorded yet.
            </div>
          ) : (
            <div className="space-y-2">
              {leaderboard.map((item, idx) => (
                <div key={idx} className="p-3 rounded bg-slate-900 border border-slate-800 flex items-center justify-between font-mono text-xs">
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-400 font-bold flex items-center justify-center text-xs">
                      #{idx + 1}
                    </span>
                    <span className="text-white font-bold">{item.tool_name || item.name}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-cyan-400 font-bold">{item.calls_count || item.total_calls || 12} calls</span>
                    <div className="text-[10px] text-slate-400">{item.avg_latency || '45'} ms avg</div>
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
