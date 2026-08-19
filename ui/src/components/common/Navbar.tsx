import React, { useState, useEffect } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Radio, Cpu, Activity, Zap, Server, Award, Trophy } from 'lucide-react';
import { sfx } from '../../services/soundEffects';
import { toolUsageTracker, ToolMastery } from '../../services/toolUsageTracker';

interface NavbarProps {
  user: any;
  onLogout: () => void;
  sseConnected: boolean;
}

// Role Hierarchy: Higher rank = higher priority displayed on the command interface
const ROLE_HIERARCHY: Record<string, { rank: number; label: string; color: string; bg: string }> = {
  platform_superadmin: { rank: 100, label: 'PLATFORM SUPERADMIN', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  superadmin: { rank: 100, label: 'SUPERADMIN', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  platform_admin: { rank: 90, label: 'PLATFORM ADMIN', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  admin: { rank: 85, label: 'COMMANDER (ADMIN)', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  org_admin: { rank: 80, label: 'FLEET ADMIRAL (ORG ADMIN)', color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' },
  workspace_admin: { rank: 70, label: 'STATION CAPTAIN (WS ADMIN)', color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' },
  developer: { rank: 60, label: 'ORBITAL ENGINEER (DEV)', color: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' },
  tool_creator: { rank: 50, label: 'FORGE SPECIALIST', color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)' },
  operator: { rank: 40, label: 'TACTICAL OPERATOR', color: '#00f0ff', bg: 'rgba(0, 240, 255, 0.15)' },
  member: { rank: 40, label: 'CREW MEMBER', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.15)' },
  agent_consumer: { rank: 30, label: 'AGENT CONSUMER', color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' },
  viewer: { rank: 20, label: 'OBSERVER (VIEWER)', color: '#64748b', bg: 'rgba(100, 116, 139, 0.15)' },
};

function getHighestPriorityRole(roles?: string[]): { label: string; color: string; bg: string } {
  if (!roles || !Array.isArray(roles) || roles.length === 0) {
    return { label: 'ORBITAL OPERATOR', color: '#00f0ff', bg: 'rgba(0, 240, 255, 0.15)' };
  }

  let highestRank = -1;
  let highestRole = { label: roles[0].toUpperCase(), color: '#00f0ff', bg: 'rgba(0, 240, 255, 0.15)' };

  for (const r of roles) {
    if (typeof r !== 'string') continue;
    const normalized = r.toLowerCase().trim().replace(/-/g, '_');
    const match = ROLE_HIERARCHY[normalized];
    const rank = match ? match.rank : 10;

    if (rank > highestRank) {
      highestRank = rank;
      highestRole = match || {
        label: r.toUpperCase().replace(/_/g, ' '),
        color: '#00f0ff',
        bg: 'rgba(0, 240, 255, 0.15)'
      };
    }
  }

  return highestRole;
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

  // Determine user display identity & highest priority role
  const activeRole = getHighestPriorityRole(user?.roles);
  const emailStr = user?.metadata?.email || user?.email;
  const usernameStr = user?.username || user?.metadata?.name || user?.name;
  const subjectStr = user?.subject ? `${user.subject.slice(0, 8)}...` : null;

  const displayName = usernameStr || (emailStr ? emailStr.split('@')[0] : subjectStr) || 'Commander';

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
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
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

        {/* User Identity & Priority Role Badge */}
        <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.15rem' }}>
          <div className="font-title" style={{
            fontSize: '0.8rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            {displayName}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.625rem',
            color: activeRole.color,
            backgroundColor: activeRole.bg,
            border: `1px solid ${activeRole.color}`,
            borderRadius: '0.25rem',
            padding: '0.1rem 0.4rem',
            textTransform: 'uppercase',
            fontWeight: 700,
            letterSpacing: '0.05em'
          }}>
            {activeRole.label}
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
