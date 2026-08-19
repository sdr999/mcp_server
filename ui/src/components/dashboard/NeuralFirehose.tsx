import React, { useEffect, useState } from 'react';
import { Radio, Filter, Pause, Play, Trash2, Zap, AlertTriangle, ShieldCheck } from 'lucide-react';
import { sseManager, TelemetryEvent } from '../../services/sse';

export const NeuralFirehose: React.FC = () => {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [selectedEvent, setSelectedEvent] = useState<TelemetryEvent | null>(null);

  useEffect(() => {
    setEvents(sseManager.getHistory());

    const unsubscribe = sseManager.subscribe(newEvent => {
      if (!isPaused) {
        setEvents(prev => {
          const updated = [...prev, newEvent];
          return updated.slice(-300);
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Control Bar */}
      <div className="hud-panel" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', padding: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', borderRadius: '0.5rem', backgroundColor: 'rgba(6, 182, 212, 0.1)', border: '1px solid rgba(6, 182, 212, 0.3)', color: '#22d3ee' }}>
            <Radio style={{ width: '1.25rem', height: '1.25rem' }} />
          </div>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              NEURAL TELEMETRY STREAM
            </h3>
            <p style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'var(--font-mono)', margin: '0.25rem 0 0 0' }}>
              SSE FIREHOSE TELEMETRY FEED (/admin/dashboard/stream)
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {/* Filter Dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', backgroundColor: '#0f172a', padding: '0.375rem 0.75rem', borderRadius: '0.25rem', border: '1px solid #334155' }}>
            <Filter style={{ width: '0.875rem', height: '0.875rem', color: '#94a3b8' }} />
            <select
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
              style={{ backgroundColor: 'transparent', fontSize: '0.75rem', color: '#ffffff', fontFamily: 'var(--font-mono)', outline: 'none', border: 'none' }}
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
            className={isPaused ? "btn-neon-gold" : "btn-neon-cyan"}
            style={{ fontSize: '0.75rem', padding: '0.375rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}
          >
            {isPaused ? <Play style={{ width: '0.875rem', height: '0.875rem' }} /> : <Pause style={{ width: '0.875rem', height: '0.875rem' }} />}
            <span>{isPaused ? 'RESUME' : 'PAUSE'}</span>
          </button>

          {/* Clear Feed */}
          <button
            onClick={clearFeed}
            style={{ padding: '0.5rem', borderRadius: '0.25rem', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#94a3b8', cursor: 'pointer', outline: 'none' }}
            title="Clear Stream History"
            onMouseOver={(e) => { e.currentTarget.style.color = '#fb7185'; e.currentTarget.style.borderColor = 'rgba(244, 63, 94, 0.4)'; }}
            onMouseOut={(e) => { e.currentTarget.style.color = '#94a3b8'; e.currentTarget.style.borderColor = '#334155'; }}
          >
            <Trash2 style={{ width: '1rem', height: '1rem' }} />
          </button>
        </div>
      </div>

      {/* Events Feed Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
        {/* Stream List */}
        <div className="hud-panel" style={{ gridColumn: 'span 2', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '600px', overflowY: 'auto' }}>
          {filteredEvents.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3rem 0', color: '#64748b', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
              Waiting for live SSE stream telemetry events...
            </div>
          ) : (
            filteredEvents.slice().reverse().map(evt => {
              const isError = evt.type === 'error';
              const isChaos = evt.type === 'chaos';
              const isSelected = selectedEvent?.id === evt.id;

              let itemStyle: React.CSSProperties = {
                padding: '0.75rem',
                borderRadius: '0.25rem',
                border: '1px solid',
                transition: 'all 0.2s ease',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              };

              if (isSelected) {
                itemStyle = { ...itemStyle, backgroundColor: 'rgba(8, 51, 68, 0.6)', borderColor: '#22d3ee', boxShadow: '0 0 12px rgba(0,240,255,0.2)' };
              } else if (isError) {
                itemStyle = { ...itemStyle, backgroundColor: 'rgba(76, 5, 25, 0.2)', borderColor: 'rgba(244, 63, 94, 0.3)' };
              } else if (isChaos) {
                itemStyle = { ...itemStyle, backgroundColor: 'rgba(69, 26, 3, 0.2)', borderColor: 'rgba(245, 158, 11, 0.3)' };
              } else {
                itemStyle = { ...itemStyle, backgroundColor: 'rgba(15, 23, 42, 0.5)', borderColor: '#1e293b' };
              }

              return (
                <div
                  key={evt.id}
                  onClick={() => setSelectedEvent(evt)}
                  style={itemStyle}
                  onMouseOver={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.borderColor = isError ? '#fb7185' : isChaos ? '#fbbf24' : '#334155';
                    }
                  }}
                  onMouseOut={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.borderColor = isError ? 'rgba(244, 63, 94, 0.3)' : isChaos ? 'rgba(245, 158, 11, 0.3)' : '#1e293b';
                    }
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    {isError ? (
                      <AlertTriangle style={{ width: '1rem', height: '1rem', color: '#fb7185', flexShrink: 0 }} />
                    ) : isChaos ? (
                      <Zap style={{ width: '1rem', height: '1rem', color: '#fbbf24', flexShrink: 0 }} />
                    ) : (
                      <ShieldCheck style={{ width: '1rem', height: '1rem', color: '#22d3ee', flexShrink: 0 }} />
                    )}
                    <div>
                      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#ffffff', fontFamily: 'var(--font-mono)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>{evt.summary}</span>
                      </div>
                      <div style={{ fontSize: '10px', color: '#94a3b8', fontFamily: 'var(--font-mono)', marginTop: '0.125rem' }}>
                        {new Date(evt.timestamp).toLocaleTimeString()} • ID: {evt.id}
                      </div>
                    </div>
                  </div>

                  <span style={{
                    fontSize: '10px', fontFamily: 'var(--font-mono)', fontWeight: 700, padding: '0.125rem 0.5rem', borderRadius: '0.25rem',
                    backgroundColor: isError ? 'rgba(244, 63, 94, 0.2)' : 'rgba(6, 182, 212, 0.2)',
                    color: isError ? '#fb7185' : '#22d3ee'
                  }}>
                    {evt.type.toUpperCase()}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Selected Event Details Inspector */}
        <div className="hud-panel" style={{ padding: '1.25rem' }}>
          <h4 style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#22d3ee', letterSpacing: '0.05em', textTransform: 'uppercase', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem', marginBottom: '0.75rem', margin: 0 }}>
            TELEMETRY EVENT PAYLOAD INSPECTOR
          </h4>

          {selectedEvent ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
              <div>
                <span style={{ color: '#64748b' }}>EVENT ID:</span>
                <p style={{ color: '#ffffff', fontWeight: 700, margin: '0.125rem 0 0 0' }}>{selectedEvent.id}</p>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>TIMESTAMP:</span>
                <p style={{ color: '#22d3ee', margin: '0.125rem 0 0 0' }}>{selectedEvent.timestamp}</p>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>TYPE:</span>
                <p style={{ color: '#34d399', fontWeight: 700, margin: '0.125rem 0 0 0' }}>{selectedEvent.type}</p>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>RAW PAYLOAD:</span>
                <pre style={{ width: '100%', backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.25rem', padding: '0.5rem', fontSize: '11px', color: '#6ee7b7', marginTop: '0.25rem', overflow: 'auto', maxHeight: '16rem', boxSizing: 'border-box' }}>
                  {JSON.stringify(selectedEvent.details, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <p style={{ fontSize: '0.75rem', color: '#64748b', fontFamily: 'var(--font-mono)', fontStyle: 'italic', textAlign: 'center', padding: '3rem 0', margin: 0 }}>
              Select an event from the firehose feed to inspect its full payload.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
