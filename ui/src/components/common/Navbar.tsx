import React, { useState } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Radio, Cpu, Activity, Globe, Disc } from 'lucide-react';
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
      borderBottom: '1px solid rgba(42, 62, 102, 0.8)',
      padding: '0.65rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      backgroundColor: '#090e18',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.6)'
    }}>
      {/* Brand & Citadel Station Info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.5rem',
          height: '2.5rem',
          borderRadius: '0.375rem',
          background: 'linear-gradient(180deg, #e5a93b 0%, #b45309 100%)',
          border: '1px solid #fde047',
          boxShadow: '0 0 15px rgba(229, 169, 59, 0.35)'
        }}>
          <Disc className="animate-spin" style={{ width: '1.35rem', height: '1.35rem', color: '#ffffff', animationDuration: '8s' }} />
        </div>
        <div>
          <h1 className="font-title" style={{
            fontSize: '1.25rem',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            ASTRAHUS CITADEL OS
            <span style={{
              fontSize: '0.65rem',
              padding: '0.15rem 0.5rem',
              borderRadius: '0.25rem',
              background: 'rgba(56, 189, 248, 0.15)',
              color: '#38bdf8',
              border: '1px solid rgba(56, 189, 248, 0.4)'
            }}>SECURITY 0.0</span>
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
            {sseConnected ? 'CITADEL WARP RELAY ONLINE' : 'RELAY OFFLINE'}
          </p>
        </div>
      </div>

      {/* Station Capacitor & Credits Telemetry */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.25rem',
        backgroundColor: '#0c121e',
        padding: '0.4rem 1.25rem',
        borderRadius: '0.5rem',
        border: '1px solid rgba(42, 62, 102, 0.8)'
      }}>
        {/* Pilot License Rank */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{
            background: 'rgba(229, 169, 59, 0.15)',
            padding: '0.35rem 0.6rem',
            borderRadius: '0.375rem',
            border: '1px solid rgba(229, 169, 59, 0.4)',
            color: '#e5a93b',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem'
          }}>
            <Shield style={{ width: '1rem', height: '1rem' }} />
            <span className="font-title" style={{ fontSize: '0.8rem' }}>LICENSE RANK {userLevel}</span>
          </div>
          <div>
            <div className="font-mono" style={{ fontSize: '0.75rem', color: '#e5a93b' }}>
              {userExp} / {nextLevelExp} <span style={{ color: '#94a3b8', fontSize: '0.65rem' }}>SP</span>
            </div>
            <div style={{ width: '6.5rem', height: '5px', backgroundColor: '#060911', borderRadius: '2px', overflow: 'hidden', border: '1px solid #78350f', marginTop: '2px' }}>
              <div style={{ width: `${expProgress}%`, height: '100%', background: 'linear-gradient(90deg, #38bdf8, #e5a93b)' }} />
            </div>
          </div>
        </div>

        {/* Capacitor Energy */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid rgba(42, 62, 102, 0.8)' }}>
          <Cpu style={{ width: '1.1rem', height: '1.1rem', color: '#38bdf8' }} />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="font-title" style={{ fontSize: '0.7rem', color: '#38bdf8' }}>CAPACITOR</span>
            <span className="font-mono" style={{ fontSize: '0.8rem', fontWeight: 700, color: '#34d399' }}>100% (STABLE)</span>
          </div>
        </div>

        {/* ISK Credits */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid rgba(42, 62, 102, 0.8)' }}>
          <div className="font-title" style={{ fontSize: '0.85rem', color: '#fde047' }}>
            🪙 48,250,000 <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>ISK</span>
          </div>
        </div>
      </div>

      {/* Comms Audio & Station Undock */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleToggleSound}
          style={{
            background: muted ? '#1e293b' : 'rgba(56, 189, 248, 0.1)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            borderRadius: '0.375rem',
            padding: '0.45rem',
            color: '#38bdf8',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title={muted ? 'Enable Station Audio' : 'Mute Station Audio'}
        >
          {muted ? <VolumeX style={{ width: '1.1rem', height: '1.1rem' }} /> : <Volume2 style={{ width: '1.1rem', height: '1.1rem' }} />}
        </button>

        {/* Pilot ID */}
        <div style={{ textAlign: 'right' }}>
          <div className="font-title" style={{
            fontSize: '0.9rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            {user?.sub || user?.username || 'Fleet Commander'}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.7rem',
            color: '#e5a93b',
            textTransform: 'uppercase'
          }}>
            {user?.roles?.[0] || 'STATION MASTER'}
          </div>
        </div>

        {/* Undock / Exit */}
        <button
          onClick={() => {
            sfx.playTapSound();
            onLogout();
          }}
          className="btn-eve btn-eve-crimson"
          style={{
            fontSize: '0.75rem',
            padding: '0.45rem 0.85rem'
          }}
          title="Undock from Station"
        >
          <LogOut style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>UNDOCK</span>
        </button>
      </div>
    </header>
  );
};
