import React, { useState } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Radio, Cpu, Activity, FlaskConical, CircleDot } from 'lucide-react';
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
      borderBottom: '1px solid #1e2638',
      padding: '0.65rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      backgroundColor: '#0c0f17',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.6)'
    }}>
      {/* Brand & Aperture Lab Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.5rem',
          height: '2.5rem',
          borderRadius: '0.375rem',
          background: 'linear-gradient(180deg, #00a6ed 0%, #0077b6 100%)',
          border: '1px solid #7dd3fc',
          boxShadow: '0 0 15px rgba(0, 166, 237, 0.4)'
        }}>
          <FlaskConical style={{ width: '1.35rem', height: '1.35rem', color: '#ffffff' }} />
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
            APERTURE SCIENCE
            <span style={{
              fontSize: '0.65rem',
              padding: '0.15rem 0.5rem',
              borderRadius: '0.25rem',
              background: 'rgba(255, 119, 0, 0.15)',
              color: '#ff7700',
              border: '1px solid rgba(255, 119, 0, 0.4)'
            }}>TEST CHAMBER PROTOCOL</span>
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
            {sseConnected ? 'GLaDOS SENSORS: ONLINE' : 'TELEMETRY OFFLINE'}
          </p>
        </div>
      </div>

      {/* Test Subject Progression & Quantum Tunneling */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.25rem',
        backgroundColor: '#121722',
        padding: '0.4rem 1.25rem',
        borderRadius: '0.5rem',
        border: '1px solid #1e2638'
      }}>
        {/* Test Subject Level */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{
            background: 'rgba(0, 166, 237, 0.15)',
            padding: '0.35rem 0.6rem',
            borderRadius: '0.375rem',
            border: '1px solid rgba(0, 166, 237, 0.4)',
            color: '#00a6ed',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem'
          }}>
            <Shield style={{ width: '1rem', height: '1rem' }} />
            <span className="font-title" style={{ fontSize: '0.8rem' }}>CANDIDATE LVL {userLevel}</span>
          </div>
          <div>
            <div className="font-mono" style={{ fontSize: '0.75rem', color: '#00a6ed' }}>
              {userExp} / {nextLevelExp} <span style={{ color: '#94a3b8', fontSize: '0.65rem' }}>PTS</span>
            </div>
            <div style={{ width: '6.5rem', height: '5px', backgroundColor: '#0b0d13', borderRadius: '2px', overflow: 'hidden', border: '1px solid #005580', marginTop: '2px' }}>
              <div style={{ width: `${expProgress}%`, height: '100%', background: 'linear-gradient(90deg, #00a6ed, #ff7700)' }} />
            </div>
          </div>
        </div>

        {/* Portal Quantum Stability */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2638' }}>
          <CircleDot style={{ width: '1.1rem', height: '1.1rem', color: '#ff7700' }} />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="font-title" style={{ fontSize: '0.7rem', color: '#ff7700' }}>PORTAL STABILITY</span>
            <span className="font-mono" style={{ fontSize: '0.8rem', fontWeight: 700, color: '#34d399' }}>99.98% OPTIMAL</span>
          </div>
        </div>

        {/* Cake Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid #1e2638' }}>
          <span className="font-mono" style={{ fontSize: '0.8rem', color: '#fde047' }}>
            🎂 CAKE: <strong style={{ color: '#38bdf8' }}>AVAILABLE</strong>
          </span>
        </div>
      </div>

      {/* Lab Comms & Session End */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleToggleSound}
          style={{
            background: muted ? '#1e293b' : 'rgba(0, 166, 237, 0.1)',
            border: '1px solid rgba(0, 166, 237, 0.3)',
            borderRadius: '0.375rem',
            padding: '0.45rem',
            color: '#00a6ed',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title={muted ? 'Enable Lab Audio' : 'Mute Lab Audio'}
        >
          {muted ? <VolumeX style={{ width: '1.1rem', height: '1.1rem' }} /> : <Volume2 style={{ width: '1.1rem', height: '1.1rem' }} />}
        </button>

        {/* Subject ID */}
        <div style={{ textAlign: 'right' }}>
          <div className="font-title" style={{
            fontSize: '0.9rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            {user?.sub || user?.username || 'Test Subject #42'}
          </div>
          <div className="font-mono" style={{
            fontSize: '0.7rem',
            color: '#ff7700',
            textTransform: 'uppercase'
          }}>
            {user?.roles?.[0] || 'CHAMBER RESEARCHER'}
          </div>
        </div>

        {/* Exit Facility Button */}
        <button
          onClick={() => {
            sfx.playTapSound();
            onLogout();
          }}
          className="btn-portal btn-portal-crimson"
          style={{
            fontSize: '0.75rem',
            padding: '0.45rem 0.85rem'
          }}
          title="Exit Testing Facility"
        >
          <LogOut style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>EXIT LAB</span>
        </button>
      </div>
    </header>
  );
};
