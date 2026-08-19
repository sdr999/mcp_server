import React, { useState, useEffect } from 'react';
import confetti from 'canvas-confetti';
import { api } from './services/api';
import { sseManager } from './services/sse';
import { Navbar } from './components/common/Navbar';
import { Sidebar } from './components/common/Sidebar';
import { AuthPortal } from './components/auth/AuthPortal';
import { SystemHUD } from './components/dashboard/SystemHUD';
import { NeuralFirehose } from './components/dashboard/NeuralFirehose';
import { ToolSpellbook } from './components/tools/ToolSpellbook';
import { ToolFoundry } from './components/tools/ToolFoundry';
import { ApprovalQueue } from './components/queue/ApprovalQueue';
import { OpenAPIVault } from './components/openapi/OpenAPIVault';
import { FederationGateways } from './components/federation/FederationGateways';
import { GuildCitadel } from './components/tenancy/GuildCitadel';
import { ChaosArena } from './components/analytics/ChaosArena';
import { PromptVault } from './components/prompts/PromptVault';

import { sfx } from './services/soundEffects';

export function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('mcp_token'));
  const [user, setUser] = useState<any | null>(null);
  const [userExp, setUserExp] = useState<number>(3450);
  const [userLevel, setUserLevel] = useState<number>(12);
  const [activeTab, setActiveTab] = useState<string>('spellbook');
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [sseConnected, setSseConnected] = useState<boolean>(false);

  // Initialize SSE & Auth User verification
  useEffect(() => {
    if (token) {
      api.whoami()
        .then(res => setUser(res.data))
        .catch(() => {});

      // Connect SSE stream
      sseManager.connect();
      const unsub = sseManager.subscribe(() => {
        setSseConnected(sseManager.getStatus());
      });

      // Fetch pending queue count for sidebar badge
      api.getPendingTools()
        .then(res => {
          const raw = res.data;
          const len = Array.isArray(raw) ? raw.length : raw?.pending?.length || 0;
          setPendingCount(len);
        })
        .catch(() => {});

      return () => {
        unsub();
      };
    }
  }, [token]);

  const handleLogout = () => {
    localStorage.removeItem('mcp_token');
    localStorage.removeItem('mcp_refresh_token');
    sseManager.disconnect();
    setToken(null);
    setUser(null);
  };

  const handleExpGain = (gained: number) => {
    setUserExp(prev => {
      const updated = prev + gained;
      const nextLevelThreshold = userLevel * 1000;
      if (updated >= nextLevelThreshold) {
        setUserLevel(lvl => lvl + 1);
        sfx.playLevelUpSound();
        // Trigger Gamified Confetti Level-Up effect!
        try {
          confetti({
            particleCount: 120,
            spread: 80,
            origin: { y: 0.6 }
          });
        } catch (e) {}
      }
      return updated;
    });
  };

  if (!token) {
    return (
      <AuthPortal
        onLoginSuccess={(newToken, userData) => {
          setToken(newToken);
          setUser(userData);
        }}
      />
    );
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#070e1e',
      color: '#f8fafc',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'var(--font-game)'
    }}>
      {/* Top Navbar HUD */}
      <Navbar
        user={user}
        userExp={userExp}
        userLevel={userLevel}
        onLogout={handleLogout}
        sseConnected={sseConnected}
      />

      {/* Main Layout: Sidebar + Main Content */}
      <div style={{ flex: 1, display: 'flex' }}>
        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          pendingCount={pendingCount}
        />

        <main style={{
          flex: 1,
          padding: '1.5rem',
          overflowY: 'auto',
          maxWidth: '85rem',
          margin: '0 auto',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.25rem'
        }}>
          {/* Tactical Orbital Breadcrumb & Telemetry Bar */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.65rem 1.25rem',
            background: '#0d131f',
            border: '1px solid #1e2c45',
            borderRadius: '0.375rem',
            fontSize: '0.8rem',
            color: '#94a3b8',
            boxShadow: '0 4px 14px rgba(0,0,0,0.5)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="font-title" style={{ color: '#00f0ff' }}>🛰️ ORBITAL COMMAND</span>
              <span>/</span>
              <span className="font-mono" style={{ color: '#ff9f1c', textTransform: 'uppercase' }}>TACTICAL OPS</span>
              <span>/</span>
              <span className="font-title" style={{ color: '#ffffff', textTransform: 'uppercase' }}>{activeTab}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <span className="font-title" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: sseConnected ? '#4ade80' : '#f87171', fontSize: '0.75rem' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: sseConnected ? '#22c55e' : '#ef4444', boxShadow: sseConnected ? '0 0 8px #22c55e' : 'none' }} />
                {sseConnected ? 'TELEMETRY STREAM: READY' : 'TELEMETRY: OFFLINE'}
              </span>
            </div>
          </div>

          {activeTab === 'dashboard' && <SystemHUD />}
          {activeTab === 'firehose' && <NeuralFirehose />}
          {activeTab === 'spellbook' && <ToolSpellbook onExpGain={handleExpGain} />}
          {activeTab === 'foundry' && <ToolFoundry onExpGain={handleExpGain} />}
          {activeTab === 'queue' && <ApprovalQueue onExpGain={handleExpGain} />}
          {activeTab === 'openapi' && <OpenAPIVault onExpGain={handleExpGain} />}
          {activeTab === 'federation' && <FederationGateways onExpGain={handleExpGain} />}
          {activeTab === 'tenancy' && <GuildCitadel onExpGain={handleExpGain} />}
          {activeTab === 'chaos' && <ChaosArena onExpGain={handleExpGain} />}
          {activeTab === 'prompts' && <PromptVault onExpGain={handleExpGain} />}
        </main>
      </div>
    </div>
  );
}

export default App;
