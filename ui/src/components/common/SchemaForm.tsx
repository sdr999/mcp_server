import React, { useState } from 'react';

interface SchemaFormProps {
  schema: any;
  onSubmit: (formData: any) => void;
  loading?: boolean;
}

export const SchemaForm: React.FC<SchemaFormProps> = ({ schema, onSubmit, loading }) => {
  const properties = schema?.properties || schema?.parameters?.properties || schema?.inputSchema?.properties || {};
  const requiredFields: string[] = schema?.required || schema?.parameters?.required || schema?.inputSchema?.required || [];
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [rawJsonMode, setRawJsonMode] = useState(false);
  const [rawJsonStr, setRawJsonStr] = useState('{}');
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Helper to generate sample arguments dictionary from schema
  const generateSampleArgs = React.useCallback(() => {
    const props = schema?.properties || schema?.parameters?.properties || schema?.inputSchema?.properties || {};
    const args: Record<string, any> = {};
    Object.entries(props).forEach(([key, prop]: [string, any]) => {
      if (prop.default !== undefined) {
        args[key] = prop.default;
      } else if (prop.enum && prop.enum.length > 0) {
        args[key] = prop.enum[0];
      } else if (prop.type === 'number' || prop.type === 'integer') {
        args[key] = key === 'a' ? 1 : key === 'b' ? 2 : 10;
      } else if (prop.type === 'boolean') {
        args[key] = true;
      } else if (prop.type === 'array') {
        args[key] = ["sample_item"];
      } else {
        args[key] = `sample_${key}`;
      }
    });
    return args;
  }, [schema]);

  // Pre-fill form data and raw JSON on schema change
  React.useEffect(() => {
    const samples = generateSampleArgs();
    setFormData(samples);
    setRawJsonStr(JSON.stringify({ arguments: samples }, null, 2));
  }, [schema, generateSampleArgs]);

  const handleChange = (key: string, value: any) => {
    setFormData(prev => {
      const updated = { ...prev, [key]: value };
      setRawJsonStr(JSON.stringify({ arguments: updated }, null, 2));
      return updated;
    });
  };

  const handleRawJsonToggle = () => {
    if (!rawJsonMode) {
      // Switching to Raw JSON mode -> sync current formData into {"arguments": formData}
      const currentArgs = Object.keys(formData).length > 0 ? formData : generateSampleArgs();
      setRawJsonStr(JSON.stringify({ arguments: currentArgs }, null, 2));
    } else {
      // Switching back to Form Controls -> attempt parsing arguments from raw JSON
      try {
        const parsed = JSON.parse(rawJsonStr);
        const args = parsed.arguments || parsed;
        if (typeof args === 'object' && args !== null) {
          setFormData(args);
        }
      } catch (e) {}
    }
    setRawJsonMode(!rawJsonMode);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (rawJsonMode) {
      try {
        const parsed = JSON.parse(rawJsonStr);
        setJsonError(null);
        // Extract arguments if wrapped in {"arguments": ...}
        const finalArgs = (parsed && typeof parsed === 'object' && 'arguments' in parsed)
          ? parsed.arguments
          : parsed;
        onSubmit(finalArgs);
      } catch (err: any) {
        setJsonError('Invalid JSON format: ' + err.message);
      }
    } else {
      onSubmit(formData);
    }
  };

  const propertyKeys = Object.keys(properties);

  const inputStyle = {
    width: '100%',
    backgroundColor: '#0f172a',
    border: '1px solid #334155',
    borderRadius: '0.25rem',
    padding: '0.5rem 0.75rem',
    fontSize: '0.75rem',
    color: '#ffffff',
    outline: 'none',
    fontFamily: 'var(--font-mono)',
    boxSizing: 'border-box' as const
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid #1e293b' }}>
        <h4 style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.05em', color: '#22d3ee', textTransform: 'uppercase', fontFamily: 'var(--font-mono)', margin: 0 }}>
          TOOL PARAMETER INPUTS {rawJsonMode ? '(RAW JSON PAYLOAD)' : '(FORM CONTROLS)'}
        </h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            type="button"
            onClick={() => {
              const samples = generateSampleArgs();
              setFormData(samples);
              setRawJsonStr(JSON.stringify({ arguments: samples }, null, 2));
            }}
            style={{ fontSize: '11px', color: '#34d399', textDecoration: 'none', fontFamily: 'var(--font-mono)', background: 'rgba(52, 211, 153, 0.1)', border: '1px solid rgba(52, 211, 153, 0.3)', borderRadius: '0.25rem', padding: '0.15rem 0.5rem', cursor: 'pointer' }}
          >
            ⚡ Load Sample Values
          </button>
          <button
            type="button"
            onClick={handleRawJsonToggle}
            style={{ fontSize: '11px', color: '#94a3b8', textDecoration: 'underline', fontFamily: 'var(--font-mono)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            {rawJsonMode ? 'Switch to Form Controls' : 'Switch to Raw JSON'}
          </button>
        </div>
      </div>

      {rawJsonMode ? (
        <div>
          <div className="font-mono" style={{ fontSize: '0.7rem', color: '#64748b', marginBottom: '0.25rem' }}>
            Auto-formatted POST body: <code style={{ color: '#00f0ff' }}>{'{ "arguments": { ... } }'}</code>
          </div>
          <textarea
            value={rawJsonStr}
            onChange={e => setRawJsonStr(e.target.value)}
            rows={8}
            style={{ ...inputStyle, minHeight: '8rem', color: '#34d399' }}
            placeholder='{\n  "arguments": {\n    "param1": "value"\n  }\n}'
          />
          {jsonError && <p style={{ fontSize: '0.75rem', color: '#fb7185', marginTop: '0.25rem', fontFamily: 'var(--font-mono)', margin: '0.25rem 0 0 0' }}>{jsonError}</p>}
        </div>
      ) : propertyKeys.length === 0 ? (
        <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontStyle: 'italic', padding: '0.5rem 0', fontFamily: 'var(--font-mono)' }}>
          No parameters required for this tool.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {propertyKeys.map(key => {
            const prop = properties[key];
            const isRequired = requiredFields.includes(key);
            const propType = prop.type || 'string';

            return (
              <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#cbd5e1', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'var(--font-mono)' }}>
                  <span>
                    {key} {isRequired && <span style={{ color: '#fb7185' }}>*</span>}
                  </span>
                  <span style={{ fontSize: '10px', color: '#64748b', fontWeight: 400 }}>({propType})</span>
                </label>

                {prop.description && (
                  <p style={{ fontSize: '11px', color: '#94a3b8', margin: 0 }}>{prop.description}</p>
                )}

                {propType === 'boolean' ? (
                  <select
                    value={formData[key] ? 'true' : 'false'}
                    onChange={e => handleChange(key, e.target.value === 'true')}
                    style={inputStyle}
                  >
                    <option value="false">false</option>
                    <option value="true">true</option>
                  </select>
                ) : propType === 'number' || propType === 'integer' ? (
                  <input
                    type="number"
                    value={formData[key] ?? ''}
                    onChange={e => handleChange(key, parseFloat(e.target.value))}
                    required={isRequired}
                    style={inputStyle}
                  />
                ) : prop.enum ? (
                  <select
                    value={formData[key] || ''}
                    onChange={e => handleChange(key, e.target.value)}
                    required={isRequired}
                    style={inputStyle}
                  >
                    <option value="">Select an option...</option>
                    {prop.enum.map((opt: string) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={formData[key] || ''}
                    onChange={e => handleChange(key, e.target.value)}
                    required={isRequired}
                    placeholder={`Enter ${key}...`}
                    style={inputStyle}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className="btn-neon-cyan"
        style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '0.625rem 0', marginTop: '0.5rem', fontSize: '0.75rem', letterSpacing: '0.1em' }}
      >
        {loading ? 'CASTING SPELL (EXECUTING)...' : 'EXECUTE TOOL CALL ⚡'}
      </button>
    </form>
  );
};
