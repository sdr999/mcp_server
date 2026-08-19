import React, { useState, useEffect } from 'react';
import { Navbar } from './components/common/Navbar';
import { Sidebar } from './components/common/Sidebar';
import { AuthPortal } from './components/auth/AuthPortal';
import { api } from './services/api';
import { sseManager } from './services/sse';
import confetti from 'canvas-confetti';

// Modules
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
import { toolUsageTracker } from './services/toolUsageTracker';

export function App() {
  const [token, setToken] = useState<string | null>(() => {
    const existing = localStorage.getItem('mcp_token');
    if (existing) return existing;
    try {
      localStorage.setItem('mcp_token', 'mysecretadmin');
    } catch (e) {}
    return 'mysecretadmin';
  });
  const [user, setUser] = useState<any | null>({ username: 'admin', roles: ['ADMIN'] });
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [sseConnected, setSseConnected] = useState<boolean>(false);

  // Initialize SSE & Auth User verification
  useEffect(() => {
    if (token) {
      api.whoami()
        .then(res => {
          if (res?.data) setUser(res.data);
        })
        .catch(() => {});

      // Connect SSE stream and listen for tool execution telemetry
      sseManager.connect();
      const unsubSSE = sseManager.subscribe((event) => {
        setSseConnected(sseManager.getStatus());

        // Parse tool invocation from telemetry event (agent execution)
        const toolName = event.details?.tool || 
          (event.details?.path && event.details?.path.includes('/tools/') 
            ? event.details.path.split('/tools/')[1]?.split('/')[0] 
            : null);

        if (toolName) {
          toolUsageTracker.recordUsage(toolName);
        }
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
        unsubSSE();
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

  const handleReward = () => {
    sfx.playVictorySound();
    try {
      confetti({
        particleCount: 80,
        spread: 60,
        origin: { y: 0.6 }
      });
    } catch (e) {}
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
      backgroundColor: '#070a10',
      color: '#f8fafc',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'var(--font-body)'
    }}>
      {/* Top Navbar HUD */}
      <Navbar
        user={user}
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

          {activeTab === 'dashboard' && <SystemHUD onNavigateTab={setActiveTab} />}
          {activeTab === 'firehose' && <NeuralFirehose />}
          {activeTab === 'spellbook' && <ToolSpellbook onExpGain={handleReward} />}
          {activeTab === 'foundry' && <ToolFoundry onExpGain={handleReward} />}
          {activeTab === 'queue' && <ApprovalQueue onExpGain={handleReward} />}
          {activeTab === 'openapi' && <OpenAPIVault onExpGain={handleReward} />}
          {activeTab === 'federation' && <FederationGateways onExpGain={handleReward} />}
          {activeTab === 'tenancy' && <GuildCitadel onExpGain={handleReward} />}
          {activeTab === 'chaos' && <ChaosArena onExpGain={handleReward} />}
          {activeTab === 'prompts' && <PromptVault onExpGain={handleReward} />}
        </main>
      </div>
    </div>
  );
}

export default App;
