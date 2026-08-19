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
    <aside className="hud-panel" style={{
      width: collapsed ? '4.5rem' : '16rem',
      height: 'calc(100vh - 65px)',
      position: 'sticky',
      top: '65px',
      padding: collapsed ? '0.75rem 0.5rem' : '1rem',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      borderRadius: 0,
      borderTop: 0,
      borderLeft: 0,
      borderBottom: 0,
      transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), padding 0.3s ease',
      zIndex: 40
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: collapsed ? '0.25rem 0' : '0.25rem 0.5rem'
        }}>
          {!collapsed && (
            <span className="font-mono" style={{
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.1em',
              color: '#64748b',
              textTransform: 'uppercase'
            }}>
              COMMAND MODULES
            </span>
          )}
          <button
            onClick={toggle}
            style={{
              background: 'rgba(0,240,255,0.08)',
              border: '1px solid rgba(0,240,255,0.25)',
              color: '#22d3ee',
              borderRadius: '0.375rem',
              padding: '0.35rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s ease'
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
                onClick={() => setActiveTab(item.id)}
                title={collapsed ? `${item.label}${item.count ? ` (${item.count})` : ''}` : undefined}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: collapsed ? 'center' : 'space-between',
                  padding: collapsed ? '0.75rem 0' : '0.625rem 0.875rem',
                  borderRadius: '0.5rem',
                  fontSize: '0.875rem',
                  fontWeight: isActive ? 700 : 600,
                  letterSpacing: '0.025em',
                  transition: 'all 0.2s ease',
                  backgroundColor: isActive ? 'rgba(6,182,212,0.15)' : 'transparent',
                  color: isActive ? '#22d3ee' : '#94a3b8',
                  border: isActive ? '1px solid rgba(6,182,212,0.4)' : '1px solid transparent',
                  boxShadow: isActive ? '0 0 12px rgba(0,240,255,0.2)' : 'none',
                  cursor: 'pointer',
                  position: 'relative'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <Icon style={{ width: '1.125rem', height: '1.125rem', color: isActive ? '#22d3ee' : '#64748b' }} />
                  {!collapsed && <span>{item.label}</span>}
                </div>

                {!collapsed && item.badge && (
                  <span className="font-mono" style={{
                    fontSize: '10px',
                    padding: '0.125rem 0.375rem',
                    borderRadius: '0.25rem',
                    backgroundColor: 'rgba(16,185,129,0.2)',
                    color: '#34d399',
                    border: '1px solid rgba(16,185,129,0.3)'
                  }}>
                    {item.badge}
                  </span>
                )}

                {item.count !== undefined && item.count > 0 && (
                  <span className="font-mono animate-pulse" style={{
                    fontSize: '0.75rem',
                    fontWeight: 900,
                    padding: collapsed ? '0.125rem 0.375rem' : '0.125rem 0.5rem',
                    borderRadius: '9999px',
                    backgroundColor: '#f43f5e',
                    color: 'white',
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
        paddingTop: '1rem',
        borderTop: '1px solid #1e293b',
        textAlign: 'center'
      }}>
        {!collapsed ? (
          <>
            <div className="font-mono" style={{ fontSize: '11px', color: '#64748b' }}>
              MCP CITADEL OS v2.0
            </div>
            <div className="font-mono" style={{
              fontSize: '10px',
              color: 'rgba(6,182,212,0.7)',
              marginTop: '0.125rem'
            }}>
              ALL SYSTEMS OPERATIONAL
            </div>
          </>
        ) : (
          <div className="font-mono" style={{ fontSize: '10px', color: '#22d3ee' }}>v2.0</div>
        )}
      </div>
    </aside>
  );
};

