"""Dark-themed responsive Dashboard HTML template."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MCP Tool Server — Live Reliability Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --green: #22c55e;
      --red: #ef4444;
      --amber: #f59e0b;
    }
    body {
      margin: 0;
      padding: 20px;
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    h1 {
      margin-top: 0;
      color: var(--accent);
      font-size: 24px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
      margin-top: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
    }
    .card-title {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 10px;
    }
    .metric-value {
      font-size: 28px;
      font-weight: bold;
      color: var(--text);
    }
    .status-badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: bold;
    }
    .status-closed { background: rgba(34, 197, 94, 0.2); color: var(--green); }
    .status-open { background: rgba(239, 68, 68, 0.2); color: var(--red); }
    .status-halfopen { background: rgba(245, 158, 11, 0.2); color: var(--amber); }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      padding: 8px;
      border-bottom: 1px solid var(--border);
    }
    th { color: var(--text-muted); }
    td.key-col { font-family: monospace; color: var(--accent); font-weight: bold; }
    .error-text { color: var(--red); font-size: 18px; }
  </style>
</head>
<body>
  <h1><span>👁️</span> MCP Live Reliability & Telemetry Dashboard</h1>
  <p style="color: var(--text-muted);">Real-time stream from server event loop. JSON KV endpoint: <a href="/admin/dashboard/json" style="color:var(--accent);">/admin/dashboard/json</a></p>

  <div class="grid">
    <div class="card">
      <div class="card-title">Registered Tools</div>
      <div class="metric-value" id="total_tools">-</div>
    </div>
    <div class="card">
      <div class="card-title">Server Status</div>
      <div class="metric-value" id="server_ready">CONNECTING</div>
    </div>
    <div class="card">
      <div class="card-title">Total Spend (USD)</div>
      <div class="metric-value" id="total_spend">$0.0000</div>
    </div>
    <div class="card">
      <div class="card-title">Chaos Engine</div>
      <div class="metric-value" id="chaos_status">OFF</div>
    </div>
    <div class="card">
      <div class="card-title">Active SSE Clients</div>
      <div class="metric-value" id="sse_clients">- / 10</div>
    </div>
    <div class="card">
      <div class="card-title">Prompt Templates</div>
      <div class="metric-value" id="total_prompts">0</div>
    </div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column: span 2;">
      <div class="card-title">Per-Tool Invocations & Success Rates</div>
      <table>
        <thead>
          <tr>
            <th>Tool Name</th>
            <th>Total Calls</th>
            <th>Successes</th>
            <th>Errors</th>
            <th>Success Rate</th>
          </tr>
        </thead>
        <tbody id="tools_table">
          <tr><td colspan="5">Loading tool execution metrics...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column: span 1;">
      <div class="card-title">Circuit Breaker Status</div>
      <table>
        <thead>
          <tr>
            <th>Breaker Name</th>
            <th>State</th>
            <th>Failures</th>
            <th>Successes</th>
          </tr>
        </thead>
        <tbody id="circuit_table">
          <tr><td colspan="4">No circuit breakers active</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card" style="grid-column: span 1;">
      <div class="card-title">Key-Value System Summary</div>
      <table>
        <thead>
          <tr>
            <th>Property Key</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody id="kv_table">
          <tr><td colspan="2">Loading key-value summary...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const urlParams = new URLSearchParams(window.location.search);
    let token = urlParams.get("token") || localStorage.getItem("mcp_admin_token") || "";
    if (urlParams.get("token")) {
      localStorage.setItem("mcp_admin_token", urlParams.get("token"));
    }

    const evtSource = new EventSource("/admin/dashboard/stream?token=" + encodeURIComponent(token));

    evtSource.onmessage = function(event) {
      const data = JSON.parse(event.data);
      document.getElementById("total_tools").innerText = (data.total_tools !== undefined) ? data.total_tools : "0";
      document.getElementById("server_ready").innerText = data.ready ? "READY" : "LOADING";
      document.getElementById("server_ready").className = "metric-value";
      document.getElementById("total_spend").innerText = "$" + (data.total_spend_usd || 0.0).toFixed(4);
      document.getElementById("chaos_status").innerText = data.chaos_enabled ? "ACTIVE ⚡" : "DISABLED";
      document.getElementById("chaos_status").style.color = data.chaos_enabled ? "var(--amber)" : "var(--text)";
      document.getElementById("sse_clients").innerText = (data.active_sse_clients || 1) + " / 10";
      document.getElementById("total_prompts").innerText = data.total_prompts || "0";

      // Render Per-Tool Execution table
      const toolsTable = document.getElementById("tools_table");
      if (data.tool_metrics && Object.keys(data.tool_metrics).length > 0) {
        toolsTable.innerHTML = "";
        for (const [toolName, m] of Object.entries(data.tool_metrics)) {
          const rate = m.success_rate_percent || 100.0;
          const badgeClass = rate >= 100.0 ? "status-closed" : (rate >= 80.0 ? "status-halfopen" : "status-open");
          toolsTable.innerHTML += '<tr>' +
            '<td class="key-col">' + toolName + '</td>' +
            '<td>' + (m.calls || 0) + '</td>' +
            '<td>' + (m.successes || 0) + '</td>' +
            '<td>' + (m.errors || 0) + '</td>' +
            '<td><span class="status-badge ' + badgeClass + '">' + rate.toFixed(1) + '%</span></td>' +
          '</tr>';
        }
      } else {
        toolsTable.innerHTML = '<tr><td colspan="5">No registered tools or execution metrics recorded yet</td></tr>';
      }

      // Render Circuit Breaker table
      const cbTable = document.getElementById("circuit_table");
      if (data.circuit_breakers && Object.keys(data.circuit_breakers).length > 0) {
        cbTable.innerHTML = "";
        for (const [name, stats] of Object.entries(data.circuit_breakers)) {
          const state = stats.state || "CLOSED";
          const badgeClass = state === "CLOSED" ? "status-closed" : (state === "OPEN" ? "status-open" : "status-halfopen");
          cbTable.innerHTML += '<tr>' +
            '<td>' + name + '</td>' +
            '<td><span class="status-badge ' + badgeClass + '">' + state + '</span></td>' +
            '<td>' + (stats.failure_count || 0) + '</td>' +
            '<td>' + (stats.success_count || 0) + '</td>' +
          '</tr>';
        }
      } else {
        cbTable.innerHTML = '<tr><td colspan="4">No circuit breakers active</td></tr>';
      }

      // Render Key-Value System Summary table
      const kvTable = document.getElementById("kv_table");
      kvTable.innerHTML = "";
      for (const [k, v] of Object.entries(data)) {
        if (k === "circuit_breakers" || k === "tool_metrics" || k === "cost_summary" || k === "chaos_summary") continue;
        const valStr = (typeof v === "object") ? JSON.stringify(v) : String(v);
        kvTable.innerHTML += '<tr>' +
          '<td class="key-col">' + k + '</td>' +
          '<td>' + valStr + '</td>' +
        '</tr>';
      }
    };

    evtSource.onerror = function(err) {
      const statusEl = document.getElementById("server_ready");
      statusEl.innerText = "UNAUTHORIZED / DISCONNECTED";
      statusEl.className = "metric-value error-text";
    };
  </script>
</body>
</html>
"""
