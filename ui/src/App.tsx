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
    <div className="min-h-screen bg-[#07090e] text-slate-100 flex flex-col font-rajdhani">
      {/* Top Navbar HUD */}
      <Navbar
        user={user}
        userExp={userExp}
        userLevel={userLevel}
        onLogout={handleLogout}
        sseConnected={sseConnected}
      />

      {/* Main Layout: Sidebar + Main Content */}
      <div className="flex-1 flex">
        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          pendingCount={pendingCount}
        />

        <main className="flex-1 p-6 overflow-y-auto max-w-7xl mx-auto w-full">
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
