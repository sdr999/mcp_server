import React, { useEffect, useState } from 'react';
import { Wand2, Search, Play, CheckCircle2, AlertTriangle, Code2, Clock, Copy, Check, Terminal, Sparkles, Flame, Shield } from 'lucide-react';
import { api } from '../../services/api';
import { SchemaForm } from '../common/SchemaForm';
import { sfx } from '../../services/soundEffects';

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
  const [rarityFilter, setRarityFilter] = useState<'ALL' | 'COMMON' | 'RARE' | 'EPIC' | 'LEGENDARY'>('ALL');

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

  const getToolRarity = (tool: any): 'common' | 'rare' | 'epic' | 'legendary' => {
    const name = tool.name?.toLowerCase() || '';
    if (name.includes('weather') || name.includes('gpt') || name.includes('ai') || name.includes('forecast')) return 'legendary';
    if (name.includes('calc') || name.includes('add') || name.includes('crypto') || name.includes('auth')) return 'epic';
    if (name.includes('echo') || name.includes('ping') || name.includes('time') || name.includes('check')) return 'rare';
    return 'common';
  };

  const getToolElixir = (tool: any): number => {
    const rarity = getToolRarity(tool);
    if (rarity === 'legendary') return 5;
    if (rarity === 'epic') return 4;
    if (rarity === 'rare') return 3;
    return 2;
  };

  const getToolEmoji = (tool: any): string => {
    const name = tool.name?.toLowerCase() || '';
    if (name.includes('weather')) return '⚡';
    if (name.includes('calc') || name.includes('add') || name.includes('math')) return '🔮';
    if (name.includes('ping') || name.includes('echo')) return '🏹';
    if (name.includes('ai') || name.includes('prompt')) return '🧙‍♂️';
    if (name.includes('auth') || name.includes('security')) return '🛡️';
    return '🧪';
  };

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

  const filteredTools = tools.filter(t => {
    const matchesSearch = t.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.description?.toLowerCase().includes(searchQuery.toLowerCase());
    const rarity = getToolRarity(t).toUpperCase();
    const matchesRarity = rarityFilter === 'ALL' || rarity === rarityFilter;
    return matchesSearch && matchesRarity;
  });

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Clash Royale Arena Header */}
      <div className="hud-panel" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            padding: '0.65rem',
            borderRadius: '0.75rem',
            background: 'linear-gradient(180deg, #f472b6, #db2777)',
            border: '2px solid #fbcfe8',
            boxShadow: '0 4px 10px rgba(219, 39, 119, 0.4)'
          }}>
            <Wand2 style={{ width: '1.5rem', height: '1.5rem', color: '#ffffff' }} />
          </div>
          <div>
            <h3 className="font-title" style={{ fontSize: '1.2rem', color: '#ffffff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              🃏 BATTLE DECK (TOOL SPELLBOOK)
              <span className="trophy-badge" style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem' }}>
                {tools.length} CARDS IN DECK
              </span>
            </h3>
            <p className="font-game" style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
              SELECT A SPELL CARD • LOAD ELIXIR PARAMETERS • CAST INTO ARENA
            </p>
          </div>
        </div>

        {/* Rarity Filter Tabs */}
        <div style={{ display: 'flex', gap: '0.35rem', background: '#0c172c', padding: '0.25rem', borderRadius: '0.5rem', border: '1px solid #2a3e66' }}>
          {(['ALL', 'COMMON', 'RARE', 'EPIC', 'LEGENDARY'] as const).map(rarity => (
            <button
              key={rarity}
              onClick={() => {
                sfx.playTapSound();
                setRarityFilter(rarity);
              }}
              className="font-title"
              style={{
                fontSize: '0.7rem',
                padding: '0.3rem 0.65rem',
                borderRadius: '0.375rem',
                border: 'none',
                cursor: 'pointer',
                background: rarityFilter === rarity ? '#0284c7' : 'transparent',
                color: rarityFilter === rarity ? '#ffffff' : '#94a3b8',
                boxShadow: rarityFilter === rarity ? '0 2px 4px rgba(0,0,0,0.5)' : 'none'
              }}
            >
              {rarity}
            </button>
          ))}
        </div>
      </div>

      {/* Main Grid: Card Deck (Left) & Spell Cast Workbench (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1.5rem' }}>
        {/* Left Column: Battle Cards Deck */}
        <div style={{ gridColumn: 'span 5', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* Search Box */}
          <div style={{ position: 'relative' }}>
            <Search style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', width: '1rem', height: '1rem', color: '#38bdf8' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search spells, tools, weapons..."
              className="font-game"
              style={{
                width: '100%',
                boxSizing: 'border-box',
                backgroundColor: '#0c172c',
                border: '2px solid #2a3e66',
                borderRadius: '0.625rem',
                padding: '0.6rem 1rem 0.6rem 2.5rem',
                fontSize: '0.85rem',
                color: '#ffffff',
                outline: 'none',
                boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)'
              }}
            />
          </div>

          {/* Card Deck Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem', maxHeight: '650px', overflowY: 'auto', paddingRight: '0.25rem' }}>
            {loading ? (
              <div className="font-title" style={{ gridColumn: 'span 2', textAlign: 'center', padding: '3rem 0', color: '#94a3b8', fontSize: '0.85rem' }}>
                SHUFFLING DECK...
              </div>
            ) : filteredTools.length === 0 ? (
              <div className="font-title" style={{ gridColumn: 'span 2', textAlign: 'center', padding: '3rem 0', color: '#94a3b8', fontSize: '0.85rem' }}>
                NO CARDS FOUND IN THIS ARENA
              </div>
            ) : (
              filteredTools.map(tool => {
                const rarity = getToolRarity(tool);
                const elixir = getToolElixir(tool);
                const emoji = getToolEmoji(tool);
                const isSelected = selectedTool?.name === tool.name;

                return (
                  <div
                    key={tool.name}
                    onClick={() => handleSelectTool(tool)}
                    className={`cr-card cr-card-${rarity}`}
                    style={{
                      padding: '0.85rem',
                      transform: isSelected ? 'translateY(-4px) scale(1.03)' : undefined,
                      borderColor: isSelected ? '#fde047' : undefined,
                      boxShadow: isSelected ? '0 0 20px rgba(253, 224, 71, 0.6)' : undefined
                    }}
                  >
                    {/* Top Badges: Elixir Cost & Rarity Tag */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <div className="elixir-badge" title={`${elixir} Elixir Cost`}>
                        {elixir}
                      </div>
                      <span className="level-badge">
                        LVL 12
                      </span>
                    </div>

                    {/* Card Icon & Artwork Frame */}
                    <div style={{
                      height: '4rem',
                      background: 'radial-gradient(circle, #1e293b 0%, #0c172c 100%)',
                      borderRadius: '0.5rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      border: '1px solid rgba(255,255,255,0.1)',
                      marginBottom: '0.5rem'
                    }}>
                      <span style={{ fontSize: '2rem', filter: 'drop-shadow(0 4px 6px rgba(0,0,0,0.6))' }}>{emoji}</span>
                    </div>

                    {/* Card Title & Rarity */}
                    <h4 className="font-title" style={{ fontSize: '0.85rem', color: '#ffffff', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {tool.name}
                    </h4>
                    <p className="font-game" style={{ fontSize: '0.7rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', minHeight: '2rem' }}>
                      {tool.description || 'Deploys a specialized MCP tool spell.'}
                    </p>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Active Card Cast Workbench */}
        <div className="hud-panel" style={{ gridColumn: 'span 7', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {selectedTool ? (
            <>
              {/* Selected Spell Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '2px solid #2a3e66', paddingBottom: '0.85rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div className="elixir-badge" style={{ width: '2.25rem', height: '2.25rem', fontSize: '1rem' }}>
                    {getToolElixir(selectedTool)}
                  </div>
                  <div>
                    <h3 className="font-title" style={{ fontSize: '1.25rem', color: '#ffffff', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {selectedTool.name}
                      <span className={`level-badge`} style={{ textTransform: 'uppercase' }}>
                        {getToolRarity(selectedTool)} SPELL
                      </span>
                    </h3>
                    <p className="font-game" style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0, marginTop: '0.2rem' }}>
                      {selectedTool.description || 'Target and execute spell on MCP host.'}
                    </p>
                  </div>
                </div>

                <div className="trophy-badge" style={{ fontSize: '0.75rem' }}>
                  ⭐ MASTERY I
                </div>
              </div>

              {/* Sample Execution Reference Panel */}
              <div style={{ backgroundColor: '#0c172c', border: '2px solid #2a3e66', borderRadius: '0.625rem', padding: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className="font-title" style={{ fontSize: '0.75rem', color: '#fde047' }}>
                    ⚡ RUNTIME COMMAND SNIPPET
                  </span>
                  <div style={{ display: 'flex', gap: '0.35rem' }}>
                    <button
                      onClick={() => handleCopy(getSampleCode(selectedTool, 'curl'))}
                      className="font-title"
                      style={{
                        background: '#0284c7',
                        border: '1px solid #38bdf8',
                        borderRadius: '0.375rem',
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
                </div>
                <pre className="font-mono" style={{ backgroundColor: '#070e1e', padding: '0.6rem', borderRadius: '0.375rem', fontSize: '0.7rem', color: '#38bdf8', overflow: 'auto', maxHeight: '6rem', margin: 0 }}>
                  {getSampleCode(selectedTool, 'curl')}
                </pre>
              </div>

              {/* Parameter Form */}
              <div style={{ backgroundColor: '#0c172c', border: '2px solid #2a3e66', borderRadius: '0.625rem', padding: '1.25rem' }}>
                <SchemaForm
                  schema={selectedTool.parameters || selectedTool.inputSchema || {}}
                  onSubmit={handleToolExecute}
                  loading={executing}
                />
              </div>

              {/* Execution Results View */}
              {executionResult && (
                <div style={{
                  backgroundColor: executionResult.success ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                  border: `2px solid ${executionResult.success ? '#22c55e' : '#ef4444'}`,
                  borderRadius: '0.625rem',
                  padding: '1.25rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                    <h4 className="font-title" style={{ fontSize: '1rem', color: executionResult.success ? '#4ade80' : '#f87171', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {executionResult.success ? <CheckCircle2 style={{ width: '1.25rem', height: '1.25rem' }} /> : <AlertTriangle style={{ width: '1.25rem', height: '1.25rem' }} />}
                      {executionResult.success ? 'VICTORY! SPELL CAST SUCCESSFUL' : 'SPELL DEFLECTED (ERROR)'}
                    </h4>
                    {executionDuration && (
                      <span className="font-title" style={{ fontSize: '0.75rem', color: '#fde047', background: '#0c172c', padding: '0.2rem 0.5rem', borderRadius: '0.375rem', border: '1px solid #ca8a04' }}>
                        ⏱️ {executionDuration}ms
                      </span>
                    )}
                  </div>

                  <pre className="font-mono" style={{ backgroundColor: '#070e1e', padding: '0.75rem', borderRadius: '0.5rem', fontSize: '0.75rem', color: executionResult.success ? '#86efac' : '#fca5a5', overflow: 'auto', maxHeight: '14rem', margin: 0 }}>
                    {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="font-title" style={{ textAlign: 'center', padding: '6rem 0', color: '#64748b' }}>
              <span style={{ fontSize: '3rem', display: 'block', marginBottom: '1rem' }}>🃏</span>
              SELECT A SPELL CARD FROM YOUR BATTLE DECK ON THE LEFT
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
