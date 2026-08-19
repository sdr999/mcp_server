import React, { useEffect, useState } from 'react';
import { Wand2, Search, Play, CheckCircle2, AlertTriangle, Code2, Clock } from 'lucide-react';
import { api } from '../../services/api';
import { SchemaForm } from '../common/SchemaForm';

export const ToolSpellbook: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [tools, setTools] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTool, setSelectedTool] = useState<any | null>(null);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any | null>(null);
  const [executionDuration, setExecutionDuration] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCatalog = async () => {
    try {
      setLoading(true);
      const res = await api.getToolsCatalog();
      const rawTools = res.data;
      if (Array.isArray(rawTools)) setTools(rawTools);
      else if (rawTools?.tools) setTools(rawTools.tools);
      else if (typeof rawTools === 'object') {
        const list = Object.entries(rawTools).map(([name, val]: [string, any]) => ({
          name,
          ...val
        }));
        setTools(list);
      }
    } catch (e) {
      console.error('Failed to load tool spellbook catalog', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
  }, []);

  const handleToolExecute = async (formData: any) => {
    if (!selectedTool) return;
    setExecuting(true);
    setExecutionResult(null);
    setExecutionDuration(null);

    const startTime = performance.now();
    try {
      const res = await api.callTool(selectedTool.name, formData);
      const duration = Math.round(performance.now() - startTime);
      setExecutionDuration(duration);
      setExecutionResult({
        success: true,
        data: res.data
      });
      // Award 100 EXP on successful spell cast!
      if (onExpGain) onExpGain(100);
    } catch (err: any) {
      const duration = Math.round(performance.now() - startTime);
      setExecutionDuration(duration);
      setExecutionResult({
        success: false,
        error: err.response?.data || err.message
      });
    } finally {
      setExecuting(false);
    }
  };

  const filteredTools = tools.filter(t => 
    t.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Search */}
      <div className="hud-panel" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', padding: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(6, 182, 212, 0.1)', border: '1px solid rgba(6, 182, 212, 0.3)', color: '#22d3ee' }}>
            <Wand2 style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', letterSpacing: '0.05em', margin: 0 }}>
              SPELLBOOK (MCP TOOL CATALOG)
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem' }}>
              INSPECT & CAST REGISTERED MCP SPELLS (/tools/{'{name}'}/call)
            </p>
          </div>
        </div>

        {/* Search Bar */}
        <div style={{ position: 'relative', width: '100%', maxWidth: '18rem' }}>
          <Search style={{ width: '1rem', height: '1rem', color: '#64748b', position: 'absolute', left: '0.75rem', top: '0.625rem' }} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search spells by name..."
            className="font-mono"
            style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '0.5rem', padding: '0.5rem 0.75rem 0.5rem 2.25rem', fontSize: '0.75rem', color: '#ffffff', outline: 'none' }}
          />
        </div>
      </div>

      {/* Grid: Tools Catalog vs Execution Arena */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1.5rem' }}>
        {/* Left Column: Tool Cards Grid */}
        <div style={{ gridColumn: 'span 5', display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '700px', overflowY: 'auto', paddingRight: '0.25rem' }}>
          {loading ? (
            <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              Loading spellbook tools...
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.75rem' }}>
              No matching tools found in catalog.
            </div>
          ) : (
            filteredTools.map(t => {
              const isSelected = selectedTool?.name === t.name;

              return (
                <div
                  key={t.name}
                  onClick={() => {
                    setSelectedTool(t);
                    setExecutionResult(null);
                  }}
                  className="hud-panel"
                  style={{
                    padding: '1rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    border: isSelected ? '1px solid rgba(34, 211, 238, 0.5)' : '1px solid transparent',
                    backgroundColor: isSelected ? 'rgba(8, 51, 68, 0.4)' : undefined,
                    boxShadow: isSelected ? '0 0 20px rgba(0,240,255,0.25)' : undefined
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                    <h4 className="font-mono" style={{ fontSize: '0.875rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                      <Code2 style={{ width: '1rem', height: '1rem', color: '#22d3ee' }} />
                      {t.name}
                    </h4>
                    <span className="font-mono" style={{ fontSize: '0.625rem', padding: '0.125rem 0.5rem', borderRadius: '0.25rem', backgroundColor: 'rgba(6, 182, 212, 0.2)', color: '#22d3ee' }}>
                      SPELL
                    </span>
                  </div>
                  <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.25rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {t.description || 'No description provided.'}
                  </p>
                </div>
              );
            })
          )}
        </div>

        {/* Right Column: Interactive Spell Casting Arena */}
        <div className="hud-panel" style={{ gridColumn: 'span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {selectedTool ? (
            <>
              <div style={{ borderBottom: '1px solid #1e293b', paddingBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <h3 className="font-mono" style={{ fontSize: '1.125rem', fontWeight: 900, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                    <Play style={{ width: '1.25rem', height: '1.25rem', color: '#22d3ee' }} />
                    {selectedTool.name}
                  </h3>
                  <span className="font-mono" style={{ fontSize: '0.75rem', color: '#34d399', backgroundColor: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', padding: '0.25rem 0.625rem', borderRadius: '0.25rem' }}>
                    +100 EXP REWARD
                  </span>
                </div>
                <p style={{ fontSize: '0.75rem', color: '#cbd5e1', margin: 0, marginTop: '0.25rem' }}>
                  {selectedTool.description}
                </p>
              </div>

              {/* Dynamic Parameter Form */}
              <SchemaForm
                schema={selectedTool.parameters || selectedTool.inputSchema || {}}
                onSubmit={handleToolExecute}
                loading={executing}
              />

              {/* Execution Result Box */}
              {executionResult && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', paddingTop: '1rem', borderTop: '1px solid #1e293b' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {executionResult.success ? (
                        <>
                          <CheckCircle2 style={{ width: '1rem', height: '1rem', color: '#34d399' }} />
                          <span style={{ color: '#34d399' }}>SPELL CAST SUCCESSFUL</span>
                        </>
                      ) : (
                        <>
                          <AlertTriangle style={{ width: '1rem', height: '1rem', color: '#fb7185' }} />
                          <span style={{ color: '#fb7185' }}>SPELL FAILED</span>
                        </>
                      )}
                    </span>
                    {executionDuration !== null && (
                      <span className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <Clock style={{ width: '0.875rem', height: '0.875rem', color: '#22d3ee' }} />
                        {executionDuration} ms
                      </span>
                    )}
                  </div>

                  <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#67e8f9', overflow: 'auto', maxHeight: '18rem', margin: 0 }}>
                    {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="font-mono" style={{ textAlign: 'center', padding: '5rem 0', color: '#64748b', fontSize: '0.875rem' }}>
              <Wand2 style={{ width: '3rem', height: '3rem', color: '#334155', margin: '0 auto 0.75rem auto' }} />
              Select a spell from the left spellbook catalog to test execution.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
