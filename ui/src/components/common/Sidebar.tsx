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
  ChevronRight,
  Terminal,
  Cpu
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
  isCollapsed,
  onToggleCollapse
}) => {
  const [collapsedInternal, setCollapsedInternal] = useState(false);
  const collapsed = isCollapsed !== undefined ? isCollapsed : collapsedInternal;
  const toggle = onToggleCollapse ?? (() => setCollapsedInternal(prev => !prev));

  const navItems = [
    { id: 'dashboard', label: 'Tactical HUD', icon: Activity, badge: 'ACTIVE' },
    { id: 'spellbook', label: 'Deployable Modules (Tools)', icon: Wand2 },
    { id: 'firehose', label: 'Neural Telemetry Feed', icon: Radio },
    { id: 'foundry', label: 'Module Foundry (AI)', icon: Hammer },
    { id: 'queue', label: 'Security Review Queue', icon: Clock, count: pendingCount },
    { id: 'openapi', label: 'OpenAPI Spec Vault', icon: ScrollText },
    { id: 'federation', label: 'Relay Gateways', icon: Globe2 },
    { id: 'tenancy', label: 'Fleet & Citadel (RBAC)', icon: Users2 },
    { id: 'chaos', label: 'Stress Simulation Arena', icon: Swords },
    { id: 'prompts', label: 'Protocol Prompts', icon: ShieldCheck },
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
      backgroundColor: '#0a0f1a',
      borderRight: '1px solid #1e2c45',
      transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), padding 0.3s ease',
      zIndex: 40,
      boxShadow: '4px 0 20px rgba(0,0,0,0.6)'
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
              fontSize: '0.7rem',
              letterSpacing: '0.1em',
              color: '#64748b',
              textTransform: 'uppercase'
            }}>
              TACTICAL MODULES
            </span>
          )}
          <button
            onClick={() => {
              sfx.playTapSound();
              toggle();
            }}
            style={{
              background: '#0d131f',
              border: '1px solid #1e2c45',
              color: '#00f0ff',
              borderRadius: '0.375rem',
              padding: '0.35rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
            title={collapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          >
            {collapsed ? <ChevronRight style={{ width: '1rem', height: '1rem' }} /> : <ChevronLeft style={{ width: '1rem', height: '1rem' }} />}
          </button>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          {navItems.map(item => {
            const Icon = item.icon;
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
                  borderRadius: '0.375rem',
                  fontSize: '0.8rem',
                  fontFamily: 'var(--font-title)',
                  fontWeight: isActive ? 700 : 500,
                  letterSpacing: '0.03em',
                  transition: 'all 0.12s ease',
                  backgroundColor: isActive ? 'rgba(0, 240, 255, 0.12)' : 'transparent',
                  color: isActive ? '#00f0ff' : '#94a3b8',
                  border: isActive ? '1px solid #00f0ff' : '1px solid transparent',
                  boxShadow: isActive ? '0 0 15px rgba(0, 240, 255, 0.25), inset 0 0 10px rgba(0, 240, 255, 0.1)' : 'none',
                  cursor: 'pointer',
                  position: 'relative'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <Icon style={{ width: '1.1rem', height: '1.1rem', color: isActive ? '#00f0ff' : '#64748b' }} />
                  {!collapsed && <span>{item.label}</span>}
                </div>

                {!collapsed && item.badge && (
                  <span className="font-mono" style={{
                    fontSize: '9px',
                    padding: '0.125rem 0.375rem',
                    borderRadius: '0.25rem',
                    backgroundColor: 'rgba(16, 185, 129, 0.15)',
                    color: '#34d399',
                    border: '1px solid rgba(16, 185, 129, 0.4)'
                  }}>
                    {item.badge}
                  </span>
                )}

                {item.count !== undefined && item.count > 0 && (
                  <span className="font-mono" style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    padding: collapsed ? '0.125rem 0.375rem' : '0.125rem 0.5rem',
                    borderRadius: '0.25rem',
                    backgroundColor: '#f43f5e',
                    color: 'white',
                    boxShadow: '0 0 8px #f43f5e',
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

      <div style={{
        paddingTop: '0.75rem',
        borderTop: '1px solid #1e2c45',
        textAlign: 'center'
      }}>
        {!collapsed ? (
          <div style={{
            background: '#0d131f',
            padding: '0.5rem',
            borderRadius: '0.375rem',
            border: '1px solid #1e2c45'
          }}>
            <div className="font-title" style={{ fontSize: '0.75rem', color: '#00f0ff' }}>
              ⚡ ORBITAL CORE ACTIVE
            </div>
            <div className="font-mono" style={{
              fontSize: '0.65rem',
              color: '#64748b',
              marginTop: '0.15rem'
            }}>
              MCP PROTOCOL READY
            </div>
          </div>
        ) : (
          <div className="font-title" style={{ fontSize: '10px', color: '#00f0ff' }}>CORE</div>
        )}
      </div>
    </aside>
  );
};
