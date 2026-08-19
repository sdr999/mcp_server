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
    <div style={{display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
      {/* Header */}
      <div className="hud-panel" style={{padding: '1.0rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: '0.75rem'}}>
          <div style={{padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(6, 182, 212, 0.1)', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.3)', color: '#22d3ee'}}>
            <Users2 style={{width: '1.25rem', height: '1.25rem'}} />
          </div>
          <div>
            <h3 style={{fontSize: '1rem', fontWeight: '700', color: '#ffffff', letterSpacing: '0.05em'}}>
              GUILD & CITADEL CONTROL (MULTI-TENANCY & RBAC)
            </h3>
            <p className="font-mono" style={{fontSize: '0.75rem', color: '#94a3b8'}}>
              TENANT ORGANIZATIONS, WORKSPACES & ROLE ACCESS CONTROL GRANTS (/admin/orgs*)
            </p>
          </div>
        </div>

        {/* Org Selector */}
        <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
          <select
            value={selectedOrg}
            onChange={e => setSelectedOrg(e.target.value)}
            className="font-mono" style={{backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.4)', color: '#22d3ee', fontSize: '0.75rem', fontWeight: '700', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', borderRadius: '0.25rem'}}
          >
            <option value="">SELECT GUILD ORG...</option>
            {orgs.map(o => {
              const id = o.id || o.org_id || o.name;
              return <option key={id} value={id}>{id} ({o.name || id})</option>;
            })}
          </select>

          <button onClick={fetchOrgs} className="btn-neon-cyan" style={{fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem'}}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="font-mono" style={{padding: '0.75rem', borderRadius: '0.25rem', backgroundColor: 'rgba(8, 51, 68, 0.6)', border: '1px solid #1e293b', borderColor: 'rgba(6, 182, 212, 0.4)', color: '#67e8f9', fontSize: '0.75rem'}}>
          {statusMsg}
        </div>
      )}

      {/* Grid Layout */}
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '1.5rem'}}>
        {/* Create Org & Workspaces */}
        <div style={{display: 'flex', flexDirection: 'column', gap: '1.5rem'}}>
          {/* Create Org */}
          <form onSubmit={handleCreateOrg} className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
            <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#22d3ee', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem'}}>
              <Building2 style={{width: '1rem', height: '1rem'}} /> CREATE GUILD ORGANIZATION
            </h4>
            <input
              type="text"
              required
              value={newOrgId}
              onChange={e => setNewOrgId(e.target.value)}
              placeholder="Org ID (e.g. org_acme)"
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
            <input
              type="text"
              required
              value={newOrgName}
              onChange={e => setNewOrgName(e.target.value)}
              placeholder="Org Name (e.g. Acme Guild)"
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
            <button type="submit" className="btn-neon-cyan" style={{width: '100%', justifyContent: 'center', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem'}}>
              CREATE ORG ⚡ (+200 EXP)
            </button>
          </form>

          {/* Workspaces */}
          <div className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
            <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#34d399', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem'}}>
              <Layers style={{width: '1rem', height: '1rem'}} /> WORKSPACES ({workspaces.length})
            </h4>
            <form onSubmit={handleCreateWorkspace} style={{display: 'flex', gap: '0.5rem'}}>
              <input
                type="text"
                required
                value={newWsName}
                onChange={e => setNewWsName(e.target.value)}
                placeholder="Workspace name..."
                className="font-mono" style={{flex: '1 1 0%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', fontSize: '0.75rem', color: '#ffffff'}}
              />
              <button type="submit" className="btn-neon-cyan" style={{fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem'}}>ADD</button>
            </form>
            <div style={{display: 'flex', flexDirection: 'column', gap: '0.375rem', maxHeight: '10rem', overflowY: 'auto', paddingTop: '0.5rem'}}>
              {workspaces.map((ws, i) => (
                <div key={i} className="font-mono" style={{padding: '0.5rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b', fontSize: '0.75rem', color: '#cbd5e1'}}>
                  {ws.name || ws.id || JSON.stringify(ws)}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Member Role Bindings */}
        <div className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#fbbf24', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem'}}>
            <ShieldCheck style={{width: '1rem', height: '1rem'}} /> GUILD MEMBERS & ROLES ({members.length})
          </h4>

          <form onSubmit={handleBindMember} style={{display: 'flex', flexDirection: 'column', gap: '0.5rem'}}>
            <input
              type="text"
              required
              value={memberSubject}
              onChange={e => setMemberSubject(e.target.value)}
              placeholder="User Subject / Email..."
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
            <select
              value={memberRole}
              onChange={e => setMemberRole(e.target.value)}
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#fbbf24'}}
            >
              <option value="admin">ADMIN (Full Guild Clearance)</option>
              <option value="operator">OPERATOR (Tool Forge & Execute)</option>
              <option value="agent_consumer">AGENT CONSUMER (Execute Only)</option>
              <option value="viewer">VIEWER (Read Only)</option>
            </select>
            <button type="submit" className="btn-neon-cyan" style={{width: '100%', justifyContent: 'center', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem'}}>
              BIND MEMBER ROLE (+150 EXP)
            </button>
          </form>

          <div style={{display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '16rem', overflowY: 'auto', paddingTop: '0.5rem'}}>
            {members.map((m, i) => (
              <div key={i} style={{padding: '0.625rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                <div>
                  <div className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#ffffff'}}>{m.subject || m.user_id}</div>
                  <div className="font-mono" style={{fontSize: '10px', color: '#fbbf24', textTransform: 'uppercase'}}>{m.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Tool Access Grants */}
        <div className="hud-panel" style={{padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
          <h4 className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#fb7185', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', borderColor: '#1e293b', paddingBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem'}}>
            <Key style={{width: '1rem', height: '1rem'}} /> TOOL ACCESS GRANTS MATRIX ({grants.length})
          </h4>

          <form onSubmit={handleAddToolGrant} style={{display: 'flex', flexDirection: 'column', gap: '0.5rem'}}>
            <input
              type="text"
              required
              value={grantPrincipal}
              onChange={e => setGrantPrincipal(e.target.value)}
              placeholder="Principal (* or user sub)..."
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
            <input
              type="text"
              required
              value={grantToolName}
              onChange={e => setGrantToolName(e.target.value)}
              placeholder="Tool Pattern (* or calc_*)..."
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            />
            <select
              value={grantEffect}
              onChange={e => setGrantEffect(e.target.value as any)}
              className="font-mono" style={{width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderColor: '#334155', borderRadius: '0.25rem', paddingLeft: '0.75rem', paddingRight: '0.75rem', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem', color: '#ffffff'}}
            >
              <option value="allow">ALLOW EFFECT</option>
              <option value="deny">DENY EFFECT (OVERRIDE)</option>
            </select>
            <button type="submit" className="btn-neon-magenta" style={{width: '100%', justifyContent: 'center', paddingTop: '0.5rem', paddingBottom: '0.5rem', fontSize: '0.75rem'}}>
              ADD GRANT POLICY (+150 EXP)
            </button>
          </form>

          <div style={{display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '16rem', overflowY: 'auto', paddingTop: '0.5rem'}}>
            {grants.map((g, i) => (
              <div key={i} style={{padding: '0.625rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #1e293b', borderColor: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                <div>
                  <div className="font-mono" style={{fontSize: '0.75rem', fontWeight: '700', color: '#ffffff'}}>Tool: {g.tool_pattern || g.tool}</div>
                  <div className="font-mono" style={{fontSize: '10px', color: '#94a3b8'}}>Principal: {g.principal || '*'}</div>
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
