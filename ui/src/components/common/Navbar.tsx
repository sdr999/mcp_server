import React, { useState } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Radio, Cpu, Activity, Terminal } from 'lucide-react';
import { sfx } from '../../services/soundEffects';

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
  const [muted, setMuted] = useState(sfx.isMuted());
  const nextLevelExp = userLevel * 1000;
  const expProgress = Math.min(Math.floor((userExp / nextLevelExp) * 100), 100);

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
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.5rem',
          height: '2.5rem',
          borderRadius: '0.375rem',
          background: 'linear-gradient(180deg, #0284c7, #0369a1)',
          border: '1px solid #38bdf8',
          boxShadow: '0 0 15px rgba(0, 240, 255, 0.35)'
        }}>
          <Radio className="animate-pulse" style={{ width: '1.35rem', height: '1.35rem', color: '#ffffff' }} />
        </div>
        <div>
          <h1 className="font-title" style={{
            fontSize: '1.2rem',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            MCP ORBITAL COMMAND
            <span style={{
              fontSize: '0.65rem',
              padding: '0.15rem 0.5rem',
              borderRadius: '0.25rem',
              background: 'rgba(0, 240, 255, 0.15)',
              color: '#00f0ff',
              border: '1px solid rgba(0, 240, 255, 0.4)'
            }}>TACTICAL OS v2.0</span>
          </h1>
          <p className="font-mono" style={{
            fontSize: '0.75rem',
            color: '#94a3b8',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            <span style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: sseConnected ? '#10b981' : '#f43f5e',
              boxShadow: sseConnected ? '0 0 8px #10b981' : 'none'
            }} />
            {sseConnected ? 'RADAR TELEMETRY: ARMED' : 'RECONNECTING COMMS...'}
          </p>
        </div>
      </div>

      {/* Tactical Telemetry Gauges */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.25rem',
        backgroundColor: '#0d131f',
        padding: '0.4rem 1.25rem',
        borderRadius: '0.5rem',
        border: '1px solid #1e2c45'
      }}>
        {/* Clearance Rank */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{
            background: 'rgba(245, 158, 11, 0.15)',
            padding: '0.35rem 0.6rem',
            borderRadius: '0.375rem',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            color: '#fbbf24',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem'
          }}>
            <Shield style={{ width: '1rem', height: '1rem' }} />
            <span className="font-title" style={{ fontSize: '0.8rem' }}>CLEARANCE LVL {userLevel}</span>
          </div>
          <div>
            <div className="font-mono" style={{ fontSize: '0.75rem', color: '#fbbf24' }}>
              {userExp} / {nextLevelExp} <span style={{ color: '#94a3b8', fontSize: '0.65rem' }}>EXP</span>
            </div>
            <div style={{ width: '6.5rem', height: '5px', backgroundColor: '#070a10', borderRadius: '2px', overflow: 'hidden', border: '1px solid #78350f', marginTop: '2px' }}>
              <div style={{ width: `${expProgress}%`, height: '100%', background: 'linear-gradient(90deg, #00f0ff, #fbbf24)' }} />
            </div>
          </div>
        </div>

        {/* Reactor Power Output */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2c45' }}>
          <Cpu style={{ width: '1.1rem', height: '1.1rem', color: '#00f0ff' }} />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="font-title" style={{ fontSize: '0.7rem', color: '#00f0ff' }}>REACTOR OUTPUT</span>
            <span className="font-mono" style={{ fontSize: '0.8rem', fontWeight: 700, color: '#34d399' }}>100% NOMINAL</span>
          </div>
        </div>

        {/* Uplink Latency */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2c45' }}>
          <Activity style={{ width: '1.1rem', height: '1.1rem', color: '#10b981' }} />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="font-title" style={{ fontSize: '0.7rem', color: '#94a3b8' }}>ORBITAL LATENCY</span>
            <span className="font-mono" style={{ fontSize: '0.8rem', fontWeight: 700, color: '#38bdf8' }}>1.2 ms</span>
          </div>
        </div>
      </div>

      {/* Audio Comms & Session Control */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleToggleSound}
          style={{
            background: muted ? '#1e293b' : 'rgba(0, 240, 255, 0.1)',
            border: '1px solid rgba(0, 240, 255, 0.3)',
            borderRadius: '0.375rem',
            padding: '0.45rem',
            color: '#00f0ff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title={muted ? 'Enable Comms Audio' : 'Mute Comms Audio'}
        >
          {muted ? <VolumeX style={{ width: '1.1rem', height: '1.1rem' }} /> : <Volume2 style={{ width: '1.1rem', height: '1.1rem' }} />}
        </button>

        {/* User Badge */}
        <div style={{ textAlign: 'right' }}>
          <div className="font-title" style={{
            fontSize: '0.85rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            {user?.sub || user?.username || 'Commander'}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.7rem',
            color: '#00f0ff',
            textTransform: 'uppercase'
          }}>
            {user?.roles?.[0] || 'ORBITAL OPERATOR'}
          </div>
        </div>

        {/* Disconnect Button */}
        <button
          onClick={() => {
            sfx.playTapSound();
            onLogout();
          }}
          className="btn-sc btn-sc-crimson"
          style={{
            fontSize: '0.75rem',
            padding: '0.45rem 0.85rem'
          }}
          title="Disconnect from Command Station"
        >
          <LogOut style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>DISCONNECT</span>
        </button>
      </div>
    </header>
  );
};
