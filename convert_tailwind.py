import os
import re

def tailwind_to_style(cls_str):
    styles = {}
    classes_to_keep = []
    
    keep_list = {'hud-panel', 'hud-panel-magenta', 'hud-panel-gold', 'btn-neon-cyan', 'btn-neon-magenta', 'badge-neon', 'badge-ok', 'badge-error', 'badge-warning', 'font-title', 'font-mono'}
    
    for cls in cls_str.split():
        if cls in keep_list:
            classes_to_keep.append(cls)
            continue
            
        # Display
        if cls == 'flex': styles['display'] = 'flex'
        elif cls == 'grid': styles['display'] = 'grid'
        elif cls == 'hidden': styles['display'] = 'none'
        elif cls == 'block': styles['display'] = 'block'
        
        # Flex/Grid
        elif cls == 'items-center': styles['alignItems'] = 'center'
        elif cls == 'justify-between': styles['justifyContent'] = 'space-between'
        elif cls == 'justify-center': styles['justifyContent'] = 'center'
        elif cls.startswith('gap-'):
            val = cls.split('-')[1]
            styles['gap'] = f'{float(val)*0.25}rem' if val.replace('.','',1).isdigit() else val
        elif cls == 'grid-cols-1': styles['gridTemplateColumns'] = 'repeat(1, minmax(0, 1fr))'
        elif cls == 'lg:grid-cols-12': styles['gridTemplateColumns'] = 'repeat(12, minmax(0, 1fr))'
        elif cls == 'lg:grid-cols-3': styles['gridTemplateColumns'] = 'repeat(3, minmax(0, 1fr))'
        elif cls == 'lg:grid-cols-2': styles['gridTemplateColumns'] = 'repeat(2, minmax(0, 1fr))'
        elif cls == 'lg:col-span-5': styles['gridColumn'] = 'span 5 / span 5'
        elif cls == 'lg:col-span-7': styles['gridColumn'] = 'span 7 / span 7'
        elif cls == 'flex-1': styles['flex'] = '1 1 0%'
        
        # Spacing
        elif cls.startswith('p-'): styles['padding'] = f'{float(cls.split("-")[1])*0.25}rem' if cls.split('-')[1].replace('.','',1).isdigit() else '1rem'
        elif cls.startswith('px-'): styles['paddingLeft'] = styles['paddingRight'] = f'{float(cls.split("-")[1])*0.25}rem' if cls.split('-')[1].replace('.','',1).isdigit() else '1rem'
        elif cls.startswith('py-'): styles['paddingTop'] = styles['paddingBottom'] = f'{float(cls.split("-")[1])*0.25}rem' if cls.split('-')[1].replace('.','',1).isdigit() else '1rem'
        elif cls.startswith('pt-'): styles['paddingTop'] = f'{float(cls.split("-")[1])*0.25}rem'
        elif cls.startswith('pb-'): styles['paddingBottom'] = f'{float(cls.split("-")[1])*0.25}rem'
        elif cls.startswith('mb-'): styles['marginBottom'] = f'{float(cls.split("-")[1])*0.25}rem'
        elif cls.startswith('mt-'): styles['marginTop'] = f'{float(cls.split("-")[1])*0.25}rem'
        elif cls == 'space-y-6':
            styles['display'] = 'flex'; styles['flexDirection'] = 'column'; styles['gap'] = '1.5rem'
        elif cls == 'space-y-4': styles['display'] = 'flex'; styles['flexDirection'] = 'column'; styles['gap'] = '1rem'
        elif cls == 'space-y-3': styles['display'] = 'flex'; styles['flexDirection'] = 'column'; styles['gap'] = '0.75rem'
        elif cls == 'space-y-2': styles['display'] = 'flex'; styles['flexDirection'] = 'column'; styles['gap'] = '0.5rem'
        elif cls == 'space-y-1.5': styles['display'] = 'flex'; styles['flexDirection'] = 'column'; styles['gap'] = '0.375rem'
        
        # Sizing
        elif cls == 'w-full': styles['width'] = '100%'
        elif cls == 'w-5': styles['width'] = '1.25rem'
        elif cls == 'h-5': styles['height'] = '1.25rem'
        elif cls == 'w-4': styles['width'] = '1rem'
        elif cls == 'h-4': styles['height'] = '1rem'
        elif cls == 'w-3.5': styles['width'] = '0.875rem'
        elif cls == 'h-3.5': styles['height'] = '0.875rem'
        elif cls == 'w-6': styles['width'] = '1.5rem'
        elif cls == 'h-6': styles['height'] = '1.5rem'
        elif cls == 'h-64': styles['height'] = '16rem'
        elif cls == 'max-h-40': styles['maxHeight'] = '10rem'
        elif cls == 'max-h-64': styles['maxHeight'] = '16rem'
        elif cls == 'max-h-[500px]': styles['maxHeight'] = '500px'
        
        # Typography
        elif cls == 'text-xs': styles['fontSize'] = '0.75rem'
        elif cls == 'text-sm': styles['fontSize'] = '0.875rem'
        elif cls == 'text-base': styles['fontSize'] = '1rem'
        elif cls == 'text-[10px]': styles['fontSize'] = '10px'
        elif cls == 'text-[11px]': styles['fontSize'] = '11px'
        elif cls == 'font-bold': styles['fontWeight'] = '700'
        elif cls == 'font-black': styles['fontWeight'] = '900'
        elif cls == 'tracking-wider': styles['letterSpacing'] = '0.05em'
        elif cls == 'tracking-widest': styles['letterSpacing'] = '0.1em'
        elif cls == 'uppercase': styles['textTransform'] = 'uppercase'
        elif cls == 'text-center': styles['textAlign'] = 'center'
        elif cls == 'text-right': styles['textAlign'] = 'right'
        elif cls == 'italic': styles['fontStyle'] = 'italic'
        elif cls == 'line-clamp-1': styles['WebkitLineClamp'] = '1'; styles['display'] = '-webkit-box'; styles['WebkitBoxOrient'] = 'vertical'; styles['overflow'] = 'hidden'
        elif cls == 'line-clamp-3': styles['WebkitLineClamp'] = '3'; styles['display'] = '-webkit-box'; styles['WebkitBoxOrient'] = 'vertical'; styles['overflow'] = 'hidden'
        
        # Colors
        elif cls == 'text-white': styles['color'] = '#ffffff'
        elif cls == 'text-slate-300': styles['color'] = '#cbd5e1'
        elif cls == 'text-slate-400': styles['color'] = '#94a3b8'
        elif cls == 'text-slate-500': styles['color'] = '#64748b'
        elif cls == 'text-emerald-400': styles['color'] = '#34d399'
        elif cls == 'text-cyan-400': styles['color'] = '#22d3ee'
        elif cls == 'text-cyan-300': styles['color'] = '#67e8f9'
        elif cls == 'text-purple-400': styles['color'] = '#c084fc'
        elif cls == 'text-amber-400': styles['color'] = '#fbbf24'
        elif cls == 'text-rose-400': styles['color'] = '#fb7185'
        
        elif cls == 'bg-slate-950': styles['backgroundColor'] = '#020617'
        elif cls == 'bg-slate-900': styles['backgroundColor'] = '#0f172a'
        elif cls == 'bg-emerald-500/10': styles['backgroundColor'] = 'rgba(16, 185, 129, 0.1)'
        elif cls == 'bg-cyan-500/10': styles['backgroundColor'] = 'rgba(6, 182, 212, 0.1)'
        elif cls == 'bg-purple-500/10': styles['backgroundColor'] = 'rgba(168, 85, 247, 0.1)'
        elif cls == 'bg-rose-500/10': styles['backgroundColor'] = 'rgba(244, 63, 94, 0.1)'
        elif cls == 'bg-cyan-950/60': styles['backgroundColor'] = 'rgba(8, 51, 68, 0.6)'
        elif cls == 'bg-emerald-950/40': styles['backgroundColor'] = 'rgba(2, 44, 34, 0.4)'
        elif cls == 'bg-amber-500/20': styles['backgroundColor'] = 'rgba(245, 158, 11, 0.2)'
        elif cls == 'bg-rose-500/20': styles['backgroundColor'] = 'rgba(244, 63, 94, 0.2)'
        elif cls == 'bg-emerald-500/20': styles['backgroundColor'] = 'rgba(16, 185, 129, 0.2)'
        
        # Borders
        elif cls == 'border': styles['border'] = '1px solid #1e293b'
        elif cls == 'border-b': styles['borderBottom'] = '1px solid #1e293b'
        elif cls == 'border-slate-800': styles['borderColor'] = '#1e293b'
        elif cls == 'border-slate-700': styles['borderColor'] = '#334155'
        elif cls == 'border-emerald-500/30': styles['borderColor'] = 'rgba(16, 185, 129, 0.3)'
        elif cls == 'border-cyan-500/30': styles['borderColor'] = 'rgba(6, 182, 212, 0.3)'
        elif cls == 'border-cyan-500/40': styles['borderColor'] = 'rgba(6, 182, 212, 0.4)'
        elif cls == 'border-purple-500/30': styles['borderColor'] = 'rgba(168, 85, 247, 0.3)'
        elif cls == 'border-rose-500/30': styles['borderColor'] = 'rgba(244, 63, 94, 0.3)'
        elif cls == 'border-rose-500/40': styles['borderColor'] = 'rgba(244, 63, 94, 0.4)'
        elif cls == 'border-amber-500/40': styles['borderColor'] = 'rgba(245, 158, 11, 0.4)'
        
        # Radius
        elif cls == 'rounded': styles['borderRadius'] = '0.25rem'
        elif cls == 'rounded-lg': styles['borderRadius'] = '0.5rem'
        elif cls == 'rounded-full': styles['borderRadius'] = '9999px'
        
        # Effects
        elif cls == 'overflow-hidden': styles['overflow'] = 'hidden'
        elif cls == 'overflow-y-auto': styles['overflowY'] = 'auto'
        elif cls == 'cursor-pointer': styles['cursor'] = 'pointer'
        elif cls == 'transition-all': styles['transition'] = 'all 0.3s ease'
        elif cls == 'shadow-[0_0_15px_rgba(0,255,102,0.15)]': styles['boxShadow'] = '0 0 15px rgba(0,255,102,0.15)'
        elif cls == 'focus:outline-none': pass
        elif cls == 'focus:border-cyan-400': pass
        
    return classes_to_keep, styles

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Find all className="..."
    def replacer(match):
        cls_str = match.group(1)
        classes, styles = tailwind_to_style(cls_str)
        
        res = ''
        if classes:
            res += f'className="{ " ".join(classes) }"'
        if styles:
            style_str = ", ".join(f"{k}: '{v}'" if isinstance(v, str) else f"{k}: {v}" for k, v in styles.items())
            if res:
                res += f' style={{{{{style_str}}}}}'
            else:
                res = f'style={{{{{style_str}}}}}'
            
        return res

    # regex to match simple className="..."
    content = re.sub(r'className=\"([^\"]+)\"', replacer, content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

files = [
    r"d:\python\mcp_server\ui\src\components\federation\FederationGateways.tsx",
    r"d:\python\mcp_server\ui\src\components\tenancy\GuildCitadel.tsx",
    r"d:\python\mcp_server\ui\src\components\analytics\ChaosArena.tsx",
    r"d:\python\mcp_server\ui\src\components\prompts\PromptVault.tsx"
]

for f in files:
    process_file(f)
print('Done!')
