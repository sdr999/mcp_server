export interface TelemetryEvent {
  id: string;
  timestamp: string;
  type: string; // 'tool_call' | 'error' | 'status_change' | 'onboard' | 'chaos'
  summary: string;
  details?: any;
}

export class SSEManager {
  private eventSource: EventSource | null = null;
  private listeners: ((event: TelemetryEvent) => void)[] = [];
  private ringBuffer: TelemetryEvent[] = [];
  private maxBufferSize = 500;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private isConnected = false;

  constructor(private url: string = '/admin/dashboard/stream') {}

  public connect() {
    if (this.eventSource) return;

    const token = localStorage.getItem('mcp_token');
    const fullUrl = token ? `${this.url}?token=${encodeURIComponent(token)}` : this.url;

    try {
      this.eventSource = new EventSource(fullUrl);

      this.eventSource.onopen = () => {
        this.isConnected = true;
        this.reconnectDelay = 1000;
      };

      this.eventSource.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data);
          const telemetryEvent: TelemetryEvent = {
            id: raw.id || `evt-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
            timestamp: raw.timestamp || new Date().toISOString(),
            type: raw.type || 'tool_call',
            summary: raw.summary || raw.message || JSON.stringify(raw),
            details: raw
          };

          // Ring buffer management
          if (this.ringBuffer.length >= this.maxBufferSize) {
            this.ringBuffer.shift();
          }
          this.ringBuffer.push(telemetryEvent);

          // Notify subscribers
          this.listeners.forEach(cb => cb(telemetryEvent));
        } catch (parseErr) {
          console.error('Failed to parse SSE event', parseErr);
        }
      };

      this.eventSource.onerror = () => {
        this.isConnected = false;
        this.disconnect();
        // Exponential backoff reconnect
        setTimeout(() => {
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
          this.connect();
        }, this.reconnectDelay);
      };
    } catch (e) {
      console.error('Failed to instantiate EventSource', e);
    }
  }

  public disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      this.isConnected = false;
    }
  }

  public subscribe(callback: (event: TelemetryEvent) => void) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter(cb => cb !== callback);
    };
  }

  public getHistory(): TelemetryEvent[] {
    return [...this.ringBuffer];
  }

  public getStatus(): boolean {
    return this.isConnected;
  }
}

export const sseManager = new SSEManager();
