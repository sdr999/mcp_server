import React, { useState } from 'react';

interface SchemaFormProps {
  schema: any;
  onSubmit: (formData: any) => void;
  loading?: boolean;
}

export const SchemaForm: React.FC<SchemaFormProps> = ({ schema, onSubmit, loading }) => {
  const properties = schema?.properties || {};
  const requiredFields: string[] = schema?.required || [];
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [rawJsonMode, setRawJsonMode] = useState(false);
  const [rawJsonStr, setRawJsonStr] = useState('{}');
  const [jsonError, setJsonError] = useState<string | null>(null);

  const handleChange = (key: string, value: any) => {
    setFormData(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (rawJsonMode) {
      try {
        const parsed = JSON.parse(rawJsonStr);
        setJsonError(null);
        onSubmit(parsed);
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
          TOOL PARAMETER INPUTS
        </h4>
        <button
          type="button"
          onClick={() => setRawJsonMode(!rawJsonMode)}
          style={{ fontSize: '11px', color: '#94a3b8', textDecoration: 'underline', fontFamily: 'var(--font-mono)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          {rawJsonMode ? 'Switch to Form Controls' : 'Switch to Raw JSON'}
        </button>
      </div>

      {rawJsonMode ? (
        <div>
          <textarea
            value={rawJsonStr}
            onChange={e => setRawJsonStr(e.target.value)}
            rows={8}
            style={{ ...inputStyle, minHeight: '8rem', color: '#34d399' }}
            placeholder="{ 'param1': 'value' }"
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
