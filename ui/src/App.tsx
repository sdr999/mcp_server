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

export function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('mcp_token'));
  const [user, setUser] = useState<any | null>(null);
  const [userExp, setUserExp] = useState<number>(3450);
  const [userLevel, setUserLevel] = useState<number>(4);
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [sseConnected, setSseConnected] = useState<boolean>(false);

  // Initialize SSE & Auth User verification
  useEffect(() => {
    if (token) {
      api.whoami()
        .then(res => setUser(res.data))
        .catch(() => {
          // Token invalid, clear
          // localStorage.removeItem('mcp_token');
          // setToken(null);
        });

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
        // Trigger Gamified Confetti Level-Up effect!
        try {
          confetti({
            particleCount: 100,
            spread: 70,
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
      backgroundColor: '#07090e',
      color: '#f1f5f9',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'var(--font-body)'
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
          maxWidth: '80rem',
          margin: '0 auto',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem'
        }}>
          {/* Breadcrumb & Navigation Context Bar */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.5rem 1rem',
            background: 'rgba(15, 23, 42, 0.5)',
            border: '1px solid rgba(30, 41, 59, 0.8)',
            borderRadius: '0.375rem',
            fontSize: '0.75rem',
            color: '#94a3b8',
            fontFamily: 'var(--font-mono)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ color: '#00f0ff', fontWeight: 700 }}>CITADEL OS</span>
              <span>/</span>
              <span style={{ color: '#ff0055', textTransform: 'uppercase' }}>MODULE</span>
              <span>/</span>
              <span style={{ color: '#ffffff', fontWeight: 700, textTransform: 'uppercase' }}>{activeTab}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: sseConnected ? '#34d399' : '#f43f5e' }}>
                <span className={sseConnected ? 'animate-ping' : ''} style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: sseConnected ? '#34d399' : '#f43f5e' }} />
                {sseConnected ? 'TELEMETRY ONLINE' : 'OFFLINE'}
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
