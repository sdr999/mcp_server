// src/theme.ts
// Centralized Clash Royale design tokens & helpers

export const crColors = {
  arenaBg: '#070e1e',
  cardBg: '#13223f',
  cardInner: '#0c172c',
  borderStone: '#2a3e66',

  // Buttons & Accents
  gold: '#f59e0b',
  goldLight: '#fde047',
  goldDark: '#b45309',

  blue: '#0284c7',
  blueLight: '#38bdf8',
  blueDark: '#0369a1',

  elixir: '#db2777',
  elixirLight: '#f472b6',
  elixirDark: '#be185d',

  green: '#22c55e',
  greenLight: '#4ade80',
  greenDark: '#15803d',

  red: '#ef4444',
  redLight: '#f87171',
  redDark: '#dc2626',

  // Rarities
  common: '#94a3b8',
  rare: '#f59e0b',
  epic: '#c084fc',
  legendary: '#38bdf8',

  textMain: '#f8fafc',
  textMuted: '#94a3b8',
};

export const fonts = {
  title: "'Lilita One', 'Orbitron', cursive, sans-serif",
  game: "'Fredoka', 'Rajdhani', sans-serif",
  mono: "'JetBrains Mono', monospace",
};

export const crButtonBase = {
  fontFamily: fonts.title,
  textTransform: 'uppercase' as const,
  borderRadius: '0.625rem',
  cursor: 'pointer',
  userSelect: 'none' as const,
  transition: 'transform 0.08s ease, box-shadow 0.08s ease',
};
