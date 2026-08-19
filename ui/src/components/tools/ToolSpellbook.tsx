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
    <div className="space-y-6">
      {/* Header & Search */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 hud-panel p-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Wand2 className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider">
              SPELLBOOK (MCP TOOL CATALOG)
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              INSPECT & CAST REGISTERED MCP SPELLS (/tools/{'{name}'}/call)
            </p>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search spells by name..."
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
          />
        </div>
      </div>

      {/* Grid: Tools Catalog vs Execution Arena */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Tool Cards Grid */}
        <div className="lg:col-span-5 space-y-3 max-h-[700px] overflow-y-auto pr-1">
          {loading ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              Loading spellbook tools...
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
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
                  className={`hud-panel p-4 cursor-pointer transition-all ${
                    isSelected
                      ? 'border-cyan-400 bg-cyan-950/40 shadow-[0_0_20px_rgba(0,240,255,0.25)]'
                      : 'hover:border-cyan-500/50'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <h4 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                      <Code2 className="w-4 h-4 text-cyan-400" />
                      {t.name}
                    </h4>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400">
                      SPELL
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 line-clamp-2 mt-1">
                    {t.description || 'No description provided.'}
                  </p>
                </div>
              );
            })
          )}
        </div>

        {/* Right Column: Interactive Spell Casting Arena */}
        <div className="lg:col-span-7 hud-panel p-6 space-y-5">
          {selectedTool ? (
            <>
              <div className="border-b border-slate-800 pb-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-black text-white font-mono flex items-center gap-2">
                    <Play className="w-5 h-5 text-cyan-400" />
                    {selectedTool.name}
                  </h3>
                  <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 rounded">
                    +100 EXP REWARD
                  </span>
                </div>
                <p className="text-xs text-slate-300 mt-1">
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
                <div className="space-y-2 pt-4 border-t border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono font-bold uppercase flex items-center gap-2">
                      {executionResult.success ? (
                        <>
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          <span className="text-emerald-400">SPELL CAST SUCCESSFUL</span>
                        </>
                      ) : (
                        <>
                          <AlertTriangle className="w-4 h-4 text-rose-400" />
                          <span className="text-rose-400">SPELL FAILED</span>
                        </>
                      )}
                    </span>
                    {executionDuration && (
                      <span className="text-xs font-mono text-slate-400 flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5 text-cyan-400" />
                        {executionDuration} ms
                      </span>
                    )}
                  </div>

                  <pre className="w-full bg-slate-950 border border-slate-800 rounded p-3 font-mono text-xs text-cyan-300 overflow-auto max-h-72">
                    {JSON.stringify(executionResult.data || executionResult.error, null, 2)}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-20 text-slate-500 font-mono text-sm">
              <Wand2 className="w-12 h-12 text-slate-700 mx-auto mb-3 animate-pulse" />
              Select a spell from the left spellbook catalog to test execution.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
