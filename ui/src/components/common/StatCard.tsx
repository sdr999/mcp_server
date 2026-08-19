import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon: LucideIcon;
  color?: 'cyan' | 'magenta' | 'gold' | 'green' | 'blue';
  trend?: string;
  onClick?: () => void;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtext,
  icon: Icon,
  color = 'blue',
  trend,
  onClick
}) => {
  const colorMap = {
    cyan: {
      color: '#38bdf8',
      background: 'linear-gradient(180deg, rgba(56, 189, 248, 0.15), rgba(3, 105, 161, 0.2))',
      border: '2px solid #0284c7',
      iconBg: 'linear-gradient(180deg, #38bdf8, #0284c7)',
    },
    blue: {
      color: '#38bdf8',
      background: 'linear-gradient(180deg, rgba(56, 189, 248, 0.15), rgba(3, 105, 161, 0.2))',
      border: '2px solid #0284c7',
      iconBg: 'linear-gradient(180deg, #38bdf8, #0284c7)',
    },
    magenta: {
      color: '#f472b6',
      background: 'linear-gradient(180deg, rgba(244, 114, 182, 0.15), rgba(190, 24, 93, 0.2))',
      border: '2px solid #db2777',
      iconBg: 'linear-gradient(180deg, #f472b6, #db2777)',
    },
    gold: {
      color: '#fde047',
      background: 'linear-gradient(180deg, rgba(253, 224, 71, 0.15), rgba(202, 138, 4, 0.2))',
      border: '2px solid #ca8a04',
      iconBg: 'linear-gradient(180deg, #fde047, #ca8a04)',
    },
    green: {
      color: '#4ade80',
      background: 'linear-gradient(180deg, rgba(74, 222, 128, 0.15), rgba(22, 163, 74, 0.2))',
      border: '2px solid #16a34a',
      iconBg: 'linear-gradient(180deg, #4ade80, #16a34a)',
    },
  };

  const theme = colorMap[color] || colorMap.blue;

  return (
    <div 
      onClick={onClick}
      className="hud-panel" 
      style={{
        padding: '1.25rem',
        background: '#13223f',
        border: '2px solid #2a3e66',
        boxShadow: '0 6px 16px rgba(0, 0, 0, 0.5)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'transform 0.15s ease, border-color 0.15s ease'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="font-title" style={{ 
          fontSize: '0.8rem', 
          color: '#94a3b8', 
          textTransform: 'uppercase'
        }}>
          {title}
        </span>
        <div style={{ 
          padding: '0.45rem', 
          borderRadius: '0.5rem', 
          background: theme.iconBg, 
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 2px 6px rgba(0, 0, 0, 0.4)'
        }}>
          <Icon style={{ width: '1.25rem', height: '1.25rem' }} />
        </div>
      </div>

      <div style={{ marginTop: '0.65rem' }}>
        <div className="font-title" style={{ 
          fontSize: '1.75rem', 
          color: theme.color,
          letterSpacing: '0.02em'
        }}>
          {value}
        </div>
        {subtext && (
          <p className="font-game" style={{ 
            fontSize: '0.75rem', 
            color: '#94a3b8', 
            marginTop: '0.25rem', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'space-between',
            margin: 0
          }}>
            <span>{subtext}</span>
            {trend && <span className="font-title" style={{ color: '#4ade80', fontSize: '0.75rem' }}>{trend}</span>}
          </p>
        )}
      </div>
    </div>
  );
};
