// src/services/toolUsageTracker.ts
// Tracks per-tool usage, mastery levels, and cluster rankings across agent & manual executions

export interface ToolMastery {
  name: string;
  calls: number;
  level: number;
  levelTitle: string;
  nextLevelCalls: number;
  progressPercent: number;
  lastUsed?: string;
  lastDurationMs?: number;
  rank?: number;
}

class ToolUsageTracker {
  private usageMap: Record<string, { calls: number; lastUsed: string; lastDurationMs?: number }> = {};
  private listeners: (() => void)[] = [];

  constructor() {
    this.loadFromStorage();
  }

  private loadFromStorage() {
    try {
      const raw = localStorage.getItem('mcp_tool_usage_stats');
      if (raw) {
        this.usageMap = JSON.parse(raw);
      }
    } catch (e) {
      this.usageMap = {};
    }
  }

  private saveToStorage() {
    try {
      localStorage.setItem('mcp_tool_usage_stats', JSON.stringify(this.usageMap));
    } catch (e) {}
  }

  public recordUsage(toolName: string, durationMs?: number) {
    if (!toolName) return;
    const cleanName = toolName.trim();
    if (!this.usageMap[cleanName]) {
      this.usageMap[cleanName] = { calls: 0, lastUsed: new Date().toISOString() };
    }
    this.usageMap[cleanName].calls += 1;
    this.usageMap[cleanName].lastUsed = new Date().toISOString();
    if (durationMs !== undefined) {
      this.usageMap[cleanName].lastDurationMs = durationMs;
    }
    this.saveToStorage();
    this.notify();
  }

  public getToolStats(toolName: string, rank?: number): ToolMastery {
    const cleanName = toolName?.trim() || '';
    const entry = this.usageMap[cleanName] || { calls: 0, lastUsed: '' };
    const calls = entry.calls;

    let level = 1;
    let levelTitle = 'Operational';
    let prevThreshold = 0;
    let nextThreshold = 3;

    if (calls >= 50) {
      level = 5;
      levelTitle = 'Elite Protocol';
      prevThreshold = 50;
      nextThreshold = 100;
    } else if (calls >= 25) {
      level = 4;
      levelTitle = 'Mastered';
      prevThreshold = 25;
      nextThreshold = 50;
    } else if (calls >= 10) {
      level = 3;
      levelTitle = 'Hardened';
      prevThreshold = 10;
      nextThreshold = 25;
    } else if (calls >= 3) {
      level = 2;
      levelTitle = 'Active Strike';
      prevThreshold = 3;
      nextThreshold = 10;
    } else {
      level = 1;
      levelTitle = 'Operational';
      prevThreshold = 0;
      nextThreshold = 3;
    }

    const progressPercent = Math.min(
      Math.max(Math.round(((calls - prevThreshold) / (nextThreshold - prevThreshold)) * 100), 0),
      100
    );

    return {
      name: cleanName,
      calls,
      level,
      levelTitle,
      nextLevelCalls: nextThreshold,
      progressPercent,
      lastUsed: entry.lastUsed,
      lastDurationMs: entry.lastDurationMs,
      rank
    };
  }

  public getTotalCalls(): number {
    return Object.values(this.usageMap).reduce((acc, curr) => acc + (curr.calls || 0), 0);
  }

  public getRankedTools(allToolNames: string[] = []): ToolMastery[] {
    // Combine all known tool names
    const namesSet = new Set([...allToolNames, ...Object.keys(this.usageMap)]);
    const list: ToolMastery[] = [];

    namesSet.forEach(name => {
      list.push(this.getToolStats(name));
    });

    // Sort descending by calls, then name
    list.sort((a, b) => {
      if (b.calls !== a.calls) return b.calls - a.calls;
      return a.name.localeCompare(b.name);
    });

    // Assign rank 1-indexed
    return list.map((item, idx) => ({
      ...item,
      rank: idx + 1
    }));
  }

  public getTopRankedTool(allToolNames: string[] = []): ToolMastery | null {
    const ranked = this.getRankedTools(allToolNames);
    return ranked.length > 0 && ranked[0].calls > 0 ? ranked[0] : null;
  }

  public subscribe(cb: () => void) {
    this.listeners.push(cb);
    return () => {
      this.listeners = this.listeners.filter(l => l !== cb);
    };
  }

  private notify() {
    this.listeners.forEach(cb => cb());
  }
}

export const toolUsageTracker = new ToolUsageTracker();
