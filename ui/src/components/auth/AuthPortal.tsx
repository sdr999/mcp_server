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
    <div style={{
      minHeight: '100vh',
      backgroundColor: 'var(--bg-obsidian)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '1rem',
      position: 'relative',
      overflow: 'hidden',
      background: 'radial-gradient(ellipse at top, rgba(8,51,68,0.3), rgba(2,6,23,1), black)'
    }}>
      {/* Background Neon Grid Accent */}
      <div style={{
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(to right, rgba(0,240,255,0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,240,255,0.05) 1px, transparent 1px)',
        backgroundSize: '4rem 4rem',
        pointerEvents: 'none'
      }} />

      <div className="hud-panel" style={{
        width: '100%',
        maxWidth: '28rem',
        padding: '2rem',
        position: 'relative',
        zIndex: 10,
        boxShadow: '0 0 50px rgba(0,240,255,0.15)',
        borderColor: 'rgba(6,182,212,0.4)'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '4rem',
            height: '4rem',
            borderRadius: '1rem',
            backgroundColor: 'rgba(8,51,68,0.6)',
            border: '1px solid rgba(6,182,212,0.5)',
            marginBottom: '1rem',
            boxShadow: '0 0 20px rgba(0,240,255,0.4)'
          }}>
            <Zap className="animate-pulse" style={{ width: '2rem', height: '2rem', color: '#22d3ee' }} />
          </div>
          <h2 className="font-title" style={{
            fontSize: '1.5rem',
            fontWeight: 900,
            color: 'white',
            letterSpacing: '0.1em',
            textTransform: 'uppercase'
          }}>
            CITADEL ACCESS PORTAL
          </h2>
          <p className="font-mono" style={{
            fontSize: '0.75rem',
            color: '#22d3ee',
            marginTop: '0.25rem'
          }}>
            SECURITY LEVEL 5 - BIOMETRIC AUTHENTICATION REQUIRED
          </p>
        </div>

        {error && (
          <div className="font-mono" style={{
            marginBottom: '1.5rem',
            padding: '0.75rem',
            borderRadius: '0.25rem',
            backgroundColor: 'rgba(244,63,94,0.1)',
            border: '1px solid rgba(244,63,94,0.4)',
            color: '#fb7185',
            fontSize: '0.75rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            <AlertCircle style={{ width: '1rem', height: '1rem', flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label className="font-mono" style={{
              fontSize: '0.75rem',
              fontWeight: 700,
              color: '#cbd5e1',
              display: 'block',
              marginBottom: '0.25rem'
            }}>
              COMMANDER USERNAME
            </label>
            <div style={{ position: 'relative' }}>
              <User style={{ width: '1rem', height: '1rem', color: '#64748b', position: 'absolute', left: '0.75rem', top: '0.75rem' }} />
              <input
                type="text"
                required
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Enter username..."
                className="font-mono"
                style={{
                  width: '100%',
                  backgroundColor: '#020617',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  padding: '0.625rem 0.75rem 0.625rem 2.25rem',
                  fontSize: '0.875rem',
                  color: 'white',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          {mode === 'signup' && (
            <div>
              <label className="font-mono" style={{
                fontSize: '0.75rem',
                fontWeight: 700,
                color: '#cbd5e1',
                display: 'block',
                marginBottom: '0.25rem'
              }}>
                GUILD EMAIL ADDRESS
              </label>
              <div style={{ position: 'relative' }}>
                <Mail style={{ width: '1rem', height: '1rem', color: '#64748b', position: 'absolute', left: '0.75rem', top: '0.75rem' }} />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="Enter email..."
                  className="font-mono"
                  style={{
                    width: '100%',
                    backgroundColor: '#020617',
                    border: '1px solid #334155',
                    borderRadius: '0.5rem',
                    padding: '0.625rem 0.75rem 0.625rem 2.25rem',
                    fontSize: '0.875rem',
                    color: 'white',
                    outline: 'none',
                  }}
                />
              </div>
            </div>
          )}

          <div>
            <label className="font-mono" style={{
              fontSize: '0.75rem',
              fontWeight: 700,
              color: '#cbd5e1',
              display: 'block',
              marginBottom: '0.25rem'
            }}>
              SECURITY KEY (PASSWORD)
            </label>
            <div style={{ position: 'relative' }}>
              <Lock style={{ width: '1rem', height: '1rem', color: '#64748b', position: 'absolute', left: '0.75rem', top: '0.75rem' }} />
              <input
                type="password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="font-mono"
                style={{
                  width: '100%',
                  backgroundColor: '#020617',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  padding: '0.625rem 0.75rem 0.625rem 2.25rem',
                  fontSize: '0.875rem',
                  color: 'white',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-neon-cyan font-title"
            style={{
              width: '100%',
              justifyContent: 'center',
              paddingTop: '0.75rem',
              paddingBottom: '0.75rem',
              fontSize: '0.875rem',
              letterSpacing: '0.1em',
              marginTop: '0.5rem'
            }}
          >
            {loading ? 'AUTHENTICATING...' : mode === 'signin' ? 'ENTER CITADEL ⚡' : 'CREATE GUILD PROFILE 🛡️'}
          </button>
        </form>

        <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid #1e293b', textAlign: 'center' }}>
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signin' ? 'signup' : 'signin');
              setError(null);
            }}
            className="font-mono"
            style={{
              fontSize: '0.75rem',
              color: '#22d3ee',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              textDecoration: 'underline'
            }}
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
