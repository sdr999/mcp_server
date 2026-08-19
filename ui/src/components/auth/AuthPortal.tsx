import React, { useState } from 'react';
import { Shield, Key, User, Lock, Mail, Zap, AlertCircle } from 'lucide-react';
import { api } from '../../services/api';

interface AuthPortalProps {
  onLoginSuccess: (token: string, user: any) => void;
}

export const AuthPortal: React.FC<AuthPortalProps> = ({ onLoginSuccess }) => {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (mode === 'signin') {
        const res = await api.signin({ username, password });
        const { access_token, refresh_token, user } = res.data;
        localStorage.setItem('mcp_token', access_token);
        if (refresh_token) localStorage.setItem('mcp_refresh_token', refresh_token);
        onLoginSuccess(access_token, user || { username });
      } else {
        await api.signup({ username, email, password });
        // Automatically sign in after signup
        const res = await api.signin({ username, password });
        const { access_token, refresh_token, user } = res.data;
        localStorage.setItem('mcp_token', access_token);
        if (refresh_token) localStorage.setItem('mcp_refresh_token', refresh_token);
        onLoginSuccess(access_token, user || { username });
      }
    } catch (err: any) {
      console.error('Auth error', err);
      setError(err.response?.data?.detail || err.response?.data?.message || 'Authentication failed. Check credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#07090e] flex items-center justify-center p-4 relative overflow-hidden bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-950/30 via-slate-950 to-black">
      {/* Background Neon Grid Accent */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00f0ff08_1px,transparent_1px),linear-gradient(to_bottom,#00f0ff08_1px,transparent_1px)] bg-[size:4rem_4rem] pointer-events-none" />

      <div className="w-full max-w-md hud-panel p-8 relative z-10 shadow-[0_0_50px_rgba(0,240,255,0.15)] border-cyan-500/40">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-cyan-950/60 border border-cyan-500/50 mb-4 shadow-[0_0_20px_rgba(0,240,255,0.4)]">
            <Zap className="w-8 h-8 text-cyan-400 animate-pulse" />
          </div>
          <h2 className="text-2xl font-black text-white tracking-widest uppercase">
            CITADEL ACCESS PORTAL
          </h2>
          <p className="text-xs text-cyan-400 font-mono mt-1">
            SECURITY LEVEL 5 - BIOMETRIC AUTHENTICATION REQUIRED
          </p>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded bg-rose-500/10 border border-rose-500/40 text-rose-400 text-xs font-mono flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              COMMANDER USERNAME
            </label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="text"
                required
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Enter username..."
                className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>
          </div>

          {mode === 'signup' && (
            <div>
              <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
                GUILD EMAIL ADDRESS
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="Enter email..."
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400 font-mono"
                />
              </div>
            </div>
          )}

          <div>
            <label className="text-xs font-mono font-bold text-slate-300 block mb-1">
              SECURITY KEY (PASSWORD)
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full btn-neon-cyan justify-center py-3 text-sm tracking-widest mt-2"
          >
            {loading ? 'AUTHENTICATING...' : mode === 'signin' ? 'ENTER CITADEL ⚡' : 'CREATE GUILD PROFILE 🛡️'}
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-slate-800 text-center">
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signin' ? 'signup' : 'signin');
              setError(null);
            }}
            className="text-xs font-mono text-cyan-400 hover:underline"
          >
            {mode === 'signin'
              ? "Don't have a Citadel clearance? Register new profile"
              : 'Already have clearances? Sign in here'}
          </button>
        </div>
      </div>
    </div>
  );
};
