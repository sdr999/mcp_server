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

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <h4 className="text-xs font-mono font-bold tracking-wider text-cyan-400 uppercase">
          TOOL PARAMETER INPUTS
        </h4>
        <button
          type="button"
          onClick={() => setRawJsonMode(!rawJsonMode)}
          className="text-[11px] font-mono text-slate-400 hover:text-cyan-400 underline"
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
            className="w-full bg-slate-950 border border-slate-700 rounded p-3 font-mono text-xs text-emerald-400 focus:outline-none focus:border-cyan-400"
            placeholder="{ 'param1': 'value' }"
          />
          {jsonError && <p className="text-xs text-rose-400 font-mono mt-1">{jsonError}</p>}
        </div>
      ) : propertyKeys.length === 0 ? (
        <div className="text-xs text-slate-400 font-mono italic py-2">
          No parameters required for this tool.
        </div>
      ) : (
        <div className="space-y-3">
          {propertyKeys.map(key => {
            const prop = properties[key];
            const isRequired = requiredFields.includes(key);
            const propType = prop.type || 'string';

            return (
              <div key={key} className="space-y-1">
                <label className="text-xs font-mono font-bold text-slate-300 flex items-center justify-between">
                  <span>
                    {key} {isRequired && <span className="text-rose-400">*</span>}
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">({propType})</span>
                </label>

                {prop.description && (
                  <p className="text-[11px] text-slate-400">{prop.description}</p>
                )}

                {propType === 'boolean' ? (
                  <select
                    value={formData[key] ? 'true' : 'false'}
                    onChange={e => handleChange(key, e.target.value === 'true')}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
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
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
                  />
                ) : prop.enum ? (
                  <select
                    value={formData[key] || ''}
                    onChange={e => handleChange(key, e.target.value)}
                    required={isRequired}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
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
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
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
        className="w-full btn-neon-cyan justify-center py-2.5 mt-2 text-xs tracking-widest"
      >
        {loading ? 'CASTING SPELL (EXECUTING)...' : 'EXECUTE TOOL CALL ⚡'}
      </button>
    </form>
  );
};
