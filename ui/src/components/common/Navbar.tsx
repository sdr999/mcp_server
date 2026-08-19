import React from 'react';
import { Shield, Zap, Flame, LogOut, Cpu } from 'lucide-react';

interface NavbarProps {
  user: any;
  userExp: number;
  userLevel: number;
  onLogout: () => void;
  sseConnected: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  userExp,
  userLevel,
  onLogout,
  sseConnected
}) => {
  const nextLevelExp = userLevel * 1000;
  const expProgress = Math.min(Math.floor((userExp / nextLevelExp) * 100), 100);

  return (
    <header className="hud-panel" style={{
      borderBottom: '1px solid rgba(0,240,255,0.3)',
      padding: '0.75rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      backgroundColor: 'rgba(7,9,14,0.9)',
      backdropFilter: 'blur(12px)'
    }}>
      {/* Brand & Reactor Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.5rem',
          height: '2.5rem',
          borderRadius: '0.5rem',
          backgroundColor: 'rgba(8,51,68,0.5)',
          border: '1px solid rgba(6,182,212,0.5)',
          boxShadow: '0 0 15px rgba(0,240,255,0.3)'
        }}>
          <Zap className="animate-pulse" style={{ width: '1.5rem', height: '1.5rem', color: '#22d3ee' }} />
        </div>
        <div>
          <h1 className="font-title" style={{
            fontSize: '1.25rem',
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            MCP CITADEL 
            <span style={{
              fontSize: '0.75rem',
              padding: '0.125rem 0.5rem',
              borderRadius: '0.25rem',
              backgroundColor: 'rgba(6,182,212,0.2)',
              color: '#22d3ee',
              border: '1px solid rgba(6,182,212,0.4)'
            }}>v2.0</span>
          </h1>
          <p style={{
            fontSize: '0.75rem',
            color: '#94a3b8',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            <span className={sseConnected ? 'animate-ping' : ''} style={{
              width: '0.5rem',
              height: '0.5rem',
              borderRadius: '9999px',
              backgroundColor: sseConnected ? '#34d399' : '#f43f5e'
            }} />
            {sseConnected ? 'NEURAL STREAM ACTIVE' : 'STREAM RECONNECTING'}
          </p>
        </div>
      </div>

      {/* Gamified Level & EXP Gauge */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.5rem',
        backgroundColor: 'rgba(15,23,42,0.6)',
        padding: '0.5rem 1.25rem',
        borderRadius: '0.5rem',
        border: '1px solid #1e293b'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{
            padding: '0.375rem',
            borderRadius: '0.25rem',
            backgroundColor: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.3)',
            color: '#fbbf24'
          }}>
            <Flame className="animate-bounce" style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <div className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8' }}>COMMANDER LEVEL</div>
            <div className="font-mono" style={{
              fontSize: '1rem',
              fontWeight: 900,
              color: '#fbbf24',
              letterSpacing: '0.05em'
            }}>
              LVL {userLevel} <span style={{ fontSize: '0.75rem', fontWeight: 400, color: '#94a3b8' }}>({userExp} / {nextLevelExp} XP)</span>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div style={{ width: '9rem' }}>
          <div className="xp-bar-outer">
            <div className="xp-bar-inner" style={{ width: `${expProgress}%` }} />
          </div>
          <div className="font-mono" style={{
            fontSize: '10px',
            color: '#22d3ee',
            textAlign: 'right',
            marginTop: '0.125rem'
          }}>{expProgress}% NEXT RANK</div>
        </div>

        {/* Fuel / API Rate Gauge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          paddingLeft: '1rem',
          borderLeft: '1px solid #1e293b'
        }}>
          <Cpu style={{ width: '1rem', height: '1rem', color: '#22d3ee' }} />
          <span className="font-mono" style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
            MANA: <strong style={{ color: '#34d399' }}>100%</strong>
          </span>
        </div>
      </div>

      {/* User Profile & Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{ textAlign: 'right' }}>
          <div style={{
            fontSize: '0.875rem',
            fontWeight: 700,
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.25rem',
            justifyContent: 'flex-end'
          }}>
            <Shield style={{ width: '0.875rem', height: '0.875rem', color: '#fbbf24' }} />
            {user?.sub || user?.username || 'Commander'}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.75rem',
            color: '#22d3ee',
            textTransform: 'uppercase',
            letterSpacing: '0.05em'
          }}>
            {user?.roles?.[0] || 'GUILD MASTER'}
          </div>
        </div>

        <button
          onClick={onLogout}
          className="btn-neon-magenta"
          style={{
            fontSize: '0.75rem',
            padding: '0.375rem 0.75rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.375rem'
          }}
          title="Sign out of Citadel"
        >
          <LogOut style={{ width: '1rem', height: '1rem' }} />
          <span>EXIT</span>
        </button>
      </div>
    </header>
  );
};
