import os

def replace_in_file(path, old, new):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. RefreshCw
for p in [
    r'd:\python\mcp_server\ui\src\components\analytics\ChaosArena.tsx',
    r'd:\python\mcp_server\ui\src\components\federation\FederationGateways.tsx',
    r'd:\python\mcp_server\ui\src\components\prompts\PromptVault.tsx',
    r'd:\python\mcp_server\ui\src\components\tenancy\GuildCitadel.tsx'
]:
    replace_in_file(p, "className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}", "style={{ width: '0.875rem', height: '0.875rem', animation: loading ? 'spin 1s linear infinite' : 'none' }}")

# 2. ChaosArena Button
ca = r'd:\python\mcp_server\ui\src\components\analytics\ChaosArena.tsx'
replace_in_file(ca,
    "className={`btn-neon-${chaosEnabled ? 'magenta' : 'cyan'} text-xs py-1.5 px-3`}",
    "className={chaosEnabled ? 'btn-neon-magenta' : 'btn-neon-cyan'} style={{ fontSize: '0.75rem', paddingTop: '0.375rem', paddingBottom: '0.375rem', paddingLeft: '0.75rem', paddingRight: '0.75rem' }}"
)

# 3. FederationGateways Row
fg = r'd:\python\mcp_server\ui\src\components\federation\FederationGateways.tsx'
fg_old = """className={`p-3.5 rounded border transition-all cursor-pointer flex items-center justify-between ${
                      isSelected
                        ? 'bg-emerald-950/40 border-emerald-400 shadow-[0_0_15px_rgba(0,255,102,0.15)]'
                        : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                    }`}"""
fg_new = """style={{
                      padding: '0.875rem', borderRadius: '0.25rem', border: '1px solid',
                      borderColor: isSelected ? '#34d399' : '#1e293b',
                      backgroundColor: isSelected ? 'rgba(2, 44, 34, 0.4)' : '#0f172a',
                      boxShadow: isSelected ? '0 0 15px rgba(0,255,102,0.15)' : 'none',
                      transition: 'all 0.3s ease', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                    }}"""
replace_in_file(fg, fg_old, fg_new)

# 4. GuildCitadel Badge
gc = r'd:\python\mcp_server\ui\src\components\tenancy\GuildCitadel.tsx'
gc_old = """className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  g.effect === 'deny' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'
                }`}"""
gc_new = """className="font-mono" style={{
                  fontSize: '10px', fontWeight: '700', paddingLeft: '0.5rem', paddingRight: '0.5rem', paddingTop: '0.125rem', paddingBottom: '0.125rem', borderRadius: '0.25rem',
                  backgroundColor: g.effect === 'deny' ? 'rgba(244, 63, 94, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                  color: g.effect === 'deny' ? '#fb7185' : '#34d399'
                }}"""
replace_in_file(gc, gc_old, gc_new)

print('Dynamic classes replaced.')
