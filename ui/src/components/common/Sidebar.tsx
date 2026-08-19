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
  Sliders,
  Layers
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
    { id: 'dashboard', label: 'Station Overview', icon: Activity, badge: 'STATION' },
    { id: 'spellbook', label: 'Module Fitting Bay (Tools)', icon: Sliders },
    { id: 'firehose', label: 'Telemetry Stream', icon: Radio },
    { id: 'foundry', label: 'Industry Assembly (AI)', icon: Hammer },
    { id: 'queue', label: 'Corporate Approvals', icon: Clock, count: pendingCount },
    { id: 'openapi', label: 'OpenAPI Blueprint Vault', icon: ScrollText },
    { id: 'federation', label: 'Warp Relay Gateways', icon: Globe2 },
    { id: 'tenancy', label: 'Corporation & Alliance (RBAC)', icon: Users2 },
    { id: 'chaos', label: 'Combat Stress Simulation', icon: Swords },
    { id: 'prompts', label: 'Archon Prompt Directives', icon: ShieldCheck },
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
      backgroundColor: '#090e18',
      borderRight: '1px solid rgba(42, 62, 102, 0.8)',
      transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), padding 0.3s ease',
      zIndex: 40,
      boxShadow: '4px 0 20px rgba(0,0,0,0.5)'
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
              letterSpacing: '0.08em',
              color: '#94a3b8',
              textTransform: 'uppercase'
            }}>
              STATION SERVICES
            </span>
          )}
          <button
            onClick={() => {
              sfx.playTapSound();
              toggle();
            }}
            style={{
              background: '#0c121e',
              border: '1px solid rgba(42, 62, 102, 0.8)',
              color: '#38bdf8',
              borderRadius: '0.375rem',
              padding: '0.35rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
            title={collapsed ? 'Expand Station Menu' : 'Collapse Station Menu'}
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
                  fontSize: '0.85rem',
                  fontFamily: 'var(--font-title)',
                  fontWeight: isActive ? 700 : 500,
                  letterSpacing: '0.03em',
                  transition: 'all 0.12s ease',
                  backgroundColor: isActive ? 'rgba(56, 189, 248, 0.12)' : 'transparent',
                  color: isActive ? '#38bdf8' : '#94a3b8',
                  border: isActive ? '1px solid #38bdf8' : '1px solid transparent',
                  boxShadow: isActive ? '0 0 15px rgba(56, 189, 248, 0.2)' : 'none',
                  cursor: 'pointer',
                  position: 'relative'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <Icon style={{ width: '1.1rem', height: '1.1rem', color: isActive ? '#38bdf8' : '#64748b' }} />
                  {!collapsed && <span>{item.label}</span>}
                </div>

                {!collapsed && item.badge && (
                  <span className="font-mono" style={{
                    fontSize: '9px',
                    padding: '0.125rem 0.375rem',
                    borderRadius: '0.25rem',
                    backgroundColor: 'rgba(229, 169, 59, 0.15)',
                    color: '#e5a93b',
                    border: '1px solid rgba(229, 169, 59, 0.4)'
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
        borderTop: '1px solid rgba(42, 62, 102, 0.8)',
        textAlign: 'center'
      }}>
        {!collapsed ? (
          <div style={{
            background: '#0c121e',
            padding: '0.5rem',
            borderRadius: '0.375rem',
            border: '1px solid rgba(42, 62, 102, 0.8)'
          }}>
            <div className="font-title" style={{ fontSize: '0.75rem', color: '#e5a93b' }}>
              🛡️ DOCKING PERMIT ACTIVE
            </div>
            <div className="font-mono" style={{
              fontSize: '0.65rem',
              color: '#64748b',
              marginTop: '0.15rem'
            }}>
              ASTRAHUS CITADEL CLUSTER
            </div>
          </div>
        ) : (
          <div className="font-title" style={{ fontSize: '10px', color: '#e5a93b' }}>EVE</div>
        )}
      </div>
    </aside>
  );
};
