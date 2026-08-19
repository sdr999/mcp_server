import React, { useState } from 'react';
import { Shield, Volume2, VolumeX, LogOut, Flame, Sparkles } from 'lucide-react';
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
      borderBottom: '3px solid #2a3e66',
      padding: '0.65rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      backgroundColor: '#0c172c',
      boxShadow: '0 6px 20px rgba(0, 0, 0, 0.6)'
    }}>
      {/* Brand & Arena Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '2.75rem',
          height: '2.75rem',
          borderRadius: '0.75rem',
          background: 'linear-gradient(180deg, #fde047 0%, #ca8a04 100%)',
          border: '2px solid #fef08a',
          boxShadow: '0 4px 10px rgba(133, 77, 14, 0.5)'
        }}>
          <span style={{ fontSize: '1.5rem', filter: 'drop-shadow(0 2px 2px rgba(0,0,0,0.5))' }}>👑</span>
        </div>
        <div>
          <h1 className="font-title" style={{
            fontSize: '1.35rem',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            MCP CITADEL
            <span style={{
              fontSize: '0.65rem',
              padding: '0.15rem 0.5rem',
              borderRadius: '0.375rem',
              background: 'linear-gradient(180deg, #38bdf8, #0369a1)',
              color: '#ffffff',
              border: '1px solid #bae6fd'
            }}>ARENA 15</span>
          </h1>
          <p className="font-game" style={{
            fontSize: '0.75rem',
            color: '#94a3b8',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            margin: 0
          }}>
            <span style={{
              width: '0.5rem',
              height: '0.5rem',
              borderRadius: '9999px',
              backgroundColor: sseConnected ? '#22c55e' : '#ef4444',
              boxShadow: sseConnected ? '0 0 8px #22c55e' : 'none'
            }} />
            {sseConnected ? 'NEURAL ARENA ACTIVE' : 'RECONNECTING STREAM...'}
          </p>
        </div>
      </div>

      {/* Gamified Clash Royale Arena Stats Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1.25rem',
        backgroundColor: '#13223f',
        padding: '0.4rem 1.25rem',
        borderRadius: '0.75rem',
        border: '2px solid #2a3e66',
        boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.4)'
      }}>
        {/* King Level Badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{
            background: 'linear-gradient(180deg, #38bdf8, #0284c7)',
            padding: '0.35rem 0.6rem',
            borderRadius: '0.5rem',
            border: '1.5px solid #bae6fd',
            boxShadow: '0 2px 6px rgba(2, 132, 199, 0.4)',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem'
          }}>
            <span style={{ fontSize: '1rem' }}>👑</span>
            <span className="font-title" style={{ fontSize: '0.875rem' }}>LVL {userLevel}</span>
          </div>
          <div>
            <div className="font-title" style={{ fontSize: '0.75rem', color: '#fde047' }}>
              {userExp} / {nextLevelExp} <span style={{ color: '#94a3b8', fontSize: '0.65rem' }}>XP</span>
            </div>
            {/* XP Progress Bar */}
            <div style={{ width: '6.5rem', height: '6px', backgroundColor: '#070e1e', borderRadius: '3px', overflow: 'hidden', border: '1px solid #ca8a04', marginTop: '2px' }}>
              <div style={{ width: `${expProgress}%`, height: '100%', background: 'linear-gradient(90deg, #fde047, #ca8a04)' }} />
            </div>
          </div>
        </div>

        {/* Trophies Counter */}
        <div className="trophy-badge" title="Trophy League">
          <span style={{ fontSize: '1rem' }}>🏆</span>
          <span>4,850</span>
        </div>

        {/* Elixir Mana Tank */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div className="elixir-badge">💧</div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="font-title" style={{ fontSize: '0.7rem', color: '#f472b6' }}>
              ELIXIR: <strong style={{ color: '#ffffff' }}>10/10</strong>
            </div>
            <div className="elixir-bar-outer" style={{ width: '5.5rem', height: '8px' }}>
              <div className="elixir-bar-inner" style={{ width: '100%' }} />
            </div>
          </div>
        </div>

        {/* Gold & Gems */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', paddingLeft: '0.75rem', borderLeft: '2px solid #2a3e66' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: '#fde047' }} className="font-title">
            <span style={{ fontSize: '0.9rem' }}>🪙</span>
            <span style={{ fontSize: '0.8rem' }}>48.2K</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: '#38bdf8' }} className="font-title">
            <span style={{ fontSize: '0.9rem' }}>💎</span>
            <span style={{ fontSize: '0.8rem' }}>1,250</span>
          </div>
        </div>
      </div>

      {/* Audio Toggle, Profile & Sign Out */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {/* Sound FX Toggle Button */}
        <button
          onClick={handleToggleSound}
          style={{
            background: muted ? '#1e293b' : '#0284c7',
            border: '2px solid #38bdf8',
            borderRadius: '0.5rem',
            padding: '0.5rem',
            color: '#ffffff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 3px 0 #0369a1'
          }}
          title={muted ? 'Unmute Sound Effects' : 'Mute Sound Effects'}
        >
          {muted ? <VolumeX style={{ width: '1.1rem', height: '1.1rem' }} /> : <Volume2 style={{ width: '1.1rem', height: '1.1rem' }} />}
        </button>

        {/* User Card */}
        <div style={{ textAlign: 'right' }}>
          <div className="font-title" style={{
            fontSize: '0.875rem',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            justifyContent: 'flex-end'
          }}>
            <Shield style={{ width: '0.875rem', height: '0.875rem', color: '#fde047' }} />
            {user?.sub || user?.username || 'Grand Master'}
          </div>
          <div className="font-game" style={{
            fontSize: '0.7rem',
            color: '#38bdf8',
            textTransform: 'uppercase',
            fontWeight: 700
          }}>
            {user?.roles?.[0] || 'CLAN LEADER'}
          </div>
        </div>

        {/* Sign Out 3D Red Button */}
        <button
          onClick={() => {
            sfx.playTapSound();
            onLogout();
          }}
          className="btn-cr btn-cr-red"
          style={{
            fontSize: '0.75rem',
            padding: '0.45rem 0.85rem'
          }}
          title="Leave the Arena"
        >
          <LogOut style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>EXIT</span>
        </button>
      </div>
    </header>
  );
};
