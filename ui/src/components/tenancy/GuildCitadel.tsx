import React, { useEffect, useState } from 'react';
import { Users2, ShieldCheck, Building2, Layers, Key, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../services/api';

export const GuildCitadel: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<string>('');
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [members, setMembers] = useState<any[]>([]);
  const [grants, setGrants] = useState<any[]>([]);
  
  const [newOrgId, setNewOrgId] = useState('');
  const [newOrgName, setNewOrgName] = useState('');
  const [newWsName, setNewWsName] = useState('');
  const [memberSubject, setMemberSubject] = useState('');
  const [memberRole, setMemberRole] = useState('agent_consumer');
  
  const [grantPrincipal, setGrantPrincipal] = useState('*');
  const [grantToolName, setGrantToolName] = useState('*');
  const [grantEffect, setGrantEffect] = useState<'allow' | 'deny'>('allow');

  const [loading, setLoading] = useState(true);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchOrgs = async () => {
    try {
      setLoading(true);
      const res = await api.getOrgs();
      const raw = res.data;
      const list = Array.isArray(raw) ? raw : raw?.orgs || [];
      setOrgs(list);
      if (list.length > 0 && !selectedOrg) {
        const firstId = list[0].id || list[0].org_id || list[0].name;
        setSelectedOrg(firstId);
      }
    } catch (e) {
      console.error('Failed to load orgs', e);
    } finally {
      setLoading(false);
    }
  };

  const fetchOrgDetails = async (orgId: string) => {
    if (!orgId) return;
    try {
      const [wsRes, memRes, grantRes] = await Promise.allSettled([
        api.getWorkspaces(orgId),
        api.getMembers(orgId),
        api.getToolGrants(orgId)
      ]);

      if (wsRes.status === 'fulfilled') setWorkspaces(Array.isArray(wsRes.value.data) ? wsRes.value.data : wsRes.value.data?.workspaces || []);
      if (memRes.status === 'fulfilled') setMembers(Array.isArray(memRes.value.data) ? memRes.value.data : memRes.value.data?.members || []);
      if (grantRes.status === 'fulfilled') setGrants(Array.isArray(grantRes.value.data) ? grantRes.value.data : grantRes.value.data?.grants || []);
    } catch (e) {
      console.error('Failed to fetch org details', e);
    }
  };

  useEffect(() => {
    fetchOrgs();
  }, []);

  useEffect(() => {
    if (selectedOrg) fetchOrgDetails(selectedOrg);
  }, [selectedOrg]);

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createOrg({ org_id: newOrgId, name: newOrgName });
      setStatusMsg(`Guild Organization '${newOrgId}' created!`);
      setNewOrgId('');
      setNewOrgName('');
      fetchOrgs();
      if (onExpGain) onExpGain(200);
    } catch (err: any) {
      setStatusMsg(`Failed to create org: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrg) return;
    try {
      await api.createWorkspace(selectedOrg, { name: newWsName });
      setStatusMsg(`Workspace '${newWsName}' added to Org '${selectedOrg}'`);
      setNewWsName('');
      fetchOrgDetails(selectedOrg);
    } catch (err: any) {
      setStatusMsg(`Failed workspace creation: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleBindMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrg) return;
    try {
      await api.bindMember(selectedOrg, { subject: memberSubject, role: memberRole });
      setStatusMsg(`Member '${memberSubject}' bound to role '${memberRole}'`);
      setMemberSubject('');
      fetchOrgDetails(selectedOrg);
      if (onExpGain) onExpGain(150);
    } catch (err: any) {
      setStatusMsg(`Failed member binding: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleAddToolGrant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrg) return;
    try {
      await api.addToolGrant(selectedOrg, {
        principal: grantPrincipal,
        tool_pattern: grantToolName,
        effect: grantEffect
      });
      setStatusMsg(`Tool access grant added for '${grantToolName}'`);
      fetchOrgDetails(selectedOrg);
      if (onExpGain) onExpGain(150);
    } catch (err: any) {
      setStatusMsg(`Failed tool grant: ${err.response?.data?.detail || err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="hud-panel p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Users2 className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              GUILD & CITADEL CONTROL (MULTI-TENANCY & RBAC)
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              TENANT ORGANIZATIONS, WORKSPACES & ROLE ACCESS CONTROL GRANTS (/admin/orgs*)
            </p>
          </div>
        </div>

        {/* Org Selector */}
        <div className="flex items-center gap-2">
          <select
            value={selectedOrg}
            onChange={e => setSelectedOrg(e.target.value)}
            className="bg-slate-900 border border-cyan-500/40 text-cyan-400 text-xs font-mono font-bold px-3 py-1.5 rounded focus:outline-none"
          >
            <option value="">SELECT GUILD ORG...</option>
            {orgs.map(o => {
              const id = o.id || o.org_id || o.name;
              return <option key={id} value={id}>{id} ({o.name || id})</option>;
            })}
          </select>

          <button onClick={fetchOrgs} className="btn-neon-cyan text-xs py-1.5 px-3">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="p-3 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 text-xs font-mono">
          {statusMsg}
        </div>
      )}

      {/* Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Create Org & Workspaces */}
        <div className="space-y-6">
          {/* Create Org */}
          <form onSubmit={handleCreateOrg} className="hud-panel p-5 space-y-3">
            <h4 className="text-xs font-mono font-bold text-cyan-400 uppercase border-b border-slate-800 pb-2 flex items-center gap-1.5">
              <Building2 className="w-4 h-4" /> CREATE GUILD ORGANIZATION
            </h4>
            <input
              type="text"
              required
              value={newOrgId}
              onChange={e => setNewOrgId(e.target.value)}
              placeholder="Org ID (e.g. org_acme)"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            />
            <input
              type="text"
              required
              value={newOrgName}
              onChange={e => setNewOrgName(e.target.value)}
              placeholder="Org Name (e.g. Acme Guild)"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            />
            <button type="submit" className="w-full btn-neon-cyan justify-center py-2 text-xs">
              CREATE ORG ⚡ (+200 EXP)
            </button>
          </form>

          {/* Workspaces */}
          <div className="hud-panel p-5 space-y-3">
            <h4 className="text-xs font-mono font-bold text-emerald-400 uppercase border-b border-slate-800 pb-2 flex items-center gap-1.5">
              <Layers className="w-4 h-4" /> WORKSPACES ({workspaces.length})
            </h4>
            <form onSubmit={handleCreateWorkspace} className="flex gap-2">
              <input
                type="text"
                required
                value={newWsName}
                onChange={e => setNewWsName(e.target.value)}
                placeholder="Workspace name..."
                className="flex-1 bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-xs text-white focus:outline-none font-mono"
              />
              <button type="submit" className="btn-neon-cyan text-xs py-1.5 px-3">ADD</button>
            </form>
            <div className="space-y-1.5 max-h-40 overflow-y-auto pt-2">
              {workspaces.map((ws, i) => (
                <div key={i} className="p-2 rounded bg-slate-900 border border-slate-800 text-xs font-mono text-slate-300">
                  {ws.name || ws.id || JSON.stringify(ws)}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Member Role Bindings */}
        <div className="hud-panel p-5 space-y-4">
          <h4 className="text-xs font-mono font-bold text-amber-400 uppercase border-b border-slate-800 pb-2 flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4" /> GUILD MEMBERS & ROLES ({members.length})
          </h4>

          <form onSubmit={handleBindMember} className="space-y-2">
            <input
              type="text"
              required
              value={memberSubject}
              onChange={e => setMemberSubject(e.target.value)}
              placeholder="User Subject / Email..."
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            />
            <select
              value={memberRole}
              onChange={e => setMemberRole(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-amber-400 focus:outline-none font-mono"
            >
              <option value="admin">ADMIN (Full Guild Clearance)</option>
              <option value="operator">OPERATOR (Tool Forge & Execute)</option>
              <option value="agent_consumer">AGENT CONSUMER (Execute Only)</option>
              <option value="viewer">VIEWER (Read Only)</option>
            </select>
            <button type="submit" className="w-full btn-neon-cyan justify-center py-2 text-xs">
              BIND MEMBER ROLE (+150 EXP)
            </button>
          </form>

          <div className="space-y-2 max-h-64 overflow-y-auto pt-2">
            {members.map((m, i) => (
              <div key={i} className="p-2.5 rounded bg-slate-900 border border-slate-800 flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold text-white font-mono">{m.subject || m.user_id}</div>
                  <div className="text-[10px] text-amber-400 font-mono uppercase">{m.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Tool Access Grants */}
        <div className="hud-panel p-5 space-y-4">
          <h4 className="text-xs font-mono font-bold text-rose-400 uppercase border-b border-slate-800 pb-2 flex items-center gap-1.5">
            <Key className="w-4 h-4" /> TOOL ACCESS GRANTS MATRIX ({grants.length})
          </h4>

          <form onSubmit={handleAddToolGrant} className="space-y-2">
            <input
              type="text"
              required
              value={grantPrincipal}
              onChange={e => setGrantPrincipal(e.target.value)}
              placeholder="Principal (* or user sub)..."
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            />
            <input
              type="text"
              required
              value={grantToolName}
              onChange={e => setGrantToolName(e.target.value)}
              placeholder="Tool Pattern (* or calc_*)..."
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            />
            <select
              value={grantEffect}
              onChange={e => setGrantEffect(e.target.value as any)}
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none font-mono"
            >
              <option value="allow">ALLOW EFFECT</option>
              <option value="deny">DENY EFFECT (OVERRIDE)</option>
            </select>
            <button type="submit" className="w-full btn-neon-magenta justify-center py-2 text-xs">
              ADD GRANT POLICY (+150 EXP)
            </button>
          </form>

          <div className="space-y-2 max-h-64 overflow-y-auto pt-2">
            {grants.map((g, i) => (
              <div key={i} className="p-2.5 rounded bg-slate-900 border border-slate-800 flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold text-white font-mono">Tool: {g.tool_pattern || g.tool}</div>
                  <div className="text-[10px] text-slate-400 font-mono">Principal: {g.principal || '*'}</div>
                </div>
                <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  g.effect === 'deny' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'
                }`}>
                  {g.effect?.toUpperCase() || 'ALLOW'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
