import React, { useEffect, useState, useMemo } from 'react';
import { Wand2, Search, Play, CheckCircle2, AlertTriangle, Code2, Clock, Copy, Check, Terminal, Cpu, Radio, Shield, Zap, Flame, Award, Trophy, ArrowUpDown } from 'lucide-react';
import { api } from '../../services/api';
import { SchemaForm } from '../common/SchemaForm';
import { sfx } from '../../services/soundEffects';
import { toolUsageTracker, ToolMastery } from '../../services/toolUsageTracker';

export const ToolSpellbook: React.FC<{ onExpGain?: (xp: number) => void }> = ({ onExpGain }) => {
  const [tools, setTools] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTool, setSelectedTool] = useState<any | null>(null);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any | null>(null);
  const [executionDuration, setExecutionDuration] = useState<number | null>(null);
  const [lastSubmittedArgs, setLastSubmittedArgs] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [toolStatsVersion, setToolStatsVersion] = useState(0);
  const [sortBy, setSortBy] = useState<'rank' | 'level' | 'name'>('rank');

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
      console.error('Failed to load tactical module catalog', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
    const unsub = toolUsageTracker.subscribe(() => {
      setToolStatsVersion(v => v + 1);
    });
    return unsub;
  }, []);

  const handleSelectTool = (tool: any) => {
    sfx.playCardSelectSound();
    setSelectedTool(tool);
    setExecutionResult(null);
  };

  const handleToolExecute = async (formData: any) => {
    if (!selectedTool) return;
    sfx.playSpellCastSound();
    setExecuting(true);
    setExecutionResult(null);
    setExecutionDuration(null);
    setLastSubmittedArgs(formData);

    const startTime = performance.now();
    try {
      const res = await api.callTool(selectedTool.name, formData);
      const duration = Math.round(performance.now() - startTime);
      setExecutionDuration(duration);
      const isError = Boolean(res.data?.is_error);
      
      // Record usage for tool level calculation
      toolUsageTracker.recordUsage(selectedTool.name, duration);

      setExecutionResult({
        success: !isError,
        data: res.data
      });
      if (!isError) {
        sfx.playVictorySound();
        if (onExpGain) onExpGain(150);
      } else {
        sfx.playErrorBuzz();
      }
    } catch (err: any) {
      sfx.playErrorBuzz();
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

  // Build ranked tools map
  const toolNames = useMemo(() => tools.map(t => t.name), [tools]);
  const rankedToolsList = useMemo(() => toolUsageTracker.getRankedTools(toolNames), [toolNames, toolStatsVersion]);
  const ranksMap = useMemo(() => {
    const map = new Map<string, ToolMastery>();
    rankedToolsList.forEach(item => {
      map.set(item.name, item);
    });
    return map;
  }, [rankedToolsList]);

  // Filter & Sort
  const processedTools = useMemo(() => {
    let list = tools.filter(t => 
      t.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.description?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    list.sort((a, b) => {
      const statsA = ranksMap.get(a.name) || toolUsageTracker.getToolStats(a.name);
      const statsB = ranksMap.get(b.name) || toolUsageTracker.getToolStats(b.name);

      if (sortBy === 'rank') {
        return (statsA.rank ?? 999) - (statsB.rank ?? 999);
      }
      if (sortBy === 'level') {
        if (statsB.level !== statsA.level) return statsB.level - statsA.level;
        return statsB.calls - statsA.calls;
      }
      return a.name.localeCompare(b.name);
    });

    return list;
  }, [tools, searchQuery, sortBy, ranksMap]);

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
      return `import requests\n\nurl = "${baseUrl}/tools/${tool.name}/call"\nheaders = {\n    "Authorization": "Bearer ${token}",\n    "Content-Type": "application/json"\n}\npayload = ${JSON.stringify({ arguments: args }, null, 4)}\n\nresponse = requests.post(url, json=payload, headers=headers)\nprint(response.json())`;
    }
    return `const response = await fetch("${baseUrl}/tools/${tool.name}/call", {\n  method: "POST",\n  headers: {\n    "Authorization": "Bearer ${token}",\n    "Content-Type": "application/json"\n  },\n  body: JSON.stringify(${JSON.stringify({ arguments: args }, null, 2)})\n});\nconst result = await response.json();\nconsole.log(result);`;
  };

  const handleCopy = (text: string) => {
    sfx.playTapSound();
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const selectedStats = selectedTool ? (ranksMap.get(selectedTool.name) || toolUsageTracker.getToolStats(selectedTool.name)) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Header */}
      <div className="hud-panel" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            padding: '0.65rem',
            borderRadius: '0.375rem',
            background: 'rgba(0, 240, 255, 0.12)',
            border: '1px solid rgba(0, 240, 255, 0.4)',
            color: '#00f0ff'
          }}>
            <Cpu style={{ width: '1.5rem', height: '1.5rem' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1.15rem', color: '#ffffff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              TACTICAL DEPLOYABLE MODULES
              <span style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem', background: 'rgba(0, 240, 255, 0.15)', border: '1px solid #00f0ff', color: '#00f0ff', borderRadius: '0.25rem' }}>
                {tools.length} MODULES ARMED
              </span>
            </h3>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
              TOOL MASTERY & RANKINGS TRACKED LIVE ACROSS AGENT & MANUAL INVOCATIONS
            </p>
          </div>
        </div>

        {/* Sort by Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span className="font-title" style={{ fontSize: '0.7rem', color: '#64748b' }}>SORT:</span>
          <button
            onClick={() => { sfx.playTapSound(); setSortBy('rank'); }}
            style={{
              background: sortBy === 'rank' ? '#0284c7' : '#0a0f1a',
              color: sortBy === 'rank' ? '#ffffff' : '#94a3b8',
              border: `1px solid ${sortBy === 'rank' ? '#38bdf8' : '#1e2c45'}`,
              borderRadius: '0.25rem',
              padding: '0.3rem 0.6rem',
              fontSize: '0.7rem',
              cursor: 'pointer'
            }}
          >
            🏆 Rank
          </button>
          <button
            onClick={() => { sfx.playTapSound(); setSortBy('level'); }}
            style={{
              background: sortBy === 'level' ? '#0284c7' : '#0a0f1a',
              color: sortBy === 'level' ? '#ffffff' : '#94a3b8',
              border: `1px solid ${sortBy === 'level' ? '#38bdf8' : '#1e2c45'}`,
              borderRadius: '0.25rem',
              padding: '0.3rem 0.6rem',
              fontSize: '0.7rem',
              cursor: 'pointer'
            }}
          >
            ⚡ Level
          </button>
          <button
            onClick={() => { sfx.playTapSound(); setSortBy('name'); }}
            style={{
              background: sortBy === 'name' ? '#0284c7' : '#0a0f1a',
              color: sortBy === 'name' ? '#ffffff' : '#94a3b8',
              border: `1px solid ${sortBy === 'name' ? '#38bdf8' : '#1e2c45'}`,
              borderRadius: '0.25rem',
              padding: '0.3rem 0.6rem',
              fontSize: '0.7rem',
              cursor: 'pointer'
            }}
          >
            🔤 Name
          </button>
        </div>
      </div>

      {/* Main Grid: Modules List (Left) & Tactical Execution Station (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1.5rem' }}>
        {/* Left Column: Modules List */}
        <div style={{ gridColumn: 'span 5', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* Search Box */}
          <div style={{ position: 'relative' }}>
            <Search style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', width: '1rem', height: '1rem', color: '#00f0ff' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search tactical modules..."
              className="font-mono"
              style={{
                width: '100%',
                boxSizing: 'border-box',
                backgroundColor: '#0a0f1a',
                border: '1px solid #1e2c45',
                borderRadius: '0.375rem',
                padding: '0.6rem 1rem 0.6rem 2.5rem',
                fontSize: '0.8rem',
                color: '#ffffff',
                outline: 'none'
              }}
            />
          </div>

          {/* Module Cards Grid */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', maxHeight: '650px', overflowY: 'auto', paddingRight: '0.25rem' }}>
            {loading ? (
              <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.8rem' }}>
                INITIALIZING MODULE SENSORS...
              </div>
            ) : processedTools.length === 0 ? (
              <div className="font-mono" style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontSize: '0.8rem' }}>
                NO MATCHING TACTICAL MODULES FOUND
              </div>
            ) : (
              processedTools.map(tool => {
                const isSelected = selectedTool?.name === tool.name;
                const stats = ranksMap.get(tool.name) || toolUsageTracker.getToolStats(tool.name);
                const rankNum = stats.rank ?? 99;

                return (
                  <div
                    key={tool.name}
                    onClick={() => handleSelectTool(tool)}
                    className="sc-card"
                    style={{
                      padding: '0.85rem 1rem',
                      borderColor: isSelected ? '#00f0ff' : stats.calls > 0 && rankNum <= 3 ? '#ff9f1c' : '#1e2c45',
                      boxShadow: isSelected ? '0 0 20px rgba(0, 240, 255, 0.35)' : undefined,
                      background: isSelected ? 'linear-gradient(180deg, #16243d 0%, #0c1424 100%)' : undefined
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {/* Rank Badge */}
                        <span className="font-title" style={{
                          fontSize: '10px',
                          padding: '0.125rem 0.4rem',
                          borderRadius: '0.25rem',
                          background: rankNum === 1 ? 'linear-gradient(180deg, #fbbf24, #d97706)' : rankNum === 2 ? 'linear-gradient(180deg, #e2e8f0, #94a3b8)' : rankNum === 3 ? 'linear-gradient(180deg, #fdba74, #ea580c)' : '#0f172a',
                          color: rankNum <= 3 ? '#000000' : '#94a3b8',
                          fontWeight: 700,
                          border: `1px solid ${rankNum <= 3 ? '#fbbf24' : '#334155'}`
                        }}>
                          #{rankNum}
                        </span>

                        <h4 className="font-title" style={{ fontSize: '0.85rem', color: '#ffffff', margin: 0 }}>
                          {tool.name}
                        </h4>
                      </div>

                      {/* Tool Level & Invocations Badge */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                        <span className="font-title" style={{ 
                          fontSize: '10px', 
                          color: stats.level >= 4 ? '#fbbf24' : stats.level >= 3 ? '#a855f7' : stats.level >= 2 ? '#38bdf8' : '#94a3b8',
                          background: 'rgba(0, 0, 0, 0.4)', 
                          padding: '0.15rem 0.45rem', 
                          borderRadius: '0.25rem', 
                          border: `1px solid ${stats.level >= 4 ? '#d97706' : stats.level >= 3 ? '#7e22ce' : stats.level >= 2 ? '#0284c7' : '#334155'}`
                        }}>
                          LVL {stats.level} ({stats.calls} ⚡)
                        </span>
                      </div>
                    </div>

                    <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                      {tool.description || 'Tactical MCP protocol module.'}
                    </p>

                    {/* Tool Level Progress Bar */}
                    <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <div style={{ flex: 1, height: '4px', backgroundColor: '#070a10', borderRadius: '2px', overflow: 'hidden', border: '1px solid #1e2c45' }}>
                        <div style={{ width: `${stats.progressPercent}%`, height: '100%', background: stats.level >= 4 ? 'linear-gradient(90deg, #d97706, #fbbf24)' : 'linear-gradient(90deg, #0284c7, #38bdf8)' }} />
                      </div>
                      <span className="font-mono" style={{ fontSize: '9px', color: '#64748b' }}>
                        {stats.calls}/{stats.nextLevelCalls}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Tactical Execution Station */}
        <div className="hud-panel" style={{ gridColumn: 'span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {selectedTool && selectedStats ? (
            <>
              {/* Selected Module Header with Tool Mastery & Rank */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e2c45', paddingBottom: '0.85rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div style={{
                    padding: '0.5rem',
                    borderRadius: '0.375rem',
                    background: 'rgba(0, 240, 255, 0.12)',
                    border: '1px solid rgba(0, 240, 255, 0.4)',
                    color: '#00f0ff'
                  }}>
                    <Zap style={{ width: '1.25rem', height: '1.25rem' }} />
                  </div>
                  <div>
                    <h3 className="font-title" style={{ fontSize: '1.15rem', color: '#ffffff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      MODULE: {selectedTool.name}
                    </h3>
                    <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
                      {selectedTool.description || 'Target and execute protocol on MCP cluster.'}
                    </p>
                  </div>
                </div>

                {/* Tool Level & Total Invocations Badge */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <div style={{
                      background: 'rgba(251, 191, 36, 0.15)',
                      border: '1px solid rgba(251, 191, 36, 0.4)',
                      borderRadius: '0.375rem',
                      padding: '0.25rem 0.5rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      color: '#fbbf24',
                      fontSize: '0.75rem'
                    }}>
                      <Trophy style={{ width: '0.85rem', height: '0.85rem' }} />
                      <span className="font-title">RANK #{selectedStats.rank ?? 1}</span>
                    </div>
                    <div style={{
                      background: 'rgba(255, 159, 28, 0.15)',
                      border: '1px solid rgba(255, 159, 28, 0.4)',
                      borderRadius: '0.375rem',
                      padding: '0.25rem 0.5rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      color: '#ff9f1c',
                      fontSize: '0.75rem'
                    }}>
                      <Award style={{ width: '0.85rem', height: '0.85rem' }} />
                      <span className="font-title">LVL {selectedStats.level}</span>
                    </div>
                  </div>
                  <span className="font-mono" style={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                    {selectedStats.calls} total invocations ({selectedStats.levelTitle})
                  </span>
                </div>
              </div>

              {/* Sample Execution Reference Panel */}
              <div style={{ backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className="font-title" style={{ fontSize: '0.75rem', color: '#00f0ff' }}>
                    TERMINAL COMMAND SNIPPET
                  </span>
                  <button
                    onClick={() => handleCopy(getSampleCode(selectedTool, 'curl'))}
                    className="font-title"
                    style={{
                      background: '#0284c7',
                      border: '1px solid #38bdf8',
                      borderRadius: '0.25rem',
                      color: '#ffffff',
                      fontSize: '0.7rem',
                      padding: '0.2rem 0.6rem',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem'
                    }}
                  >
                    {copied ? <Check style={{ width: '0.75rem', height: '0.75rem' }} /> : <Copy style={{ width: '0.75rem', height: '0.75rem' }} />}
                    {copied ? 'COPIED!' : 'COPY cURL'}
                  </button>
                </div>
                <pre className="font-mono" style={{ backgroundColor: '#04060a', padding: '0.6rem', borderRadius: '0.25rem', fontSize: '0.7rem', color: '#38bdf8', overflow: 'auto', maxHeight: '6rem', margin: 0 }}>
                  {getSampleCode(selectedTool, 'curl')}
                </pre>
              </div>

              {/* Parameter Form */}
              <div style={{ backgroundColor: '#070a10', border: '1px solid #1e2c45', borderRadius: '0.375rem', padding: '1.25rem' }}>
                <SchemaForm
                  schema={selectedTool.parameters || selectedTool.inputSchema || {}}
                  onSubmit={handleToolExecute}
                  loading={executing}
                />
              </div>

              {/* Execution Results View */}
              {executionResult && (
                <div style={{
                  backgroundColor: executionResult.success ? 'rgba(16, 185, 129, 0.08)' : 'rgba(244, 63, 94, 0.08)',
                  border: `1px solid ${executionResult.success ? '#10b981' : '#f43f5e'}`,
                  borderRadius: '0.375rem',
                  padding: '1.25rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                    <h4 className="font-title" style={{ fontSize: '0.95rem', color: executionResult.success ? '#34d399' : '#fb7185', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {executionResult.success ? <CheckCircle2 style={{ width: '1.15rem', height: '1.15rem' }} /> : <AlertTriangle style={{ width: '1.15rem', height: '1.15rem' }} />}
                      {executionResult.success ? 'PROTOCOL COMPLETED: 200 OK' : 'EXECUTION FAILED'}
                    </h4>
                    {executionDuration && (
                      <span className="font-mono" style={{ fontSize: '0.75rem', color: '#00f0ff', background: '#0a0f1a', padding: '0.2rem 0.5rem', borderRadius: '0.25rem', border: '1px solid #1e2c45' }}>
                        ⏱️ {executionDuration} ms
                      </span>
                    )}
                  </div>

                  <pre className="font-mono" style={{ backgroundColor: '#04060a', padding: '0.75rem', borderRadius: '0.25rem', fontSize: '0.75rem', color: executionResult.success ? '#6ee7b7' : '#fca5a5', overflow: 'auto', maxHeight: '14rem', margin: 0 }}>
                    {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="font-title" style={{ textAlign: 'center', padding: '6rem 0', color: '#64748b' }}>
              <Cpu style={{ width: '2.5rem', height: '2.5rem', margin: '0 auto 0.75rem auto', color: '#1e2c45' }} />
              SELECT A TACTICAL MODULE ON THE LEFT TO ARMED STATION
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
