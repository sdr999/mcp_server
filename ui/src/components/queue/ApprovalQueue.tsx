import React, { useEffect, useState } from 'react';
import { Clock, CheckCircle2, XCircle, Code, ShieldAlert, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';

export const ApprovalQueue: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [pendingTools, setPendingTools] = useState<any[]>([]);
  const [selectedPending, setSelectedPending] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchPending = async () => {
    try {
      setLoading(true);
      const res = await api.getPendingTools();
      const raw = res.data;
      if (Array.isArray(raw)) setPendingTools(raw);
      else if (raw?.pending) setPendingTools(raw.pending);
      else if (typeof raw === 'object') {
        const list = Object.entries(raw).map(([name, val]: [string, any]) => ({
          name,
          ...val
        }));
        setPendingTools(list);
      }
    } catch (e) {
      console.error('Failed to load pending approval queue', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPending();
  }, []);

  const handleApprove = async (name: string) => {
    try {
      setActionLoading(true);
      await api.approvePendingTool(name);
      setStatusMsg(`Module '${name}' has been AUTHORIZED and deployed to active armory!`);
      setSelectedPending(null);
      fetchPending();
      if (onExpGain) onExpGain(300);
    } catch (err: any) {
      setStatusMsg(`Failed to authorize '${name}': ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async (name: string) => {
    try {
      setActionLoading(true);
      await api.rejectPendingTool(name);
      setStatusMsg(`Module '${name}' has been REJECTED.`);
      setSelectedPending(null);
      fetchPending();
    } catch (err: any) {
      setStatusMsg(`Failed to reject '${name}': ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div className="hud-panel" style={{ padding: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', borderRadius: '0.375rem', backgroundColor: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.3)', color: '#fb7185' }}>
            <Clock style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', letterSpacing: '0.05em', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              SECURITY REVIEW (PENDING APPROVAL QUEUE)
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem' }}>
              AUDIT & AUTHORIZE UNVETTED MODULE PROPOSALS (/admin/tools/pending)
            </p>
          </div>
        </div>

        <button
          onClick={fetchPending}
          disabled={loading}
          className="btn-sc btn-sc-cyan font-mono"
          style={{ fontSize: '0.75rem', padding: '0.375rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw style={{ width: '0.875rem', height: '0.875rem' }} />
          <span>REFRESH QUEUE</span>
        </button>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{ padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: 'rgba(8, 51, 68, 0.6)', border: '1px solid rgba(6, 182, 212, 0.4)', color: '#67e8f9', fontSize: '0.75rem' }}>
          {statusMsg}
        </div>
      )}

      {/* Grid: Pending List vs Detail Review */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1.5rem' }}>
        {/* Left Column: Pending Tool Cards */}
        <div style={{ gridColumn: 'span 5', display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '600px', overflowY: 'auto' }}>
          {loading ? (
            <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              Fetching pending approvals...
            </div>
          ) : pendingTools.length === 0 ? (
            <div className="hud-panel font-mono" style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8', fontSize: '0.75rem' }}>
              <CheckCircle2 style={{ width: '2rem', height: '2rem', color: '#34d399', margin: '0 auto 0.5rem auto' }} />
              Approval queue is clear. All proposed modules are reviewed.
            </div>
          ) : (
            pendingTools.map(t => {
              const isSelected = selectedPending?.name === t.name;

              return (
                <div
                  key={t.name}
                  onClick={() => setSelectedPending(t)}
                  className="hud-panel"
                  style={{
                    padding: '1rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    border: isSelected ? '1px solid #fbbf24' : '1px solid #1e2c45',
                    backgroundColor: isSelected ? 'rgba(245, 158, 11, 0.1)' : undefined
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                    <h4 className="font-mono" style={{ fontSize: '0.875rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                      <Code style={{ width: '1rem', height: '1rem', color: '#fbbf24' }} />
                      {t.name}
                    </h4>
                    <span className="font-mono" style={{ fontSize: '0.625rem', padding: '0.125rem 0.5rem', borderRadius: '0.25rem', backgroundColor: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                      PENDING AUDIT
                    </span>
                  </div>
                  <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {t.description || 'AI Synthesized Module Proposal awaiting security audit.'}
                  </p>
                </div>
              );
            })
          )}
        </div>

        {/* Right Column: Code Review & Approve/Reject Decision Box */}
        <div className="hud-panel" style={{ gridColumn: 'span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {selectedPending ? (
            <>
              <div style={{ borderBottom: '1px solid #1e2c45', paddingBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <h3 className="font-mono" style={{ fontSize: '1.125rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                    <ShieldAlert style={{ width: '1.25rem', height: '1.25rem', color: '#fbbf24' }} />
                    {selectedPending.name}
                  </h3>
                  <span className="font-mono" style={{ fontSize: '0.75rem', color: '#22d3ee', backgroundColor: 'rgba(6, 182, 212, 0.1)', border: '1px solid rgba(6, 182, 212, 0.3)', padding: '0.25rem 0.5rem', borderRadius: '0.25rem' }}>
                    AUTHOR: {selectedPending.author || 'AI Generator'}
                  </span>
                </div>
                <p style={{ fontSize: '0.75rem', color: '#cbd5e1', margin: 0, marginTop: '0.25rem' }}>
                  {selectedPending.description || 'Review the generated source code for security compliance before deploying.'}
                </p>
              </div>

              <div>
                <span className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '0.25rem' }}>SOURCE CODE INSPECTION:</span>
                <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#34d399', overflow: 'auto', maxHeight: '16rem', margin: 0 }}>
                  {selectedPending.code || selectedPending.source_code || JSON.stringify(selectedPending, null, 2)}
                </pre>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', paddingTop: '0.5rem' }}>
                <button
                  onClick={() => handleApprove(selectedPending.name)}
                  disabled={actionLoading}
                  className="btn-sc btn-sc-emerald"
                  style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', padding: '0.625rem 0', fontSize: '0.75rem' }}
                >
                  <CheckCircle2 style={{ width: '1rem', height: '1rem' }} /> AUTHORIZE & DEPLOY (+300 EXP)
                </button>
                <button
                  onClick={() => handleReject(selectedPending.name)}
                  disabled={actionLoading}
                  className="btn-sc btn-sc-crimson"
                  style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', padding: '0.625rem 0', fontSize: '0.75rem' }}
                >
                  <XCircle style={{ width: '1rem', height: '1rem' }} /> REJECT & DISCARD
                </button>
              </div>
            </>
          ) : (
            <div className="font-mono" style={{ textAlign: 'center', padding: '5rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              Select a pending proposal from the left queue to inspect source code and authorize.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
