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
      setStatusMsg(`Tool '${name}' has been APPROVED and added to the spellbook!`);
      setSelectedPending(null);
      fetchPending();
      if (onExpGain) onExpGain(300);
    } catch (err: any) {
      setStatusMsg(`Failed to approve '${name}': ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async (name: string) => {
    try {
      setActionLoading(true);
      await api.rejectPendingTool(name);
      setStatusMsg(`Tool '${name}' has been REJECTED.`);
      setSelectedPending(null);
      fetchPending();
    } catch (err: any) {
      setStatusMsg(`Failed to reject '${name}': ${err.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400">
            <Clock className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider flex items-center gap-2">
              GRAND COUNCIL REVIEW (PENDING APPROVAL QUEUE)
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              REVIEW & APPROVE UNVETTED TOOL PROPOSALS (/admin/tools/pending)
            </p>
          </div>
        </div>

        <button
          onClick={fetchPending}
          disabled={loading}
          className="btn-neon-cyan text-xs py-1.5 px-3 flex items-center gap-2"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>REFRESH QUEUE</span>
        </button>
      </div>

      {statusMsg && (
        <div className="p-3 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 text-xs font-mono">
          {statusMsg}
        </div>
      )}

      {/* Grid: Pending List vs Detail Review */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Pending Tool Cards */}
        <div className="lg:col-span-5 space-y-3 max-h-[600px] overflow-y-auto">
          {loading ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              Fetching pending approvals...
            </div>
          ) : pendingTools.length === 0 ? (
            <div className="hud-panel p-8 text-center text-slate-400 font-mono text-xs">
              <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              Approval queue is empty. All proposed tools are reviewed!
            </div>
          ) : (
            pendingTools.map(t => {
              const isSelected = selectedPending?.name === t.name;

              return (
                <div
                  key={t.name}
                  onClick={() => setSelectedPending(t)}
                  className={`hud-panel p-4 cursor-pointer transition-all ${
                    isSelected
                      ? 'border-amber-400 bg-amber-950/30 shadow-[0_0_15px_rgba(255,215,0,0.2)]'
                      : 'hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <h4 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                      <Code className="w-4 h-4 text-amber-400" />
                      {t.name}
                    </h4>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
                      PENDING REVIEW
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 line-clamp-2">
                    {t.description || 'AI Generated Tool Proposal awaiting council audit.'}
                  </p>
                </div>
              );
            })
          )}
        </div>

        {/* Right Column: Code Review & Approve/Reject Decision Box */}
        <div className="lg:col-span-7 hud-panel p-6 space-y-5">
          {selectedPending ? (
            <>
              <div className="border-b border-slate-800 pb-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-white font-mono flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5 text-amber-400" />
                    {selectedPending.name}
                  </h3>
                  <span className="text-xs font-mono text-cyan-400 bg-cyan-500/10 border border-cyan-500/30 px-2 py-1 rounded">
                    AUTHOR: {selectedPending.author || 'AI Generator'}
                  </span>
                </div>
                <p className="text-xs text-slate-300 mt-1">
                  {selectedPending.description || 'Review the generated source code for security compliance before approving.'}
                </p>
              </div>

              <div>
                <span className="text-xs font-mono text-slate-400 block mb-1">SOURCE CODE INSPECTION:</span>
                <pre className="w-full bg-slate-950 border border-slate-800 rounded p-3 font-mono text-xs text-emerald-400 overflow-auto max-h-64">
                  {selectedPending.code || selectedPending.source_code || JSON.stringify(selectedPending, null, 2)}
                </pre>
              </div>

              <div className="flex items-center gap-4 pt-2">
                <button
                  onClick={() => handleApprove(selectedPending.name)}
                  disabled={actionLoading}
                  className="flex-1 btn-neon-cyan justify-center py-2.5 text-xs tracking-wider"
                >
                  <CheckCircle2 className="w-4 h-4" /> APPROVE & FORGE SPELL (+300 EXP)
                </button>
                <button
                  onClick={() => handleReject(selectedPending.name)}
                  disabled={actionLoading}
                  className="flex-1 btn-neon-magenta justify-center py-2.5 text-xs tracking-wider"
                >
                  <XCircle className="w-4 h-4" /> REJECT & DISCARD PROPOSAL
                </button>
              </div>
            </>
          ) : (
            <div className="text-center py-20 text-slate-500 font-mono text-xs">
              Select a pending proposal from the left queue to inspect source code and vote.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
