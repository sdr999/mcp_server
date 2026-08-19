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
    <header className="hud-panel border-b border-cyan-500/30 px-6 py-3 flex items-center justify-between sticky top-0 z-50 bg-[#07090e]/90 backdrop-blur-md">
      {/* Brand & Reactor Status */}
      <div className="flex items-center gap-4">
        <div className="relative flex items-center justify-center w-10 h-10 rounded-lg bg-cyan-950/50 border border-cyan-500/50 shadow-[0_0_15px_rgba(0,240,255,0.3)]">
          <Zap className="w-6 h-6 text-cyan-400 animate-pulse" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-wider text-white flex items-center gap-2">
            MCP CITADEL <span className="text-xs px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/40">v2.0</span>
          </h1>
          <p className="text-xs text-slate-400 flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${sseConnected ? 'bg-emerald-400 animate-ping' : 'bg-rose-500'}`} />
            {sseConnected ? 'NEURAL STREAM ACTIVE' : 'STREAM RECONNECTING'}
          </p>
        </div>
      </div>

      {/* Gamified Level & EXP Gauge */}
      <div className="hidden md:flex items-center gap-6 bg-slate-900/60 px-5 py-2 rounded-lg border border-slate-800">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Flame className="w-5 h-5 animate-bounce" />
          </div>
          <div>
            <div className="text-xs text-slate-400 font-mono">COMMANDER LEVEL</div>
            <div className="text-base font-black text-amber-400 font-mono tracking-wider">
              LVL {userLevel} <span className="text-xs font-normal text-slate-400">({userExp} / {nextLevelExp} XP)</span>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="w-36">
          <div className="xp-bar-outer">
            <div className="xp-bar-inner" style={{ width: `${expProgress}%` }} />
          </div>
          <div className="text-[10px] text-cyan-400 font-mono text-right mt-0.5">{expProgress}% NEXT RANK</div>
        </div>

        {/* Fuel / API Rate Gauge */}
        <div className="flex items-center gap-2 pl-4 border-l border-slate-800">
          <Cpu className="w-4 h-4 text-cyan-400" />
          <span className="text-xs text-slate-300 font-mono">MANA: <strong className="text-emerald-400">100%</strong></span>
        </div>
      </div>

      {/* User Profile & Actions */}
      <div className="flex items-center gap-4">
        <div className="text-right hidden sm:block">
          <div className="text-sm font-bold text-white flex items-center gap-1 justify-end">
            <Shield className="w-3.5 h-3.5 text-amber-400" />
            {user?.sub || user?.username || 'Commander'}
          </div>
          <div className="text-xs text-cyan-400 font-mono uppercase tracking-wider">
            {user?.roles?.[0] || 'GUILD MASTER'}
          </div>
        </div>

        <button
          onClick={onLogout}
          className="btn-neon-magenta text-xs py-1.5 px-3 flex items-center gap-1.5"
          title="Sign out of Citadel"
        >
          <LogOut className="w-4 h-4" />
          <span className="hidden sm:inline">EXIT</span>
        </button>
      </div>
    </header>
  );
};
