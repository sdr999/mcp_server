import React, { useState } from 'react';
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
  Radio,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { sfx } from '../../services/soundEffects';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  pendingCount?: number;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ 
  activeTab, 
  setActiveTab, 
  pendingCount = 0,
  isCollapsed = false,
  onToggleCollapse
}) => {
  const [collapsedInternal, setCollapsedInternal] = useState(false);
  const collapsed = isCollapsed ?? collapsedInternal;
  const toggle = onToggleCollapse ?? (() => setCollapsedInternal(!collapsedInternal));

  const navItems = [
    { id: 'dashboard', label: 'Arena HUD', icon: Activity, badge: 'LIVE', emoji: '⚔️' },
    { id: 'spellbook', label: 'Battle Deck (Tools)', icon: Wand2, emoji: '🃏' },
    { id: 'firehose', label: 'Neural Stream', icon: Radio, emoji: '⚡' },
    { id: 'foundry', label: 'Tool Forge (AI)', icon: Hammer, emoji: '🔨' },
    { id: 'queue', label: 'Council Approvals', icon: Clock, count: pendingCount, emoji: '👑' },
    { id: 'openapi', label: 'OpenAPI Vault', icon: ScrollText, emoji: '📜' },
    { id: 'federation', label: 'Realm Gateways', icon: Globe2, emoji: '🌐' },
    { id: 'tenancy', label: 'Clan Citadel (RBAC)', icon: Users2, emoji: '🏰' },
    { id: 'chaos', label: 'Chaos Arena', icon: Swords, emoji: '💥' },
    { id: 'prompts', label: 'Archmage Prompts', icon: ShieldCheck, emoji: '✨' },
  ];

  const handleTabSelect = (id: string) => {
    sfx.playTapSound();
    setActiveTab(id);
  };

  return (
    <aside style={{
      width: collapsed ? '4.5rem' : '16.5rem',
      height: 'calc(100vh - 65px)',
      position: 'sticky',
      top: '65px',
      padding: collapsed ? '0.75rem 0.5rem' : '1rem',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      backgroundColor: '#0c172c',
      borderRight: '3px solid #2a3e66',
      transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), padding 0.3s ease',
      zIndex: 40,
      boxShadow: '4px 0 15px rgba(0,0,0,0.5)'
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: collapsed ? '0.25rem 0' : '0.25rem 0.5rem'
        }}>
          {!collapsed && (
            <span className="font-title" style={{
              fontSize: '0.75rem',
              letterSpacing: '0.05em',
              color: '#94a3b8',
              textTransform: 'uppercase'
            }}>
              ARENA COMMANDS
            </span>
          )}
          <button
            onClick={() => {
              sfx.playTapSound();
              toggle();
            }}
            style={{
              background: '#13223f',
              border: '2px solid #38bdf8',
              color: '#38bdf8',
              borderRadius: '0.5rem',
              padding: '0.35rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 0 #0369a1'
            }}
            title={collapsed ? 'Expand Arena Menu' : 'Collapse Arena Menu'}
          >
            {collapsed ? <ChevronRight style={{ width: '1rem', height: '1rem' }} /> : <ChevronLeft style={{ width: '1rem', height: '1rem' }} />}
          </button>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          {navItems.map(item => {
            const isActive = activeTab === item.id;

            return (
              <button
                key={item.id}
                onClick={() => handleTabSelect(item.id)}
                title={collapsed ? `${item.label}${item.count ? ` (${item.count})` : ''}` : undefined}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: collapsed ? 'center' : 'space-between',
                  padding: collapsed ? '0.75rem 0' : '0.625rem 0.875rem',
                  borderRadius: '0.625rem',
                  fontSize: '0.85rem',
                  fontFamily: 'var(--font-game)',
                  fontWeight: isActive ? 700 : 500,
                  transition: 'all 0.12s ease',
                  backgroundColor: isActive ? 'linear-gradient(180deg, #0284c7, #0369a1)' : '#13223f',
                  background: isActive ? 'linear-gradient(180deg, #38bdf8 0%, #0284c7 100%)' : '#13223f',
                  color: isActive ? '#ffffff' : '#cbd5e1',
                  border: isActive ? '2px solid #bae6fd' : '2px solid #2a3e66',
                  boxShadow: isActive ? '0 4px 0 #0c4a6e, 0 6px 12px rgba(2, 132, 199, 0.4)' : '0 2px 0 #0a1128',
                  transform: isActive ? 'translateY(-1px)' : 'none',
                  cursor: 'pointer',
                  position: 'relative'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontSize: '1.15rem' }}>{item.emoji}</span>
                  {!collapsed && <span className="font-game" style={{ fontSize: '0.875rem' }}>{item.label}</span>}
                </div>

                {!collapsed && item.badge && (
                  <span className="font-title" style={{
                    fontSize: '9px',
                    padding: '0.15rem 0.4rem',
                    borderRadius: '0.25rem',
                    backgroundColor: '#16a34a',
                    color: '#ffffff',
                    border: '1px solid #4ade80'
                  }}>
                    {item.badge}
                  </span>
                )}

                {item.count !== undefined && item.count > 0 && (
                  <span className="font-title" style={{
                    fontSize: '0.75rem',
                    padding: collapsed ? '0.15rem 0.35rem' : '0.15rem 0.5rem',
                    borderRadius: '9999px',
                    backgroundColor: '#ef4444',
                    color: 'white',
                    border: '1px solid #fca5a5',
                    boxShadow: '0 2px 4px rgba(239, 68, 68, 0.6)',
                    position: collapsed ? 'absolute' : 'static',
                    top: collapsed ? '2px' : 'auto',
                    right: collapsed ? '2px' : 'auto'
                  }}>
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Arena Trophy Rating Footer */}
      <div style={{
        paddingTop: '0.75rem',
        borderTop: '2px solid #2a3e66',
        textAlign: 'center'
      }}>
        {!collapsed ? (
          <div style={{
            background: '#13223f',
            padding: '0.5rem',
            borderRadius: '0.5rem',
            border: '1px solid #2a3e66'
          }}>
            <div className="font-title" style={{ fontSize: '0.75rem', color: '#fde047' }}>
              👑 ROYAL PASS ACTIVE
            </div>
            <div className="font-game" style={{
              fontSize: '0.65rem',
              color: '#38bdf8',
              marginTop: '0.15rem'
            }}>
              SEASON 15 • CITADEL LEAGUE
            </div>
          </div>
        ) : (
          <div className="font-title" style={{ fontSize: '10px', color: '#fde047' }}>👑</div>
        )}
      </div>
    </aside>
  );
};
