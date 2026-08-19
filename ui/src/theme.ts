// src/theme.ts
// Centralized design tokens for the MCP UI (no Tailwind).
// Exported objects can be imported by components to compose inline style objects.

export const colors = {
  primary: '#00ffff', // cyan neon
  secondary: '#ff00ff', // magenta neon
  accent: '#ff6b00', // orange accent
  background: 'rgba(2, 6, 23, 0.85)', // dark glass background
  panel: 'rgba(10, 10, 20, 0.7)', // slightly lighter panel
  textLight: '#e5e7eb', // light gray for text
  textDark: '#94a3b8', // muted gray
  success: '#22c55e', // green
  warning: '#f59e0b', // amber
  error: '#ef4444', // red
};

export const fonts = {
  title: 'Orbitron, sans-serif',
  body: 'Inter, sans-serif',
  mono: 'var(--font-mono)',
};

export const spacing = {
  xs: '0.25rem',
  sm: '0.5rem',
  md: '0.75rem',
  lg: '1rem',
  xl: '1.5rem',
  xxl: '2rem',
};

export const shadows = {
  glow: '0 0 8px rgba(0,255,255,0.7)',
  panel: '0 4px 12px rgba(0,0,0,0.5)',
};

export const flexCenter = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
} as const;

export const cardPanel = {
  background: 'var(--color-panel)',
  borderRadius: '0.5rem',
  padding: spacing.lg,
  boxShadow: shadows.panel,
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.1)',
} as const;

export const neonButtonBase = {
  cursor: 'pointer',
  border: 'none',
  borderRadius: '0.375rem',
  fontWeight: 600,
  fontFamily: fonts.body,
  transition: 'transform 0.1s ease, box-shadow 0.2s ease',
  boxShadow: shadows.glow,
} as const;

export const neonButtonVariants = {
  cyan: {
    background: 'rgba(0,255,255,0.15)',
    color: colors.primary,
    '&:hover': {
      background: 'rgba(0,255,255,0.3)',
      transform: 'scale(1.03)',
    },
    '&:active': {
      background: 'rgba(0,255,255,0.4)',
      transform: 'scale(0.97)',
    },
  },
  magenta: {
    background: 'rgba(255,0,255,0.15)',
    color: colors.secondary,
    '&:hover': {
      background: 'rgba(255,0,255,0.3)',
      transform: 'scale(1.03)',
    },
    '&:active': {
      background: 'rgba(255,0,255,0.4)',
      transform: 'scale(0.97)',
    },
  },
} as const;

export const mergeStyles = (...styles: any[]) =>
  Object.assign({}, ...styles);
