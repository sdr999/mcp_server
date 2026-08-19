import React, { useEffect, useState } from 'react';
import { Wand2, Search, Play, CheckCircle2, AlertTriangle, Code2, Clock, Copy, Check, Terminal } from 'lucide-react';
import { api } from '../../services/api';
import { SchemaForm } from '../common/SchemaForm';

export const ToolSpellbook: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [tools, setTools] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTool, setSelectedTool] = useState<any | null>(null);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any | null>(null);
  const [executionDuration, setExecutionDuration] = useState<number | null>(null);
  const [lastSubmittedArgs, setLastSubmittedArgs] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [activeViewMode, setActiveViewMode] = useState<'structured' | 'raw' | 'curl'>('structured');
  const [copied, setCopied] = useState(false);

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
    setLastSubmittedArgs(formData);

    const startTime = performance.now();
    try {
      const res = await api.callTool(selectedTool.name, formData);
      const duration = Math.round(performance.now() - startTime);
      setExecutionDuration(duration);
      setExecutionResult({
        success: !res.data?.is_error,
        data: res.data
      });
      // Award 100 EXP on successful spell cast!
      if (onExpGain && !res.data?.is_error) onExpGain(100);
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

  const generateSampleArgs = (tool: any) => {
    const props = tool?.parameters?.properties || tool?.inputSchema?.properties || {};
    const sample: Record<string, any> = {};
    Object.entries(props).forEach(([k, p]: [string, any]) => {
      if (p.default !== undefined) sample[k] = p.default;
      else if (p.enum && p.enum.length > 0) sample[k] = p.enum[0];
      else if (p.type === 'number' || p.type === 'integer') sample[k] = k === 'a' ? 1 : k === 'b' ? 2 : 10;
      else if (p.type === 'boolean') sample[k] = true;
      else if (p.type === 'array') sample[k] = ["sample_item"];
      else sample[k] = `sample_${k}`;
    });
    return sample;
  };

  const getSampleCode = (tool: any, lang: 'curl' | 'python' | 'javascript') => {
    if (!tool) return '';
    const token = localStorage.getItem('mcp_token') || 'mysecretadmin';
    const baseUrl = window.location.origin;
    const args = (lastSubmittedArgs && Object.keys(lastSubmittedArgs).length > 0)
      ? lastSubmittedArgs
      : generateSampleArgs(tool);
    const jsonBody = JSON.stringify({ arguments: args }, null, 2);

    if (lang === 'curl') {
      return `curl -X 'POST' \\\n  '${baseUrl}/tools/${tool.name}/call' \\\n  -H 'accept: application/json' \\\n  -H 'Authorization: Bearer ${token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '${jsonBody}'`;
    }
    if (lang === 'python') {
      return `import requests\n\nurl = "${baseUrl}/tools/${tool.name}/call"\nheaders = {\n    "Authorization": "Bearer ${token}",\n    "Content-Type": "application/json"\n}\npayload = {\n    "arguments": ${JSON.stringify(args, null, 4).replace(/true/g, 'True').replace(/false/g, 'False')}\n}\n\nresponse = requests.post(url, json=payload, headers=headers)\nprint(response.json())`;
    }
    if (lang === 'javascript') {
      return `const response = await fetch("${baseUrl}/tools/${tool.name}/call", {\n  method: "POST",\n  headers: {\n    "Authorization": "Bearer ${token}",\n    "Content-Type": "application/json"\n  },\n  body: JSON.stringify({\n    arguments: ${JSON.stringify(args, null, 4)}\n  })\n});\nconst result = await response.json();\nconsole.log(result);`;
    }
    return '';
  };

  const copyCurl = () => {
    navigator.clipboard.writeText(getSampleCode(selectedTool, 'curl'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
                    setLastSubmittedArgs({});
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

              {/* Sample Execution Reference */}
              <div style={{
                background: 'rgba(15, 23, 42, 0.7)',
                border: '1px solid rgba(0, 240, 255, 0.25)',
                borderRadius: '0.375rem',
                padding: '0.75rem 1rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="font-mono" style={{ fontSize: '0.7rem', color: '#00f0ff', textTransform: 'uppercase', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Terminal style={{ width: '0.85rem', height: '0.85rem' }} />
                    SAMPLE EXECUTION REFERENCE
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    {(['curl', 'python', 'javascript'] as const).map(lang => (
                      <button
                        key={lang}
                        onClick={() => setActiveViewMode(lang as any)}
                        style={{
                          background: activeViewMode === lang ? 'rgba(0, 240, 255, 0.25)' : 'transparent',
                          border: activeViewMode === lang ? '1px solid rgba(0, 240, 255, 0.4)' : '1px solid transparent',
                          color: activeViewMode === lang ? '#00f0ff' : '#64748b',
                          fontSize: '10px',
                          fontFamily: 'var(--font-mono)',
                          padding: '0.15rem 0.4rem',
                          borderRadius: '0.25rem',
                          cursor: 'pointer',
                          textTransform: 'uppercase'
                        }}
                      >
                        {lang}
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ position: 'relative' }}>
                  <button
                    onClick={() => {
                      const code = (activeViewMode === 'python' || activeViewMode === 'javascript')
                        ? getSampleCode(selectedTool, activeViewMode)
                        : getSampleCode(selectedTool, 'curl');
                      navigator.clipboard.writeText(code);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                    style={{
                      position: 'absolute',
                      top: '0.35rem',
                      right: '0.35rem',
                      background: 'rgba(0, 240, 255, 0.15)',
                      border: '1px solid rgba(0, 240, 255, 0.3)',
                      color: '#00f0ff',
                      padding: '0.2rem 0.4rem',
                      borderRadius: '0.25rem',
                      fontSize: '10px',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem'
                    }}
                  >
                    {copied ? <Check style={{ width: '0.65rem', height: '0.65rem', color: '#34d399' }} /> : <Copy style={{ width: '0.65rem', height: '0.65rem' }} />}
                    {copied ? 'COPIED' : 'COPY'}
                  </button>
                  <pre className="font-mono" style={{ margin: 0, padding: '0.5rem 0.75rem', paddingRight: '5rem', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', fontSize: '0.7rem', color: '#a7f3d0', overflowX: 'auto', maxHeight: '7rem' }}>
                    {(activeViewMode === 'python' || activeViewMode === 'javascript')
                      ? getSampleCode(selectedTool, activeViewMode)
                      : getSampleCode(selectedTool, 'curl')}
                  </pre>
                </div>
              </div>

              {/* Dynamic Parameter Form */}
              <SchemaForm
                schema={selectedTool.parameters || selectedTool.inputSchema || {}}
                onSubmit={handleToolExecute}
                loading={executing}
              />

              {/* Execution Result Box */}
              {executionResult && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', paddingTop: '1rem', borderTop: '1px solid #1e293b' }}>
                  {/* Status & Timing Bar */}
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

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      {executionDuration !== null && (
                        <span className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                          <Clock style={{ width: '0.875rem', height: '0.875rem', color: '#22d3ee' }} />
                          {executionDuration} ms
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Result View Mode Selector Tabs */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.5rem' }}>
                    <button
                      onClick={() => setActiveViewMode('structured')}
                      style={{
                        background: activeViewMode === 'structured' ? 'rgba(0, 240, 255, 0.2)' : 'transparent',
                        border: activeViewMode === 'structured' ? '1px solid rgba(0, 240, 255, 0.4)' : '1px solid transparent',
                        color: activeViewMode === 'structured' ? '#00f0ff' : '#94a3b8',
                        padding: '0.25rem 0.625rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                        cursor: 'pointer'
                      }}
                    >
                      Structured View
                    </button>
                    <button
                      onClick={() => setActiveViewMode('raw')}
                      style={{
                        background: activeViewMode === 'raw' ? 'rgba(0, 240, 255, 0.2)' : 'transparent',
                        border: activeViewMode === 'raw' ? '1px solid rgba(0, 240, 255, 0.4)' : '1px solid transparent',
                        color: activeViewMode === 'raw' ? '#00f0ff' : '#94a3b8',
                        padding: '0.25rem 0.625rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                        cursor: 'pointer'
                      }}
                    >
                      Raw JSON
                    </button>
                    <button
                      onClick={() => setActiveViewMode('curl')}
                      style={{
                        background: activeViewMode === 'curl' ? 'rgba(0, 240, 255, 0.2)' : 'transparent',
                        border: activeViewMode === 'curl' ? '1px solid rgba(0, 240, 255, 0.4)' : '1px solid transparent',
                        color: activeViewMode === 'curl' ? '#00f0ff' : '#94a3b8',
                        padding: '0.25rem 0.625rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.35rem'
                      }}
                    >
                      <Terminal style={{ width: '0.75rem', height: '0.75rem' }} />
                      cURL Command
                    </button>
                  </div>

                  {/* View Mode Content */}
                  {activeViewMode === 'structured' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      {/* Structured Content Card */}
                      {executionResult.data?.structured_content && (
                        <div style={{
                          background: 'rgba(15, 23, 42, 0.8)',
                          border: '1px solid rgba(0, 240, 255, 0.3)',
                          borderRadius: '0.375rem',
                          padding: '0.75rem 1rem'
                        }}>
                          <div className="font-mono" style={{ fontSize: '0.7rem', color: '#00f0ff', textTransform: 'uppercase', marginBottom: '0.5rem', fontWeight: 700 }}>
                            STRUCTURED CONTENT
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.5rem' }}>
                            {Object.entries(executionResult.data.structured_content).map(([k, v]) => (
                              <div key={k} style={{ background: 'rgba(0,0,0,0.4)', padding: '0.5rem', borderRadius: '0.25rem', border: '1px solid rgba(255,255,255,0.05)' }}>
                                <div className="font-mono" style={{ fontSize: '0.65rem', color: '#94a3b8' }}>{k}</div>
                                <div className="font-mono" style={{ fontSize: '1rem', fontWeight: 700, color: '#34d399' }}>
                                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Content Blocks */}
                      {executionResult.data?.content && Array.isArray(executionResult.data.content) && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                          {executionResult.data.content.map((item: any, idx: number) => (
                            <div key={idx} style={{
                              background: '#020617',
                              border: '1px solid #1e293b',
                              borderRadius: '0.375rem',
                              padding: '0.75rem'
                            }}>
                              <div className="font-mono" style={{ fontSize: '0.65rem', color: '#64748b', marginBottom: '0.25rem' }}>
                                CONTENT [{item.type || 'text'}]
                              </div>
                              <pre className="font-mono" style={{ margin: 0, fontSize: '0.85rem', color: '#38bdf8', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                {item.text || JSON.stringify(item)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Fallback if data is not structured format */}
                      {!executionResult.data?.structured_content && !executionResult.data?.content && (
                        <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#67e8f9', overflow: 'auto', maxHeight: '18rem', margin: 0 }}>
                          {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}

                  {activeViewMode === 'raw' && (
                    <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', fontSize: '0.75rem', color: '#67e8f9', overflow: 'auto', maxHeight: '18rem', margin: 0 }}>
                      {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                    </pre>
                  )}

                  {activeViewMode === 'curl' && (
                    <div style={{ position: 'relative' }}>
                      <button
                        onClick={copyCurl}
                        style={{
                          position: 'absolute',
                          top: '0.5rem',
                          right: '0.5rem',
                          background: 'rgba(0, 240, 255, 0.15)',
                          border: '1px solid rgba(0, 240, 255, 0.4)',
                          color: '#00f0ff',
                          padding: '0.25rem 0.5rem',
                          borderRadius: '0.25rem',
                          fontSize: '0.7rem',
                          fontFamily: 'var(--font-mono)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.25rem'
                        }}
                      >
                        {copied ? <Check style={{ width: '0.75rem', height: '0.75rem', color: '#34d399' }} /> : <Copy style={{ width: '0.75rem', height: '0.75rem' }} />}
                        {copied ? 'COPIED!' : 'COPY cURL'}
                      </button>
                      <pre className="font-mono" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.75rem', paddingRight: '6rem', fontSize: '0.75rem', color: '#a7f3d0', overflow: 'auto', margin: 0 }}>
                        {getCurlCommand()}
                      </pre>
                    </div>
                  )}
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

