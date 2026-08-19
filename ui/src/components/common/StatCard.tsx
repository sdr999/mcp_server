import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon: LucideIcon;
  color?: 'cyan' | 'magenta' | 'gold' | 'green';
  trend?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtext,
  icon: Icon,
  color = 'cyan',
  trend
}) => {
  const colorMap = {
    cyan: {
      color: '#22d3ee',
      backgroundColor: 'rgba(6, 182, 212, 0.1)',
      borderColor: 'rgba(6, 182, 212, 0.3)',
      boxShadow: '0 0 15px rgba(0,240,255,0.15)',
    },
    magenta: {
      color: '#fb7185',
      backgroundColor: 'rgba(251, 113, 133, 0.1)',
      borderColor: 'rgba(251, 113, 133, 0.3)',
      boxShadow: '0 0 15px rgba(255,0,85,0.15)',
    },
    gold: {
      color: '#fbbf24',
      backgroundColor: 'rgba(245, 158, 11, 0.1)',
      borderColor: 'rgba(245, 158, 11, 0.3)',
      boxShadow: '0 0 15px rgba(255,215,0,0.15)',
    },
    green: {
      color: '#34d399',
      backgroundColor: 'rgba(16, 185, 129, 0.1)',
      borderColor: 'rgba(16, 185, 129, 0.3)',
      boxShadow: '0 0 15px rgba(0,255,102,0.15)',
    },
  };

  const theme = colorMap[color];

  return (
    <div className="hud-panel" style={{ padding: '1.25rem', boxShadow: theme.boxShadow }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ 
          fontSize: '0.75rem', 
          fontWeight: 700, 
          letterSpacing: '0.1em', 
          color: '#94a3b8', 
          textTransform: 'uppercase',
          fontFamily: 'var(--font-mono)'
        }}>
          {title}
        </span>
        <div style={{ 
          padding: '0.5rem', 
          borderRadius: '0.5rem', 
          backgroundColor: theme.backgroundColor, 
          border: `1px solid ${theme.borderColor}`,
          color: theme.color,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <Icon style={{ width: '1.25rem', height: '1.25rem' }} />
        </div>
      </div>

      <div style={{ marginTop: '0.75rem' }}>
        <div style={{ 
          fontSize: '1.5rem', 
          fontWeight: 900, 
          letterSpacing: '-0.025em', 
          color: theme.color,
          fontFamily: 'var(--font-mono)'
        }}>
          {value}
        </div>
        {subtext && (
          <p style={{ 
            fontSize: '0.75rem', 
            color: '#94a3b8', 
            marginTop: '0.25rem', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'space-between',
            fontFamily: 'var(--font-mono)'
          }}>
            <span>{subtext}</span>
            {trend && <span style={{ color: '#34d399', fontWeight: 700 }}>{trend}</span>}
          </p>
        )}
      </div>
    </div>
  );
};
