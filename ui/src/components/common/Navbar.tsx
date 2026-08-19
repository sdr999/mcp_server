import React, { useState, useEffect } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Radio, Cpu, Activity, Zap, Server, Award, Trophy } from 'lucide-react';
import { sfx } from '../../services/soundEffects';
import { toolUsageTracker, ToolMastery } from '../../services/toolUsageTracker';

interface NavbarProps {
  user: any;
  onLogout: () => void;
  sseConnected: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  onLogout,
  sseConnected
}) => {
  const [muted, setMuted] = useState(sfx.isMuted());
  const [totalCalls, setTotalCalls] = useState(toolUsageTracker.getTotalCalls());
  const [topTool, setTopTool] = useState<ToolMastery | null>(toolUsageTracker.getTopRankedTool());

  useEffect(() => {
    const unsub = toolUsageTracker.subscribe(() => {
      setTotalCalls(toolUsageTracker.getTotalCalls());
      setTopTool(toolUsageTracker.getTopRankedTool());
    });
    return unsub;
  }, []);

  const handleToggleSound = () => {
    const isNowMuted = sfx.toggleMute();
    setMuted(isNowMuted);
  };

  return (
    <header style={{
      borderBottom: '1px solid #1e2c45',
      padding: '0.65rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      backgroundColor: '#0a0f1a',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.7)'
    }}>
      {/* Brand & Orbital Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.25rem',
          height: '2.25rem',
          borderRadius: '0.375rem',
          background: 'linear-gradient(180deg, #0284c7, #0369a1)',
          border: '1px solid #38bdf8',
          boxShadow: '0 0 12px rgba(0, 240, 255, 0.25)'
        }}>
          <Radio className="animate-pulse" style={{ width: '1.2rem', height: '1.2rem', color: '#ffffff' }} />
        </div>
        <div>
          <h1 className="font-title" style={{
            fontSize: '1.1rem',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            MCP ORBITAL COMMAND
            <span style={{
              fontSize: '0.625rem',
              padding: '0.1rem 0.4rem',
              borderRadius: '0.25rem',
              background: 'rgba(0, 240, 255, 0.12)',
              color: '#00f0ff',
              border: '1px solid rgba(0, 240, 255, 0.3)'
            }}>v2.0</span>
          </h1>
          <p className="font-mono" style={{
            fontSize: '0.7rem',
            color: '#94a3b8',
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            margin: 0
          }}>
            <span style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: sseConnected ? '#10b981' : '#f43f5e',
              boxShadow: sseConnected ? '0 0 8px #10b981' : 'none'
            }} />
            {sseConnected ? 'TELEMETRY ONLINE' : 'DISCONNECTED'}
          </p>
        </div>
      </div>

      {/* Toned-down Sleek Telemetry Center */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.5rem',
        backgroundColor: '#0d131f',
        padding: '0.35rem 1.25rem',
        borderRadius: '0.375rem',
        border: '1px solid #1e2c45',
        fontSize: '0.75rem'
      }}>
        {/* Total Tool Invocations (Agent + Manual) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Zap style={{ width: '0.95rem', height: '0.95rem', color: '#ff9f1c' }} />
          <span className="font-title" style={{ color: '#94a3b8', fontSize: '0.7rem' }}>INVOCATIONS:</span>
          <span className="font-mono" style={{ color: '#ff9f1c', fontWeight: 700 }}>
            {totalCalls} <span style={{ color: '#64748b', fontSize: '0.65rem' }}>CALLS</span>
          </span>
        </div>

        {/* Top Ranked Tool */}
        {topTool && topTool.calls > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2c45' }}>
            <Trophy style={{ width: '0.95rem', height: '0.95rem', color: '#fbbf24' }} />
            <span className="font-title" style={{ color: '#94a3b8', fontSize: '0.7rem' }}>RANK #1:</span>
            <span className="font-mono" style={{ color: '#fbbf24', fontWeight: 700 }}>
              {topTool.name} <span style={{ color: '#a855f7', fontSize: '0.65rem' }}>(LVL {topTool.level})</span>
            </span>
          </div>
        )}

        {/* Cluster Operational Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2c45' }}>
          <Server style={{ width: '0.95rem', height: '0.95rem', color: '#34d399' }} />
          <span className="font-title" style={{ color: '#94a3b8', fontSize: '0.7rem' }}>CLUSTER:</span>
          <span className="font-mono" style={{ color: '#34d399', fontWeight: 700 }}>100% NOMINAL</span>
        </div>

        {/* Latency */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2c45' }}>
          <Activity style={{ width: '0.95rem', height: '0.95rem', color: '#00f0ff' }} />
          <span className="font-title" style={{ color: '#94a3b8', fontSize: '0.7rem' }}>LATENCY:</span>
          <span className="font-mono" style={{ color: '#00f0ff', fontWeight: 700 }}>1.2 ms</span>
        </div>
      </div>

      {/* Audio & Session Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleToggleSound}
          style={{
            background: muted ? '#1e293b' : 'rgba(0, 240, 255, 0.1)',
            border: '1px solid rgba(0, 240, 255, 0.3)',
            borderRadius: '0.375rem',
            padding: '0.4rem',
            color: '#00f0ff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title={muted ? 'Enable Comms Audio' : 'Mute Comms Audio'}
        >
          {muted ? <VolumeX style={{ width: '1rem', height: '1rem' }} /> : <Volume2 style={{ width: '1rem', height: '1rem' }} />}
        </button>

        {/* User Identity */}
        <div style={{ textAlign: 'right' }}>
          <div className="font-title" style={{
            fontSize: '0.8rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            {user?.sub || user?.username || 'Commander'}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.65rem',
            color: '#00f0ff',
            textTransform: 'uppercase'
          }}>
            {user?.roles?.[0] || 'ORBITAL OPERATOR'}
          </div>
        </div>

        {/* Logout */}
        <button
          onClick={() => {
            sfx.playTapSound();
            onLogout();
          }}
          className="btn-sc btn-sc-crimson"
          style={{
            fontSize: '0.7rem',
            padding: '0.35rem 0.75rem'
          }}
          title="Disconnect from Command Station"
        >
          <LogOut style={{ width: '0.75rem', height: '0.75rem' }} />
          <span>EXIT</span>
        </button>
      </div>
    </header>
  );
};
