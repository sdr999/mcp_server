import React, { useEffect, useState } from 'react';
import { Radio, Filter, Pause, Play, Trash2, Zap, AlertTriangle, ShieldCheck } from 'lucide-react';
import { sseManager, TelemetryEvent } from '../../services/sse';

export const NeuralFirehose: React.FC = () => {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [selectedEvent, setSelectedEvent] = useState<TelemetryEvent | null>(null);

  useEffect(() => {
    // Populate from SSE manager history
    setEvents(sseManager.getHistory());

    const unsubscribe = sseManager.subscribe(newEvent => {
      if (!isPaused) {
        setEvents(prev => {
          const updated = [...prev, newEvent];
          return updated.slice(-300); // Circular buffer max 300
        });
      }
    });

    return () => unsubscribe();
  }, [isPaused]);

  const clearFeed = () => {
    setEvents([]);
  };

  const filteredEvents = events.filter(evt => {
    if (filterType === 'all') return true;
    return evt.type === filterType;
  });

  return (
    <div className="space-y-6">
      {/* Control Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 hud-panel p-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Radio className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white tracking-wider flex items-center gap-2">
              NEURAL TELEMETRY STREAM
            </h3>
            <p className="text-xs text-slate-400 font-mono">
              SSE FIREHOSE TELEMETRY FEED (/admin/dashboard/stream)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Filter Dropdown */}
          <div className="flex items-center gap-1.5 bg-slate-900 px-3 py-1.5 rounded border border-slate-700">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <select
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
              className="bg-transparent text-xs text-white font-mono focus:outline-none"
            >
              <option value="all">ALL EVENTS</option>
              <option value="tool_call">TOOL CALLS</option>
              <option value="error">ERRORS</option>
              <option value="status_change">STATUS</option>
              <option value="chaos">CHAOS INJECTION</option>
            </select>
          </div>

          {/* Pause / Resume Button */}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className={`btn-neon-${isPaused ? 'gold' : 'cyan'} text-xs py-1.5 px-3 flex items-center gap-1.5`}
          >
            {isPaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            <span>{isPaused ? 'RESUME' : 'PAUSE'}</span>
          </button>

          {/* Clear Feed */}
          <button
            onClick={clearFeed}
            className="p-2 rounded bg-slate-900 border border-slate-700 text-slate-400 hover:text-rose-400 hover:border-rose-500/40"
            title="Clear Stream History"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Events Feed Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stream List */}
        <div className="lg:col-span-2 hud-panel p-4 space-y-2 max-h-[600px] overflow-y-auto">
          {filteredEvents.length === 0 ? (
            <div className="text-center py-12 text-slate-500 font-mono text-xs">
              Waiting for live SSE stream telemetry events...
            </div>
          ) : (
            filteredEvents.slice().reverse().map(evt => {
              const isError = evt.type === 'error';
              const isChaos = evt.type === 'chaos';
              const isSelected = selectedEvent?.id === evt.id;

              return (
                <div
                  key={evt.id}
                  onClick={() => setSelectedEvent(evt)}
                  className={`p-3 rounded border transition-all cursor-pointer flex items-center justify-between ${
                    isSelected
                      ? 'bg-cyan-950/60 border-cyan-400 shadow-[0_0_12px_rgba(0,240,255,0.2)]'
                      : isError
                      ? 'bg-rose-950/20 border-rose-500/30 hover:border-rose-400'
                      : isChaos
                      ? 'bg-amber-950/20 border-amber-500/30 hover:border-amber-400'
                      : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    {isError ? (
                      <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                    ) : isChaos ? (
                      <Zap className="w-4 h-4 text-amber-400 shrink-0" />
                    ) : (
                      <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
                    )}
                    <div>
                      <div className="text-xs font-bold text-white font-mono flex items-center gap-2">
                        <span>{evt.summary}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono">
                        {new Date(evt.timestamp).toLocaleTimeString()} • ID: {evt.id}
                      </div>
                    </div>
                  </div>

                  <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                    isError ? 'bg-rose-500/20 text-rose-400' : 'bg-cyan-500/20 text-cyan-400'
                  }`}>
                    {evt.type.toUpperCase()}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Selected Event Details Inspector */}
        <div className="hud-panel p-5">
          <h4 className="text-xs font-mono font-bold text-cyan-400 tracking-wider uppercase border-b border-slate-800 pb-2 mb-3">
            TELEMETRY EVENT PAYLOAD INSPECTOR
          </h4>

          {selectedEvent ? (
            <div className="space-y-3 font-mono text-xs">
              <div>
                <span className="text-slate-500">EVENT ID:</span>
                <p className="text-white font-bold">{selectedEvent.id}</p>
              </div>
              <div>
                <span className="text-slate-500">TIMESTAMP:</span>
                <p className="text-cyan-400">{selectedEvent.timestamp}</p>
              </div>
              <div>
                <span className="text-slate-500">TYPE:</span>
                <p className="text-emerald-400 font-bold">{selectedEvent.type}</p>
              </div>
              <div>
                <span className="text-slate-500">RAW PAYLOAD:</span>
                <pre className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-[11px] text-emerald-300 mt-1 overflow-auto max-h-64">
                  {JSON.stringify(selectedEvent.details, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500 font-mono italic text-center py-12">
              Select an event from the firehose feed to inspect its full payload.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
