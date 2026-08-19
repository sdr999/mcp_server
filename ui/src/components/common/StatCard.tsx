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
      text: 'text-cyan-400',
      bg: 'bg-cyan-500/10',
      border: 'border-cyan-500/30',
      glow: 'shadow-[0_0_15px_rgba(0,240,255,0.15)]',
    },
    magenta: {
      text: 'text-rose-400',
      bg: 'bg-rose-500/10',
      border: 'border-rose-500/30',
      glow: 'shadow-[0_0_15px_rgba(255,0,85,0.15)]',
    },
    gold: {
      text: 'text-amber-400',
      bg: 'bg-amber-500/10',
      border: 'border-amber-500/30',
      glow: 'shadow-[0_0_15px_rgba(255,215,0,0.15)]',
    },
    green: {
      text: 'text-emerald-400',
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/30',
      glow: 'shadow-[0_0_15px_rgba(0,255,102,0.15)]',
    },
  };

  const theme = colorMap[color];

  return (
    <div className={`hud-panel p-5 ${theme.glow}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono font-bold tracking-widest text-slate-400 uppercase">
          {title}
        </span>
        <div className={`p-2 rounded-lg ${theme.bg} ${theme.border} border ${theme.text}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>

      <div className="mt-3">
        <div className={`text-2xl font-black font-mono tracking-tight ${theme.text}`}>
          {value}
        </div>
        {subtext && (
          <p className="text-xs text-slate-400 mt-1 flex items-center justify-between font-mono">
            <span>{subtext}</span>
            {trend && <span className="text-emerald-400 font-bold">{trend}</span>}
          </p>
        )}
      </div>
    </div>
  );
};
