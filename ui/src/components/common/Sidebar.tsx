import React from 'react';
import { 
  Activity, 
  Wand2, 
  Hammer, 
  Clock, 
  Globe2, 
  ShieldCheck, 
  Users2, 
  Swords, 
  ScrollText,
  Radio
} from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  pendingCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, pendingCount = 0 }) => {
  const navItems = [
    { id: 'dashboard', label: 'Reactor HUD', icon: Activity, badge: 'LIVE' },
    { id: 'firehose', label: 'Neural Stream', icon: Radio },
    { id: 'spellbook', label: 'Spellbook (Tools)', icon: Wand2 },
    { id: 'foundry', label: 'Tool Foundry (AI)', icon: Hammer },
    { id: 'queue', label: 'Grand Council Review', icon: Clock, count: pendingCount },
    { id: 'openapi', label: 'OpenAPI Vault', icon: ScrollText },
    { id: 'federation', label: 'Realm Gateways', icon: Globe2 },
    { id: 'tenancy', label: 'Guild & Citadel (RBAC)', icon: Users2 },
    { id: 'chaos', label: 'Battle & Chaos Arena', icon: Swords },
    { id: 'prompts', label: 'Archmage Prompts', icon: ShieldCheck },
  ];

  return (
    <aside className="w-64 hud-panel h-[calc(100vh-65px)] sticky top-[65px] p-4 flex flex-col justify-between rounded-none border-t-0 border-l-0 border-b-0">
      <div className="space-y-1">
        <div className="px-3 py-2 text-[11px] font-mono font-bold tracking-widest text-slate-500 uppercase">
          COMMAND MODULES
        </div>
        <nav className="space-y-1">
          {navItems.map(item => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;

            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-semibold tracking-wide transition-all ${
                  isActive
                    ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/40 shadow-[0_0_12px_rgba(0,240,255,0.2)] font-bold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-cyan-400' : 'text-slate-500'}`} />
                  <span>{item.label}</span>
                </div>

                {item.badge && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    {item.badge}
                  </span>
                )}

                {item.count !== undefined && item.count > 0 && (
                  <span className="text-xs font-mono font-black px-2 py-0.5 rounded-full bg-rose-500 text-white animate-pulse">
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="pt-4 border-t border-slate-800 text-center">
        <div className="text-[11px] text-slate-500 font-mono">
          MCP CITADEL OS v2.0
        </div>
        <div className="text-[10px] text-cyan-500/70 font-mono mt-0.5">
          ALL SYSTEMS OPERATIONAL
        </div>
      </div>
    </aside>
  );
};
